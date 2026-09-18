import os
import json
import time
import asyncio
from typing import Set, Optional, Dict, Any, List, Tuple, Union
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Body, Query, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from pydantic import BaseModel
import httpx
import websockets
from dotenv import load_dotenv
import uvicorn

import re
import socket
import struct
import ipaddress
from database import init_db, get_db, SessionLocal
from sqlalchemy.orm import Session
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
            },
            "snipe": {
                "name": "🎯 잠재저격주문서",
                "price": getattr(state, "merchant_snipe_price", 500000) or 500000,
                "stock": getattr(state, "merchant_snipe_stock", 3) or 0,
            }
        }
    }
    return res

def serialize_user_inspector_data(u: User, state: MarketState, now: float, db: Optional[Session] = None) -> Dict[str, Any]:
    """Serializes a single user's assets, positions, equipment, items, and asset history for inspection."""
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
    bank_info = te.get_user_bank_info(db, u, state) if db else {
        "bank_balance": getattr(u, "bank_balance", 0) or 0,
        "points": cash,
        "interest_rate_pct": 0.5,
        "savings": None,
        "fund": {"units": 0.0, "valuation": 0, "nav": 1000.0, "pnl": 0, "pnl_pct": 0.0},
        "fund_valuation": 0,
        "insurance": None,
        "credit": te.get_user_credit_info(u, market_state=state),
        "debt": debt,
        "special_snipe_scrolls": te.get_user_special_snipe_scrolls(u)
    }
    bank_bal = int(bank_info.get("bank_balance", 0) or 0)
    fund_val = int(bank_info.get("fund_valuation", 0) or 0)
    net_worth = int(round(cash + bank_bal + fund_val + total_stock_value - debt))

    # 2. Equipments & Potentials
    equipments = []
    equipped_item = None
    sf_state = te.get_starforce_event_state(db) if db else None
    user_eq_list = te.ensure_user_equipment(db, u) if db else (u.equipments or [])
    for eq in user_eq_list:
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

        sf_info = te.get_pickaxe_info(eq.starforce or 0, event_state=sf_state)
        pot_eff = te.get_equipment_potential_effects(eq)
        pot_discount_pct = min(50.0, float(pot_eff.get("starforce_discount_pct", 0.0)))
        upg_cost = sf_info["upgrade_cost"]
        if pot_discount_pct > 0:
            upg_cost = max(100, int(round(upg_cost * (1.0 - pot_discount_pct / 100.0))))

        eq_dict = {
            "id": eq.id,
            "name": eq.name,
            "starforce": eq.starforce,
            "is_equipped": eq.is_equipped,
            "is_cube_locked": getattr(eq, "is_cube_locked", False) or False,
            "is_line1_locked": getattr(eq, "is_line1_locked", False) or False,
            "is_line2_locked": getattr(eq, "is_line2_locked", False) or False,
            "is_line3_locked": getattr(eq, "is_line3_locked", False) or False,
            "potential_tier": pot_tier,
            "potential_tier_display": te.CUBE_TIER_DISPLAY.get(pot_tier, pot_tier),
            "potential_lines": lines,
            "pity_count": getattr(eq, "pity_count", 0) or 0,
            "info": sf_info,
            "upgrade_cost": upg_cost,
            "effects": pot_eff
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
        "snipe_scroll_count": getattr(u, "snipe_scroll_count", 0) or 0,
        "special_snipe_scrolls": te.get_user_special_snipe_scrolls(u) if hasattr(te, "get_user_special_snipe_scrolls") else {},
        "cube_count": getattr(u, "cube_count", 0) or 0,
        "cube_fragments": getattr(u, "cube_fragments", 0) or 0,
        "arm_shield": getattr(u, "arm_shield", True),
        "arm_downgrade": getattr(u, "arm_downgrade", True),
        "arm_boost": getattr(u, "arm_boost", False),
        "arm_snipe": getattr(u, "arm_snipe", False),
        "auto_mining_active": bool(auto_until > now),
        "auto_mining_remaining_sec": max(0, int(auto_until - now))
    }

    # Mining Status & Cooldown
    eq_item_obj = te.get_user_equipped_item(db, u) if db else None
    eq_lvl = eq_item_obj.starforce if eq_item_obj else getattr(u, "pickaxe_level", 0) or 0
    eq_lvl = max(0, min(30, int(eq_lvl)))
    p_info = te.get_pickaxe_info(eq_lvl, event_state=sf_state)
    pot_eff_equipped = te.get_equipment_potential_effects(eq_item_obj) if eq_item_obj else {}
    pot_cd_red = pot_eff_equipped.get("mining_cd_reduction", 0)
    heavy_cd_add = pot_eff_equipped.get("heavy_mining_cd_add", 0)
    effective_cd_min = max(2, p_info["cooldown_minutes"] - pot_cd_red + heavy_cd_add)
    cooldown_sec = effective_cd_min * 60

    remaining_cd_sec = 0
    next_mine_time_epoch = 0.0
    last_mined_epoch = 0.0
    if u.last_mined_at:
        last_t = u.last_mined_at if u.last_mined_at.tzinfo else u.last_mined_at.replace(tzinfo=timezone.utc)
        last_mined_epoch = last_t.timestamp()
        elapsed = (datetime.now(timezone.utc) - last_t).total_seconds()
        if elapsed < cooldown_sec:
            remaining_cd_sec = int(cooldown_sec - elapsed)
            next_mine_time_epoch = last_mined_epoch + cooldown_sec

    mining_status = {
        "can_mine": remaining_cd_sec <= 0,
        "remaining_cd_sec": remaining_cd_sec,
        "next_mine_time_epoch": next_mine_time_epoch,
        "last_mined_epoch": last_mined_epoch,
        "effective_cd_min": effective_cd_min,
        "effective_cd_sec": cooldown_sec,
        "pickaxe_level": eq_lvl,
        "pickaxe_name": p_info["name"],
        "yield_multiplier": round(p_info["yield_multiplier"] + pot_eff_equipped.get("yield_boost", 0.0), 2),
        "crit_bonus": round(p_info.get("crit_bonus", 0.0) + pot_eff_equipped.get("crit_boost", 0.0), 1),
        "bonus_points": p_info.get("bonus_points", 0) + pot_eff_equipped.get("bonus_cash", 0),
        "treasury_pool": float(getattr(state, "treasury_pool", 0.0) or 0.0)
    }

    credit_info = te.get_user_credit_info(u, market_state=state)

    # 4. Asset History
    history_entries = []
    hist_records = getattr(u, "asset_history", None)
    if (not hist_records or len(hist_records) < 2) and db:
        hist_records = te.seed_single_user_asset_history(db, u)
    for h in (hist_records or []):
        history_entries.append({
            "id": h.id,
            "net_worth": h.net_worth,
            "cash": h.cash,
            "stock_value": round(h.stock_value, 1),
            "debt": h.debt,
            "credit_score": h.credit_score,
            "event_type": h.event_type,
            "note": h.note,
            "created_at": h.created_at.isoformat() if h.created_at else None
        })

    max_lev = te.get_user_max_leverage_multiplier(db, u) if db else 10
    beast_cnt = 0
    if max_lev >= 60:
        beast_cnt = 3
    elif max_lev >= 40:
        beast_cnt = 2
    elif max_lev >= 20:
        beast_cnt = 1

    return {
        "id": u.id,
        "username": u.username,
        "points": u.points,
        "cash": cash,
        "bank_balance": bank_bal,
        "debt": debt,
        "net_worth": net_worth,
        "stock_value": round(total_stock_value, 1),
        "total_mined": getattr(u, "total_mined", 0.0) or 0.0,
        "credit": credit_info,
        "bank": bank_info,
        "max_leverage_multiplier": max_lev,
        "beast_heart_count": beast_cnt,
        "positions": positions,
        "equipments": equipments,
        "equipped_item": equipped_item,
        "items": items,
        "mining": mining_status,
        "asset_history": history_entries[-30:]
    }

