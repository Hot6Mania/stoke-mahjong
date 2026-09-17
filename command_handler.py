import os
import re
import time
from datetime import datetime, timezone
from typing import Tuple, Optional, Dict, Any
from sqlalchemy.orm import Session
from models import Position
from trading_engine import (
    STARTING_POINTS,
    get_market_state,
    get_or_create_user,
    calculate_position_valuation,
    execute_buy,
    execute_sell,
    execute_liquidate,
    register_limit_order,
    parse_product_type,
    execute_mining,
    execute_borrow,
    execute_repay,
    execute_bankruptcy,
    submit_bankruptcy_application,
    get_treasury_info,
    execute_margin_buy,
    is_market_locked,
    get_casino_state,
    open_casino,
    close_casino,
    execute_slot_gamble,
    execute_dice_gamble,
    settle_match
)

CHANNEL_ID = os.getenv("CHANNEL_ID", "4495f96624a2c60bd1ed5a6139014d20")
GUIDE_WEB_URL = os.getenv("GUIDE_WEB_URL", "https://hot6mania.github.io/stoke-mahjong/")

HELP_MESSAGE = f"""📈 [마작 주식 명령어 안내]
• 거래: !매수 [종목] [수량/올인], !매도 [종목] [수량/전량], !청산
• 금융: !내정보, !대출 [금액/최대], !상환, !채굴, !국고, !남은시간
• 도박: !슬롯 [금액/올인], !주사위 [홀/짝] [금액], !카지노, !슬롯확률
• 종목: 1X, 2X, 3X, 5X, 10X (레버리지) / INV, 2X_INV~10X_INV (인버스) (약어: !약어)
📖 상세 웹 가이드: {GUIDE_WEB_URL}"""
GUIDE_STOCK = HELP_MESSAGE

GUIDE_BUY = "💡 매수 사용법: !매수 [종목] [수량/올인/빚올인] (!올인, !구매도 가능. 예: !올인 1X, !매수 1X 올인, !구매 10X 1, !빚올인 10X)"
GUIDE_SELL = "💡 매도 사용법: !매도 [종목] [수량/전량] (!판매, !전량매도 가능. 예: !매도 10X 전량, !전량매도 10X)"
GUIDE_LIMIT = "💡 지정가 사용법: !지정가 [매수/매도] [종목] [목표가] [수량] (예: !지정가 매수 1X 300 10)"
GUIDE_LIQUIDATE = "💡 청산 사용법: !청산 [종목/전량] (예: !청산 10X, !청산 전량)"
GUIDE_BORROW = "💡 대출 사용법: !대출 [금액/최대] (경기 중에도 24시간 상시 가능, 예: !대출 최대, !대출 30000 | 개장 중엔 !빚올인 10X)"
GUIDE_REPAY = "💡 상환 사용법: !상환 [금액/전액] (예: !상환 20000, !상환 전액)"
GUIDE_CASINO = "🎰 [국고 카지노 사용법]\n• 슬롯머신: !슬롯 [금액/올인] (확률 확인: !슬롯확률)\n• 주사위: !주사위 [홀/짝/대/소] [금액/올인]\n• 카지노 상태: !카지노\n* 스트리머 전용: !정산 [등수] [점수], !카지노오픈 [분] [최대한도], !카지노마감"

