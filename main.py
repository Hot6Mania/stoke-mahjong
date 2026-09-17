import os
import json
import time
import asyncio
from typing import Set, Optional, Dict, Any, List, Tuple
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
import httpx
import websockets
from dotenv import load_dotenv
import uvicorn

import re
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
    "score": "2340/9000 (3055)",
    "score_diff": "▼715",
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
    """Extract current rank points from score string e.g. '2340/9000 (3055)' -> 2340."""
    if not score_str:
        return None
    m = re.search(r"(\d+)\s*/", score_str)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*(?:pt|점)", score_str, re.IGNORECASE)
    if m:
        return int(m.group(1))
    nums = re.findall(r"\b\d{3,5}\b", score_str)
    if nums:
        return int(nums[0])
    return None

def extract_day_start_points(score_str: str) -> Optional[int]:
    """Extract today's starting rank points from score string e.g. '2340/9000 (3055)' -> 3055."""
    if not score_str:
        return None
    m = re.search(r"\(\s*(\d+)\s*\)", score_str)
    if m:
        return int(m.group(1))
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
    c_max_bet = getattr(state, "casino_max_bet", 100000) or 100000
    if c_open and c_end and c_end > 0 and time.time() > c_end:
        c_open = False
        c_rem = 0

    res = {
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
        "casino_max_bet": c_max_bet
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
            print(f"[Donation] 🎉 [1:100 충전 성공] {details['username']} +{details['points_credited']:,}P (현재 잔고: {details['remaining_points']:,}P)")
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
                                            record_trade_event(event)
                                            # Broadcast trade/order update to OBS overlay immediately
                                            leaderboard = te.get_leaderboard(db, top_n=3)
                                            state = te.get_market_state(db)
                                            await manager.broadcast({
                                                **event,
                                                "leaderboard": leaderboard,
                                                "market_state": serialize_market_state(state),
                                                "recent_trades": list(recent_trades)
                                            })

                                        if reply:
                                            asyncio.create_task(dispatch_chat_notice(reply, fallback_bot=self))
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
async def sync_tracker_loop():
    """Background task to sync real mahjong stats from http://127.0.0.1:7500/data.json."""
    while True:
        try:
            async with httpx.AsyncClient(timeout=1.5) as client:
                for url in ["http://127.0.0.1:7500/data.json", "http://localhost:7500/data.json"]:
                    try:
                        res = await client.get(url)
                        if res.status_code == 200:
                            data = res.json()
                            if isinstance(data, dict) and data.get("nickname") != "정보 없음":
                                latest_tracker_data.update(data)

                                # Check if rank points changed
                                score_str = data.get("score", "")
                                pts = extract_rank_points(score_str)
                                day_start = extract_day_start_points(score_str)

                                if pts is not None and pts > 0:
                                    db = SessionLocal()
                                    try:
                                        state = te.get_market_state(db)
                                        if day_start and getattr(state, "day_open_price", None) != day_start:
                                            state.day_open_price = day_start
                                            db.commit()

                                        if state.current_rank_point != pts:
                                            delta = pts - state.current_rank_point
                                            rank = 1 if delta > 0 else (3 if delta < 0 else 2)
                                            settle_res = te.settle_match(db, rank=rank, point_delta=delta)
                                            leaderboard = te.get_leaderboard(db, top_n=3)

                                            # 5분 자유 거래 시간 자동 오픈 (300초 카운트다운 후 자동 마감)
                                            await start_free_trading_window(300)

                                            if settle_res.get("liquidations"):
                                                liq_count = len(settle_res["liquidations"])
                                                liq_chat = f"🚨 [마진콜 경고] 총 {liq_count}건의 레버리지/인버스 포지션이 강제 청산되었습니다!"
                                                asyncio.create_task(dispatch_chat_notice(liq_chat, fallback_bot=bot_instance))

                                            await manager.broadcast({
                                                "type": "settlement",
                                                **settle_res,
                                                "tracker_data": latest_tracker_data,
                                                "leaderboard": leaderboard,
                                                "free_trading_remaining": 300,
                                                "market_state": serialize_market_state(state)
                                            })
                                        else:
                                            # Periodic tracker update broadcast
                                            await manager.broadcast({
                                                "type": "tracker_update",
                                                "tracker_data": latest_tracker_data,
                                                "market_state": serialize_market_state(state)
                                            })
                                    finally:
                                        db.close()
                                break
                    except Exception:
                        continue
        except Exception:
            pass
        await asyncio.sleep(2)

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

    yield

    bot_task.cancel()
    session_task.cancel()
    tracker_task.cancel()

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

class SettleMatchRequest(BaseModel):
    rank: int
    point_delta: int

class GrantPointsRequest(BaseModel):
    user_id: str
    username: Optional[str] = None
    points: int
    mode: Optional[str] = "add"

class ChatCommandRequest(BaseModel):
    user_id: str
    username: str
    message: str

class BankruptcyJudgeRequest(BaseModel):
    app_id: int
    verdict: str
    comment: Optional[str] = ""

class CasinoOpenRequest(BaseModel):
    duration_minutes: float = 3.0
    max_bet: int = 100000

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
            res = await client.get("http://127.0.0.1:7500/data.json")
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, dict) and data.get("nickname") != "정보 없음":
                    latest_tracker_data.update(data)
    except Exception:
        pass
    return latest_tracker_data

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for OBS overlay and Admin live tickers."""
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
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

    if result.get("liquidations"):
        liq_count = len(result["liquidations"])
        liq_chat = f"🚨 [마진콜 경고] 총 {liq_count}건의 레버리지/인버스 포지션이 전액 강제 청산되었습니다!"
        asyncio.create_task(dispatch_chat_notice(liq_chat, fallback_bot=bot_instance))

    return {
        "success": True,
        **result,
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
    """GET /api/admin/users - Returns list of all registered viewers with points and debt."""
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
        res.append({
            "id": u.id,
            "username": u.username,
            "points": u.points,
            "debt": getattr(u, "debt", 0) or 0,
            "total_mined": getattr(u, "total_mined", 0.0) or 0.0
        })
    res.sort(key=lambda x: x["points"], reverse=True)
    return {"success": True, "users": res}

@app.post("/api/admin/reset-market")
async def api_reset_market(db=Depends(get_db)):
    """Reset market state to default values for testing."""
    state = te.get_market_state(db)
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
    max_b = req.max_bet if req else 100000
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