def get_all_users_inspector_data(db) -> List[Dict[str, Any]]:
    """Returns inspector data for all non-dummy registered viewers, sorted by net_worth descending."""
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
        res.append(serialize_user_inspector_data(u, state, now, db=db))

    res.sort(key=lambda x: x["net_worth"], reverse=True)
    return res

def sync_docs_market_state(state, db=None):
    """Save latest market state to docs/market_state.json for GitHub Pages."""
    try:
        docs_dir = os.path.join(os.path.dirname(__file__), "docs")
        if os.path.exists(docs_dir):
            data = serialize_market_state(state)
            day_open = data.get("day_open_price", 2034)
            day_diff = state.current_price - day_open
            day_diff_pct = (day_diff / day_open * 100.0) if day_open > 0 else 0.0

            total_users = 0
            if db is not None:
                try:
                    total_users = db.query(models.User).count()
                except Exception:
                    pass
            if total_users == 0:
                try:
                    users_file = os.path.join(docs_dir, "users_state.json")
                    if os.path.exists(users_file):
                        with open(users_file, "r", encoding="utf-8") as uf:
                            u_data = json.load(uf)
                            total_users = u_data.get("count", len(u_data.get("users", [])))
                except Exception:
                    pass

            payload = {
                **data,
                "day_diff": day_diff,
                "day_diff_pct": round(day_diff_pct, 2),
                "total_users": total_users,
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            json_path = os.path.join(docs_dir, "market_state.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def sync_docs_users_state(db):
    """Save latest public viewers ranking and inspection data to docs/users_state.json for GitHub Pages."""
    try:
        docs_dir = os.path.join(os.path.dirname(__file__), "docs")
        if os.path.exists(docs_dir):
            users_data = get_all_users_inspector_data(db)
            payload = {
                "success": True,
                "users": users_data,
                "count": len(users_data),
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            json_path = os.path.join(docs_dir, "users_state.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def sync_all_docs(db, state=None):
    """Convenience helper to sync both market_state.json and users_state.json."""
    if state is None:
        state = te.get_market_state(db)
    sync_docs_market_state(state, db=db)
    sync_docs_users_state(db)

latest_tunnel_url: Optional[str] = None

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
                    elif -35 <= delta < 40:
                        rank = 2
                    else:
                        rank = 3

                # Method C: Sanity check for Mahjong Soul rank point rules
                # 1st place always gains +40pt or more.
                # 2nd place in Sanma (0 Uma) typically ranges from -35pt to +39pt.
                # 3rd place (last in Sanma) suffers severe penalty (<= -40pt).
                if 0 <= delta < 40 and rank in (3, 4):
                    rank = 2
                elif delta >= 40 and rank != 1:
                    rank = 1
                elif delta <= -45 and rank in (1, 2):
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

                sync_all_docs(db, state)
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

    # Sync initial GitHub Pages docs snapshot (market_state.json & users_state.json)
    try:
        db_init = SessionLocal()
        te.seed_initial_asset_history_if_needed(db_init)
        sync_all_docs(db_init)
        db_init.close()
        print("📁 공식 웹 가이드 스냅샷(market_state.json, users_state.json) 동기화 완료")
    except Exception as e:
        print(f"⚠️ 초기 스냅샷 생성 오류: {e}")

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

def is_admin_access_allowed(request: Request) -> bool:
    """Checks whether the request is allowed to access admin routes (localhost/streamer PC only)."""
    # 1. Any Cloudflare Tunnel headers -> definitely external public tunnel!
    if any(h in request.headers for h in ("cf-connecting-ip", "cf-ray", "cf-visitor", "cf-ipcountry", "cdn-loop")):
        return False

    # 2. Any forwarded proxy headers -> definitely external proxy!
    if any(h in request.headers for h in ("x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "forwarded")):
        return False

    # 3. Host header check (must be localhost, 127.0.0.1, testserver, ::1, or private LAN/WSL IP)
    host_raw = (request.headers.get("host") or "").split(":")[0].lower()
    if host_raw not in ("localhost", "127.0.0.1", "testserver", "::1"):
        try:
            h_ip = ipaddress.ip_address(host_raw)
            if not (h_ip.is_loopback or h_ip.is_private or h_ip.is_link_local):
                return False
        except ValueError:
            return False

    # 4. Client IP check (must be loopback, private LAN/WSL host gateway, or testclient)
    client_ip = request.client.host if request.client else ""
    if client_ip in ("127.0.0.1", "::1", "testclient", "localhost", "testserver"):
        return True

    try:
        c_ip = ipaddress.ip_address(client_ip)
        if c_ip.is_loopback or c_ip.is_private or c_ip.is_link_local:
            return True
        if getattr(c_ip, "ipv4_mapped", None):
            mapped = c_ip.ipv4_mapped
            if mapped.is_loopback or mapped.is_private or mapped.is_link_local:
                return True
    except ValueError:
        pass

    return False

ADMIN_PROTECTED_EXACT = {
    "/admin",
    "/api/casino/open",
    "/api/casino/close",
    "/api/lottery/open",
    "/api/lottery/close",
    "/api/merchant/open",
    "/api/merchant/close",
    "/api/chzzk/set-tokens",
    "/api/chzzk/exchange-code",
    "/api/chzzk/send-test",
    "/api/chzzk/subscribe-donation",
    "/api/chzzk/donation",
    "/api/tracker/push",
    "/api/chat/command",
    "/api/transfer",
}

ADMIN_PROTECTED_PREFIXES = (
    "/admin/",
    "/api/admin/",
)

@app.middleware("http")
async def block_external_admin_middleware(request: Request, call_next):
    path = request.url.path
    if path in ADMIN_PROTECTED_EXACT or path.startswith(ADMIN_PROTECTED_PREFIXES):
        if not is_admin_access_allowed(request):
            if path.startswith("/api/"):
                return JSONResponse(
                    status_code=403,
                    content={
                        "success": False,
                        "detail": "🚫 관리자/제어 API는 외부 접근이 원천 차단되어 있습니다. (스트리머 로컬 전용)"
                    }
                )
            return HTMLResponse(
                status_code=403,
                content="""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="utf-8">
    <title>403 접근 차단</title>
    <style>
        body { background: #0b0f19; color: #f87171; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
        .card { background: #1e293b; padding: 36px; border-radius: 14px; border: 2px solid #ef4444; text-align: center; max-width: 520px; box-shadow: 0 20px 40px rgba(0,0,0,0.7); }
        h1 { font-size: 20px; margin-bottom: 12px; color: #ef4444; }
        p { font-size: 14px; color: #94a3b8; line-height: 1.6; }
        .badge { display: inline-block; background: rgba(239, 68, 68, 0.2); color: #f87171; padding: 4px 10px; border-radius: 4px; font-weight: 700; font-size: 11px; margin-bottom: 14px; }
        a { display: inline-block; margin-top: 20px; padding: 10px 22px; background: #38bdf8; color: #0f172a; text-decoration: none; border-radius: 8px; font-weight: 800; font-size: 14px; }
        a:hover { background: #0284c7; }
    </style>
</head>
<body>
    <div class="card">
        <div class="badge">SECURITY SHIELD</div>
        <h1>🚫 403 Forbidden: 관리자 페이지 접근 차단</h1>
        <p>관리자 제어판 및 관리 API는 보안을 위해 <strong>외부 인터넷 접근이 원천 봉쇄</strong>되어 있습니다.<br>스트리머 본인의 로컬 PC(localhost)에서만 접근 가능합니다.</p>
        <a href="/">시청자 가이드 & 스펙 조회로 이동</a>
    </div>
</body>
</html>"""
            )
    return await call_next(request)

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

class WebLoginRequest(BaseModel):
    username: str
    code: str

class WebSetPinRequest(BaseModel):
    token: Optional[str] = None
    pin: str

class WebTransferRequest(BaseModel):
    token: str
    target_name: str
    amount: str

class WebExchangeBuyRequest(BaseModel):
    token: str
    listing_token: str

class WebExchangeSellItemRequest(BaseModel):
    token: str
    item_type: str
    quantity: int
    price: int
    target_buyer: Optional[str] = None

class WebExchangeSellEquipmentRequest(BaseModel):
    token: str
    equipment_id: int
    price: int
    target_buyer: Optional[str] = None

class WebExchangeCancelRequest(BaseModel):
    token: str
    listing_token: str

class WebArenaOpenRequest(BaseModel):
    token: str
    bet: str

class WebArenaJoinRequest(BaseModel):
    token: str
    host_id: Optional[str] = None

class WebArenaChallengeRequest(BaseModel):
    token: str
    target_name: str
    bet: str

class WebArenaActionRequest(BaseModel):
    token: str

class WebStockTradeRequest(BaseModel):
    token: str
    action: str  # "BUY" or "SELL"
    product_type: str
    quantity: Optional[int] = None
    is_all_in: Optional[bool] = False

class WebMineRequest(BaseModel):
    token: str

class WebEquipRequest(BaseModel):
    token: str
    equipment_id: int

class WebEnhanceRequest(BaseModel):
    token: str
    equipment_id: Optional[int] = None
    use_shield: Optional[bool] = None
    use_boost: Optional[bool] = None
    use_downgrade: Optional[bool] = None

class WebCubeUseRequest(BaseModel):
    token: str
    equipment_id: Optional[int] = None
    target_keyword: Optional[str] = None
    use_snipe: Optional[bool] = False
    lock_lines: Optional[List[int]] = None
    special_snipe_code: Optional[str] = None

class WebCubeBuyRequest(BaseModel):
    token: str
    count: int = 1

class WebCubeFragmentExchangeRequest(BaseModel):
    token: str

class WebCubeLockToggleRequest(BaseModel):
    token: str
    equipment_id: Optional[int] = None

class WebCubeLineLockRequest(BaseModel):
    token: str
    equipment_id: Optional[int] = None
    line_arg: str
    state: Optional[str] = None

class WebMerchantBuyRequest(BaseModel):
    token: str
    item_key: str
    quantity: Optional[Union[int, str]] = "1"

class WebCasinoSlotRequest(BaseModel):
    token: str
    bet: Union[int, str]

class WebCasinoDiceRequest(BaseModel):
    token: str
    choice: str
    bet: Union[int, str]

class WebCasinoRaceRequest(BaseModel):
    token: str
    runner: str
    bet: Union[int, str]

class WebCasinoMahjongRequest(BaseModel):
    token: str
    choice: str
    bet: Union[int, str]

class WebLotteryBuyRequest(BaseModel):
    token: str
    count: Optional[Union[int, str]] = 1
    lottery_type: Optional[str] = "basic"

class WebBankDepositRequest(BaseModel):
    token: str
    amount: Union[int, str]

class WebBankWithdrawRequest(BaseModel):
    token: str
    amount: Union[int, str]

class WebBankSavingsOpenRequest(BaseModel):
    token: str
    per_round: Union[int, str]
    rounds: Optional[Union[int, str]] = "5"

class WebBankSavingsCancelRequest(BaseModel):
    token: str

class WebBankFundBuyRequest(BaseModel):
    token: str
    amount: Union[int, str]

class WebBankFundSellRequest(BaseModel):
    token: str
    units: Optional[Union[int, float, str]] = "전부"

class WebBankInsuranceBuyRequest(BaseModel):
    token: str

class WebBankLoanBorrowRequest(BaseModel):
    token: str
    amount: Union[int, str]

class WebBankLoanRepayRequest(BaseModel):
    token: str
    amount: Optional[Union[int, str]] = "전액"



# ---------------------------------------------------------
# Web Views & OBS Overlay
# ---------------------------------------------------------
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")

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

@app.get("/", response_class=HTMLResponse)
@app.get("/guide", response_class=HTMLResponse)
async def get_guide():
    """Serves the Viewer Web Guide (matching GitHub Pages)."""
    guide_path = os.path.join(DOCS_DIR, "index.html")
    if os.path.exists(guide_path):
        with open(guide_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>가이드 페이지 준비 중입니다.</h1>")

@app.get("/market_state.json")
@app.get("/docs/market_state.json")
async def get_market_state_json():
    """Serves static market_state.json snapshot for web guide."""
    path = os.path.join(DOCS_DIR, "market_state.json")
    if os.path.exists(path):
        return FileResponse(path, media_type="application/json")
    return JSONResponse(status_code=404, content={"detail": "market_state.json not found"})

@app.get("/users_state.json")
@app.get("/docs/users_state.json")
async def get_users_state_json():
    """Serves static users_state.json snapshot for web guide."""
    path = os.path.join(DOCS_DIR, "users_state.json")
    if os.path.exists(path):
        return FileResponse(path, media_type="application/json")
    return JSONResponse(status_code=404, content={"detail": "users_state.json not found"})

@app.get("/mystery_merchant.jpg")
@app.get("/docs/mystery_merchant.jpg")
async def get_mystery_merchant_img():
    """Serves mystery merchant hooded portrait."""
    path = os.path.join(DOCS_DIR, "mystery_merchant.jpg")
    if os.path.exists(path):
        return FileResponse(path, media_type="image/jpeg")
    return JSONResponse(status_code=404, content={"detail": "mystery_merchant.jpg not found"})

TILES_DIR = os.path.join(DOCS_DIR, "tiles")
if os.path.exists(TILES_DIR):
    from starlette.staticfiles import StaticFiles
    app.mount("/tiles", StaticFiles(directory=TILES_DIR), name="tiles")
    app.mount("/docs/tiles", StaticFiles(directory=TILES_DIR), name="docs_tiles")

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
@app.get("/api/users")
async def api_admin_users(db=Depends(get_db)):
    """GET /api/users & /api/admin/users - Returns list of all registered viewers with complete assets, equipment, and items."""
    users_data = get_all_users_inspector_data(db)
    return {"success": True, "users": users_data}

@app.get("/api/user/{user_id_or_username}")
async def api_get_single_user(user_id_or_username: str, db=Depends(get_db)):
    """GET /api/user/{user_id_or_username} - Returns detailed asset, position, equipment, and item breakdown for a single viewer."""
    target = (user_id_or_username or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="유저 ID 또는 닉네임을 입력해주세요.")
    
    user = te.get_user_by_identifier(db, target)
    if not user:
        # Case-insensitive username search
        user = db.query(User).filter(User.username.ilike(target)).first()
    if not user:
        user = db.query(User).filter(User.id.ilike(target)).first()
    
    if not user:
        raise HTTPException(status_code=404, detail=f"시청자 '{target}' 정보를 찾을 수 없습니다.")
    
    state = te.get_market_state(db)
    now = time.time()
    user_data = serialize_user_inspector_data(user, state, now, db=db)
    return {
        "success": True,
        **user_data,
        "user": user_data
    }

@app.get("/api/user/{user_id_or_username}/asset-history")
async def api_get_user_asset_history(user_id_or_username: str, db=Depends(get_db)):
    """GET /api/user/{user_id_or_username}/asset-history - Returns historical asset snapshot progression for charts."""
    target = (user_id_or_username or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="유저 ID 또는 닉네임을 입력해주세요.")

    user = te.get_user_by_identifier(db, target)
    if not user:
        user = db.query(User).filter(User.username.ilike(target)).first()
    if not user:
        user = db.query(User).filter(User.id.ilike(target)).first()

    if not user:
        raise HTTPException(status_code=404, detail=f"시청자 '{target}' 정보를 찾을 수 없습니다.")

    history = te.get_user_asset_history(db, user.id)
    return {
        "success": True,
        "user_id": user.id,
        "username": user.username,
        "history": history
    }

class TunnelUrlRequest(BaseModel):
    url: str

@app.get("/api/tunnel")
async def api_get_tunnel():
    """GET /api/tunnel - Returns current active Cloudflare Tunnel URL if set."""
    return {"success": True, "tunnel_url": latest_tunnel_url}

@app.post("/api/admin/tunnel")
async def api_set_tunnel(req: TunnelUrlRequest):
    """POST /api/admin/tunnel - Sets or updates the active Cloudflare Tunnel URL."""
    global latest_tunnel_url
    clean_url = req.url.strip().rstrip("/")
    latest_tunnel_url = clean_url
    print(f"🌐 [Cloudflare Tunnel] 외부 터널 주소 갱신: {latest_tunnel_url}")
    return {"success": True, "tunnel_url": latest_tunnel_url}

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


# ---------------------------------------------------------
# Web Desk & Interactive Lounge Endpoints
# ---------------------------------------------------------
def should_broadcast_web_notice(action_type: str, details: Optional[Dict[str, Any]], reply: str) -> bool:
    """Filter to ensure web actions do not spam stream chat, only grand milestones."""
    if not details or not reply:
        return False

    # 1. Starforce Pickaxe Milestones: exactly 15, 20, 25, 30 stars!
    if action_type == "enhancement":
        outcome = str(details.get("outcome", ""))
        new_level = int(details.get("new_level", 0))
        if outcome == "success" and new_level in [15, 20, 25, 30]:
            return True
        return False

    # 2. Casino Games: Slots, Dice, Race, Mahjong
    if action_type in ["slot", "dice", "race", "mahjong", "casino"]:
        payout = int(details.get("gross_payout") or details.get("net_payout") or details.get("payout") or 0)
        is_jackpot = bool(details.get("jackpot") or details.get("is_jackpot"))
        bet_type = str(details.get("bet_type", ""))
        won = bool(details.get("won", False))
        if won and (payout >= 500000 or is_jackpot or bet_type == "exact"):
            return True
        return False

    # 3. Lottery: 1st prize or payout >= 500,000P
    if action_type == "lottery":
        rank = details.get("rank") or details.get("prize_rank")
        payout = int(details.get("prize") or details.get("payout") or 0)
        if rank in [1, "1등"] or payout >= 500000:
            return True
        return False

    return False

def maybe_dispatch_web_grand_notice(action_type: str, details: Optional[Dict[str, Any]], reply: str):
    """Dispatches a chat notice only if it qualifies as a grand celebration."""
    if reply and should_broadcast_web_notice(action_type, details, reply):
        asyncio.create_task(dispatch_chat_notice(reply, fallback_bot=bot_instance))


def authenticate_web_user(db: Session, token: Optional[str]) -> User:
    """Helper to authenticate user via web session token."""
    if not token:
        raise HTTPException(status_code=401, detail="인증 토큰이 누락되었습니다. 먼저 웹 로그인을 진행해주세요.")
    user = te.get_user_by_token(db, token)
    if not user:
        raise HTTPException(status_code=401, detail="유효하지 않거나 만료된 로그인 세션입니다. 다시 로그인해주세요.")
    return user


@app.post("/api/web/auth/challenge")
async def api_web_auth_challenge():
    """Generates a reverse authentication challenge for secure chat login (prevents account hijacking)."""
    res = te.create_web_auth_challenge()
    return {"success": True, **res}


@app.get("/api/web/auth/poll")
async def api_web_auth_poll(challenge_id: str, db=Depends(get_db)):
    """Polls reverse authentication status."""
    res = te.poll_web_auth_challenge(db, challenge_id)
    if res.get("status") == "AUTHORIZED":
        user = db.query(User).filter_by(web_token=res["token"]).first()
        state = te.get_market_state(db)
        now = time.time()
        user_data = serialize_user_inspector_data(user, state, now, db=db) if user else None
        return {
            "success": True,
            "status": "AUTHORIZED",
            "token": res["token"],
            "user": user_data
        }
    return {"success": True, **res}


@app.post("/api/web/login")
async def api_web_login(req: WebLoginRequest, request: Request, db=Depends(get_db)):
    """Logs in viewer with 4-digit temporary code or permanent PIN with brute-force protection."""
    client_ip = request.client.host if request.client else "unknown"
    ok, token, user, msg = te.verify_web_login(db, req.username, req.code, client_ip=client_ip)
    if not ok or not user or not token:
        raise HTTPException(status_code=400, detail=msg)
    state = te.get_market_state(db)
    now = time.time()
    user_data = serialize_user_inspector_data(user, state, now, db=db)
    return {
        "success": True,
        "token": token,
        "message": msg,
        "user": user_data
    }


@app.post("/api/web/user/set-pin")
async def api_web_user_set_pin(
    req: WebSetPinRequest,
    x_web_token: Optional[str] = Header(None, alias="x-web-token"),
    db=Depends(get_db)
):
    """Sets or changes permanent 4-digit PIN securely from web interface without chat leaking."""
    eff_token = req.token or x_web_token
    user = authenticate_web_user(db, eff_token)
    ok, msg = te.set_user_web_pin(db, user.id, req.pin)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}


@app.get("/api/web/me")
async def api_web_me(
    token: Optional[str] = None,
    x_web_token: Optional[str] = Header(None, alias="x-web-token"),
    authorization: Optional[str] = Header(None),
    db=Depends(get_db)
):
    """Returns profile & wallet status for authenticated web session."""
    eff_token = token or x_web_token
    if not eff_token and authorization and authorization.startswith("Bearer "):
        eff_token = authorization.split(" ")[1].strip()
    user = authenticate_web_user(db, eff_token)
    state = te.get_market_state(db)
    now = time.time()
    user_data = serialize_user_inspector_data(user, state, now, db=db)
    return {"success": True, "user": user_data}


@app.post("/api/web/logout")
async def api_web_logout(
    token: Optional[str] = Body(None, embed=True),
    x_web_token: Optional[str] = Header(None, alias="x-web-token"),
    db=Depends(get_db)
):
    """Invalidates active web session token."""
    eff = token or x_web_token
    if eff:
        user = te.get_user_by_token(db, eff)
        if user:
            user.web_token = None
            db.commit()
    return {"success": True, "message": "로그아웃되었습니다."}


@app.post("/api/web/transfer")
async def api_web_transfer(req: WebTransferRequest, db=Depends(get_db)):
    """P2P wire transfer from Web Lounge."""
    user = authenticate_web_user(db, req.token)
    success, reply, details = te.execute_transfer(
        db, user.id, user.username, req.target_name, req.amount
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
    sync_all_docs(db, state)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    return {"success": True, "reply": reply, "details": details, "user": user_data}


@app.get("/api/web/exchange/listings")
async def api_web_exchange_listings(
    token: Optional[str] = None,
    x_web_token: Optional[str] = Header(None, alias="x-web-token"),
    db=Depends(get_db)
):
    """Returns active marketplace listings (items & equipments) for web GUI."""
    eff_token = token or x_web_token
    user = te.get_user_by_token(db, eff_token) if eff_token else None
    data = te.get_active_market_listings_data(db, user_id=user.id if user else None)
    return {"success": True, **data}


@app.post("/api/web/exchange/buy")
async def api_web_exchange_buy(req: WebExchangeBuyRequest, db=Depends(get_db)):
    """Buys item or equipment from marketplace."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.execute_buy_exchange(db, user.id, user.username, req.listing_token)
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    sync_all_docs(db)
    state = te.get_market_state(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    return {"success": True, "reply": reply, "details": details, "user": user_data}


@app.post("/api/web/exchange/sell-item")
async def api_web_exchange_sell_item(req: WebExchangeSellItemRequest, db=Depends(get_db)):
    """Registers consumable scroll or cube for sale on exchange."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.execute_list_item(
        db, user.id, user.username, req.item_type, str(req.quantity), str(req.price), target_buyer_token=req.target_buyer
    )
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    sync_all_docs(db)
    state = te.get_market_state(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    return {"success": True, "reply": reply, "details": details, "user": user_data}


@app.post("/api/web/exchange/sell-equipment")
async def api_web_exchange_sell_equipment(req: WebExchangeSellEquipmentRequest, db=Depends(get_db)):
    """Registers pickaxe equipment for sale on exchange."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.execute_list_equipment(
        db, user.id, user.username, str(req.equipment_id), str(req.price), target_buyer_token=req.target_buyer
    )
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    sync_all_docs(db)
    state = te.get_market_state(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    return {"success": True, "reply": reply, "details": details, "user": user_data}


@app.post("/api/web/exchange/cancel")
async def api_web_exchange_cancel(req: WebExchangeCancelRequest, db=Depends(get_db)):
    """Cancels active listing and returns item to seller inventory."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.execute_cancel_exchange(db, user.id, user.username, req.listing_token)
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    sync_all_docs(db)
    state = te.get_market_state(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    return {"success": True, "reply": reply, "details": details, "user": user_data}


@app.get("/api/web/arena/status")
async def api_web_arena_status(
    token: Optional[str] = None,
    x_web_token: Optional[str] = Header(None, alias="x-web-token"),
    db=Depends(get_db)
):
    """Returns live arena state, open matches, and recent logs."""
    eff_token = token or x_web_token
    user = te.get_user_by_token(db, eff_token) if eff_token else None
    data = te.get_arena_data(db, user_id=user.id if user else None)
    return {"success": True, **data}


@app.post("/api/web/arena/open")
async def api_web_arena_open(req: WebArenaOpenRequest, db=Depends(get_db)):
    """Opens a public arena match."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.open_public_arena_match(db, user.id, user.username, req.bet)
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    asyncio.create_task(dispatch_chat_notice(reply, fallback_bot=bot_instance))
    await manager.broadcast({"type": "pvp_open", "data": details, "reply": reply})
    return {"success": True, "reply": reply, "details": details}


@app.post("/api/web/arena/join")
async def api_web_arena_join(req: WebArenaJoinRequest, db=Depends(get_db)):
    """Joins an open public arena match."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.join_public_arena_match(db, user.id, user.username, target_host=req.host_id)
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    asyncio.create_task(dispatch_chat_notice(reply, fallback_bot=bot_instance))
    sync_all_docs(db)
    state = te.get_market_state(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    await manager.broadcast({"type": "pvp_duel", "data": details, "reply": reply})
    return {"success": True, "reply": reply, "details": details, "user": user_data}


@app.post("/api/web/arena/challenge")
async def api_web_arena_challenge(req: WebArenaChallengeRequest, db=Depends(get_db)):
    """Challenges a specific user to a 1:1 duel."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.create_pvp_challenge(db, user.id, user.username, req.target_name, req.bet)
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    asyncio.create_task(dispatch_chat_notice(reply, fallback_bot=bot_instance))
    await manager.broadcast({"type": "pvp_challenge", "data": details, "reply": reply})
    return {"success": True, "reply": reply, "details": details}


@app.post("/api/web/arena/accept")
async def api_web_arena_accept(req: WebArenaActionRequest, db=Depends(get_db)):
    """Accepts pending duel or open arena match."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.accept_pvp_challenge(db, user.id, user.username)
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    asyncio.create_task(dispatch_chat_notice(reply, fallback_bot=bot_instance))
    sync_all_docs(db)
    state = te.get_market_state(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    await manager.broadcast({"type": "pvp_duel", "data": details, "reply": reply})
    return {"success": True, "reply": reply, "details": details, "user": user_data}


@app.post("/api/web/arena/decline")
async def api_web_arena_decline(req: WebArenaActionRequest, db=Depends(get_db)):
    """Declines pending duel challenge."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.decline_pvp_challenge(db, user.id, user.username)
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    asyncio.create_task(dispatch_chat_notice(reply, fallback_bot=bot_instance))
    await manager.broadcast({"type": "pvp_declined", "data": details, "reply": reply})
    return {"success": True, "reply": reply, "details": details}


@app.post("/api/web/trade/stock")
async def api_web_trade_stock(req: WebStockTradeRequest, db=Depends(get_db)):
    """Executes stock buy or sell order from web desk."""
    user = authenticate_web_user(db, req.token)
    p_type = te.parse_product_type(req.product_type)
    if not p_type:
        raise HTTPException(status_code=400, detail=f"유효하지 않은 종목입니다: '{req.product_type}'")

    action = (req.action or "").strip().upper()
    if action == "BUY":
        qty_token = "올인" if req.is_all_in else str(req.quantity or 1)
        ok, reply, event = te.execute_buy(db, user.id, user.username, req.product_type, qty_token)
    elif action == "SELL":
        qty_token = "전량" if req.is_all_in else str(req.quantity or 1)
        ok, reply, event = te.execute_sell(db, user.id, user.username, req.product_type, qty_token)
    else:
        raise HTTPException(status_code=400, detail="action은 'BUY' 또는 'SELL'이어야 합니다.")

    if not ok:
        raise HTTPException(status_code=400, detail=reply)

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
    sync_all_docs(db)
    state = te.get_market_state(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    return {"success": True, "reply": reply, "user": user_data}


@app.post("/api/web/mining/mine")
async def api_web_mining_mine(req: WebMineRequest, db=Depends(get_db)):
    """Executes Proof of Watch mining from Web Lounge."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.execute_mining(db, user.id, user.username)
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    state = te.get_market_state(db)
    leaderboard = te.get_leaderboard(db, top_n=3)
    await manager.broadcast({
        "type": "mining_result",
        "data": details,
        "leaderboard": leaderboard,
        "market_state": serialize_market_state(state)
    })
    sync_all_docs(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    return {"success": True, "reply": reply, "details": details, "user": user_data}


@app.post("/api/web/equipment/equip")
async def api_web_equipment_equip(req: WebEquipRequest, db=Depends(get_db)):
    """Equips designated pickaxe equipment from Web Lounge."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.execute_equip_item(db, user.id, user.username, str(req.equipment_id))
    if not ok and "이미" not in reply:
        raise HTTPException(status_code=400, detail=reply)
    state = te.get_market_state(db)
    sync_all_docs(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    return {"success": True, "reply": reply, "details": details, "user": user_data}


@app.post("/api/web/enhancement/upgrade")
async def api_web_enhancement_upgrade(req: WebEnhanceRequest, db=Depends(get_db)):
    """Executes MapleStory Starforce enhancement from Web Lounge."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.execute_pickaxe_upgrade(
        db, user.id, user.username,
        item_id_or_index=str(req.equipment_id) if req.equipment_id else None,
        use_shield=req.use_shield,
        use_boost=req.use_boost,
        use_downgrade=req.use_downgrade
    )
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    if reply:
        maybe_dispatch_web_grand_notice("enhancement", details, reply)
    state = te.get_market_state(db)
    leaderboard = te.get_leaderboard(db, top_n=3)
    await manager.broadcast({
        "type": "starforce_upgrade",
        "data": details,
        "leaderboard": leaderboard,
        "market_state": serialize_market_state(state)
    })
    sync_all_docs(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    return {"success": True, "reply": reply, "details": details, "user": user_data}


@app.post("/api/web/cube/use")
async def api_web_cube_use(req: WebCubeUseRequest, db=Depends(get_db)):
    """Executes Miracle Cube potential reset from Web Lounge."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.execute_cube_use(
        db, user.id, user.username,
        item_id_or_index=str(req.equipment_id) if req.equipment_id else None,
        target_keyword=req.target_keyword,
        use_snipe=bool(req.use_snipe),
        lock_lines=req.lock_lines,
        special_snipe_code=req.special_snipe_code
    )
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    state = te.get_market_state(db)
    await manager.broadcast({
        "type": "cube_used",
        "data": details,
        "market_state": serialize_market_state(state)
    })
    sync_all_docs(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    return {"success": True, "reply": reply, "details": details, "user": user_data}


@app.post("/api/web/cube/buy")
async def api_web_cube_buy(req: WebCubeBuyRequest, db=Depends(get_db)):
    """Purchases Miracle Cubes from Web Lounge."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.execute_buy_cubes(db, user.id, user.username, str(req.count))
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    state = te.get_market_state(db)
    sync_all_docs(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    return {"success": True, "reply": reply, "details": details, "user": user_data}


@app.post("/api/web/cube/fragment-exchange")
async def api_web_cube_fragment_exchange(req: WebCubeFragmentExchangeRequest, db=Depends(get_db)):
    """Exchanges 10 Cube Fragments for 15,000P refund."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.execute_cube_fragment_exchange(db, user.id, user.username)
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    state = te.get_market_state(db)
    sync_all_docs(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    return {"success": True, "reply": reply, "details": details, "user": user_data}


@app.post("/api/web/cube/lock-toggle")
async def api_web_cube_lock_toggle(req: WebCubeLockToggleRequest, db=Depends(get_db)):
    """Toggles cube lock (safety protection) on equipment."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.execute_equipment_cube_lock(db, user.id, user.username, str(req.equipment_id) if req.equipment_id else None)
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    state = te.get_market_state(db)
    sync_all_docs(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    return {"success": True, "reply": reply, "details": details, "user": user_data}


@app.post("/api/web/cube/line-lock")
async def api_web_cube_line_lock(req: WebCubeLineLockRequest, db=Depends(get_db)):
    """Locks or unlocks specific potential line on equipment."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.execute_potential_line_lock(
        db, user.id, user.username,
        line_arg=req.line_arg,
        state_str=req.state,
        item_id_or_index=str(req.equipment_id) if req.equipment_id else None
    )
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    state = te.get_market_state(db)
    sync_all_docs(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    return {"success": True, "reply": reply, "details": details, "user": user_data}


@app.get("/api/web/cube/snipe-options")
async def api_web_cube_snipe_options():
    """Returns available options and full guide for the Snipe Scroll (잠재저격주문서)."""
    return {
        "success": True,
        "options": te.get_snipe_options_data(),
        "guide_text": te.get_snipe_options_guide_text()
    }


@app.get("/api/web/merchant/status")
async def api_web_merchant_status(db=Depends(get_db)):
    """Current Mysterious Merchant status and items for Web GUI."""
    m_state = te.get_merchant_state(db)
    if not m_state.get("is_active"):
        for item in m_state.get("items", {}).values():
            item["price"] = "???"
            item["stock"] = "???"
    return {"success": True, "merchant": m_state}


@app.post("/api/web/merchant/buy")
async def api_web_merchant_buy(req: WebMerchantBuyRequest, db=Depends(get_db)):
    """Buys scroll item from Mysterious Merchant via Web GUI."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.execute_buy_merchant_item(db, user.id, user.username, req.item_key, str(req.quantity or 1))
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    sync_all_docs(db)
    state = te.get_market_state(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    return {"success": True, "reply": reply, "details": details, "user": user_data, "merchant": te.get_merchant_state(db)}


@app.get("/api/web/casino/status")
async def api_web_casino_status(db=Depends(get_db)):
    """Current Casino status and Treasury pool for Web GUI."""
    c_state = te.get_casino_state(db)
    return {"success": True, "casino": c_state}


@app.post("/api/web/casino/slot")
async def api_web_casino_slot(req: WebCasinoSlotRequest, db=Depends(get_db)):
    """Plays 3-reel slot gamble via Web GUI."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.execute_slot_gamble(db, user.id, user.username, str(req.bet))
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    maybe_dispatch_web_grand_notice("slot", details, reply)
    sync_all_docs(db)
    state = te.get_market_state(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    return {"success": True, "reply": reply, "details": details, "user": user_data, "casino": te.get_casino_state(db)}


@app.post("/api/web/casino/dice")
async def api_web_casino_dice(req: WebCasinoDiceRequest, db=Depends(get_db)):
    """Plays 2-dice gamble via Web GUI."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.execute_dice_gamble(db, user.id, user.username, req.choice, str(req.bet))
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    maybe_dispatch_web_grand_notice("dice", details, reply)
    sync_all_docs(db)
    state = te.get_market_state(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    return {"success": True, "reply": reply, "details": details, "user": user_data, "casino": te.get_casino_state(db)}


@app.post("/api/web/casino/race")
async def api_web_casino_race(req: WebCasinoRaceRequest, db=Depends(get_db)):
    """Plays Yakuman 4-Greats race gamble via Web GUI."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.execute_yakuman_race_gamble(db, user.id, user.username, req.runner, str(req.bet))
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    maybe_dispatch_web_grand_notice("race", details, reply)
    sync_all_docs(db)
    state = te.get_market_state(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    return {"success": True, "reply": reply, "details": details, "user": user_data, "casino": te.get_casino_state(db)}


@app.post("/api/web/casino/mahjong")
async def api_web_casino_mahjong(req: WebCasinoMahjongRequest, db=Depends(get_db)):
    """Plays Mahjong tile guess gamble via Web GUI."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.execute_mahjong_tile_gamble(db, user.id, user.username, req.choice, str(req.bet))
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    maybe_dispatch_web_grand_notice("mahjong", details, reply)
    sync_all_docs(db)
    state = te.get_market_state(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    return {"success": True, "reply": reply, "details": details, "user": user_data, "casino": te.get_casino_state(db)}


@app.get("/api/web/lottery/status")
async def api_web_lottery_status(db=Depends(get_db)):
    """Current Lottery event status for Web GUI."""
    l_state = te.get_lottery_event_state(db)
    return {"success": True, "lottery": l_state}


@app.post("/api/web/lottery/buy")
async def api_web_lottery_buy(req: WebLotteryBuyRequest, db=Depends(get_db)):
    """Buys and scratches lottery tickets via Web GUI."""
    user = authenticate_web_user(db, req.token)
    try:
        cnt = int(req.count or 1)
    except (ValueError, TypeError):
        cnt = 1
    ok, reply, details = te.execute_buy_lottery(db, user.id, user.username, count=cnt, lottery_type=req.lottery_type or "basic")
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    maybe_dispatch_web_grand_notice("lottery", details, reply)
    sync_all_docs(db)
    state = te.get_market_state(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    return {"success": True, "reply": reply, "details": details, "user": user_data, "lottery": te.get_lottery_event_state(db)}


# ---------------------------------------------------------
# Central Bank (치즈나베 중앙은행) Web Endpoints
# ---------------------------------------------------------
@app.get("/api/web/bank/info")
async def api_web_bank_info(
    token: Optional[str] = None,
    x_web_token: Optional[str] = Header(None, alias="x-web-token"),
    db=Depends(get_db)
):
    """Fetches Central Bank account details (demand deposit, savings, fund, insurance, loan)."""
    eff_token = token or x_web_token
    user = authenticate_web_user(db, eff_token)
    info = te.get_user_bank_info(user, db=db)
    return {"success": True, "bank": info}


@app.post("/api/web/bank/deposit")
async def api_web_bank_deposit(req: WebBankDepositRequest, db=Depends(get_db)):
    """Deposit cash into demand deposit (+0.5% interest per round)."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.execute_bank_deposit(db, user.id, user.username, str(req.amount))
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    sync_all_docs(db)
    state = te.get_market_state(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    return {"success": True, "reply": reply, "details": details, "user": user_data, "bank": te.get_user_bank_info(user, db=db)}


@app.post("/api/web/bank/withdraw")
async def api_web_bank_withdraw(req: WebBankWithdrawRequest, db=Depends(get_db)):
    """Withdraw cash from demand deposit."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.execute_bank_withdraw(db, user.id, user.username, str(req.amount))
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    sync_all_docs(db)
    state = te.get_market_state(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    return {"success": True, "reply": reply, "details": details, "user": user_data, "bank": te.get_user_bank_info(user, db=db)}


@app.post("/api/web/bank/savings/open")
async def api_web_bank_savings_open(req: WebBankSavingsOpenRequest, db=Depends(get_db)):
    """Opens periodic installment savings account (+20% bonus interest at maturity)."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.execute_open_savings(db, user.id, user.username, str(req.per_round), str(req.rounds or 5))
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    sync_all_docs(db)
    state = te.get_market_state(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    return {"success": True, "reply": reply, "details": details, "user": user_data, "bank": te.get_user_bank_info(user, db=db)}


@app.post("/api/web/bank/savings/cancel")
async def api_web_bank_savings_cancel(req: WebBankSavingsCancelRequest, db=Depends(get_db)):
    """Cancels active installment savings and refunds principal."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.execute_cancel_savings(db, user.id, user.username)
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    sync_all_docs(db)
    state = te.get_market_state(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    return {"success": True, "reply": reply, "details": details, "user": user_data, "bank": te.get_user_bank_info(user, db=db)}


@app.post("/api/web/bank/fund/buy")
async def api_web_bank_fund_buy(req: WebBankFundBuyRequest, db=Depends(get_db)):
    """Invests points in Mahjong Index Fund."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.execute_buy_fund(db, user.id, user.username, str(req.amount))
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    sync_all_docs(db)
    state = te.get_market_state(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    return {"success": True, "reply": reply, "details": details, "user": user_data, "bank": te.get_user_bank_info(user, db=db)}


@app.post("/api/web/bank/fund/sell")
async def api_web_bank_fund_sell(req: WebBankFundSellRequest, db=Depends(get_db)):
    """Redeems Mahjong Index Fund units for cash."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.execute_sell_fund(db, user.id, user.username, str(req.units or "전부"))
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    sync_all_docs(db)
    state = te.get_market_state(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    return {"success": True, "reply": reply, "details": details, "user": user_data, "bank": te.get_user_bank_info(user, db=db)}


@app.post("/api/web/bank/insurance/buy")
async def api_web_bank_insurance_buy(req: WebBankInsuranceBuyRequest, db=Depends(get_db)):
    """Purchases Starforce Destruction Insurance (5 rounds coverage, 1,000,000P payout)."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.execute_buy_insurance(db, user.id, user.username)
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    sync_all_docs(db)
    state = te.get_market_state(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    return {"success": True, "reply": reply, "details": details, "user": user_data, "bank": te.get_user_bank_info(user, db=db)}


@app.post("/api/web/bank/loan/borrow")
async def api_web_bank_loan_borrow(req: WebBankLoanBorrowRequest, db=Depends(get_db)):
    """Borrows loan from central treasury according to credit tier."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.execute_borrow(db, user.id, user.username, str(req.amount))
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    sync_all_docs(db)
    state = te.get_market_state(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    return {"success": True, "reply": reply, "details": details, "user": user_data, "bank": te.get_user_bank_info(user, db=db)}


@app.post("/api/web/bank/loan/repay")
async def api_web_bank_loan_repay(req: WebBankLoanRepayRequest, db=Depends(get_db)):
    """Repays outstanding debt to central treasury."""
    user = authenticate_web_user(db, req.token)
    ok, reply, details = te.execute_repay(db, user.id, user.username, str(req.amount or "전액"))
    if not ok:
        raise HTTPException(status_code=400, detail=reply)
    sync_all_docs(db)
    state = te.get_market_state(db)
    user_data = serialize_user_inspector_data(user, state, time.time(), db=db)
    return {"success": True, "reply": reply, "details": details, "user": user_data, "bank": te.get_user_bank_info(user, db=db)}



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
@app.get("/api/web/buyers")
async def api_get_buyers(limit: int = 100, db=Depends(get_db)):
    """GET /api/buyers - Returns real-time list of current buyers/shareholders with positions, valuation, and market breakdown."""
    data = te.get_current_buyers(db, limit=limit)
    if "summary" in data:
        data["summary"]["free_trading_remaining"] = get_free_trading_remaining()
    return {
        "success": True,
        **data,
        "recent_trades": list(recent_trades)
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