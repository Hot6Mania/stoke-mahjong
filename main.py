import os
import json
import time
import asyncio
from typing import Set, Optional, Dict, Any, List, Tuple
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Body, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
import httpx
import websockets
from dotenv import load_dotenv
import uvicorn

import re
import socket
import struct
from database import init_db, get_db, SessionLocal
from models import User, Position, MarketState, ProductType, DonationRecord
import db_backup
import trading_engine as te
from command_handler import handle_chat_command
from chzzk_api import chzzk_api, dispatch_chat_notice
from chzzk_session import ChzzkSessionWorker

# Load environment variables
load_dotenv()

CHANNEL_ID = os.getenv("CHANNEL_ID", "")
NID_AUT = os.getenv("NID_AUT", "")
NID_SES = os.getenv("NID_SES", "")

# ---------------------------------------------------------
# Real-time Mahjong Tracker Data (from http://localhost:7500/data.json)
# ---------------------------------------------------------
DEFAULT_TRACKER_DATA = {
    "nickname": "ちぃず鍋",
    "rank": "작성3",
    "score": "2137/9000 (2137)",
    "score_diff": "0",
    "record": "32321 13212 21112 21111 11332 32222 31111 33123 23333 11333 22133 3221",
    "date": "2026년 09월 16일",
    "hule_rate": "30.3%",
    "houjuu_rate": "15.2%",
    "furo_rate": "25.7%",
    "riichi_rate": "25.9%",
    "riichi_win_rate": "54.5%",
    "riichi_houjuu_rate": "",
    "dama_rate": "11.8%",
    "ippatsu_rate": "",
    "ura_rate": "",
    "ryukyoku_tenpai_rate": "",
    "kyoku_avg": "+1311",
    "avg_rank": "1.98",
    "rentai_rate": "",
    "obs_show_date": False,
    "obs_show_nickname": False,
    "obs_show_record": True,
    "obs_show_stats": True,
    "obs_show_hule": True,
    "obs_show_houjuu": True,
    "obs_show_furo": True,
    "obs_show_riichi": True,
    "obs_show_riichi_win": True,
    "obs_show_dama": True,
    "obs_show_kyoku_avg": True,
    "obs_show_avg_rank": True,
    "obs_label_color": "#a9c2d1",
    "obs_value_color": "#ffffff",
    "obs_container_opacity": "60",
    "obs_stats_one_line": True,
}
latest_tracker_data: Dict[str, Any] = dict(DEFAULT_TRACKER_DATA)