def handle_chat_command(
    db: Session,
    user_id: str,
    username: str,
    raw_message: str
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Dispatcher for incoming streaming chat commands.
    Returns: (reply_text, broadcast_event_dict)
    """
    import unicodedata
    raw_message = unicodedata.normalize('NFKC', str(raw_message or ""))
    msg = raw_message.strip()
    idx = msg.find("!")
    if idx == -1:
        return None, None
    msg = msg[idx:]

    # Handle accidental space after '!' (e.g. "! 10배 올인" -> "!10배 올인")
    if msg.startswith("! "):
        msg = "!" + msg[1:].lstrip()

    # Split command tokens
    tokens = msg.split()
    if len(tokens) > 1 and tokens[0] == "!":
        tokens = [f"!{tokens[1]}"] + tokens[2:]
    cmd = tokens[0].lower()

    # 1. Help / System Guide Commands
    if cmd in ["!주식명령어", "!주식도움말", "!명령어", "!도움말"]:
        return HELP_MESSAGE, None

    # 1-1. Abbreviation & Shorthand Guide (!약어, !단축어, !종목약어, etc.)
    if cmd in ["!약어", "!단축어", "!종목약어", "!줄임말", "!은어", "!별칭", "!alias"]:
        reply = (
            "🏷️ [종목 약어 & 단축어 가이드]\n"
            "• 📈 레버리지(상승/롱): 10배, 10레, 10버, 10롱 (2~5배도 동일: 5레, 5롱 등)\n"
            "• 📉 인버스(하락/숏): 숏(1X), 곱버스(2X), 10숏, 10인, 10곱 (5숏, 3인 등)\n"
            "⚡ 간편 주문 팁: 종목명만 입력해도 즉시 주문! (예: !10롱 올인, !10숏 5, !곱버스 전량)"
        )
        return reply, None

    # 2. Market State Query
    if cmd in ["!주식", "!시세", "!호가", "!가격"]:
        state = get_market_state(db)
        day_open = getattr(state, "day_open_price", None) or state.previous_price
        diff = state.current_price - day_open
        diff_pct = (diff / day_open * 100.0) if day_open > 0 else 0.0

        if diff > 0:
            change_str = f"▲+{diff:,}P (+{diff_pct:.2f}%)"
        elif diff < 0:
            change_str = f"▼{diff:,}P ({diff_pct:.2f}%)"
        else:
            change_str = "0P (0.00%)"

        end_t = float(getattr(state, "free_trading_end_time", 0.0) or 0.0)
        rem_trade = max(0, int(end_t - time.time())) if (not state.is_trading_locked and end_t > 0) else 0
        if state.is_trading_locked:
            status_badge = "[경기 중 - 거래 마감]"
        elif rem_trade > 0:
            m_t, s_t = divmod(rem_trade, 60)
            status_badge = f"[장 열림 ({m_t}분 {s_t}초 남음)]"
        else:
            status_badge = "[장 열림]"

        delta_str = f"{state.last_settlement_delta:+d}pt" if state.last_settlement_delta != 0 else "0pt"

        reply = (
            f"📊 [나베주가 시세] 현재가: {state.current_price:,}P (작혼 {state.current_rank_point:,}pt | {change_str}) | "
            f"당일시가: {day_open:,}P (직전: {delta_str}) | 상태: {status_badge} | "
            f"국고: {int(round(getattr(state, 'treasury_pool', 500000.0))):,}P"
        )
        return reply, None

    # 2-1. Remaining Time Query (!남은시간, !시간, !장시간, !남은장시간, !마감시간, !time, !타이머)
    if cmd in ["!남은시간", "!시간", "!장시간", "!남은장시간", "!마감시간", "!장마감", "!time", "!타이머"]:
        state = get_market_state(db)
        c_state = get_casino_state(db)
        user = get_or_create_user(db, user_id, username)

        now = time.time()

        # 1. Free Trading Remaining
        end_t = float(getattr(state, "free_trading_end_time", 0.0) or 0.0)
        is_locked = bool(getattr(state, "is_trading_locked", True))
        rem_trade = max(0, int(end_t - now)) if (not is_locked and end_t > 0) else 0

        if not is_locked and rem_trade > 0:
            m_t, s_t = divmod(rem_trade, 60)
            trade_str = f"🟢 장 열림 ({m_t}분 {s_t}초 후 마감)"
        elif not is_locked:
            trade_str = "🟢 장 열림 (자유 거래 중)"
        else:
            trade_str = "🔒 경기 진행 중 (거래 마감)"

        # 2. Casino Remaining
        if c_state["is_open"]:
            rem_c = c_state["remaining_sec"]
            if 0 < rem_c < 99999:
                m_c, s_c = divmod(rem_c, 60)
                casino_str = f"🎰 카지노 오픈 ({m_c}분 {s_c}초 남음)"
            else:
                casino_str = "🎰 카지노 오픈 (무제한)"
        else:
            casino_str = "💤 카지노 마감"

        # 3. User Mining Cooldown
        mine_str = "⛏️ 즉시 가능"
        if user.last_mined_at:
            now_utc = datetime.now(timezone.utc)
            last_t = user.last_mined_at
            if last_t.tzinfo is None:
                last_t = last_t.replace(tzinfo=timezone.utc)
            elapsed = (now_utc - last_t).total_seconds()
            if elapsed < 900:
                rem_m = int(900 - elapsed)
                mm, ss = divmod(rem_m, 60)
                mine_str = f"⛏️ 쿨타임 {mm}분 {ss}초"

        reply = f"⏱️ [현재 남은 시간] 거래: {trade_str} | 도박: {casino_str} | 내 채굴: {mine_str}"
        return reply, None

    # 3. Account / Wallet Query (보유와 채굴을 '보유'로 완전 통합)
    if cmd in ["!내정보", "!지갑", "!내주식", "!계좌", "!잔고"]:
        user = get_or_create_user(db, user_id, username)
        state = get_market_state(db)
        positions = db.query(Position).filter(Position.user_id == user.id, Position.quantity > 0).all()

        portfolio_val = 0
        pos_summaries = []

        for p in positions:
            val = calculate_position_valuation(p, state.current_price)
            curr_val = int(round(val["current_value"]))
            portfolio_val += curr_val
            pnl_pct = val["pnl_pct"]
            sign = "+" if pnl_pct >= 0 else ""
            qty_str = f"{int(p.quantity)}" if p.quantity.is_integer() else f"{p.quantity:.2f}"
            pos_summaries.append(f"{p.product_type.value}: {qty_str}주 (평단 {int(round(p.entry_price)):,}P, {sign}{pnl_pct:.1f}%)")

        debt = getattr(user, "debt", 0) or 0
        gross_assets = user.points + portfolio_val
        net_assets = gross_assets - debt
        total_pnl = net_assets - STARTING_POINTS
        sign = "+" if total_pnl >= 0 else ""
        total_pnl_pct = (total_pnl / float(STARTING_POINTS)) * 100.0

        div_str = f" | 누적배당: +{user.total_dividends:,}P" if getattr(user, "total_dividends", 0) > 0 else ""
        debt_str = f" | 빚(대출): {debt:,}P" if debt > 0 else ""

        if pos_summaries:
            pos_str = " | ".join(pos_summaries)
            reply = (
                f"👤 [{user.username}] 현금: {user.points:,}P{debt_str} | 순자산: {net_assets:,}P ({sign}{total_pnl_pct:.1f}%){div_str} | "
                f"보유: [{pos_str}]"
            )
        else:
            reply = f"👤 [{user.username}] 현금: {user.points:,}P{debt_str} | 순자산: {net_assets:,}P ({sign}{total_pnl_pct:.1f}%){div_str} | 보유 포지션이 없습니다."

        return reply, None

    # Central Trading Lock Enforcement Gate (주식 거래만 잠금, 채굴 및 대출은 경기 중에도 24시간 상시 가능)
    TRADING_COMMANDS = {
        "!올인", "!allin", "!풀매수", "!전액매수", "!매수올인", "!구매올인",
        "!매수", "!사기", "!buy", "!구매", "!구매하기", "!매수하기",
        "!빚올인", "!빚으로올인", "!빚투", "!신용매수", "!대출매수", "!마진매수", "!빚매수", "!신용구매",
        "!빚으로", "!빚내서",
        "!매도", "!팔기", "!sell", "!판매", "!판매하기", "!매도하기", "!전량매도", "!풀매도", "!완판",
        "!지정가", "!예약", "!limit",
        "!청산", "!정리", "!손절", "!익절"
    }

    if cmd in TRADING_COMMANDS:
        state = get_market_state(db)
        if is_market_locked(db, state):
            db.rollback()
            if cmd in ["!매도", "!팔기", "!sell", "!판매", "!판매하기", "!매도하기", "!전량매도", "!풀매도", "!완판"]:
                return "⚠️ [거래 마감] 경기가 진행 중이므로 매도할 수 없습니다. (조회, 채굴, 대출 명령만 가능)", None
            elif cmd in ["!청산", "!정리", "!손절", "!익절"]:
                return "⚠️ [거래 마감] 경기가 진행 중이므로 청산할 수 없습니다.", None
            elif cmd in ["!지정가", "!예약", "!limit"]:
                return "⚠️ [거래 마감] 경기가 진행 중이므로 지정가 주문을 접수할 수 없습니다.", None
            else: # buy, all-in, margin buy
                return "⚠️ [거래 마감] 경기가 진행 중이므로 매수할 수 없습니다. (조회, 채굴, 대출 명령만 가능)", None

    # 4. Direct All-in Buy Order (!올인, !allin, !풀매수, !전액매수, !매수올인, !구매올인, !올인10배, !풀매수10X 등)
    allin_cmds = ["!올인", "!allin", "!풀매수", "!전액매수", "!매수올인", "!구매올인"]
    matched_allin_cmd = None
    allin_rem_product = None
    for ac in allin_cmds:
        if cmd == ac:
            matched_allin_cmd = ac
            break
        elif cmd.startswith(ac):
            rem = cmd[len(ac):].strip()
            p_cand = parse_product_type(f"{rem}X" if rem in ["1", "2", "3", "5", "10"] else rem)
            if p_cand:
                matched_allin_cmd = ac
                allin_rem_product = p_cand.value
                break

    if matched_allin_cmd:
        state = get_market_state(db)
        if is_market_locked(db, state):
            db.rollback()
            return "⚠️ [거래 마감] 경기가 진행 중이므로 매수할 수 없습니다. (조회, 채굴, 대출 명령만 가능)", None

        is_margin = False
        product_str = allin_rem_product
        for t in tokens[1:]:
            clean_t = t.strip().strip("'\"`’‘“”,;[]()").strip()
            parsed_prod = parse_product_type(clean_t)
            if clean_t in ["빚", "신용", "대출", "빚으로", "빚올인", "빚투", "신용올인"]:
                is_margin = True
            elif parsed_prod:
                product_str = parsed_prod.value
            elif clean_t in ["1", "2", "3", "5", "10"]:
                product_str = f"{clean_t}X"

        if not product_str:
            product_str = "1X"

        if is_margin:
            success, reply, details = execute_margin_buy(db, user_id, username, product_str, "올인")
        else:
            success, reply, details = execute_buy(db, user_id, username, product_str, "올인")
        event = {"type": "trade_buy", "data": details} if success and details else None
        return reply, event

    # 4-0. Direct Product Command (e.g. !10X 올인, !10배 올인, !10배올인, !10배 전량, !10배 매도, !10롱 올인, !곱버스 전량)
    direct_prod = None
    direct_qty = None

    if cmd.startswith("!"):
        cmd_sub = cmd[1:]
        cand_sub = f"{cmd_sub}X" if cmd_sub in ["1", "2", "3", "5", "10"] else cmd_sub
        direct_prod = parse_product_type(cand_sub)

        if direct_prod:
            direct_qty = tokens[1] if len(tokens) >= 2 else "1"
        else:
            # Check attached forms without space (e.g. !10배올인, !10롱올인, !10배풀매수, !10배전량, !10배매도, !10배10)
            from trading_engine import PRODUCT_SYNONYMS
            for pfx in sorted(PRODUCT_SYNONYMS.keys(), key=len, reverse=True):
                if cmd_sub.startswith(pfx.lower()):
                    rem = cmd_sub[len(pfx):].strip()
                    cand = parse_product_type(pfx)
                    if cand:
                        direct_prod = cand
                        direct_qty = rem if rem else (tokens[1] if len(tokens) >= 2 else "1")
                        break

    if direct_prod:
        state = get_market_state(db)
        if is_market_locked(db, state):
            db.rollback()
            return "⚠️ [거래 마감] 경기가 진행 중이므로 거래할 수 없습니다. (조회, 채굴, 대출 명령만 가능)", None

        allin_words = ["올인", "all", "전액", "풀매수", "다", "전부", "최대", "올인매수", "전액매수"]
        margin_words = ["빚올인", "빚으로올인", "대출올인", "신용올인", "빚투", "신용구매", "빚", "대출", "신용"]
        sell_words = ["전량", "매도", "팔기", "판매", "전량매도", "풀매도", "완판", "정리", "청산", "익절", "손절"]
        buy_words = ["매수", "사기", "구매", "매수하기"]

        qty_token = (direct_qty or "1").strip().strip("'\"`’‘“”,;[]()").strip()

        # Check if action is SELL (e.g. !10배 전량, !10배 매도, !10배 매도 5, !10배전량, !10배팔기)
        if any(qty_token.startswith(sw) for sw in sell_words) or qty_token in sell_words:
            sell_qty = "전량"
            if len(tokens) >= 3:
                sell_qty = tokens[2].strip()
            elif qty_token not in sell_words:
                for sw in sell_words:
                    if qty_token.startswith(sw):
                        rem_q = qty_token[len(sw):].strip()
                        if rem_q:
                            sell_qty = rem_q
                        break
            success, reply, details = execute_sell(db, user_id, username, direct_prod.value, sell_qty)
            event = {"type": "trade_sell", "data": details} if success and details else None
            return reply, event

        # Check if action is BUY keyword (e.g. !10배 매수 5, !10배 매수 올인, !10배 매수)
        if qty_token in buy_words or any(qty_token.startswith(bw) for bw in buy_words):
            buy_qty = "1"
            if len(tokens) >= 3:
                buy_qty = tokens[2].strip()
            elif qty_token not in buy_words:
                for bw in buy_words:
                    if qty_token.startswith(bw):
                        rem_q = qty_token[len(bw):].strip()
                        if rem_q:
                            buy_qty = rem_q
                        break
            qty_token = buy_qty

        # Execute Buy / Margin Buy
        if qty_token in margin_words:
            success, reply, details = execute_margin_buy(db, user_id, username, direct_prod.value, "올인")
        elif qty_token in allin_words:
            success, reply, details = execute_buy(db, user_id, username, direct_prod.value, "올인")
        else:
            success, reply, details = execute_buy(db, user_id, username, direct_prod.value, qty_token)
        event = {"type": "trade_buy", "data": details} if success and details else None
        return reply, event

    # 4-1. Market Buy Order (!매수, !사기, etc.)
    if cmd in ["!매수", "!사기", "!buy", "!구매", "!구매하기", "!매수하기"]:
        # Flexible syntax: !매수 [종목] [수량/올인/빚올인] or !매수 [올인/수량] [종목] or !매수 올인
        if len(tokens) < 2:
            return GUIDE_BUY, None

        t1 = tokens[1].strip().strip("'\"`’‘“”,;[]()").strip()
        t2 = tokens[2].strip().strip("'\"`’‘“”,;[]()").strip() if len(tokens) >= 3 else ""

        # Check if t1 has attached all-in suffix (e.g. 10배올인, 10X올인, 10배풀매수, 10롱올인)
        for aiw in ["올인", "풀매수", "전액", "전액매수", "올인매수", "빚올인", "빚투", "전부", "다", "최대"]:
            if t1.endswith(aiw) and len(t1) > len(aiw):
                prod_part = t1[:-len(aiw)].strip()
                p_cand = parse_product_type(f"{prod_part}X" if prod_part in ["1", "2", "3", "5", "10"] else prod_part)
                if p_cand:
                    t1 = p_cand.value
                    if not t2:
                        t2 = aiw
                    break

        p1 = parse_product_type(t1)
        p2 = parse_product_type(t2) if (t2 and not t2.isdigit()) else None

        allin_words = ["올인", "all", "전액", "풀매수", "다", "전부", "최대", "올인매수", "전액매수"]
        margin_words = ["빚올인", "빚으로올인", "대출올인", "신용올인", "빚투", "신용구매", "빚", "대출", "신용"]

        if p1:
            product_str = p1.value
            qty_str = t2 if t2 else "1"
        elif p2:
            product_str = p2.value
            qty_str = t1
        elif t1 in allin_words:
            product_str = "1X"
            qty_str = "올인"
        elif t1 in margin_words:
            product_str = "1X"
            qty_str = "빚올인"
        elif t1 in ["1", "2", "3", "5", "10"]:
            product_str = f"{t1}X"
            qty_str = t2 if t2 else "1"
        else:
            product_str = t1
            qty_str = t2 if t2 else "1"

        if qty_str in margin_words:
            success, reply, details = execute_margin_buy(db, user_id, username, product_str, "올인")
        elif qty_str in allin_words:
            success, reply, details = execute_buy(db, user_id, username, product_str, "올인")
        else:
            success, reply, details = execute_buy(db, user_id, username, product_str, qty_str)

        event = {"type": "trade_buy", "data": details} if success and details else None
        return reply, event

    # 4-2. Direct Margin Buy / 빚투 / 빚올인
    if cmd in ["!빚올인", "!빚으로올인", "!빚투", "!신용매수", "!대출매수", "!마진매수", "!빚매수", "!신용구매"]:
        product_str = None
        qty_str = "올인"
        for t in tokens[1:]:
            clean_t = t.strip().strip("'\"`’‘“”,;[]()").strip()
            parsed_prod = parse_product_type(clean_t)
            if parsed_prod:
                product_str = parsed_prod.value
            elif clean_t in ["1", "2", "3", "5", "10"]:
                product_str = f"{clean_t}X"
            elif clean_t not in ["올인", "all", "전액", "빚올인", "신용"]:
                qty_str = clean_t
        if not product_str:
            product_str = "1X"
        success, reply, details = execute_margin_buy(db, user_id, username, product_str, qty_str)
        event = {"type": "trade_buy", "data": details} if success and details else None
        return reply, event

    # 4-3. 빚으로 / 빚내서
    if cmd in ["!빚으로", "!빚내서"]:
        product_str = None
        for t in tokens[1:]:
            clean_t = t.strip().strip("'\"`’‘“”,;[]()").strip()
            p = parse_product_type(clean_t)
            if p:
                product_str = p.value
                break
            elif clean_t in ["1", "2", "3", "5", "10"]:
                product_str = f"{clean_t}X"
                break
        if not product_str:
            product_str = "1X"
        success, reply, details = execute_margin_buy(db, user_id, username, product_str, "올인")
        event = {"type": "trade_buy", "data": details} if success and details else None
        return reply, event

    # 5. Market Sell Order
    if cmd in ["!매도", "!팔기", "!sell", "!판매", "!판매하기", "!매도하기", "!전량매도", "!풀매도", "!완판"]:
        all_sell_words = ["전량", "all", "모두", "올인", "전부", "다", "최대", "풀매도", "전액"]
        if cmd in ["!전량매도", "!풀매도", "!완판"]:
            raw_p = tokens[1].strip().strip("'\"`’‘“”,;[]()").strip() if len(tokens) >= 2 else "1X"
            parsed_p = parse_product_type(raw_p)
            if parsed_p:
                product_str = parsed_p.value
            elif raw_p in ["1", "2", "3", "5", "10"]:
                product_str = f"{raw_p}X"
            else:
                product_str = raw_p
            qty_str = "전량"
        elif len(tokens) < 2:
            return GUIDE_SELL, None
        else:
            t1 = tokens[1].strip().strip("'\"`’‘“”,;[]()").strip()
            t2 = tokens[2].strip().strip("'\"`’‘“”,;[]()").strip() if len(tokens) >= 3 else ""
            p1 = parse_product_type(t1)
            p2 = parse_product_type(t2) if (t2 and not t2.isdigit()) else None
            if p1:
                product_str = p1.value
                qty_str = t2 if t2 else "전량"
            elif p2:
                product_str = p2.value
                qty_str = t1
            elif t1 in all_sell_words:
                product_str = "1X"
                qty_str = "전량"
            elif t1 in ["1", "2", "3", "5", "10"]:
                product_str = f"{t1}X"
                qty_str = t2 if t2 else "전량"
            else:
                product_str = t1
                qty_str = t2 if t2 else "전량"

        if qty_str in all_sell_words:
            qty_str = "전량"

        success, reply, details = execute_sell(db, user_id, username, product_str, qty_str)
        event = {"type": "trade_sell", "data": details} if success and details else None
        return reply, event

    # 6. Limit Order
    if cmd in ["!지정가", "!예약", "!limit"]:
        # Expected syntax: !지정가 [매수/매도] [종목] [목표가] [수량]
        if len(tokens) < 5:
            return GUIDE_LIMIT, None
        order_type_str, product_str, target_price_str, qty_str = tokens[1], tokens[2], tokens[3], tokens[4]
        success, reply, details = register_limit_order(
            db, user_id, username, order_type_str, product_str, target_price_str, qty_str
        )
        event = {"type": "limit_order", "data": details} if success and details else None
        return reply, event

    # 7. Instant Liquidation / Closeout
    if cmd in ["!청산", "!정리", "!손절", "!익절"]:
        # Expected syntax: !청산 [종목/전량]
        if len(tokens) < 2:
            return GUIDE_LIQUIDATE, None
        target_str = tokens[1]
        success, reply, details = execute_liquidate(db, user_id, username, target_str)
        event = {"type": "liquidate_manual", "data": details} if success and details else None
        return reply, event

    # 8. Mining (Proof of Watch 채굴)
    if cmd in ["!채굴", "!출석", "!에어드랍", "!mine"]:
        success, reply, details = execute_mining(db, user_id, username)
        event = {"type": "mining", "data": details} if success and details else None
        return reply, event

    # 9. Treasury Info Query
    if cmd in ["!국고", "!풀", "!채굴풀"]:
        info = get_treasury_info(db)
        pool = int(info["treasury_pool"])
        reply = (
            f"🏛️ [마작 국고 현황] 채굴 풀: {pool:,}P | "
            f"거래 수수료: 1% 국고 자동 적립 | 승리 배당: 1위 5% / 2위 1% | 채굴: !채굴 (15분 쿨)"
        )
        return reply, None

    # 10. Dividend Policy Query
    if cmd in ["!배당", "!배당금"]:
        reply = (
            "🎁 [승리 배당 안내] 1X(기본주) 보유 시 스트리머가 1위를 달성할 때마다 "
            "보유 평가액의 5%가 현금 배당으로 즉시 지급됩니다! (2위: 1%, 3위: 무배당)"
        )
        return reply, None

    # 11. Margin Loan (Borrow from Treasury)
    if cmd in ["!대출", "!빚", "!사채", "!신용", "!borrow", "!loan", "!빌리기", "!차용"]:
        user = get_or_create_user(db, user_id, username)
        if len(tokens) < 2:
            current_debt = getattr(user, "debt", 0) or 0
            avail = max(0, 50000 - current_debt)
            return f"{GUIDE_BORROW} (현재 빚: {current_debt:,}P | 추가 가능 한도: {avail:,}P)", None

        # Check if user typed '!대출 10X 올인' or '!대출 올인 10X' or '!빚 10X 올인' -> route to margin buy
        if len(tokens) >= 3:
            p1 = parse_product_type(tokens[1])
            p2 = parse_product_type(tokens[2])
            if p1 and tokens[2] in ["올인", "all", "전액", "최대", "빚올인"]:
                success, reply, details = execute_margin_buy(db, user_id, username, tokens[1], "올인")
                event = {"type": "trade_buy", "data": details} if success and details else None
                return reply, event
            elif p2 and tokens[1] in ["올인", "all", "전액", "최대", "빚올인"]:
                success, reply, details = execute_margin_buy(db, user_id, username, tokens[2], "올인")
                event = {"type": "trade_buy", "data": details} if success and details else None
                return reply, event

        amt_str = tokens[1]
        success, reply, details = execute_borrow(db, user_id, username, amt_str)
        event = {"type": "loan_borrow", "data": details} if success and details else None
        return reply, event

    # 12. Loan Repay
    if cmd in ["!상환", "!빚갚기", "!갚기", "!repay"]:
        amt_str = tokens[1] if len(tokens) >= 2 else "전액"
        success, reply, details = execute_repay(db, user_id, username, amt_str)
        event = {"type": "loan_repay", "data": details} if success and details else None
        return reply, event

    # 13. Bankruptcy / Rehabilitation (Na-bae Judge's Court)
    if cmd in ["!파산신청", "!개인회생", "!파산", "!회생", "!회생신청", "!개인파산", "!회생신청서", "!파산신청서", "!워크아웃", "!구제", "!구제신청"]:
        reason = " ".join(tokens[1:]) if len(tokens) > 1 else ""
        success, reply, details = submit_bankruptcy_application(db, user_id, username, reason)
        event = {"type": "bankruptcy_requested", "data": details} if success and details else None
        return reply, event

    # 14. Streamer Casino Open / Close Controls
    if cmd in ["!카지노오픈", "!도박오픈", "!카지노열기", "!도박열기"]:
        is_streamer = (user_id == CHANNEL_ID or username in ["치즈나베", "스트리머"] or user_id in ["streamer", "admin"])
        if not is_streamer:
            return "🚫 카지노 개장은 스트리머(치즈나베)만 진행할 수 있습니다!", None
        duration = 3.0
        max_bet = 100000
        for token in tokens[1:]:
            clean_tok = token.replace(",", "").strip()
            if clean_tok.endswith("만"):
                try:
                    val = float(clean_tok[:-1])
                    max_bet = int(val * 10000)
                    continue
                except ValueError:
                    pass
            if clean_tok.endswith("분"):
                try:
                    duration = float(clean_tok[:-1])
                    continue
                except ValueError:
                    pass
            if clean_tok.replace(".", "", 1).isdigit():
                num = float(clean_tok)
                if num >= 1000:
                    max_bet = int(num)
                else:
                    duration = num
        max_bet = max(100000, max_bet)
        success, reply, details = open_casino(db, duration_minutes=duration, max_bet=max_bet)
        event = {"type": "casino_open", "data": details} if success and details else None
        return reply, event

    if cmd in ["!카지노마감", "!도박마감", "!카지노닫기", "!도박닫기", "!카지노종료", "!도박종료"]:
        is_streamer = (user_id == CHANNEL_ID or username in ["치즈나베", "스트리머"] or user_id in ["streamer", "admin"])
        if not is_streamer:
            return "🚫 카지노 마감은 스트리머(치즈나베)만 진행할 수 있습니다!", None
        success, reply, details = close_casino(db)
        event = {"type": "casino_close", "data": details} if success and details else None
        return reply, event

    # 15. Casino Status Query
    if cmd in ["!카지노", "!도박장"]:
        c_state = get_casino_state(db)
        t_info = get_treasury_info(db)
        pool = int(t_info["treasury_pool"])
        if not c_state["is_open"]:
            return f"🎰 [나베 국고 카지노: 마감] 현재 도박장이 닫혀 있습니다. (국고 상금풀: {pool:,}P) | 스트리머가 개장할 때까지 대기해주세요!", None
        rem = c_state["remaining_sec"]
        time_str = f"{rem//60}분 {rem%60}초 남음" if rem > 0 else "무제한"
        return f"🎰 [나베 국고 카지노: 영업중 🔥] 남은 시간: {time_str} | 최대 배팅: {c_state['max_bet']:,}P | 잭팟 국고: {pool:,}P | 명령어: !슬롯 [금액/올인], !주사위 [홀/짝/대/소] [금액/올인] (확률: !슬롯확률)", None

    # 15-1. Casino & Slot Odds Query
    if cmd in ["!슬롯확률", "!도박확률", "!확률", "!배당표", "!카지노확률", "!배당율"]:
        reply = (
            "🎰 [국고 슬롯 공식 확률 & 배당표]\n"
            "• 총 당첨률 37.1% (슬롯 당첨 상한 캡 완전 해제! 🔥)\n"
            "• 👑777: 국고 20% MEGA JACKPOT 즉시 독식! (최소 15배 보장, 무제한)\n"
            "• 🀄역만: 10배 | 💎: 6배 | 🔔: 4배 | 🍇: 3배 | 🍒: 2배 (캡 없음)\n"
            "• 🥈2개 일치: 일반(🍒🍇🔔) 1.5배 적중(31.6%) | 고급(💎🀄7️⃣) 2.0배 적중(2.2%)\n"
            "• 💣/불일치: 꽝 (62.9% 국고 적립 | 슬롯 당첨금 캡 제한 없음)"
        )
        return reply, None

    # 16. Slot Machine Gamble
    if cmd in ["!슬롯", "!슬롯머신", "!slot", "!도박", "!룰렛"]:
        if len(tokens) < 2:
            return "🎰 [슬롯머신] 사용법: !슬롯 [금액/올인] (예: !슬롯 1000, !슬롯 올인) | 777 대박 시 국고 20% MEGA JACKPOT 즉시 독식 (당첨금 캡 없음!)", None
        bet_str = tokens[1]
        success, reply, details = execute_slot_gamble(db, user_id, username, bet_str)
        event = None
        if success and details:
            is_jackpot = details.get("is_jackpot", False)
            if is_jackpot:
                event = {"type": "casino_jackpot", "data": {**details, "gamble_type": "slot_jackpot", "payout": details["net_payout"], "win": True}}
            else:
                event = {"type": "casino_spin", "data": {**details, "win": details["won"], "payout": details["net_payout"], "bet_amount": details["bet"]}}
        return reply, event

    # 17. Dice Roll Gamble
    if cmd in ["!주사위", "!다이스", "!dice"]:
        if len(tokens) < 3:
            return "🎲 [주사위 배틀] 사용법: !주사위 [홀/짝/대/소] [금액/올인] (예: !주사위 홀 2000, !주사위 대 올인) | 홀/짝 1.9배, 대/소 2배, 더블(1-1/6-6) 시 2.5배 대박 (당첨금 캡 없음!)", None
        if tokens[1] in ["홀", "짝", "대", "소", "even", "odd", "high", "low"]:
            choice_str = tokens[1]
            bet_str = tokens[2]
        elif tokens[2] in ["홀", "짝", "대", "소", "even", "odd", "high", "low"]:
            choice_str = tokens[2]
            bet_str = tokens[1]
        else:
            choice_str = tokens[1]
            bet_str = tokens[2]
        success, reply, details = execute_dice_gamble(db, user_id, username, choice_str, bet_str)
        event = None
        if success and details:
            dice_sum = details.get("total", 0)
            d1, d2 = details.get("dice", [0, 0])
            is_crit = details.get("is_critical", False)
            if is_crit:
                event = {"type": "casino_jackpot", "data": {**details, "gamble_type": "dice_critical", "dice1": d1, "dice2": d2, "dice_sum": dice_sum, "payout": details["net_payout"], "win": True}}
            else:
                event = {"type": "casino_dice", "data": {**details, "dice1": d1, "dice2": d2, "dice_sum": dice_sum, "user_choice": choice_str, "win": details["won"], "payout": details["net_payout"], "bet_amount": details["bet"]}}
        return reply, event

    # 18. Streamer Match Settlement Command (!정산 [등수] [변동점수])
    if cmd in ["!정산", "!경기정산", "!결과", "!settle"]:
        is_streamer = (user_id == CHANNEL_ID or username in ["치즈나베", "스트리머"] or user_id in ["streamer", "admin"])
        if not is_streamer:
            return "🚫 경기 정산은 스트리머(치즈나베) 전용 명령어입니다!", None

        if len(tokens) < 2:
            return "🎯 [경기 정산 사용법] !정산 [순위(1~4)] [변동점수(선택)] (예: !정산 2 0, !정산 1 270, !정산 2, !정산 3 -330)", None

        try:
            rank_val = int(tokens[1])
            if rank_val not in (1, 2, 3, 4):
                return "⚠️ 순위는 1, 2, 3, 4 중 하나를 입력해주세요. (예: !정산 2 0, !정산 1 270)", None
        except ValueError:
            return f"⚠️ 올바른 순위를 입력해주세요: '{tokens[1]}'", None

        delta_val = 0
        if len(tokens) >= 3:
            try:
                delta_str = tokens[2].replace("+", "").strip()
                delta_val = int(delta_str)
            except ValueError:
                delta_val = 0
        else:
            default_deltas = {1: 270, 2: 0, 3: -330, 4: -600}
            delta_val = default_deltas.get(rank_val, 0)

        settle_res = settle_match(db, rank=rank_val, point_delta=delta_val)
        new_price = settle_res["new_price"]
        divs = settle_res.get("dividends", [])
        div_count = len(divs)
        div_total = sum(d["payout"] for d in divs)
        div_label = f" | 1X 배당: {div_count}명(+{div_total:,}P)" if div_count > 0 else ""
        liq_count = len(settle_res.get("liquidations", []))
        liq_label = f" | 🚨청산 {liq_count}건" if liq_count > 0 else ""

        delta_sign = f"+{delta_val}" if delta_val > 0 else f"{delta_val}"
        reply = (
            f"📢 [경기 정산 완료] {rank_val}위 ({delta_sign}pt) 정산 완료! "
            f"새 주가: {new_price:,}P{div_label}{liq_label} | 5분간 자유 거래 오픈!"
        )
        event = {
            "type": "settlement",
            "data": {
                **settle_res,
                "rank": rank_val,
                "point_delta": delta_val,
                "free_trading_remaining": 300
            }
        }
        return reply, event

    return None, None