def extract_rank_points(score_str: str) -> Optional[int]:
    """Extract current rank points from score string e.g. '2,137pt (2,137pt)' or '2340/9000 (3055)' -> 2137 or 2340."""
    if not score_str:
        return None
    # 1. '2,137 / 9,000'
    m = re.search(r"([\d,]+)\s*/", score_str)
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            pass
    # 2. '2,137pt' or '2,137점'
    m = re.search(r"([\d,]+)\s*(?:pt|점)", score_str, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            pass
    # 3. Leading numbers before parenthesis e.g. '2,137 (2,137)'
    m = re.search(r"^([\d,]+)", score_str.strip())
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            pass
    # 4. Fallback to any 3-5 digit sequence after stripping commas
    cleaned = score_str.replace(",", "")
    nums = re.findall(r"\b\d{3,5}\b", cleaned)
    if nums:
        return int(nums[0])
    return None

def extract_day_start_points(score_str: str) -> Optional[int]:
    """Extract today's starting rank points from score string e.g. '2,137pt (2,137pt)' or '(3055)' -> 2137 or 3055."""
    if not score_str:
        return None
    m = re.search(r"\(\s*([\d,]+)\s*(?:pt|점)?\s*\)", score_str, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            return None
    return None

# ---------------------------------------------------------
# 5-Minute Free Trading Window Timer Manager & Recent Trades
# ---------------------------------------------------------
from collections import deque
recent_trades: deque = deque(maxlen=20)

def record_trade_event(event: Optional[Dict[str, Any]]):
    if event and event.get("type") in ("trade_buy", "trade_sell"):
        data = event.get("data") or {}
        recent_trades.appendleft({
            "type": event["type"],
            "data": data,
            "timestamp": time.time()
        })

FREE_TRADING_SECONDS = 300 # 5 minutes (300 seconds)
free_trading_end_time: Optional[float] = None
free_trading_task: Optional[asyncio.Task] = None

def get_free_trading_remaining(state=None) -> int:
    """Returns remaining seconds of the 5-minute free trading window."""
    global free_trading_end_time
    if state is not None:
        if getattr(state, "is_trading_locked", False):
            return 0
        end_t = getattr(state, "free_trading_end_time", 0.0) or free_trading_end_time or 0.0
    else:
        end_t = free_trading_end_time or 0.0

    if not end_t or end_t <= 0:
        return 0
    rem = int(end_t - time.time())
    return max(0, rem)

def serialize_market_state(state) -> Dict[str, Any]:
    rem_sec = get_free_trading_remaining(state)
    day_open = getattr(state, "day_open_price", None) or state.previous_price or 2340
    
    c_open = getattr(state, "casino_is_open", False) or False
    c_end = getattr(state, "casino_end_time", 0.0) or 0.0
    c_rem = max(0, int(c_end - time.time())) if c_end and c_end > 0 else (0 if not c_open else -1)
    c_max_bet = getattr(state, "casino_max_bet", 10000000) or 10000000
    if c_open and c_end and c_end > 0 and time.time() > c_end:
        c_open = False
        c_rem = 0

    # Star Force Fever Event State
    now = time.time()
    sf_type = getattr(state, "sf_event_type", None)
    sf_end = float(getattr(state, "sf_event_end_time", 0.0) or 0.0)
    sf_title = getattr(state, "sf_event_title", None)
    sf_active = bool(sf_type and sf_end > now)
    sf_rem = max(0, int(sf_end - now)) if sf_active else 0

    # State Welfare Lottery Event State
    lottery_open = bool(getattr(state, "lottery_is_open", False))
    lottery_end = float(getattr(state, "lottery_end_time", 0.0) or 0.0)
    lottery_title = getattr(state, "lottery_title", "국가 복지 복권") or "국가 복지 복권"
    lottery_active = bool(lottery_open and lottery_end > now)
    lottery_rem = max(0, int(lottery_end - now)) if lottery_active else 0

    # Mysterious Merchant State
    merchant_open = bool(getattr(state, "merchant_is_open", False))
    merchant_end = float(getattr(state, "merchant_end_time", 0.0) or 0.0)
    merchant_name = getattr(state, "merchant_name", "신비상인") or "신비상인"
    merchant_active = bool(merchant_open and merchant_end > now)
    merchant_rem = max(0, int(merchant_end - now)) if merchant_active else 0

    res = {
        "current_rank_name": getattr(state, "current_rank_name", "작성3") or "작성3",
        "current_rank_point": state.current_rank_point,
        "current_price": state.current_price,
        "previous_price": state.previous_price,
        "day_open_price": day_open,
        "is_trading_locked": state.is_trading_locked,
        "last_settlement_delta": state.last_settlement_delta,
        "treasury_pool": getattr(state, "treasury_pool", 500000.0) or 500000.0,
        "free_trading_remaining": rem_sec,
        "free_trading_end_time": getattr(state, "free_trading_end_time", 0.0) or 0.0,
        "casino_is_open": c_open,
        "casino_remaining": c_rem,
        "casino_max_bet": c_max_bet,
        "sf_event_type": sf_type if sf_active else None,
        "sf_event_title": sf_title if sf_active else None,
        "sf_is_active": sf_active,
        "sf_remaining": sf_rem,
        "lottery_is_open": lottery_active,
        "lottery_remaining": lottery_rem,
        "lottery_title": lottery_title,
        "merchant_is_open": merchant_active,
        "merchant_remaining": merchant_rem,
        "merchant_name": merchant_name,
        "merchant_items": {
            "shield": {
                "name": "🛡️ 파괴방어권",
                "price": getattr(state, "merchant_shield_price", 60000) or 60000,
                "stock": getattr(state, "merchant_shield_stock", 5) or 0,
            },
            "boost": {
                "name": "⚡ 강화확률상승권",
                "price": getattr(state, "merchant_boost_price", 25000) or 25000,
                "stock": getattr(state, "merchant_boost_stock", 10) or 0,
            },
            "downgrade": {
                "name": "📉 하강방지권",
                "price": getattr(state, "merchant_downgrade_price", 35000) or 35000,
                "stock": getattr(state, "merchant_downgrade_stock", 8) or 0,
            }
        }
    }
    return res

def sync_docs_market_state(state):
    """Save latest market state to docs/market_state.json for GitHub Pages."""
    try:
        docs_dir = os.path.join(os.path.dirname(__file__), "docs")
        if os.path.exists(docs_dir):
            data = serialize_market_state(state)
            day_open = data.get("day_open_price", 2034)
            day_diff = state.current_price - day_open
            day_diff_pct = (day_diff / day_open * 100.0) if day_open > 0 else 0.0
            payload = {
                **data,
                "day_diff": day_diff,
                "day_diff_pct": round(day_diff_pct, 2),
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            json_path = os.path.join(docs_dir, "market_state.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# ---------------------------------------------------------
# WebSocket Connection Manager for OBS & Admin Panels
# ---------------------------------------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

        # Send initial market state, free trading timer, and leaderboard upon connecting
        db = SessionLocal()
        try:
            state = te.get_market_state(db)
            leaderboard = te.get_leaderboard(db, top_n=3)
            m_state = serialize_market_state(state)
            init_payload = {
                "type": "init",
                "tracker_data": latest_tracker_data,
                "free_trading_remaining": m_state["free_trading_remaining"],
                "market_state": m_state,
                "leaderboard": leaderboard,
            }
            await websocket.send_json(init_payload)
        finally:
            db.close()

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: dict):
        disconnected = set()
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.add(connection)
        for dead in disconnected:
            self.active_connections.discard(dead)

manager = ConnectionManager()

async def start_free_trading_window(seconds: int = FREE_TRADING_SECONDS):
    """
    Opens trading for `seconds` (default 5 minutes / 300s).
    After the timer expires, automatically locks the market (is_trading_locked = True).
    """
    global free_trading_end_time, free_trading_task

    if free_trading_task and not free_trading_task.done():
        free_trading_task.cancel()

    free_trading_end_time = time.time() + seconds

    db = SessionLocal()
    try:
        state = te.get_market_state(db)
        state.is_trading_locked = False
        state.free_trading_end_time = free_trading_end_time
        db.commit()
    finally:
        db.close()

    # Broadcast to OBS overlays and Admin
    await manager.broadcast({
        "type": "free_trading_opened",
        "is_trading_locked": False,
        "duration_seconds": seconds,
        "remaining_seconds": seconds,
        "end_time": free_trading_end_time
    })

    mins = seconds // 60
    open_msg = f"📢 [자유 거래 오픈] 경기 정산 완료! 앞으로 {mins}분간 주식 자유 거래(매수/매도/채굴)가 열립니다! (남은 시간: {mins}분)"
    asyncio.create_task(dispatch_chat_notice(open_msg, fallback_bot=bot_instance))

    async def countdown_and_lock():
        try:
            await asyncio.sleep(seconds)
            db_lock = SessionLocal()
            try:
                st = te.get_market_state(db_lock)
                st.is_trading_locked = True
                st.free_trading_end_time = 0.0
                db_lock.commit()
            finally:
                db_lock.close()

            await manager.broadcast({
                "type": "free_trading_closed",
                "is_trading_locked": True,
                "remaining_seconds": 0,
                "message": "자유 거래 시간이 종료되어 거래가 마감되었습니다."
            })

            close_msg = "🔒 [거래 마감] 5분 자유 거래 시간이 종료되었습니다. 다음 경기 종료 시까지 주식 거래가 마감됩니다."
            asyncio.create_task(dispatch_chat_notice(close_msg, fallback_bot=bot_instance))
            print("[Market] 🔒 5분 자유 거래 시간 만료 -> 거래 자동 마감 (Lock On)")
        except asyncio.CancelledError:
            pass

    free_trading_task = asyncio.create_task(countdown_and_lock())

# ---------------------------------------------------------
# Centralized Donation Event Processor & Packet Parser
# ---------------------------------------------------------
async def handle_donation_event(
    donation_payload: Dict[str, Any],
    fallback_bot: Optional[Any] = None
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Central donation processor for both official OpenAPI session events
    and unofficial live chat WebSocket packets.
    Credits points at 1 KRW : 100 Points ratio, broadcasts to OBS overlays,
    and dispatches stream chat notification.
    """
    bot = fallback_bot or bot_instance
    db = SessionLocal()
    try:
        success, reply, details = te.validate_and_process_donation(db, donation_payload)
        if success and details:
            leaderboard = te.get_leaderboard(db, top_n=3)
            state = te.get_market_state(db)
            await manager.broadcast({
                "type": "donation_charged",
                "data": details,
                "leaderboard": leaderboard,
                "market_state": serialize_market_state(state)
            })
            if reply:
                asyncio.create_task(dispatch_chat_notice(reply, fallback_bot=bot))
            print(f"[Donation] 🎉 [1:1000 충전 성공] {details['username']} +{details['points_credited']:,}P (현재 잔고: {details['remaining_points']:,}P)")
        elif not success:
            print(f"[Donation] ℹ️ 후원 처리 스킵/중복: {reply}")
        return success, reply, details
    except Exception as e:
        print(f"[Donation] ❌ 후원 처리 오류: {e}")
        return False, str(e), None
    finally:
        db.close()

def extract_donation_from_packet(chat: dict, cmd: int) -> Optional[Dict[str, Any]]:
    """
    Extracts structured donation payload from unofficial chat WebSocket packet.
    Handles cmd == 93102 (Donation chat) and cmd == 93101 with msgTypeCode in (10, 93102) / payAmount extras.
    """
    msg_type_code = chat.get("msgTypeCode")
    extras_raw = chat.get("extras")
    extras = {}
    if isinstance(extras_raw, dict):
        extras = extras_raw
    elif isinstance(extras_raw, str) and extras_raw.strip():
        try:
            extras = json.loads(extras_raw)
        except Exception:
            extras = {}

    is_donation = (
        cmd == 93102 or
        msg_type_code in (10, 93102) or
        bool(extras.get("payAmount") or extras.get("donationAmount") or chat.get("payAmount"))
    )
    if not is_donation:
        return None

    raw_pay_amount = extras.get("payAmount") or extras.get("donationAmount") or chat.get("payAmount")
    if not raw_pay_amount:
        return None

    profile_raw = chat.get("profile")
    profile = {}
    if isinstance(profile_raw, dict):
        profile = profile_raw
    elif isinstance(profile_raw, str) and profile_raw.strip():
        try:
            profile = json.loads(profile_raw)
        except Exception:
            profile = {}

    nickname = profile.get("nickname") or chat.get("nickname") or extras.get("nickname") or "익명후원자"
    user_id = profile.get("userIdHash") or chat.get("uid") or f"chzzk_{nickname}"
    msg = chat.get("msg") or extras.get("msg") or ""
    donation_type = extras.get("donationType") or "CHAT"
    msg_time = chat.get("msgTime") or extras.get("msgTime") or str(int(time.time() * 1000))
    donation_id = chat.get("donationId") or extras.get("donationId")

    payload = {
        "donationType": donation_type,
        "channelId": CHANNEL_ID,
        "donatorChannelId": user_id,
        "donatorNickname": nickname,
        "payAmount": raw_pay_amount,
        "donationText": msg,
        "messageTime": str(msg_time)
    }
    if donation_id:
        payload["donationId"] = str(donation_id)
    return payload

# ---------------------------------------------------------
# Chzzk Streaming Bot Integration
# ---------------------------------------------------------
class ChzzkBot:
    def __init__(self):
        self.chat_channel_id: Optional[str] = None
        self.access_token: Optional[str] = None
        self.uid: Optional[str] = None
        self.sid: Optional[str] = None
        self.ws = None
        self.is_running = False
        self.connected_at_ms: int = 0
        self.processed_msg_keys: set = set()

    async def get_auth_data(self) -> bool:
        if not CHANNEL_ID:
            print("[ChzzkBot] ⚠️ CHANNEL_ID가 비어있습니다. Chzzk 연동을 건너뜁니다.")
            return False

        cookies = {"NID_AUT": NID_AUT, "NID_SES": NID_SES}
        headers = {"User-Agent": "Mozilla/5.0"}

        try:
            async with httpx.AsyncClient(cookies=cookies, headers=headers, timeout=10.0) as client:
                # 1. 방송 채널의 채팅방 ID 조회
                res = await client.get(f"https://api.chzzk.naver.com/polling/v2/channels/{CHANNEL_ID}/live-status")
                if res.status_code != 200:
                    print(f"[ChzzkBot] ❌ 방송 상태 조회 실패 (Status: {res.status_code}). CHANNEL_ID를 확인하세요.")
                    return False
                content = res.json().get("content")
                if not content or not content.get("chatChannelId"):
                    print("[ChzzkBot] ❌ chatChannelId를 찾을 수 없습니다.")
                    return False
                self.chat_channel_id = content["chatChannelId"]

                # 2. 봇 계정의 고유 UID 조회
                res = await client.get("https://comm-api.game.naver.com/nng_main/v1/user/getUserStatus")
                if res.status_code == 200 and res.json().get("content"):
                    self.uid = res.json()["content"]["userIdHash"]
                else:
                    self.uid = "anonymous"

                # 3. 채팅 서버 접속용 Access Token 발급
                token_url = f"https://comm-api.game.naver.com/nng_main/v1/chats/access-token?channelId={self.chat_channel_id}&chatType=STREAMING"
                res = await client.get(token_url)
                if res.status_code == 200 and res.json().get("content"):
                    self.access_token = res.json()["content"]["accessToken"]
                else:
                    print("[ChzzkBot] ❌ Access Token 발급 실패.")
                    return False

            return True
        except Exception as e:
            print(f"[ChzzkBot] ❌ 치지직 인증 중 오류 발생: {e}")
            return False

    async def send_chat(self, message: str) -> bool:
        if not self.ws or not self.sid or not self.chat_channel_id:
            print(f"[ChzzkBot] ⚠️ send_chat 세션 비활성 (ws={bool(self.ws)}, sid={bool(self.sid)}, cid={bool(self.chat_channel_id)})")
            return False

        extras = {
            "chatType": "STREAMING",
            "emojis": "",
            "osType": "PC",
            "streamingChannelId": self.chat_channel_id
        }

        self.msg_tid = getattr(self, "msg_tid", 100) + 1
        payload = {
            "ver": "2",
            "cmd": 3101,
            "svcid": "game",
            "cid": self.chat_channel_id,
            "sid": self.sid,
            "bdy": {
                "extras": json.dumps(extras),
                "msg": message,
                "msgTime": int(time.time() * 1000),
                "msgTypeCode": 1
            },
            "tid": self.msg_tid
        }
        try:
            await self.ws.send(json.dumps(payload))
            print(f"[ChzzkBot] 🤖 전송 (tid={self.msg_tid}): {message}")
            return True
        except Exception as e:
            print(f"[ChzzkBot] ❌ 메시지 전송 실패: {e}")
            return False

    async def ping_loop(self):
        while self.is_running:
            await asyncio.sleep(20)
            if self.ws:
                try:
                    await self.ws.send(json.dumps({"cmd": 10000, "ver": "2"}))
                except Exception:
                    break

    async def run(self):
        if not NID_AUT or not NID_SES or not CHANNEL_ID:
            print("[ChzzkBot] ℹ️ .env에 치지직 쿠키/채널 설정이 없어 로컬 테스트 모드로 실행됩니다.")
            return

        while True:
            try:
                auth_ok = await self.get_auth_data()
                if not auth_ok:
                    print("[ChzzkBot] ⚠️ 치지직 인증 실패. 30초 후 재시도합니다.")
                    await asyncio.sleep(30)
                    continue

                server_id = sum(ord(c) for c in self.chat_channel_id) % 9 + 1
                ws_url = f"wss://kr-ss{server_id}.chat.naver.com/chat"
                self.is_running = True

                print(f"[ChzzkBot] 🔌 치지직 채팅 서버 연결 시도: {ws_url}")
                async with websockets.connect(ws_url) as ws:
                    self.ws = ws
                    # 연결 패킷 전송
                    await ws.send(json.dumps({
                        "ver": "2",
                        "cmd": 100,
                        "svcid": "game",
                        "cid": self.chat_channel_id,
                        "bdy": {
                            "uid": self.uid,
                            "devType": 2001,
                            "accTkn": self.access_token,
                            "auth": "SEND"
                        },
                        "tid": 1
                    }))

                    ping_task = asyncio.create_task(self.ping_loop())

                    try:
                        async for raw_msg in ws:
                            data = json.loads(raw_msg)
                            cmd = data.get("cmd")

                            if cmd == 10100: # Handshake success
                                bdy = data.get("bdy")
                                if bdy:
                                    self.sid = bdy.get("sid")
                                    self.connected_at_ms = int(time.time() * 1000)
                                    print("[ChzzkBot] ✅ 치지직 채팅 서버 연결 성공!")

                            elif cmd in (93101, 93102): # 93101: Chat, 93102: Donation Chat
                                bdy = data.get("bdy")
                                if not bdy:
                                    continue

                                if isinstance(bdy, dict):
                                    chat_list = bdy.get("messageList") or [bdy]
                                elif isinstance(bdy, list):
                                    chat_list = bdy
                                else:
                                    chat_list = []

                                for chat in chat_list:
                                    if not isinstance(chat, dict):
                                        continue
                                    profile_str = chat.get("profile")
                                    profile = json.loads(profile_str) if isinstance(profile_str, str) else (profile_str if isinstance(profile_str, dict) else {})
                                    nickname = profile.get("nickname", "시청자")
                                    user_id = profile.get("userIdHash") or chat.get("uid") or nickname
                                    msg = chat.get("msg", "")
                                    msg_time = chat.get("msgTime") or 0

                                    # Ignore bot's own messages
                                    if user_id == self.uid:
                                        continue

                                    # 1. Skip ancient messages from chat history replay on connect/reconnect
                                    if self.connected_at_ms > 0 and msg_time > 0 and msg_time < (self.connected_at_ms - 15000):
                                        continue

                                    # 2. Message deduplication (prevents duplicate execution of the exact same packet)
                                    msg_key = f"{user_id}_{msg_time}_{msg}"
                                    if msg_key in self.processed_msg_keys:
                                        continue
                                    self.processed_msg_keys.add(msg_key)
                                    if len(self.processed_msg_keys) > 1000:
                                        self.processed_msg_keys = set(list(self.processed_msg_keys)[500:])

                                    # 1. Check for donation packet (cmd 93102 or msgTypeCode 10 / payAmount extras)
                                    donation_payload = extract_donation_from_packet(chat, cmd)
                                    if donation_payload:
                                        await handle_donation_event(donation_payload, fallback_bot=self)
                                        continue

                                    # 2. Regular user command dispatch
                                    db = SessionLocal()
                                    try:
                                        reply, event = handle_chat_command(db, user_id, nickname, msg)
                                        if event:
                                            if event.get("type") == "settlement":
                                                await start_free_trading_window(300)
                                            record_trade_event(event)
                                            # Broadcast trade/order update to OBS overlay immediately
                                            leaderboard = te.get_leaderboard(db, top_n=3)
                                            state = te.get_market_state(db)
                                            sync_docs_market_state(state)
                                            await manager.broadcast({
                                                **event,
                                                "leaderboard": leaderboard,
                                                "market_state": serialize_market_state(state),
                                                "recent_trades": list(recent_trades)
                                            })

                                        if reply:
                                            asyncio.create_task(dispatch_chat_notice(reply, fallback_bot=self))
                                    except Exception as cmd_err:
                                        print(f"[ChzzkBot] ⚠️ 명령어 처리 중 오류 ({cmd_err}): {msg}")
                                    finally:
                                        db.close()

                            elif cmd == 10000: # Ping -> Pong
                                await ws.send(json.dumps({"cmd": 10001, "ver": "2"}))

                    finally:
                        ping_task.cancel()

            except Exception as e:
                print(f"[ChzzkBot] ⚠️ 연결 끊김 또는 에러 ({e}). 10초 후 재접속합니다...")
                await asyncio.sleep(10)

bot_instance = ChzzkBot()

session_worker = ChzzkSessionWorker(
    channel_id=CHANNEL_ID,
    on_donation=lambda d: handle_donation_event(d, fallback_bot=bot_instance),
    fallback_bot=bot_instance
)

# ---------------------------------------------------------
# Real-time Mahjong Tracker Polling Task
# ---------------------------------------------------------
last_synced_record: str = ""
last_synced_pts: Optional[int] = None
last_tracker_received_at: Optional[float] = None
last_tracker_source: str = "none"
tracker_sync_lock = asyncio.Lock()

def get_tracker_candidate_urls() -> List[str]:
    """Return list of possible local/host endpoints for the Mahjong Tracker."""
    urls = [
        "http://127.0.0.1:7500/data.json",
        "http://localhost:7500/data.json",
        "http://127.0.0.1:7500/",
        "http://localhost:7500/",
    ]
    try:
        with open("/proc/net/route") as f:
            for line in f:
                fields = line.strip().split()
                if fields[1] == '00000000':
                    host_ip = socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))
                    if host_ip and host_ip not in ("127.0.0.1", "0.0.0.0"):
                        urls.append(f"http://{host_ip}:7500/data.json")
                        urls.append(f"http://{host_ip}:7500/")
                    break
    except Exception:
        pass
    return urls

async def process_tracker_update(data: Dict[str, Any], source: str = "poll", force_settle: bool = False) -> Dict[str, Any]:
    """
    Core engine to process incoming real-time Mahjong tracker data.
    Updates rank points, detects finished games, settles matches, triggers dividends/liquidations,
    and opens the 5-minute free trading window.
    Can be called by background sync loop or via client-side relay (/api/tracker/push or WebSocket).
    """
    global last_synced_record, last_synced_pts, last_tracker_received_at, last_tracker_source

    if not isinstance(data, dict) or data.get("nickname") == "정보 없음":
        return {"success": False, "reason": "invalid_data"}

    async with tracker_sync_lock:
        last_tracker_received_at = time.time()
        last_tracker_source = source
        latest_tracker_data.update(data)

        score_str = data.get("score", "")
        pts = extract_rank_points(score_str)
        day_start = extract_day_start_points(score_str)
        rec_str = str(data.get("record", "") or "").strip()

        if pts is None or pts <= 0:
            return {"success": True, "settled": False, "reason": "no_points"}

        db = SessionLocal()
        try:
            state = te.get_market_state(db)
            if day_start and getattr(state, "day_open_price", None) != day_start:
                state.day_open_price = day_start
                db.commit()

            # Direct tracker demotion detection (e.g. tracker shows '작성2' while system was '작성3')
            tracker_rank = str(data.get("rank", "") or "").replace(" ", "").strip()
            curr_rank = getattr(state, "current_rank_name", "작성3") or "작성3"
            if "작성3" in curr_rank and "작성2" in tracker_rank:
                starting_pts = pts if (pts is not None and pts > 0) else 3000
                delist_res = te.execute_delisting_and_relist(
                    db,
                    old_rank="작성3",
                    new_rank="작성2",
                    starting_points=starting_pts
                )
                last_synced_pts = starting_pts
                last_synced_record = rec_str
                latest_tracker_data["rank"] = "작성2"
                sync_docs_market_state(state)
                await start_free_trading_window(300)
                await manager.broadcast({
                    "type": "delisting",
                    "delisting_info": delist_res,
                    "tracker_data": latest_tracker_data,
                    "market_state": serialize_market_state(state),
                    "free_trading_remaining": 300
                })
                delist_chat = (
                    f"🚨🚨 [긴급 속보: 상장폐지 & 신규 상장] 치즈나베의 '작성3' 강등으로 인해 작성3 종목이 전격 [상장폐지]되었습니다! "
                    f"기존 주주 총 {delist_res['wiped_positions_count']}명의 주식이 전량 [휴짓조각(0주)] 처리되었습니다. "
                    f"신규 종목 [작성2] (시작가 {state.current_price:,}P)가 새로 상장되어 거래가 시작됩니다!"
                )
                asyncio.create_task(dispatch_chat_notice(delist_chat, fallback_bot=bot_instance))
                print(f"[Tracker] 💥 상장폐지 및 신규 상장 완료: 작성3 -> 작성2 (시작가 {state.current_price:,}P)")
                return {
                    "success": True,
                    "settled": True,
                    "delisted": True,
                    "delisting_info": delist_res,
                    "current_price": state.current_price,
                    "day_open_price": state.day_open_price
                }

            # Baseline establishment on initial startup
            is_initial = (last_synced_pts is None and not last_synced_record)
            if is_initial and not force_settle:
                last_synced_pts = pts
                last_synced_record = rec_str
                # If market state points differ from tracker on initial sync, align quietly
                if state.current_rank_point != pts:
                    state.current_rank_point = pts
                    state.current_price = te.calculate_stock_price(pts)
                    db.commit()
                    sync_docs_market_state(state)
                await manager.broadcast({
                    "type": "tracker_update",
                    "tracker_data": latest_tracker_data,
                    "market_state": serialize_market_state(state)
                })
                print(f"[Tracker] 🔌 트래커 최초 기준점 동기화 완료: {pts:,}pt (시작가: {state.day_open_price:,}P, 전적: {rec_str})")
                return {"success": True, "initial_sync": True, "current_pts": pts, "record": rec_str}

            pts_changed = (state.current_rank_point != pts)
            rec_changed = bool(last_synced_record and rec_str and rec_str != last_synced_record)

            if pts_changed or rec_changed or force_settle:
                delta = (pts - state.current_rank_point) if pts_changed else 0
                if force_settle and delta == 0 and pts:
                    delta = (pts - state.current_rank_point)

                # Determine rank of the finished match
                new_digits = [int(c) for c in rec_str if c in "1234"]
                old_digits = [int(c) for c in last_synced_record if c in "1234"] if last_synced_record else []

                rank = None
                if old_digits and new_digits and len(new_digits) > len(old_digits):
                    if new_digits[0] != old_digits[0]:
                        rank = new_digits[0]
                    elif new_digits[-1] != old_digits[-1]:
                        rank = new_digits[-1]
                    else:
                        rank = new_digits[0]

                if rank is None:
                    if delta >= 40:
                        rank = 1
                    elif 0 <= delta < 40:
                        rank = 2
                    else:
                        rank = 3

                if 0 <= delta < 40 and rank in (3, 4):
                    rank = 2
                elif delta >= 40 and rank != 1:
                    rank = 1
                elif delta < 0 and rank in (1, 2):
                    rank = 3

                # For 3-player mahjong (Sanma), max rank is 3
                if rank and rank > 3:
                    rank = 3

                last_synced_record = rec_str
                last_synced_pts = pts

                settle_res = te.settle_match(db, rank=rank, point_delta=delta)
                leaderboard = te.get_leaderboard(db, top_n=3)

                # 5-minute free trading window auto-open
                await start_free_trading_window(300)

                if settle_res.get("delisted"):
                    delist_info = settle_res["delisting_info"]
                    sync_docs_market_state(state)
                    await manager.broadcast({
                        "type": "delisting",
                        "delisting_info": delist_info,
                        "settlement": settle_res,
                        "tracker_data": latest_tracker_data,
                        "leaderboard": leaderboard,
                        "free_trading_remaining": 300,
                        "market_state": serialize_market_state(state)
                    })
                    delist_chat = (
                        f"🚨🚨 [긴급 속보: 상장폐지 & 신규 상장] 경기 결과 점수 하락으로 작성2 강등 발생! "
                        f"작성3 종목이 전격 [상장폐지]되고 기존 주식은 전량 [휴짓조각(0주)] 처리되었습니다! "
                        f"신규 종목 [작성2] (시작가 {state.current_price:,}P) 신규 상장 및 거래 오픈!"
                    )
                    asyncio.create_task(dispatch_chat_notice(delist_chat, fallback_bot=bot_instance))
                    print(f"[Tracker] 💥 경기 결과로 상장폐지 발생: 작성3 -> 작성2 (시작가 {state.current_price:,}P)")
                    return {
                        "success": True,
                        "settled": True,
                        "delisted": True,
                        "delisting_info": delist_info,
                        "rank": rank,
                        "delta": delta,
                        "current_price": state.current_price,
                        "day_open_price": state.day_open_price
                    }

                if settle_res.get("dividends"):
                    div_count = len(settle_res["dividends"])
                    total_div = sum(d["payout"] for d in settle_res["dividends"])
                    pct_label = "5%" if rank == 1 else ("1%" if rank == 2 else "")
                    div_chat = f"🎁 [{rank}위 승리 배당] 1X(기본주) 주주 총 {div_count}명에게 {pct_label} 배당금(총 +{total_div:,}P) 지급 완료! (자유 거래 5분 오픈)"
                    asyncio.create_task(dispatch_chat_notice(div_chat, fallback_bot=bot_instance))

                if settle_res.get("liquidations"):
                    liq_count = len(settle_res["liquidations"])
                    liq_chat = f"🚨 [마진콜 경고] 총 {liq_count}건의 레버리지/인버스 포지션이 강제 청산되었습니다!"
                    asyncio.create_task(dispatch_chat_notice(liq_chat, fallback_bot=bot_instance))

                sync_docs_market_state(state)
                await manager.broadcast({
                    "type": "settlement",
                    **settle_res,
                    "tracker_data": latest_tracker_data,
                    "leaderboard": leaderboard,
                    "free_trading_remaining": 300,
                    "market_state": serialize_market_state(state)
                })
                print(f"[Tracker] 🏁 경기 결과 자동 정산 완료! (순위: {rank}위, 변동: {delta:+d}pt, 신규 주가: {state.current_price:,}P)")
                return {
                    "success": True,
                    "settled": True,
                    "rank": rank,
                    "delta": delta,
                    "current_price": state.current_price,
                    "day_open_price": state.day_open_price
                }
            else:
                last_synced_record = rec_str
                last_synced_pts = pts
                await manager.broadcast({
                    "type": "tracker_update",
                    "tracker_data": latest_tracker_data,
                    "market_state": serialize_market_state(state)
                })
                return {
                    "success": True,
                    "settled": False,
                    "current_pts": pts,
                    "record": rec_str
                }
        finally:
            db.close()

async def sync_tracker_loop():
    """Background task to sync real mahjong stats from local/host tracker."""
    while True:
        try:
            async with httpx.AsyncClient(timeout=1.5) as client:
                for url in get_tracker_candidate_urls():
                    try:
                        res = await client.get(url)
                        if res.status_code == 200:
                            data = res.json()
                            if isinstance(data, dict) and data.get("nickname") != "정보 없음":
                                await process_tracker_update(data, source=f"backend_{url}")
                                break
                    except Exception:
                        continue
        except Exception:
            pass
        await asyncio.sleep(2)

async def auto_mining_loop():
    """Background worker that periodically executes auto-mining ticks for active viewers."""
    while True:
        try:
            await asyncio.sleep(15)
            db = SessionLocal()
            try:
                te.process_all_auto_mining(db)
            finally:
                db.close()
        except asyncio.CancelledError:
            break
        except Exception:
            pass

async def starforce_fever_loop():
    """Background worker that periodically checks and triggers spontaneous Star Force Fever events."""
    last_known_active = False
    while True:
        try:
            await asyncio.sleep(10)
            db = SessionLocal()
            try:
                sf = te.get_starforce_event_state(db)
                is_active = sf.get("is_active", False)
                if is_active and not last_known_active:
                    title = sf.get("title", "스타포스 피버")
                    dur_m = max(1, sf.get("remaining_sec", 0) // 60)
                    desc = sf.get("desc", "")
                    notice = (
                        f"🔥✨ [돌발 피버 OPEN] {title} ({dur_m}분간 진행)! "
                        f"지금 채팅창에 '!강화 [장비번호]'로 곡괭이를 강화해보세요! ({desc})"
                    )
                    asyncio.create_task(dispatch_chat_notice(notice, fallback_bot=bot_instance))
                    state = te.get_market_state(db)
                    sync_docs_market_state(state)
                    await manager.broadcast({
                        "type": "starforce_fever_started",
                        "market_state": serialize_market_state(state)
                    })
                elif not is_active and last_known_active:
                    notice = "🔒 [스타포스 피버 종료] 피버 이벤트가 마감되었습니다. 다음 돌발 피버를 기대해주세요!"
                    asyncio.create_task(dispatch_chat_notice(notice, fallback_bot=bot_instance))
                    state = te.get_market_state(db)
                    sync_docs_market_state(state)
                    await manager.broadcast({
                        "type": "starforce_fever_ended",
                        "market_state": serialize_market_state(state)
                    })
                last_known_active = is_active
            finally:
                db.close()
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(5)

async def lottery_event_loop():
    """Background worker that periodically checks and triggers spontaneous State Welfare Lottery events."""
    last_known_active = False
    while True:
        try:
            await asyncio.sleep(10)
            db = SessionLocal()
            try:
                lottery = te.get_lottery_event_state(db)
                is_active = lottery.get("is_active", False)
                if is_active and not last_known_active:
                    title = lottery.get("title", "국가 복지 복권")
                    dur_m = max(1, lottery.get("remaining_sec", 0) // 60)
                    notice = (
                        f"🎉🏛️ [국가 복지 복권 OPEN] '{title}' ({dur_m}분간 진행)! "
                        f"국고 후원 당첨률 85%! 꽝이어도 500P 환급! 지금 채팅창에 '!복권' (또는 !복권 10)을 긁어보세요!"
                    )
                    asyncio.create_task(dispatch_chat_notice(notice, fallback_bot=bot_instance))
                    state = te.get_market_state(db)
                    sync_docs_market_state(state)
                    await manager.broadcast({
                        "type": "lottery_event_started",
                        "market_state": serialize_market_state(state),
                        "data": lottery
                    })
                elif not is_active and last_known_active:
                    title = lottery.get("title", "국가 복지 복권")
                    notice = f"🔒 [복권 이벤트 마감] '{title}' 판매가 마감되었습니다. 잠시 후 다음 복지 시간에 다시 열립니다!"
                    asyncio.create_task(dispatch_chat_notice(notice, fallback_bot=bot_instance))
                    state = te.get_market_state(db)
                    sync_docs_market_state(state)
                    await manager.broadcast({
                        "type": "lottery_event_ended",
                        "market_state": serialize_market_state(state),
                        "data": lottery
                    })
                last_known_active = is_active
            finally:
                db.close()
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(5)

async def merchant_event_loop():
    """Background worker that periodically checks and triggers spontaneous Mysterious Merchant visits."""
    last_known_active = False
    while True:
        try:
            await asyncio.sleep(10)
            db = SessionLocal()
            try:
                merchant = te.get_merchant_state(db)
                is_active = merchant.get("is_active", False)
                if is_active and not last_known_active:
                    name = merchant.get("merchant_name", "신비상인")
                    dur_m = max(1, merchant.get("remaining_sec", 0) // 60)
                    notice = (
                        f"🧞‍♂️🛒 [신비상인 출현!] 방랑 {name}이(가) 마을에 나타났습니다 ({dur_m}분간 체류)! "
                        f"파괴방어권/강화확률상승권/하강방지권 한정 수량 입고! 지금 채팅창에 '!신비상인' 또는 '!구매'를 확인하세요!"
                    )
                    asyncio.create_task(dispatch_chat_notice(notice, fallback_bot=bot_instance))
                    state = te.get_market_state(db)
                    sync_docs_market_state(state)
                    await manager.broadcast({
                        "type": "merchant_appeared",
                        "market_state": serialize_market_state(state),
                        "data": merchant
                    })
                elif not is_active and last_known_active:
                    name = merchant.get("merchant_name", "신비상인")
                    notice = f"🔒 [신비상인 퇴장] {name}이(가) 보따리를 싸고 마을을 떠났습니다. 다음 방문을 기다려주세요!"
                    asyncio.create_task(dispatch_chat_notice(notice, fallback_bot=bot_instance))
                    state = te.get_market_state(db)
                    sync_docs_market_state(state)
                    await manager.broadcast({
                        "type": "merchant_left",
                        "market_state": serialize_market_state(state),
                        "data": merchant
                    })
                last_known_active = is_active
            finally:
                db.close()
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(5)

# ---------------------------------------------------------
# FastAPI Lifespan & App Setup
# ---------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Initialize SQLite Database
    init_db()
    print("✅ 데이터베이스 초기화 완료 (SQLite: stoke_mahjong.db)")

    # 2. Run Chzzk Official Session Worker, Unofficial Bot & Mahjong Tracker Sync in Background
    bot_task = asyncio.create_task(bot_instance.run())
    session_task = asyncio.create_task(session_worker.run())
    tracker_task = asyncio.create_task(sync_tracker_loop())
    auto_mining_task = asyncio.create_task(auto_mining_loop())
    fever_task = asyncio.create_task(starforce_fever_loop())
    lottery_task = asyncio.create_task(lottery_event_loop())
    merchant_task = asyncio.create_task(merchant_event_loop())

    yield

    bot_task.cancel()
    session_task.cancel()
    tracker_task.cancel()
    auto_mining_task.cancel()
    fever_task.cancel()
    lottery_task.cancel()
    merchant_task.cancel()

app = FastAPI(title="마작 주식 & 파생상품 거래 시스템", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# Request Models
# ---------------------------------------------------------
class LockMarketRequest(BaseModel):
    locked: Optional[bool] = None

class SetDayOpenRequest(BaseModel):
    price: Optional[int] = None

class SettleMatchRequest(BaseModel):
    rank: int
    point_delta: int

class DelistRequest(BaseModel):
    old_rank: Optional[str] = "작성3"
    new_rank: Optional[str] = "작성2"
    starting_points: Optional[int] = 3000

class GrantPointsRequest(BaseModel):
    user_id: str
    username: Optional[str] = None
    points: int
    mode: Optional[str] = "add"

class ChatCommandRequest(BaseModel):
    user_id: str
    username: str
    message: str

class TransferRequest(BaseModel):
    sender_id: str
    sender_username: Optional[str] = "이체자"
    target_name: str
    amount: str

class BankruptcyJudgeRequest(BaseModel):
    app_id: int
    verdict: str
    comment: Optional[str] = ""

class CasinoOpenRequest(BaseModel):
    duration_minutes: float = 3.0
    max_bet: int = 10000000

class LotteryOpenRequest(BaseModel):
    duration_minutes: Optional[int] = 10
    title: Optional[str] = "국가 복지 복권"

class MerchantOpenRequest(BaseModel):
    duration_minutes: Optional[int] = 10
    merchant_name: Optional[str] = "신비상인"

# ---------------------------------------------------------
# Web Views & OBS Overlay
# ---------------------------------------------------------
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")

@app.get("/", response_class=HTMLResponse)
@app.get("/overlay", response_class=HTMLResponse)
async def get_overlay():
    """Serves the OBS Browser Source Overlay (Supports ?mode=stock or ?mode=mahjong)."""
    overlay_path = os.path.join(TEMPLATES_DIR, "overlay.html")
    with open(overlay_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/overlay/stock", response_class=HTMLResponse)
@app.get("/stock-overlay", response_class=HTMLResponse)
async def get_stock_overlay():
    """Serves the Standalone OBS Stock & Leaderboard Overlay."""
    stock_path = os.path.join(TEMPLATES_DIR, "stock_overlay.html")
    with open(stock_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/overlay/mahjong", response_class=HTMLResponse)
@app.get("/mahjong-overlay", response_class=HTMLResponse)
@app.get("/tracker-overlay", response_class=HTMLResponse)
async def get_mahjong_overlay():
    """Serves the Standalone OBS Mahjong Stats Overlay (matching 7500 style)."""
    mahjong_path = os.path.join(TEMPLATES_DIR, "mahjong_overlay.html")
    with open(mahjong_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/overlay/buyers", response_class=HTMLResponse)
@app.get("/buyers-overlay", response_class=HTMLResponse)
@app.get("/buyers", response_class=HTMLResponse)
@app.get("/overlay/holders", response_class=HTMLResponse)
async def get_buyers_overlay():
    """Serves the Standalone OBS Current Buyers & Shareholders Overlay."""
    buyers_path = os.path.join(TEMPLATES_DIR, "buyers_overlay.html")
    with open(buyers_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/admin", response_class=HTMLResponse)
async def get_admin():
    """Serves the Streamer Admin Panel."""
    admin_path = os.path.join(TEMPLATES_DIR, "admin.html")
    with open(admin_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

DOCS_DIR = os.path.join(os.path.dirname(__file__), "docs")

@app.get("/guide", response_class=HTMLResponse)
async def get_guide():
    """Serves the Viewer Web Guide (matching GitHub Pages)."""
    guide_path = os.path.join(DOCS_DIR, "index.html")
    if os.path.exists(guide_path):
        with open(guide_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>가이드 페이지 준비 중입니다.</h1>")

# ---------------------------------------------------------
# Chzzk OpenAPI & Authentication Endpoints
# ---------------------------------------------------------
@app.get("/api/chzzk/login")
async def api_chzzk_login(redirect_uri: Optional[str] = None):
    """Redirects streamer to official Chzzk account interlock for OAuth Authorization."""
    target_redirect = redirect_uri or os.getenv("REDIRECT_URI", "http://localhost:7700/callback")
    url = chzzk_api.get_auth_url(target_redirect)
    return RedirectResponse(url=url)

@app.get("/callback")
@app.get("/api/chzzk/callback")
async def api_chzzk_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    """Handles OAuth callback code from Chzzk Developer Center."""
    if error:
        return HTMLResponse(content=f"<h3>치지직 인증 실패: {error}</h3><p><a href='/admin'>관리자 화면으로 돌아가기</a></p>", status_code=400)
    if not code:
        return HTMLResponse(content="<h3>인증 코드가 전달되지 않았습니다.</h3><p><a href='/admin'>관리자 화면으로 돌아가기</a></p>", status_code=400)

    success, msg = await chzzk_api.exchange_code(code, state or "")
    if success:
        asyncio.create_task(session_worker.reconnect())
        return RedirectResponse(url="/admin?chzzk_auth=success")
    else:
        return HTMLResponse(content=f"<h3>토큰 발급 실패: {msg}</h3><p><a href='/admin'>관리자 화면으로 돌아가기</a></p>", status_code=500)

@app.post("/api/chzzk/exchange-code")
async def api_chzzk_exchange_code(body: Dict[str, str] = Body(...)):
    """Exchanges an authorization code directly for access/refresh tokens."""
    code = body.get("code", "").strip()
    state = body.get("state", "chzzk_auth").strip()
    if not code:
        return {"success": False, "message": "인증 코드(code)를 입력해주세요."}

    success, msg = await chzzk_api.exchange_code(code, state)
    if success:
        asyncio.create_task(session_worker.reconnect())
        return {
            "success": True,
            "message": "✅ 치지직 토큰 발급 완료! 후원 이벤트 구독이 즉시 자동 시작됩니다.",
            "status": chzzk_api.get_status()
        }
    else:
        return {"success": False, "message": f"❌ 토큰 발급 실패: {msg}"}

@app.get("/api/chzzk/status")
async def api_chzzk_status():
    """Returns diagnostic status of Chzzk OpenAPI credentials, official session worker, and websocket bot."""
    st = chzzk_api.get_status()
    st["bot_websocket_connected"] = bool(bot_instance.ws and bot_instance.sid)
    st["session_worker"] = session_worker.get_status()
    st["channel_id"] = CHANNEL_ID
    return st

@app.post("/api/chzzk/subscribe-donation")
async def api_chzzk_subscribe_donation():
    """Manually triggers session worker donation subscription with current tokens."""
    ok = await session_worker.subscribe_donation_event()
    return {
        "success": ok,
        "session_worker": session_worker.get_status()
    }

@app.post("/api/chzzk/send-test")
async def api_chzzk_send_test(body: Dict[str, str] = Body(...)):
    """Sends a test notice message to Chzzk chat."""
    msg = body.get("message", "🔔 [치지직 테스트] 주식 봇이 정상 작동 중입니다.")
    ok = await dispatch_chat_notice(msg, fallback_bot=bot_instance)
    return {"success": ok, "message": msg}

@app.post("/api/chzzk/set-tokens")
async def api_chzzk_set_tokens(tokens: Dict[str, Any] = Body(...)):
    """Directly updates tokens.json with new access/refresh tokens."""
    chzzk_api.save_tokens(tokens)
    asyncio.create_task(session_worker.reconnect())
    return {"success": True, "tokens": chzzk_api.get_status()}

@app.get("/api/tracker/data")
@app.get("/data.json")
async def get_tracker_data():
    """Returns the latest real-time Mahjong tracker data (from localhost:7500/data.json)."""
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            for url in get_tracker_candidate_urls():
                try:
                    res = await client.get(url)
                    if res.status_code == 200:
                        data = res.json()
                        if isinstance(data, dict) and data.get("nickname") != "정보 없음":
                            latest_tracker_data.update(data)
                            break
                except Exception:
                    continue
    except Exception:
        pass
    return latest_tracker_data

@app.get("/api/tracker/status")
async def get_tracker_status(db=Depends(get_db)):
    """Returns the real-time status of the Mahjong 7500 tracker connection."""
    now = time.time()
    is_live = bool(last_tracker_received_at and (now - last_tracker_received_at < 15))
    state = te.get_market_state(db)
    return {
        "connected": is_live,
        "last_received_at": last_tracker_received_at,
        "seconds_ago": round(now - last_tracker_received_at, 1) if last_tracker_received_at else None,
        "source": last_tracker_source,
        "current_price": state.current_price,
        "current_rank_point": state.current_rank_point,
        "day_open_price": state.day_open_price,
        "last_synced_pts": last_synced_pts,
        "last_synced_record": last_synced_record,
        "tracker_data": latest_tracker_data,
    }

@app.post("/api/tracker/push")
async def push_tracker_data(req: Dict[str, Any] = Body(...), force_settle: bool = Query(False)):
    """
    POST /api/tracker/push
    Client-side relay endpoint (from OBS overlays or Admin browser on host) to push
    http://localhost:7500/data.json directly into the backend engine.
    """
    force = force_settle or bool(req.get("force_settle"))
    data = req.get("data") if ("data" in req and isinstance(req["data"], dict)) else req
    res = await process_tracker_update(data, source="client_push", force_settle=force)
    return res

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for OBS overlay and Admin live tickers."""
    await manager.connect(websocket)
    try:
        while True:
            text = await websocket.receive_text()
            try:
                msg = json.loads(text)
                if isinstance(msg, dict):
                    action = msg.get("action") or msg.get("type")
                    if action == "tracker_push":
                        t_data = msg.get("data") or msg.get("tracker_data")
                        force = bool(msg.get("force_settle"))
                        if isinstance(t_data, dict):
                            await process_tracker_update(t_data, source="ws_relay", force_settle=force)
            except Exception:
                pass
    except (WebSocketDisconnect, Exception):
        manager.disconnect(websocket)

# ---------------------------------------------------------
# Admin & Streamer Control Endpoints
# ---------------------------------------------------------
@app.post("/api/admin/lock-market")
async def api_lock_market(req: Optional[LockMarketRequest] = None, db=Depends(get_db)):
    """
    POST /api/admin/lock-market
    Toggles or sets the trading lock status.
    """
    global free_trading_task, free_trading_end_time
    state = te.get_market_state(db)
    if req and req.locked is not None:
        state.is_trading_locked = req.locked
    else:
        state.is_trading_locked = not state.is_trading_locked

    if state.is_trading_locked:
        if free_trading_task and not free_trading_task.done():
            free_trading_task.cancel()
        free_trading_end_time = None
        state.free_trading_end_time = 0.0

    db.commit()
    db.refresh(state)

    rem_sec = get_free_trading_remaining(state)
    # Broadcast to OBS overlays
    await manager.broadcast({
        "type": "market_lock",
        "is_trading_locked": state.is_trading_locked,
        "free_trading_remaining": rem_sec
    })

    return {
        "success": True,
        "is_trading_locked": state.is_trading_locked,
        "free_trading_remaining": rem_sec,
        "message": f"시장 상태가 '{'경기 중 - 거래 마감' if state.is_trading_locked else '장 열림'}'으로 변경되었습니다."
    }

@app.post("/api/admin/start-free-trading")
async def api_start_free_trading(seconds: Optional[int] = Body(default=300, embed=True)):
    """
    POST /api/admin/start-free-trading
    Manually start or reset the 5-minute free trading window timer (default 300s).
    """
    sec = seconds or 300
    await start_free_trading_window(sec)
    return {
        "success": True,
        "is_trading_locked": False,
        "duration_seconds": sec,
        "remaining_seconds": sec,
        "message": f"{sec // 60}분 자유 거래 시간이 시작되었습니다."
    }

@app.post("/api/admin/settle-match")
async def api_settle_match(req: SettleMatchRequest, db=Depends(get_db)):
    """
    POST /api/admin/settle-match
    Settles match outcome: updates rank points, recalculates base price,
    rebalances leveraged/derivative positions, checks liquidations, and starts 5-min free trading window.
    """
    result = te.settle_match(db, rank=req.rank, point_delta=req.point_delta)
    leaderboard = te.get_leaderboard(db, top_n=3)
    state = te.get_market_state(db)

    # 5분 자유 거래 시간 자동 오픈 (300초 카운트다운 후 자동 마감)
    await start_free_trading_window(300)

    # Broadcast settlement event and liquidations
    settlement_event = {
        "type": "settlement",
        **result,
        "leaderboard": leaderboard,
        "free_trading_remaining": 300,
        "market_state": serialize_market_state(state)
    }
    await manager.broadcast(settlement_event)

    if result.get("dividends"):
        div_count = len(result["dividends"])
        total_div = sum(d["payout"] for d in result["dividends"])
        pct_label = "5%" if req.rank == 1 else ("1%" if req.rank == 2 else "")
        div_chat = f"🎁 [{req.rank}위 승리 배당] 1X(기본주) 주주 총 {div_count}명에게 {pct_label} 배당금(총 +{total_div:,}P) 지급 완료!"
        asyncio.create_task(dispatch_chat_notice(div_chat, fallback_bot=bot_instance))

    if result.get("liquidations"):
        liq_count = len(result["liquidations"])
        liq_chat = f"🚨 [마진콜 경고] 총 {liq_count}건의 레버리지/인버스 포지션이 전액 강제 청산되었습니다!"
        asyncio.create_task(dispatch_chat_notice(liq_chat, fallback_bot=bot_instance))

    if result.get("delisted"):
        delist_info = result["delisting_info"]
        sync_docs_market_state(state)
        await manager.broadcast({
            "type": "delisting",
            "delisting_info": delist_info,
            "settlement": result,
            "leaderboard": leaderboard,
            "free_trading_remaining": 300,
            "market_state": serialize_market_state(state)
        })
        delist_chat = (
            f"🚨🚨 [긴급 속보: 상장폐지 & 신규 상장] 경기 정산으로 작성2 강등! "
            f"작성3 종목이 전격 [상장폐지]되고 기존 주식은 전량 [휴짓조각(0주)] 처리되었습니다! "
            f"신규 종목 [작성2] (시작가 {state.current_price:,}P) 신규 상장 및 거래 오픈!"
        )
        asyncio.create_task(dispatch_chat_notice(delist_chat, fallback_bot=bot_instance))

    return {
        "success": True,
        **result,
        "free_trading_remaining": 300
    }

@app.post("/api/admin/delist")
async def api_delist(req: Optional[DelistRequest] = None, db=Depends(get_db)):
    """
    POST /api/admin/delist
    Demote and execute delisting (상장폐지) of the old rank stock, wiping existing stock shares to 0,
    and launching the new stock at starting points (e.g. 작성2 at 3,000P).
    """
    old_r = req.old_rank if req and req.old_rank else "작성3"
    new_r = req.new_rank if req and req.new_rank else "작성2"
    pts = req.starting_points if req and req.starting_points else 3000

    delist_res = te.execute_delisting_and_relist(db, old_rank=old_r, new_rank=new_r, starting_points=pts)
    state = te.get_market_state(db)
    sync_docs_market_state(state)

    await start_free_trading_window(300)

    await manager.broadcast({
        "type": "delisting",
        "delisting_info": delist_res,
        "market_state": serialize_market_state(state),
        "free_trading_remaining": 300
    })

    delist_chat = (
        f"🚨🚨 [긴급 속보: 상장폐지 & 신규 상장] 치즈나베의 '{old_r}' 강등으로 인해 {old_r} 종목이 전격 [상장폐지]되었습니다! "
        f"기존 주주 총 {delist_res['wiped_positions_count']}명의 주식이 전량 [휴짓조각(0주)] 처리되었습니다. "
        f"신규 종목 [{new_r}] (시작가 {state.current_price:,}P)가 새로 상장되어 거래가 시작됩니다!"
    )
    asyncio.create_task(dispatch_chat_notice(delist_chat, fallback_bot=bot_instance))

    return {
        "success": True,
        "delisting_info": delist_res,
        "market_state": serialize_market_state(state),
        "free_trading_remaining": 300
    }

@app.post("/api/admin/grant-points")
async def api_grant_points(req: GrantPointsRequest, db=Depends(get_db)):
    """
    POST /api/admin/grant-points
    Administrative grant/reset for viewer testing.
    Resolves existing viewer by ID or Nickname.
    """
    target = (req.username or req.user_id or "").strip()
    user = te.get_user_by_identifier(db, req.user_id)
    if not user and req.username:
        user = te.get_user_by_identifier(db, req.username)
    if not user:
        user = te.get_or_create_user(db, req.user_id, target)

    if req.mode == "set":
        user.points = req.points
    else:
        user.points += req.points

    db.commit()
    db.refresh(user)

    leaderboard = te.get_leaderboard(db, top_n=3)
    await manager.broadcast({
        "type": "leaderboard_update",
        "leaderboard": leaderboard
    })

    return {
        "success": True,
        "user_id": user.id,
        "username": user.username,
        "points": user.points
    }

@app.get("/api/admin/users")
async def api_admin_users(db=Depends(get_db)):
    """GET /api/admin/users - Returns list of all registered viewers with complete assets, equipment, and items."""
    state = te.get_market_state(db)
    now = time.time()
    users = db.query(User).all()
    res = []
    for u in users:
        uid_lower = (u.id or "").lower()
        uname_lower = (u.username or "").lower()
        if (
            any(uid_lower.startswith(p) for p in ("fresh_", "test_", "viewer_", "strictly_", "dummy_", "sim_", "bug_", "user_temp", "u_"))
            or any(uname_lower.startswith(p) for p in ("테스터", "유저_", "새유저", "철통잠금", "더미", "테스트", "임시유저", "임시"))
            or uname_lower in ("테스트유저", "시청자1", "타이머만료유저", "후원테스터", "마진유저", "임시유저")
            or uid_lower in ("user_temp_123", "u_매수_10x_올인")
        ):
            continue

        # 1. Stock positions & valuation
        positions = []
        total_stock_value = 0.0
        for p in (u.positions or []):
            if p.quantity > 0:
                val = te.calculate_position_valuation(p, state.current_price)
                cur_val = round(val["current_value"], 1)
                total_stock_value += cur_val
                p_name = p.product_type.value if hasattr(p.product_type, "value") else str(p.product_type)
                positions.append({
                    "product_type": p_name,
                    "quantity": p.quantity,
                    "entry_price": p.entry_price,
                    "invested_cash": p.invested_cash,
                    "current_value": cur_val,
                    "unit_price": round(val["unit_price"], 1),
                    "unrealized_pnl": round(val["unrealized_pnl"], 1),
                    "pnl_pct": round(val["pnl_pct"], 2)
                })

        cash = u.points
        debt = getattr(u, "debt", 0) or 0
        net_worth = int(round(cash + total_stock_value - debt))

        # 2. Equipments & Potentials
        equipments = []
        equipped_item = None
        for eq in (u.equipments or []):
            pot_tier = (eq.potential_tier or "NONE").upper()
            lines = []
            for raw_l in [eq.potential_line_1, eq.potential_line_2, eq.potential_line_3]:
                if raw_l:
                    try:
                        parsed = json.loads(raw_l) if isinstance(raw_l, str) else raw_l
                        if isinstance(parsed, dict):
                            lines.append(parsed.get("text", str(parsed)))
                        else:
                            lines.append(str(parsed))
                    except Exception:
                        lines.append(str(raw_l))
                else:
                    lines.append(None)

            eq_dict = {
                "id": eq.id,
                "name": eq.name,
                "starforce": eq.starforce,
                "is_equipped": eq.is_equipped,
                "potential_tier": pot_tier,
                "potential_tier_display": te.CUBE_TIER_DISPLAY.get(pot_tier, pot_tier),
                "potential_lines": lines,
                "pity_count": getattr(eq, "pity_count", 0) or 0
            }
            equipments.append(eq_dict)
            if eq.is_equipped:
                equipped_item = eq_dict

        # 3. Items & Consumables
        auto_until = getattr(u, "auto_mining_until", 0.0) or 0.0
        items = {
            "shield_scroll_count": getattr(u, "shield_scroll_count", 0) or 0,
            "boost_scroll_count": getattr(u, "boost_scroll_count", 0) or 0,
            "downgrade_scroll_count": getattr(u, "downgrade_scroll_count", 0) or 0,
            "cube_count": getattr(u, "cube_count", 0) or 0,
            "cube_fragments": getattr(u, "cube_fragments", 0) or 0,
            "auto_mining_active": bool(auto_until > now),
            "auto_mining_remaining_sec": max(0, int(auto_until - now))
        }

        res.append({
            "id": u.id,
            "username": u.username,
            "points": u.points,
            "cash": cash,
            "debt": debt,
            "net_worth": net_worth,
            "stock_value": round(total_stock_value, 1),
            "total_mined": getattr(u, "total_mined", 0.0) or 0.0,
            "positions": positions,
            "equipments": equipments,
            "equipped_item": equipped_item,
            "items": items
        })

    res.sort(key=lambda x: x["net_worth"], reverse=True)
    return {"success": True, "users": res}

@app.post("/api/admin/reset-market")
async def api_reset_market(db=Depends(get_db)):
    """Reset market state to default values for testing."""
    state = te.get_market_state(db)
    state.current_rank_name = "작성3"
    state.current_rank_point = 2340
    state.current_price = 2340
    state.previous_price = 2340
    state.is_trading_locked = False
    state.last_settlement_delta = 0
    db.commit()

    leaderboard = te.get_leaderboard(db, top_n=3)
    await manager.broadcast({
        "type": "market_update",
        "market_state": serialize_market_state(state),
        "leaderboard": leaderboard
    })
    return {"success": True, "message": "시장 상태가 기본값(2340pt, 2340P)으로 초기화되었습니다."}

@app.post("/api/admin/set-day-open")
async def api_set_day_open(req: Optional[SetDayOpenRequest] = None, db=Depends(get_db)):
    """POST /api/admin/set-day-open - Set today's opening rank point / stock price baseline."""
    price_val = req.price if req else None
    target_price = te.set_day_open_price(db, price_val)
    state = te.get_market_state(db)

    sync_docs_market_state(state)
    market_serialized = serialize_market_state(state)
    leaderboard = te.get_leaderboard(db, top_n=3)

    await manager.broadcast({
        "type": "market_update",
        "market_state": market_serialized,
        "leaderboard": leaderboard
    })
    return {
        "success": True,
        "day_open_price": target_price,
        "message": f"당일 시가가 {target_price:,}P로 설정되었습니다."
    }

# ---------------------------------------------------------
# Chat Command Simulator & Public APIs
# ---------------------------------------------------------
@app.post("/api/chat/command")
async def api_chat_command(req: ChatCommandRequest, db=Depends(get_db)):
    """Test chat command dispatcher via HTTP."""
    reply, event = handle_chat_command(db, req.user_id, req.username, req.message)

    if reply:
        asyncio.create_task(dispatch_chat_notice(reply, fallback_bot=bot_instance))

    if event:
        record_trade_event(event)
        leaderboard = te.get_leaderboard(db, top_n=3)
        state = te.get_market_state(db)
        await manager.broadcast({
            **event,
            "leaderboard": leaderboard,
            "market_state": serialize_market_state(state),
            "recent_trades": list(recent_trades)
        })

    return {
        "success": True,
        "reply": reply,
        "event": event
    }

@app.post("/api/transfer")
async def api_transfer(req: TransferRequest, db=Depends(get_db)):
    """API endpoint to execute account transfer between users."""
    success, reply, details = te.execute_transfer(
        db, req.sender_id, req.sender_username or "이체자", req.target_name, req.amount
    )
    if not success:
        raise HTTPException(status_code=400, detail=reply)

    event = {"type": "account_transfer", "data": details}
    record_trade_event(event)
    leaderboard = te.get_leaderboard(db, top_n=3)
    state = te.get_market_state(db)
    await manager.broadcast({
        **event,
        "leaderboard": leaderboard,
        "market_state": serialize_market_state(state),
        "recent_trades": list(recent_trades)
    })
    return {"success": True, "reply": reply, "details": details}

@app.get("/api/market/state")
async def api_market_state(db=Depends(get_db)):
    state = te.get_market_state(db)
    m = serialize_market_state(state)
    day_open = m["day_open_price"]
    day_diff = state.current_price - day_open
    day_diff_pct = (day_diff / day_open * 100.0) if day_open > 0 else 0.0
    sync_docs_market_state(state)
    return {
        **m,
        "day_diff": day_diff,
        "day_diff_pct": day_diff_pct,
        "free_trading_end_time": free_trading_end_time
    }

@app.post("/api/admin/refill-treasury")
async def api_refill_treasury(amount: Optional[float] = Body(default=500000.0, embed=True), db=Depends(get_db)):
    """POST /api/admin/refill-treasury - Replenish the community treasury pool."""
    state = te.get_market_state(db)
    fill_amount = amount or 500000.0
    state.treasury_pool = max(state.treasury_pool, fill_amount)
    db.commit()
    await manager.broadcast({
        "type": "market_update",
        "market_state": serialize_market_state(state)
    })
    return {"success": True, "treasury_pool": state.treasury_pool, "message": f"국고가 {int(state.treasury_pool):,}P로 보충되었습니다."}

@app.get("/api/admin/bankruptcy/pending")
async def api_get_pending_bankruptcies(db=Depends(get_db)):
    """GET /api/admin/bankruptcy/pending - List all pending bankruptcy applications for streamer ruling."""
    applications = te.get_pending_bankruptcy_applications(db)
    return {"success": True, "applications": applications}

@app.post("/api/admin/bankruptcy/judge")
async def api_judge_bankruptcy(req: BankruptcyJudgeRequest, db=Depends(get_db)):
    """POST /api/admin/bankruptcy/judge - Streamer delivers verdict ('full', 'half', 'reject')."""
    success, reply, details = te.judge_bankruptcy_application(
        db, req.app_id, req.verdict, req.comment or ""
    )
    if not success:
        raise HTTPException(status_code=400, detail=reply)

    if reply:
        asyncio.create_task(dispatch_chat_notice(reply, fallback_bot=bot_instance))

    state = te.get_market_state(db)
    leaderboard = te.get_leaderboard(db, top_n=3)
    await manager.broadcast({
        "type": "bankruptcy_verdict",
        "data": details,
        "leaderboard": leaderboard,
        "market_state": serialize_market_state(state)
    })

    return {"success": True, "reply": reply, "data": details}

@app.post("/api/casino/open")
async def api_casino_open(req: Optional[CasinoOpenRequest] = None, db=Depends(get_db)):
    """POST /api/casino/open - Streamer opens casino via Admin panel."""
    dur = req.duration_minutes if req else 3.0
    max_b = req.max_bet if req else 10000000
    success, reply, details = te.open_casino(db, duration_minutes=dur, max_bet=max_b)
    if not success:
        raise HTTPException(status_code=400, detail=reply)

    if reply:
        asyncio.create_task(dispatch_chat_notice(reply, fallback_bot=bot_instance))

    state = te.get_market_state(db)
    leaderboard = te.get_leaderboard(db, top_n=3)
    await manager.broadcast({
        "type": "casino_open",
        "data": details,
        "leaderboard": leaderboard,
        "market_state": serialize_market_state(state)
    })
    return {"success": True, "reply": reply, "data": details, "market_state": serialize_market_state(state)}

@app.post("/api/casino/close")
async def api_casino_close(db=Depends(get_db)):
    """POST /api/casino/close - Streamer closes casino via Admin panel."""
    success, reply, details = te.close_casino(db)
    if not success:
        raise HTTPException(status_code=400, detail=reply)

    if reply:
        asyncio.create_task(dispatch_chat_notice(reply, fallback_bot=bot_instance))

    state = te.get_market_state(db)
    leaderboard = te.get_leaderboard(db, top_n=3)
    await manager.broadcast({
        "type": "casino_close",
        "data": details,
        "leaderboard": leaderboard,
        "market_state": serialize_market_state(state)
    })
    return {"success": True, "reply": reply, "data": details, "market_state": serialize_market_state(state)}

@app.get("/api/casino/status")
async def api_casino_status(db=Depends(get_db)):
    """GET /api/casino/status - Current casino and treasury status."""
    c_state = te.get_casino_state(db)
    t_info = te.get_treasury_info(db)
    return {
        "success": True,
        "casino": c_state,
        "treasury": t_info
    }

@app.post("/api/lottery/open")
@app.post("/api/admin/lottery/open")
async def api_lottery_open(req: Optional[LotteryOpenRequest] = None, db=Depends(get_db)):
    """POST /api/admin/lottery/open - Streamer opens State Welfare Lottery event via Admin panel."""
    dur = req.duration_minutes if req and req.duration_minutes else 10
    title = req.title if req and req.title else "국가 복지 복권"
    success, reply, details = te.open_lottery_event(db, duration_minutes=dur, title=title)
    if not success:
        raise HTTPException(status_code=400, detail=reply)

    if reply:
        asyncio.create_task(dispatch_chat_notice(reply, fallback_bot=bot_instance))

    state = te.get_market_state(db)
    sync_docs_market_state(state)
    await manager.broadcast({
        "type": "lottery_event_started",
        "data": details,
        "market_state": serialize_market_state(state)
    })
    return {"success": True, "reply": reply, "data": details, "market_state": serialize_market_state(state)}

@app.post("/api/lottery/close")
@app.post("/api/admin/lottery/close")
async def api_lottery_close(db=Depends(get_db)):
    """POST /api/admin/lottery/close - Streamer closes State Welfare Lottery event via Admin panel."""
    success, reply, details = te.close_lottery_event(db)
    if not success:
        raise HTTPException(status_code=400, detail=reply)

    if reply:
        asyncio.create_task(dispatch_chat_notice(reply, fallback_bot=bot_instance))

    state = te.get_market_state(db)
    sync_docs_market_state(state)
    await manager.broadcast({
        "type": "lottery_event_ended",
        "data": details,
        "market_state": serialize_market_state(state)
    })
    return {"success": True, "reply": reply, "data": details, "market_state": serialize_market_state(state)}

@app.get("/api/lottery/status")
async def api_lottery_status(db=Depends(get_db)):
    """GET /api/lottery/status - Current lottery event and treasury status."""
    l_state = te.get_lottery_event_state(db)
    t_info = te.get_treasury_info(db)
    return {
        "success": True,
        "lottery": l_state,
        "treasury": t_info
    }

@app.post("/api/merchant/open")
@app.post("/api/admin/merchant/open")
async def api_merchant_open(req: Optional[MerchantOpenRequest] = None, db=Depends(get_db)):
    """POST /api/admin/merchant/open - Streamer opens Mysterious Merchant event via Admin panel."""
    dur = req.duration_minutes if req and req.duration_minutes else 10
    name = req.merchant_name if req and req.merchant_name else "신비상인"
    success, reply, details = te.open_merchant(db, duration_minutes=dur, name=name)
    if not success:
        raise HTTPException(status_code=400, detail=reply)

    if reply:
        asyncio.create_task(dispatch_chat_notice(reply, fallback_bot=bot_instance))

    state = te.get_market_state(db)
    sync_docs_market_state(state)
    await manager.broadcast({
        "type": "merchant_appeared",
        "data": details,
        "market_state": serialize_market_state(state)
    })
    return {"success": True, "reply": reply, "data": details, "market_state": serialize_market_state(state)}

@app.post("/api/merchant/close")
@app.post("/api/admin/merchant/close")
async def api_merchant_close(db=Depends(get_db)):
    """POST /api/admin/merchant/close - Streamer closes Mysterious Merchant event via Admin panel."""
    success, reply, details = te.close_merchant(db)
    if not success:
        raise HTTPException(status_code=400, detail=reply)

    if reply:
        asyncio.create_task(dispatch_chat_notice(reply, fallback_bot=bot_instance))

    state = te.get_market_state(db)
    sync_docs_market_state(state)
    await manager.broadcast({
        "type": "merchant_left",
        "data": details,
        "market_state": serialize_market_state(state)
    })
    return {"success": True, "reply": reply, "data": details, "market_state": serialize_market_state(state)}

@app.get("/api/merchant/status")
async def api_merchant_status(db=Depends(get_db)):
    """GET /api/merchant/status - Current Mysterious Merchant status and items."""
    m_state = te.get_merchant_state(db)
    t_info = te.get_treasury_info(db)
    return {
        "success": True,
        "merchant": m_state,
        "treasury": t_info
    }

@app.get("/api/leaderboard")
async def api_get_leaderboard(top_n: int = 3, db=Depends(get_db)):
    return te.get_leaderboard(db, top_n=top_n)

@app.get("/api/buyers")
async def api_get_buyers(limit: int = 100, db=Depends(get_db)):
    """GET /api/buyers - Returns real-time list of current buyers/shareholders with positions, valuation, and market breakdown."""
    data = te.get_current_buyers(db, limit=limit)
    return {
        "success": True,
        **data,
        "recent_trades": list(recent_trades)
    }

@app.get("/api/user/{user_id}")
async def api_get_user(user_id: str, db=Depends(get_db)):
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    state = te.get_market_state(db)

    positions = []
    for p in user.positions:
        if p.quantity > 0:
            val = te.calculate_position_valuation(p, state.current_price)
            positions.append({
                "product_type": p.product_type.value,
                "quantity": p.quantity,
                "entry_price": p.entry_price,
                "invested_cash": p.invested_cash,
                "current_value": val["current_value"],
                "pnl": val["unrealized_pnl"],
                "pnl_pct": val["pnl_pct"]
            })

    return {
        "id": user.id,
        "username": user.username,
        "points": user.points,
        "positions": positions
    }

# ---------------------------------------------------------
# Chzzk Donation & DB Safety / Backup Endpoints
# ---------------------------------------------------------
@app.post("/api/chzzk/donation")
async def api_chzzk_donation(payload: Dict[str, Any] = Body(...)):
    """
    POST /api/chzzk/donation:
    Receives Chzzk donation event, validates input, prevents duplicates,
    creates pre-transaction backup, and credits points at 1 KRW : 100 Points ratio.
    """
    success, reply, details = await handle_donation_event(payload, fallback_bot=bot_instance)
    if not success:
        return {"success": False, "message": reply}
    return {"success": True, "message": reply, "details": details}

@app.get("/api/donations/history")
async def api_donations_history(limit: int = 20, db=Depends(get_db)):
    """GET /api/donations/history - List recent donations with credited points."""
    history = te.get_donation_history(db, limit=limit)
    return {"success": True, "donations": history}

@app.post("/api/admin/db/backup")
async def api_admin_db_backup(reason: Optional[str] = Body(default="manual", embed=True)):
    """POST /api/admin/db/backup - Safely triggers an online hot backup of the SQLite database."""
    ok, msg, path = db_backup.create_backup(reason=reason or "manual")
    return {"success": ok, "message": msg, "path": path}

@app.get("/api/admin/db/backups")
async def api_admin_db_backups():
    """GET /api/admin/db/backups - List all stored database backups."""
    backups = db_backup.list_backups()
    return {"success": True, "backups": backups}

@app.post("/api/admin/db/restore")
async def api_admin_db_restore(filename: str = Body(..., embed=True)):
    """POST /api/admin/db/restore - Safely restores database from a designated backup after verification."""
    ok, msg = db_backup.restore_backup(filename)
    return {"success": ok, "message": msg}

@app.get("/api/admin/db/verify")
async def api_admin_db_verify():
    """GET /api/admin/db/verify - Runs PRAGMA integrity_check and returns database health status."""
    res = db_backup.verify_db_integrity()
    return res

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=7700, reload=True)