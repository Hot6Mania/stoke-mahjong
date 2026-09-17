import time
import math
import json
import hashlib
import random
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Tuple, List, Optional
from sqlalchemy import func
from sqlalchemy.orm import Session
from models import (
    User, Position, MarketState, LimitOrder, ProductType,
    OrderType, OrderStatus, BankruptcyApplication, BankruptcyStatus,
    DonationRecord
)

PRODUCT_MULTIPLIERS: Dict[ProductType, float] = {
    ProductType.ONE_X: 1.0,
    ProductType.TWO_X: 2.0,
    ProductType.THREE_X: 3.0,
    ProductType.FIVE_X: 5.0,
    ProductType.TEN_X: 10.0,
    ProductType.INV: -1.0,
    ProductType.TWO_X_INV: -2.0,
    ProductType.THREE_X_INV: -3.0,
    ProductType.FIVE_X_INV: -5.0,
    ProductType.TEN_X_INV: -10.0,
}

SUPPORTED_PRODUCTS_GUIDE: str = "1X, 2X, 3X, 5X, 10X (레버리지) / INV, 2X_INV, 3X_INV, 5X_INV, 10X_INV (인버스)"

PRODUCT_SYNONYMS = {
    "1X": ProductType.ONE_X,
    "1x": ProductType.ONE_X,
    "1배": ProductType.ONE_X,
    "1레": ProductType.ONE_X,
    "1버": ProductType.ONE_X,
    "1레버": ProductType.ONE_X,
    "1롱": ProductType.ONE_X,
    "롱": ProductType.ONE_X,
    "기본": ProductType.ONE_X,
    "기본주": ProductType.ONE_X,
    "현물": ProductType.ONE_X,

    "2X": ProductType.TWO_X,
    "2x": ProductType.TWO_X,
    "2배": ProductType.TWO_X,
    "2레": ProductType.TWO_X,
    "2버": ProductType.TWO_X,
    "2레버": ProductType.TWO_X,
    "2롱": ProductType.TWO_X,
    "2배롱": ProductType.TWO_X,
    "2배레버": ProductType.TWO_X,
    "2배레버리지": ProductType.TWO_X,
    "2X레버": ProductType.TWO_X,
    "레버리지": ProductType.TWO_X,
    "레버": ProductType.TWO_X,

    "3X": ProductType.THREE_X,
    "3x": ProductType.THREE_X,
    "3배": ProductType.THREE_X,
    "3레": ProductType.THREE_X,
    "3버": ProductType.THREE_X,
    "3레버": ProductType.THREE_X,
    "3롱": ProductType.THREE_X,
    "3배롱": ProductType.THREE_X,
    "3배레버": ProductType.THREE_X,
    "3배레버리지": ProductType.THREE_X,
    "3X레버": ProductType.THREE_X,

    "5X": ProductType.FIVE_X,
    "5x": ProductType.FIVE_X,
    "5배": ProductType.FIVE_X,
    "5레": ProductType.FIVE_X,
    "5버": ProductType.FIVE_X,
    "5레버": ProductType.FIVE_X,
    "5롱": ProductType.FIVE_X,
    "5배롱": ProductType.FIVE_X,
    "5배레버": ProductType.FIVE_X,
    "5배레버리지": ProductType.FIVE_X,
    "5X레버": ProductType.FIVE_X,

    "10X": ProductType.TEN_X,
    "10x": ProductType.TEN_X,
    "10배": ProductType.TEN_X,
    "10배주": ProductType.TEN_X,
    "10배주식": ProductType.TEN_X,
    "10레": ProductType.TEN_X,
    "10버": ProductType.TEN_X,
    "10롱": ProductType.TEN_X,
    "10배롱": ProductType.TEN_X,
    "10X롱": ProductType.TEN_X,
    "10레버": ProductType.TEN_X,
    "10배레버": ProductType.TEN_X,
    "10배레버리지": ProductType.TEN_X,
    "10X레버": ProductType.TEN_X,

    "INV": ProductType.INV,
    "inv": ProductType.INV,
    "1X_INV": ProductType.INV,
    "1XINV": ProductType.INV,
    "1배인버스": ProductType.INV,
    "1인": ProductType.INV,
    "1곱": ProductType.INV,
    "1숏": ProductType.INV,
    "인버스": ProductType.INV,
    "인버스1X": ProductType.INV,
    "숏": ProductType.INV,

    "2X_INV": ProductType.TWO_X_INV,
    "2x_inv": ProductType.TWO_X_INV,
    "2XINV": ProductType.TWO_X_INV,
    "2xinv": ProductType.TWO_X_INV,
    "곱버스": ProductType.TWO_X_INV,
    "2X인버스": ProductType.TWO_X_INV,
    "2x인버스": ProductType.TWO_X_INV,
    "2배인버스": ProductType.TWO_X_INV,
    "2배곱버스": ProductType.TWO_X_INV,
    "2인": ProductType.TWO_X_INV,
    "2곱": ProductType.TWO_X_INV,
    "2X숏": ProductType.TWO_X_INV,
    "2배숏": ProductType.TWO_X_INV,
    "2숏": ProductType.TWO_X_INV,
    "인버스2X": ProductType.TWO_X_INV,
    "인버스2배": ProductType.TWO_X_INV,

    "3X_INV": ProductType.THREE_X_INV,
    "3x_inv": ProductType.THREE_X_INV,
    "3XINV": ProductType.THREE_X_INV,
    "3xinv": ProductType.THREE_X_INV,
    "3배인버스": ProductType.THREE_X_INV,
    "3배곱버스": ProductType.THREE_X_INV,
    "3인": ProductType.THREE_X_INV,
    "3곱": ProductType.THREE_X_INV,
    "3X인버스": ProductType.THREE_X_INV,
    "3X숏": ProductType.THREE_X_INV,
    "3배숏": ProductType.THREE_X_INV,
    "3숏": ProductType.THREE_X_INV,
    "인버스3X": ProductType.THREE_X_INV,
    "인버스3배": ProductType.THREE_X_INV,

    "5X_INV": ProductType.FIVE_X_INV,
    "5x_inv": ProductType.FIVE_X_INV,
    "5XINV": ProductType.FIVE_X_INV,
    "5xinv": ProductType.FIVE_X_INV,
    "5배인버스": ProductType.FIVE_X_INV,
    "5배곱버스": ProductType.FIVE_X_INV,
    "5인": ProductType.FIVE_X_INV,
    "5곱": ProductType.FIVE_X_INV,
    "5X인버스": ProductType.FIVE_X_INV,
    "5X숏": ProductType.FIVE_X_INV,
    "5배숏": ProductType.FIVE_X_INV,
    "5숏": ProductType.FIVE_X_INV,
    "인버스5X": ProductType.FIVE_X_INV,
    "인버스5배": ProductType.FIVE_X_INV,

    "10X_INV": ProductType.TEN_X_INV,
    "10x_inv": ProductType.TEN_X_INV,
    "10XINV": ProductType.TEN_X_INV,
    "10xinv": ProductType.TEN_X_INV,
    "10배인버스": ProductType.TEN_X_INV,
    "10배곱버스": ProductType.TEN_X_INV,
    "10인": ProductType.TEN_X_INV,
    "10곱": ProductType.TEN_X_INV,
    "10X인버스": ProductType.TEN_X_INV,
    "10X숏": ProductType.TEN_X_INV,
    "10배숏": ProductType.TEN_X_INV,
    "10숏": ProductType.TEN_X_INV,
    "인버스10X": ProductType.TEN_X_INV,
    "인버스10배": ProductType.TEN_X_INV,
}

def parse_product_type(text: str) -> Optional[ProductType]:
    """Parse product string or Korean synonym into ProductType enum, stripping quotes and symbols."""
    if not text:
        return None
    cleaned = str(text).strip().strip("'\"`’‘“”,;[]()").strip()
    if not cleaned:
        return None

    # Exact or uppercase lookup
    if cleaned.upper() in PRODUCT_SYNONYMS:
        return PRODUCT_SYNONYMS[cleaned.upper()]
    if cleaned in PRODUCT_SYNONYMS:
        return PRODUCT_SYNONYMS[cleaned]

    # Handle forms like "10x", "5x", "10배", "5배", "10레", "10버", "10롱"
    upper_c = cleaned.upper()
    for suffix in ["X", "배", "레", "버", "레버", "배레버", "롱", "배롱", "X롱", "배주", "배주식"]:
        if upper_c.endswith(suffix):
            prefix = upper_c[:-len(suffix)].strip()
            if prefix in ["1", "2", "3", "5", "10"]:
                return PRODUCT_SYNONYMS.get(f"{prefix}X")

    # Handle inverse forms like "10숏", "10인", "10곱", "10인버스", "10곱버스"
    for suffix in ["인", "곱", "숏", "배인", "배곱", "배숏", "인버스", "곱버스", "X인버스", "X숏", "X_INV", "XINV"]:
        if upper_c.endswith(suffix):
            prefix = upper_c[:-len(suffix)].strip()
            if prefix in ["1", "2", "3", "5", "10"]:
                inv_key = "INV" if prefix == "1" else f"{prefix}X_INV"
                return PRODUCT_SYNONYMS.get(inv_key)

    return None

STARTING_POINTS: int = 50000
DEFAULT_TREASURY_POOL: float = 500000.0
TRADING_FEE_RATE: float = 0.01  # 1% 거래 수수료 -> 국고 채굴풀 자동 적립
MAX_LOAN_LIMIT: int = 50000     # 최대 50,000P 신용 대출 한도
LOAN_INTEREST_RATE: float = 0.02 # 경기당 2% 대출 이자 (국고 환수)

# 계좌이체 세금 정책: 1만P 이상 5%, 10만P 이상 10% (1만P 미만 면세)
TRANSFER_TAX_THRESHOLD: int = 10000       # 1만P 이상 이체 시 세금 부과
TRANSFER_TAX_RATE: float = 0.05           # 1만P 이상 기본 5% 이체세
TRANSFER_HIGH_TAX_THRESHOLD: int = 100000 # 10만P 이상 초고액 이체 시
TRANSFER_HIGH_TAX_RATE: float = 0.10      # 10만P 이상 10% 증여세

def parse_korean_amount(val_str: Any) -> Optional[int]:
    """Parse amounts like 10000, 10,000, 5만, 10만, 1.5만, 5천, 1억 into integer points."""
    if val_str is None:
        return None
    s = str(val_str).strip().lower().replace(",", "").replace("p", "").replace("원", "")
    if not s:
        return None
    if s.isdigit():
        return int(s)

    # 억
    m_eok = re.match(r"^(\d+(?:\.\d+)?)\s*억$", s)
    if m_eok:
        try:
            return int(round(float(m_eok.group(1)) * 100000000))
        except ValueError:
            return None

    # 만 (e.g. 5만, 1.5만, 10만)
    m_man = re.match(r"^(\d+(?:\.\d+)?)\s*만$", s)
    if m_man:
        try:
            return int(round(float(m_man.group(1)) * 10000))
        except ValueError:
            return None

    # 천 (e.g. 5천, 1.5천)
    m_cheon = re.match(r"^(\d+(?:\.\d+)?)\s*천$", s)
    if m_cheon:
        try:
            return int(round(float(m_cheon.group(1)) * 1000))
        except ValueError:
            return None

    # Compound: e.g. 5만5천 or 1만2000
    m_comp = re.match(r"^(\d+)\s*만\s*(\d+)?$", s)
    if m_comp:
        try:
            man_part = int(m_comp.group(1)) * 10000
            rem_str = m_comp.group(2)
            rem_part = int(rem_str) if rem_str else 0
            return man_part + rem_part
        except ValueError:
            return None

    try:
        f = float(s)
        return int(round(f))
    except ValueError:
        return None

def calculate_transfer_tax(amount: int) -> Tuple[int, float, str]:
    """
    Calculate transfer tax based on amount:
    - < 10,000P: 0% (면세)
    - 10,000P ~ 99,999P: 5% (고액 이체세)
    - >= 100,000P: 10% (초고액 증여세)
    Returns: (tax_amount, tax_rate, tax_label)
    """
    if amount >= TRANSFER_HIGH_TAX_THRESHOLD:
        tax = max(1, int(round(amount * TRANSFER_HIGH_TAX_RATE)))
        return tax, TRANSFER_HIGH_TAX_RATE, "초고액 증여세"
    elif amount >= TRANSFER_TAX_THRESHOLD:
        tax = max(1, int(round(amount * TRANSFER_TAX_RATE)))
        return tax, TRANSFER_TAX_RATE, "고액 이체세"
    else:
        return 0, 0.0, "면세"

def format_quantity(quantity: Any) -> str:
    """Safely format stock quantity: integer if whole number (e.g. 5), else 2 decimals (e.g. 5.25)."""
    try:
        f = float(quantity)
        if f.is_integer():
            return str(int(f))
        return f"{f:.2f}"
    except (ValueError, TypeError):
        return str(quantity)

def calculate_stock_price(rank_points: int) -> int:
    """1:1 Rank Point Peg with a safety floor of 100P to prevent bankruptcy."""
    return max(100, int(rank_points))

def get_market_state(db: Session) -> MarketState:
    """Retrieve market state or create default."""
    state = db.query(MarketState).filter_by(id=1).first()
    if not state:
        initial_rank = 2340
        initial_price = calculate_stock_price(initial_rank)
        state = MarketState(
            id=1,
            current_rank_point=initial_rank,
            current_price=initial_price,
            previous_price=initial_price,
            day_open_price=initial_price,
            is_trading_locked=False,
            last_settlement_delta=0,
            treasury_pool=DEFAULT_TREASURY_POOL
        )
        db.add(state)
        db.commit()
        db.refresh(state)
    else:
        updated = False
        if getattr(state, "treasury_pool", None) is None or state.treasury_pool < 50000.0:
            state.treasury_pool = DEFAULT_TREASURY_POOL
            updated = True
        if getattr(state, "day_open_price", None) is None or state.day_open_price <= 0:
            state.day_open_price = state.current_price or 2340
            updated = True
        end_time = getattr(state, "free_trading_end_time", 0.0) or 0.0
        if not state.is_trading_locked and end_time > 0 and time.time() >= end_time:
            state.is_trading_locked = True
            state.free_trading_end_time = 0.0
            updated = True
        if updated:
            try:
                db.commit()
                db.refresh(state)
            except Exception:
                pass
    return state

def is_market_locked(db: Session, state: Optional[MarketState] = None) -> bool:
    """
    Checks if the trading market is currently locked.
    Enforces lock if:
    1. state.is_trading_locked == True
    2. free_trading_end_time was set and has expired (time.time() >= free_trading_end_time)
    If expired, automatically updates state.is_trading_locked = True in DB.
    """
    if not state:
        state = get_market_state(db)

    if getattr(state, "is_trading_locked", False):
        return True

    end_time = getattr(state, "free_trading_end_time", 0.0) or 0.0
    if end_time > 0 and time.time() >= end_time:
        state.is_trading_locked = True
        state.free_trading_end_time = 0.0
        try:
            db.commit()
            db.refresh(state)
        except Exception:
            pass
        return True

    return False

def get_user_by_identifier(db: Session, identifier: str) -> Optional[User]:
    """Find user by exact ID or exact/case-insensitive username."""
    if not identifier:
        return None
    clean = identifier.strip()
    # 1. By ID
    u = db.query(User).filter_by(id=clean).first()
    if u:
        return u
    # 2. By Username (exact)
    u = db.query(User).filter_by(username=clean).first()
    if u:
        return u
    # 3. By Username (case-insensitive)
    u = db.query(User).filter(User.username.ilike(clean)).first()
    return u

def get_or_create_user(db: Session, user_id: str, username: str) -> User:
    """Find or initialize user with starting points (50,000P). Resolves by ID or Username."""
    # 1. Search by user_id
    user = db.query(User).filter_by(id=user_id).first()

    # 2. Search by username if not found
    if not user and username:
        user = db.query(User).filter_by(username=username).first()
        if not user:
            user = db.query(User).filter(User.username.ilike(username.strip())).first()

    # 3. Check if user_id was passed as username
    if not user and user_id:
        user = db.query(User).filter_by(username=user_id).first()
        if not user:
            user = db.query(User).filter(User.username.ilike(user_id.strip())).first()

    if not user:
        user = User(id=user_id, username=username or user_id, points=STARTING_POINTS)
        db.add(user)
        db.commit()
        db.refresh(user)
    elif username and user.username != username and not user.username.startswith("chzzk_"):
        user.username = username
        db.commit()
    return user

def calculate_position_valuation(position: Position, current_base_price: int) -> Dict[str, Any]:
    """Calculate the real-time market value, unrealized PnL, and effective unit price of a position."""
    if not position or position.quantity <= 0 or position.invested_cash <= 0:
        return {
            "current_value": 0.0,
            "unit_price": float(current_base_price),
            "unrealized_pnl": 0.0,
            "pnl_pct": 0.0,
        }

    entry = position.entry_price if position.entry_price > 0 else float(current_base_price)
    base_return = (current_base_price - entry) / entry if entry > 0 else 0.0
    multiplier = PRODUCT_MULTIPLIERS.get(position.product_type, 1.0)
    product_return = base_return * multiplier

    # Total current valuation of this position
    current_value = max(0.0, position.invested_cash * (1.0 + product_return))
    unrealized_pnl = current_value - position.invested_cash
    pnl_pct = product_return * 100.0
    unit_price = current_value / position.quantity if position.quantity > 0 else float(current_base_price)

    return {
        "current_value": current_value,
        "unit_price": unit_price,
        "unrealized_pnl": unrealized_pnl,
        "pnl_pct": pnl_pct,
    }

def execute_buy(
    db: Session,
    user_id: str,
    username: str,
    product_str: str,
    quantity_str: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Execute market buy order."""
    state = get_market_state(db)
    if is_market_locked(db, state):
        db.rollback()
        return False, "⚠️ [거래 마감] 경기가 진행 중이므로 매수할 수 없습니다. (조회 명령만 가능)", None

    product_type = parse_product_type(product_str)
    if not product_type:
        return False, f"⚠️ 알 수 없는 종목입니다: '{product_str}' (지원: {SUPPORTED_PRODUCTS_GUIDE})", None
    product_str = product_type.value

    user = get_or_create_user(db, user_id, username)
    current_price = state.current_price

    # Determine quantity
    clean_qty_str = quantity_str.strip()
    for unit in ["주", "개"]:
        if clean_qty_str.endswith(unit) and len(clean_qty_str) > len(unit):
            candidate = clean_qty_str[:-len(unit)].strip()
            try:
                float(candidate)
                clean_qty_str = candidate
                break
            except ValueError:
                pass

    if clean_qty_str in ["빚올인", "빚으로올인", "대출올인", "신용올인", "빚투"]:
        return execute_margin_buy(db, user_id, username, product_str, "올인")

    if clean_qty_str in ["올인", "all", "전액", "풀매수", "올인매수", "전액매수", "최대", "전부", "다"]:
        quantity = math.floor(user.points / (current_price * (1.0 + TRADING_FEE_RATE)))
        if quantity <= 0:
            current_debt = getattr(user, "debt", 0) or 0
            avail_loan = max(0, MAX_LOAN_LIMIT - current_debt)
            treasury_avail = int(getattr(state, "treasury_pool", DEFAULT_TREASURY_POOL) or 0)
            actual_avail = min(avail_loan, treasury_avail)
            if actual_avail > 0:
                return False, (
                    f"⚠️ 보유 포인트가 부족하여 올인 매수할 수 없습니다 (보유: {user.points:,}P, 1주 필요: {int(current_price * (1.0 + TRADING_FEE_RATE)):,}P). "
                    f"💡 빚(국고 대출)으로 올인하시려면 '!매수 {product_type.value} 빚올인' 또는 '!빚올인 {product_type.value}'을 입력하세요! (대출 가능 한도: {actual_avail:,}P)"
                ), None
            return False, f"⚠️ 포인트가 부족하여 올인 매수할 수 없습니다. (보유: {user.points:,}P, 현재가: {current_price:,}P, 수수료: 1%)", None
    else:
        try:
            quantity = float(clean_qty_str)
            if quantity <= 0:
                return False, "⚠️ 매수 수량은 0보다 커야 합니다.", None
        except ValueError:
            return False, f"⚠️ 유효하지 않은 수량입니다: '{quantity_str}' (수량 숫자 또는 '올인' 입력)", None

    cost = int(round(quantity * current_price))
    fee = max(1, int(round(cost * TRADING_FEE_RATE))) if cost > 0 else 0
    total_deduct = cost + fee

    while total_deduct > user.points and quantity > 0:
        quantity -= 1
        cost = int(round(quantity * current_price))
        fee = max(1, int(round(cost * TRADING_FEE_RATE))) if cost > 0 else 0
        total_deduct = cost + fee

    if quantity <= 0 or user.points < total_deduct:
        return False, f"⚠️ 잔여 포인트 부족! 필요: {total_deduct:,}P (체결금 {cost:,}P + 수수료 {fee:,}P) | 보유: {user.points:,}P", None

    # Deduct cash & accumulate fee to Treasury Pool
    user.points -= total_deduct
    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL
    state.treasury_pool += fee

    # Update or create position
    pos = db.query(Position).filter_by(user_id=user.id, product_type=product_type).first()
    if pos and pos.quantity > 0:
        new_quantity = pos.quantity + quantity
        new_invested = pos.invested_cash + cost
        weighted_entry = new_invested / new_quantity
        pos.quantity = new_quantity
        pos.invested_cash = new_invested
        pos.entry_price = weighted_entry
    else:
        if not pos:
            pos = Position(
                user_id=user.id,
                product_type=product_type,
                quantity=quantity,
                entry_price=float(current_price),
                invested_cash=float(cost)
            )
            db.add(pos)
        else:
            pos.quantity = quantity
            pos.entry_price = float(current_price)
            pos.invested_cash = float(cost)

    db.commit()
    db.refresh(user)
    db.refresh(pos)

    qty_display = format_quantity(quantity)
    is_allin = clean_qty_str in ["올인", "all", "전액", "풀매수", "올인매수", "전액매수", "최대", "전부", "다"]
    allin_label = "전액 올인 " if is_allin else ""
    msg = (
        f"✅ [매수 체결] [구매 완료] {user.username}님이 {product_type.value} {qty_display}주(총 {cost:,}P)를 "
        f"{allin_label}구매했습니다! "
        f"(매수 완료 | 체결단가: {current_price:,}P, 수수료: {fee:,}P 국고 적립, 잔여: {user.points:,}P)"
    )
    return True, msg, {
        "user_id": user.id,
        "username": user.username,
        "product_type": product_type.value,
        "quantity": quantity,
        "price": current_price,
        "cost": cost,
        "fee": fee,
        "total_cost": total_deduct,
        "remaining_points": user.points,
        "treasury_pool": state.treasury_pool
    }

def execute_margin_buy(
    db: Session,
    user_id: str,
    username: str,
    product_str: str,
    quantity_str: str = "올인"
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Execute Margin Buy / 빚으로 올인:
    Borrow available credit from community treasury pool (up to MAX_LOAN_LIMIT)
    and immediately invest all available points into the target stock product.
    """
    state = get_market_state(db)
    if is_market_locked(db, state):
        db.rollback()
        return False, "⚠️ [거래 마감] 경기가 진행 중이므로 매수할 수 없습니다. (조회 명령만 가능)", None

    product_type = parse_product_type(product_str)
    if not product_type:
        return False, f"⚠️ 알 수 없는 종목입니다: '{product_str}' (지원: {SUPPORTED_PRODUCTS_GUIDE})", None
    product_str = product_type.value

    user = get_or_create_user(db, user_id, username)
    current_price = state.current_price
    current_debt = getattr(user, "debt", 0) or 0

    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL

    # Calculate borrowable capacity
    max_borrow = max(0, MAX_LOAN_LIMIT - current_debt)
    borrow_amount = min(max_borrow, int(state.treasury_pool))

    # If user has borrowable room and treasury has funds, borrow first
    if borrow_amount > 0:
        state.treasury_pool -= borrow_amount
        user.debt = current_debt + borrow_amount
        user.points += borrow_amount

    # Now calculate buy quantity with total cash
    clean_qty_str = (quantity_str or "올인").strip()
    if clean_qty_str in ["올인", "all", "전액", "풀매수", "올인매수", "전액매수", "최대", "전부", "다", "빚올인", "빚으로올인", "대출올인", "신용올인", "빚투"]:
        quantity = math.floor(user.points / (current_price * (1.0 + TRADING_FEE_RATE)))
        if quantity <= 0:
            db.commit()
            if borrow_amount > 0:
                return False, f"⚠️ 국고에서 {borrow_amount:,}P를 대출하였으나 현재 주가({current_price:,}P) 1주를 매수하기에 부족합니다. (보유 현금: {user.points:,}P, 총 빚: {user.debt:,}P)", None
            return False, f"⚠️ 이미 최대 대출 한도({MAX_LOAN_LIMIT:,}P)에 도달하였고 잔여 포인트({user.points:,}P)도 부족하여 매수할 수 없습니다. (총 빚: {user.debt:,}P)", None
    else:
        try:
            quantity = float(clean_qty_str)
            if quantity <= 0:
                return False, "⚠️ 매수 수량은 0보다 커야 합니다.", None
        except ValueError:
            return False, f"⚠️ 유효하지 않은 수량입니다: '{quantity_str}' (수량 숫자 또는 '올인' 입력)", None

    cost = int(round(quantity * current_price))
    fee = max(1, int(round(cost * TRADING_FEE_RATE))) if cost > 0 else 0
    total_deduct = cost + fee

    while total_deduct > user.points and quantity > 0:
        quantity -= 1
        cost = int(round(quantity * current_price))
        fee = max(1, int(round(cost * TRADING_FEE_RATE))) if cost > 0 else 0
        total_deduct = cost + fee

    if quantity <= 0 or user.points < total_deduct:
        db.commit()
        return False, f"⚠️ 잔여 포인트 부족! 필요: {total_deduct:,}P (체결금 {cost:,}P + 수수료 {fee:,}P) | 보유 현금: {user.points:,}P (빚: {user.debt:,}P)", None

    # Deduct cash & accumulate fee to Treasury Pool
    user.points -= total_deduct
    state.treasury_pool += fee

    # Update or create position
    pos = db.query(Position).filter_by(user_id=user.id, product_type=product_type).first()
    if pos and pos.quantity > 0:
        new_quantity = pos.quantity + quantity
        new_invested = pos.invested_cash + cost
        weighted_entry = new_invested / new_quantity
        pos.quantity = new_quantity
        pos.invested_cash = new_invested
        pos.entry_price = weighted_entry
    else:
        if not pos:
            pos = Position(
                user_id=user.id,
                product_type=product_type,
                quantity=quantity,
                entry_price=float(current_price),
                invested_cash=float(cost)
            )
            db.add(pos)
        else:
            pos.quantity = quantity
            pos.entry_price = float(current_price)
            pos.invested_cash = float(cost)

    db.commit()
    db.refresh(user)
    db.refresh(pos)
    db.refresh(state)

    qty_display = format_quantity(quantity)
    if borrow_amount > 0:
        msg = (
            f"💳🔥 [빚투 / 신용 올인 체결] {user.username}님 국고 대출 {borrow_amount:,}P 실행 후 "
            f"{product_type.value} {qty_display}주(총 {cost:,}P)를 전액 올인 구매했습니다! (풀매수 완료 | "
            f"체결단가: {current_price:,}P | 총 채무: {user.debt:,}P | 잔여 현금: {user.points:,}P)"
        )
    else:
        msg = (
            f"✅ [매수 체결] [구매 완료] {user.username}님이 {product_type.value} {qty_display}주(총 {cost:,}P)를 전액 올인 구매했습니다! (매수 완료 | "
            f"체결단가: {current_price:,}P, 수수료: {fee:,}P 국고 적립, 잔여: {user.points:,}P)"
        )

    return True, msg, {
        "user_id": user.id,
        "username": user.username,
        "product_type": product_type.value,
        "quantity": quantity,
        "price": current_price,
        "cost": cost,
        "fee": fee,
        "total_cost": total_deduct,
        "borrowed_amount": borrow_amount,
        "total_debt": user.debt,
        "remaining_points": user.points,
        "treasury_pool": state.treasury_pool
    }

def execute_sell(
    db: Session,
    user_id: str,
    username: str,
    product_str: str,
    quantity_str: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Execute market sell order."""
    state = get_market_state(db)
    if is_market_locked(db, state):
        db.rollback()
        return False, "⚠️ [거래 마감] 경기가 진행 중이므로 매도할 수 없습니다. (조회 명령만 가능)", None

    product_type = parse_product_type(product_str)
    if not product_type:
        return False, f"⚠️ 알 수 없는 종목입니다: '{product_str}' (지원: {SUPPORTED_PRODUCTS_GUIDE})", None
    product_str = product_type.value

    user = get_or_create_user(db, user_id, username)
    pos = db.query(Position).filter_by(user_id=user.id, product_type=product_type).first()

    if not pos or pos.quantity <= 0:
        return False, f"⚠️ {user.username}님은 {product_type.value} 포지션을 보유하고 있지 않습니다.", None

    clean_qty = quantity_str.strip()
    for unit in ["주", "개"]:
        if clean_qty.endswith(unit) and len(clean_qty) > len(unit):
            candidate = clean_qty[:-len(unit)].strip()
            try:
                float(candidate)
                clean_qty = candidate
                break
            except ValueError:
                pass

    if clean_qty in ["전량", "all", "모두", "올인", "전부", "다", "최대", "풀매도", "전액"]:
        sell_qty = pos.quantity
    else:
        try:
            sell_qty = float(clean_qty)
            if sell_qty <= 0:
                return False, "⚠️ 매도 수량은 0보다 커야 합니다.", None
            if sell_qty > pos.quantity + 1e-9:
                qty_has = format_quantity(pos.quantity)
                return False, f"⚠️ 보유 수량을 초과했습니다! (현재 보유: {qty_has}주)", None
        except ValueError:
            return False, f"⚠️ 유효하지 않은 수량입니다: '{quantity_str}' (수량 숫자 또는 '전량' 입력)", None

    val = calculate_position_valuation(pos, state.current_price)
    ratio = min(1.0, sell_qty / pos.quantity)
    gross_payout = int(round(val["current_value"] * ratio))
    fee = max(1, int(round(gross_payout * TRADING_FEE_RATE))) if gross_payout > 0 else 0
    net_payout = max(0, gross_payout - fee)
    invested_part = pos.invested_cash * ratio
    pnl = net_payout - invested_part
    pnl_pct = (pnl / invested_part * 100.0) if invested_part > 0 else 0.0

    # Credit net points & accumulate fee to Treasury Pool
    user.points += net_payout
    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL
    state.treasury_pool += fee

    # Adjust position
    pos.quantity = max(0.0, pos.quantity - sell_qty)
    pos.invested_cash = max(0.0, pos.invested_cash - invested_part)
    if pos.quantity <= 1e-6 or pos.invested_cash <= 0:
        pos.quantity = 0.0
        pos.invested_cash = 0.0
        pos.entry_price = 0.0

    db.commit()
    db.refresh(user)

    qty_display = format_quantity(sell_qty)
    sign = "+" if pnl >= 0 else ""
    msg = f"✅ [매도 체결 / 판매 완료] {user.username}님이 {product_type.value} {qty_display}주를 판매했습니다! (매도 완료 | +{net_payout:,}P 입금, 수수료: {fee:,}P 국고 적립, 손익: {sign}{int(round(pnl)):,}P / {sign}{pnl_pct:.1f}%)"

    return True, msg, {
        "user_id": user.id,
        "username": user.username,
        "product_type": product_type.value,
        "quantity": sell_qty,
        "payout": net_payout,
        "gross_payout": gross_payout,
        "fee": fee,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "remaining_points": user.points,
        "treasury_pool": state.treasury_pool
    }

def execute_liquidate(
    db: Session,
    user_id: str,
    username: str,
    target_str: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Execute user-requested instant market liquidation (!청산 [종목/전량]).
    Sells position(s) at current market value immediately.
    """
    state = get_market_state(db)
    if is_market_locked(db, state):
        db.rollback()
        return False, "⚠️ [거래 마감] 경기가 진행 중이므로 청산할 수 없습니다.", None

    user = get_or_create_user(db, user_id, username)
    clean_target = target_str.strip()

    if clean_target in ["전량", "all", "모두", "전체"]:
        positions = db.query(Position).filter(Position.user_id == user.id, Position.quantity > 0).all()
        if not positions:
            return False, f"⚠️ {user.username}님은 보유 중인 포지션이 없습니다.", None

        total_gross_payout = 0
        total_invested = 0.0
        closed_details = []

        for p in positions:
            val = calculate_position_valuation(p, state.current_price)
            payout = int(round(val["current_value"]))
            total_gross_payout += payout
            total_invested += p.invested_cash
            closed_details.append(f"{p.product_type.value}({int(payout):,}P)")
            p.quantity = 0.0
            p.invested_cash = 0.0
            p.entry_price = 0.0

        fee = max(1, int(round(total_gross_payout * TRADING_FEE_RATE))) if total_gross_payout > 0 else 0
        net_payout = max(0, total_gross_payout - fee)
        total_pnl = net_payout - total_invested

        user.points += net_payout
        if getattr(state, "treasury_pool", None) is None:
            state.treasury_pool = DEFAULT_TREASURY_POOL
        state.treasury_pool += fee
        db.commit()

        sign = "+" if total_pnl >= 0 else ""
        msg = f"⚡ [전량 청산 완료] {user.username}님의 모든 포지션 즉시 정리 완료! (회수: +{net_payout:,}P, 수수료: {fee:,}P 국고 적립, 손익: {sign}{int(round(total_pnl)):,}P | 종목: {', '.join(closed_details)})"
        return True, msg, {
            "user_id": user.id,
            "username": user.username,
            "total_payout": net_payout,
            "gross_payout": total_gross_payout,
            "fee": fee,
            "total_pnl": total_pnl,
            "remaining_points": user.points,
            "treasury_pool": state.treasury_pool
        }
    else:
        # Liquidate specific product
        product_type = parse_product_type(clean_target)
        if not product_type:
            return False, f"⚠️ 청산 대상이 올바르지 않습니다: '{target_str}' (예: !청산 전량, !청산 2X)", None
        return execute_sell(db, user_id, username, product_type.value, "전량")

def register_limit_order(
    db: Session,
    user_id: str,
    username: str,
    order_type_str: str,
    product_str: str,
    target_price_str: str,
    quantity_str: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Register limit order (!지정가 [매수/매도] [종목] [목표가] [수량])."""
    state = get_market_state(db)
    if is_market_locked(db, state):
        db.rollback()
        return False, "⚠️ [거래 마감] 경기가 진행 중이므로 지정가 주문을 접수할 수 없습니다.", None

    # Parse order type
    clean_ot = order_type_str.strip().upper()
    if clean_ot in ["매수", "BUY"]:
        order_type = OrderType.BUY
    elif clean_ot in ["매도", "SELL"]:
        order_type = OrderType.SELL
    else:
        return False, f"⚠️ 주문 유형은 '매수' 또는 '매도'여야 합니다: '{order_type_str}'", None

    product_type = parse_product_type(product_str)
    if not product_type:
        return False, f"⚠️ 알 수 없는 종목입니다: '{product_str}' (지원: {SUPPORTED_PRODUCTS_GUIDE})", None
    product_str = product_type.value

    try:
        target_price = float(target_price_str)
        if target_price <= 0:
            return False, "⚠️ 목표가는 0보다 커야 합니다.", None
    except ValueError:
        return False, f"⚠️ 목표가가 올바른 숫자가 아닙니다: '{target_price_str}'", None

    try:
        quantity = float(quantity_str)
        if quantity <= 0:
            return False, "⚠️ 주문 수량은 0보다 커야 합니다.", None
    except ValueError:
        return False, f"⚠️ 주문 수량이 올바른 숫자가 아닙니다: '{quantity_str}'", None

    user = get_or_create_user(db, user_id, username)
    current_price = state.current_price

    if order_type == OrderType.BUY:
        # Check cash and reserve
        cost_reserved = int(round(target_price * quantity))
        fee_reserved = max(1, int(round(cost_reserved * TRADING_FEE_RATE))) if cost_reserved > 0 else 0
        total_reserved = cost_reserved + fee_reserved
        if user.points < total_reserved:
            return False, f"⚠️ 잔여 포인트 부족! 예약 필요금: {total_reserved:,}P (수수료 {fee_reserved:,}P 포함) | 보유: {user.points:,}P", None

        # Check if immediate fill
        if current_price <= target_price:
            actual_cost = int(round(current_price * quantity))
            fee = max(1, int(round(actual_cost * TRADING_FEE_RATE))) if actual_cost > 0 else 0
            total_deduct = actual_cost + fee
            user.points -= total_deduct
            if getattr(state, "treasury_pool", None) is None:
                state.treasury_pool = DEFAULT_TREASURY_POOL
            state.treasury_pool += fee

            pos = db.query(Position).filter_by(user_id=user.id, product_type=product_type).first()
            if pos and pos.quantity > 0:
                pos.quantity += quantity
                pos.invested_cash += actual_cost
                pos.entry_price = pos.invested_cash / pos.quantity
            else:
                if not pos:
                    pos = Position(
                        user_id=user.id,
                        product_type=product_type,
                        quantity=quantity,
                        entry_price=float(current_price),
                        invested_cash=float(actual_cost)
                    )
                    db.add(pos)
                else:
                    pos.quantity = quantity
                    pos.entry_price = float(current_price)
                    pos.invested_cash = float(actual_cost)

            order = LimitOrder(
                user_id=user.id,
                order_type=order_type,
                product_type=product_type,
                target_price=target_price,
                quantity=quantity,
                status=OrderStatus.FILLED
            )
            db.add(order)
            db.commit()
            qty_display = format_quantity(quantity)
            msg = f"✅ [지정가 매수 즉시 체결] 현재가({current_price:,}P)가 목표가({target_price:g}P) 이하이므로 즉시 체결되었습니다! ({product_type.value} {qty_display}주, 수수료: {fee:,}P 국고 적립, 잔여: {user.points:,}P)"
            return True, msg, {"order_id": order.id, "status": "FILLED"}
        else:
            # Reserve cash and place pending order
            user.points -= total_reserved
            order = LimitOrder(
                user_id=user.id,
                order_type=order_type,
                product_type=product_type,
                target_price=target_price,
                quantity=quantity,
                status=OrderStatus.PENDING
            )
            db.add(order)
            db.commit()
            qty_display = format_quantity(quantity)
            msg = f"📌 [지정가 매수 예약] #{order.id} {product_type.value} {qty_display}주 @ 목표가 {target_price:g}P 예약 완료 (예약금: {total_reserved:,}P 차감)"
            return True, msg, {"order_id": order.id, "status": "PENDING"}

    else: # SELL
        pos = db.query(Position).filter_by(user_id=user.id, product_type=product_type).first()
        if not pos or pos.quantity < quantity - 1e-9:
            has_q = pos.quantity if pos else 0
            qty_has = format_quantity(has_q)
            return False, f"⚠️ 매도 예약할 수량이 부족합니다. (보유: {qty_has}주)", None

        if current_price >= target_price:
            # Immediate fill
            val = calculate_position_valuation(pos, current_price)
            ratio = min(1.0, quantity / pos.quantity)
            gross_payout = int(round(val["current_value"] * ratio))
            fee = max(1, int(round(gross_payout * TRADING_FEE_RATE))) if gross_payout > 0 else 0
            net_payout = max(0, gross_payout - fee)
            invested_part = pos.invested_cash * ratio
            pnl = net_payout - invested_part

            user.points += net_payout
            if getattr(state, "treasury_pool", None) is None:
                state.treasury_pool = DEFAULT_TREASURY_POOL
            state.treasury_pool += fee

            pos.quantity = max(0.0, pos.quantity - quantity)
            pos.invested_cash = max(0.0, pos.invested_cash - invested_part)
            if pos.quantity <= 1e-6:
                pos.quantity = 0.0
                pos.invested_cash = 0.0
                pos.entry_price = 0.0

            order = LimitOrder(
                user_id=user.id,
                order_type=order_type,
                product_type=product_type,
                target_price=target_price,
                quantity=quantity,
                status=OrderStatus.FILLED
            )
            db.add(order)
            db.commit()
            qty_display = format_quantity(quantity)
            sign = "+" if pnl >= 0 else ""
            msg = f"✅ [지정가 매도 즉시 체결] 현재가({current_price:,}P)가 목표가({target_price:g}P) 이상이므로 즉시 체결되었습니다! ({product_type.value} {qty_display}주, +{net_payout:,}P 입금, 수수료: {fee:,}P 국고 적립)"
            return True, msg, {"order_id": order.id, "status": "FILLED"}
        else:
            # Reserve shares from position
            ratio = min(1.0, quantity / pos.quantity)
            invested_part = pos.invested_cash * ratio
            pos.quantity = max(0.0, pos.quantity - quantity)
            pos.invested_cash = max(0.0, pos.invested_cash - invested_part)
            if pos.quantity <= 1e-6:
                pos.quantity = 0.0
                pos.invested_cash = 0.0
                pos.entry_price = 0.0

            order = LimitOrder(
                user_id=user.id,
                order_type=order_type,
                product_type=product_type,
                target_price=target_price,
                quantity=quantity,
                status=OrderStatus.PENDING
            )
            db.add(order)
            db.commit()
            qty_display = format_quantity(quantity)
            msg = f"📌 [지정가 매도 예약] #{order.id} {product_type.value} {qty_display}주 @ 목표가 {target_price:g}P 예약 완료"
            return True, msg, {"order_id": order.id, "status": "PENDING"}

def settle_match(db: Session, rank: int, point_delta: int) -> Dict[str, Any]:
    """
    Admin match settlement:
    1. Updates rank points and recalculates base stock price
    2. Rebalances positions and runs liquidation (margin call) checks
    3. Triggers pending limit orders matching new price
    4. Unlocks trading market
    """
    state = get_market_state(db)
    old_price = state.current_price
    state.current_rank_point += point_delta
    new_price = calculate_stock_price(state.current_rank_point)
    return_pct = (new_price - old_price) / old_price if old_price > 0 else 0.0

    state.previous_price = old_price
    state.current_price = new_price
    state.last_settlement_delta = point_delta

    # Settle active positions & check liquidations
    positions = db.query(Position).filter(Position.quantity > 0, Position.invested_cash > 0).all()
    liquidations: List[Dict[str, Any]] = []

    for pos in positions:
        mult = PRODUCT_MULTIPLIERS.get(pos.product_type, 1.0)
        entry = pos.entry_price if pos.entry_price > 0 else float(old_price)
        base_ret = (new_price - entry) / entry if entry > 0 else 0.0
        product_ret = base_ret * mult

        # Margin Call / Liquidation Check:
        # If leveraged/inverse position loss >= 100% (or account value <= 0), forcefully liquidate
        is_derivative = pos.product_type != ProductType.ONE_X
        if is_derivative and product_ret <= -1.0:
            user = pos.user
            uname = user.username if user else pos.user_id
            liquidations.append({
                "user_id": pos.user_id,
                "username": uname,
                "product_type": pos.product_type.value,
                "lost_cash": int(round(pos.invested_cash)),
                "lost_quantity": pos.quantity,
                "entry_price": pos.entry_price,
            })
            pos.quantity = 0.0
            pos.invested_cash = 0.0
            pos.entry_price = 0.0
        else:
            # Do NOT alter pos.entry_price, pos.invested_cash, or pos.quantity!
            # The user's purchase price (평단가) must strictly reflect what they bought it for.
            pass

    # Accumulate liquidated collateral into Treasury Pool (No money lost, redistributed to community)
    total_liquidated_cash = sum(liq["lost_cash"] for liq in liquidations)
    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL
    state.treasury_pool += total_liquidated_cash

    # PoS Victory Dividend: 1st place pays 5%, 2nd place pays 1% to all 1X holders
    dividends_distributed: List[Dict[str, Any]] = []
    try:
        r = int(rank)
    except (ValueError, TypeError):
        r = 0
    div_rate = 0.05 if r == 1 else (0.01 if r == 2 else 0.0)

    if div_rate > 0:
        all_positions = db.query(Position).filter(Position.quantity > 0).all()
        for p in all_positions:
            is_one_x = (
                p.product_type == ProductType.ONE_X or
                p.product_type == "1X" or
                getattr(p.product_type, "value", None) == "1X"
            )
            if is_one_x and p.user:
                u = p.user
                payout = max(1, int(round(p.quantity * new_price * div_rate))) if (p.quantity > 0 and new_price > 0) else 0
                if payout > 0:
                    u.points += payout
                    u.total_dividends = (u.total_dividends or 0) + payout
                    dividends_distributed.append({
                        "user_id": u.id,
                        "username": u.username,
                        "payout": payout,
                        "shares": p.quantity,
                        "rate_pct": div_rate * 100.0
                    })

    # Process pending limit orders
    pending_orders = db.query(LimitOrder).filter_by(status=OrderStatus.PENDING).all()
    filled_orders: List[Dict[str, Any]] = []

    for order in pending_orders:
        user = order.user
        if not user:
            continue

        if order.order_type == OrderType.BUY and new_price <= order.target_price:
            # BUY order filled
            cost_reserved = int(round(order.target_price * order.quantity))
            fee_reserved = max(1, int(round(cost_reserved * TRADING_FEE_RATE))) if cost_reserved > 0 else 0
            total_reserved = cost_reserved + fee_reserved

            actual_cost = int(round(new_price * order.quantity))
            actual_fee = max(1, int(round(actual_cost * TRADING_FEE_RATE))) if actual_cost > 0 else 0
            actual_total = actual_cost + actual_fee

            refund = max(0, total_reserved - actual_total)
            user.points += refund
            if getattr(state, "treasury_pool", None) is None:
                state.treasury_pool = DEFAULT_TREASURY_POOL
            state.treasury_pool += actual_fee

            pos = db.query(Position).filter_by(user_id=user.id, product_type=order.product_type).first()
            if pos and pos.quantity > 0:
                pos.quantity += order.quantity
                pos.invested_cash += actual_cost
                pos.entry_price = float(new_price)
            else:
                if not pos:
                    pos = Position(
                        user_id=user.id,
                        product_type=order.product_type,
                        quantity=order.quantity,
                        entry_price=float(new_price),
                        invested_cash=float(actual_cost)
                    )
                    db.add(pos)
                else:
                    pos.quantity = order.quantity
                    pos.entry_price = float(new_price)
                    pos.invested_cash = float(actual_cost)

            order.status = OrderStatus.FILLED
            filled_orders.append({
                "order_id": order.id,
                "user_id": user.id,
                "username": user.username,
                "order_type": "BUY",
                "product_type": order.product_type.value,
                "quantity": order.quantity,
                "target_price": order.target_price,
                "fill_price": new_price,
                "fee": actual_fee
            })

        elif order.order_type == OrderType.SELL and new_price >= order.target_price:
            # SELL order filled
            gross_payout = int(round(new_price * order.quantity))
            fee = max(1, int(round(gross_payout * TRADING_FEE_RATE))) if gross_payout > 0 else 0
            net_payout = max(0, gross_payout - fee)
            user.points += net_payout
            if getattr(state, "treasury_pool", None) is None:
                state.treasury_pool = DEFAULT_TREASURY_POOL
            state.treasury_pool += fee

            order.status = OrderStatus.FILLED
            filled_orders.append({
                "order_id": order.id,
                "user_id": user.id,
                "username": user.username,
                "order_type": "SELL",
                "product_type": order.product_type.value,
                "quantity": order.quantity,
                "target_price": order.target_price,
                "fill_price": new_price,
                "fee": fee
            })

    # Loan interest: 2% charged on all outstanding debts at settlement
    total_interest_collected = 0
    debtors = db.query(User).filter(User.debt > 0).all()
    for debtor in debtors:
        interest = int(math.ceil(debtor.debt * LOAN_INTEREST_RATE))
        if interest > 0:
            if debtor.points >= interest:
                debtor.points -= interest
                total_interest_collected += interest
            else:
                paid = debtor.points
                unpaid = interest - paid
                debtor.points = 0
                debtor.debt += unpaid  # unpaid interest compounded into debt principal
                total_interest_collected += paid

    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL
    state.treasury_pool += total_interest_collected

    # Unlock market after settlement
    state.is_trading_locked = False

    db.commit()
    db.refresh(state)

    return {
        "rank": rank,
        "point_delta": point_delta,
        "new_rank_points": state.current_rank_point,
        "old_price": old_price,
        "new_price": new_price,
        "return_pct": return_pct,
        "is_trading_locked": state.is_trading_locked,
        "treasury_pool": state.treasury_pool,
        "liquidations": liquidations,
        "dividends": dividends_distributed,
        "filled_orders": filled_orders,
        "interest_collected": total_interest_collected
    }

# 메이플 스타일 곡괭이 스타포스 강화표 (0성 ~ 25성 MAX)
# 0~14성: 파괴 0% (안전/하락) | 15성~: 파괴 확률 존재 (파괴 시 12성 장비의 흔적 복원)
STARFORCE_TIERS: Dict[int, Dict[str, Any]] = {
    0: {"cost": 2000, "success": 99.75, "maintain": 0.25, "drop": 0.0, "destroy": 0.0},
    1: {"cost": 4000, "success": 94.50, "maintain": 5.50, "drop": 0.0, "destroy": 0.0},
    2: {"cost": 6000, "success": 89.25, "maintain": 10.75, "drop": 0.0, "destroy": 0.0},
    3: {"cost": 8000, "success": 89.25, "maintain": 10.75, "drop": 0.0, "destroy": 0.0},
    4: {"cost": 12000, "success": 84.00, "maintain": 16.00, "drop": 0.0, "destroy": 0.0},
    5: {"cost": 16000, "success": 78.75, "maintain": 21.25, "drop": 0.0, "destroy": 0.0},
    6: {"cost": 20000, "success": 73.50, "maintain": 26.50, "drop": 0.0, "destroy": 0.0},
    7: {"cost": 25000, "success": 68.25, "maintain": 31.75, "drop": 0.0, "destroy": 0.0},
    8: {"cost": 30000, "success": 63.00, "maintain": 37.00, "drop": 0.0, "destroy": 0.0},
    9: {"cost": 40000, "success": 57.75, "maintain": 42.25, "drop": 0.0, "destroy": 0.0},
    10: {"cost": 50000, "success": 52.50, "maintain": 47.50, "drop": 0.0, "destroy": 0.0},
    # 11~14성: 실패 시 1성 하락, 파괴 없음 (0%)
    11: {"cost": 70000, "success": 47.25, "maintain": 0.0, "drop": 52.75, "destroy": 0.0},
    12: {"cost": 100000, "success": 42.00, "maintain": 0.0, "drop": 58.00, "destroy": 0.0},
    13: {"cost": 140000, "success": 36.75, "maintain": 0.0, "drop": 63.25, "destroy": 0.0},
    14: {"cost": 200000, "success": 31.50, "maintain": 0.0, "drop": 68.50, "destroy": 0.0},
    # 15성: 15성 방지턱이라 실패 시 유지, 파괴 확률 발생 (2.055%)
    15: {"cost": 300000, "success": 31.50, "maintain": 66.445, "drop": 0.0, "destroy": 2.055},
    # 16~19성: 실패 시 하락, 파괴 발생
    16: {"cost": 450000, "success": 31.50, "maintain": 0.0, "drop": 66.445, "destroy": 2.055},
    17: {"cost": 650000, "success": 15.75, "maintain": 0.0, "drop": 77.510, "destroy": 6.740},
    18: {"cost": 900000, "success": 15.75, "maintain": 0.0, "drop": 77.510, "destroy": 6.740},
    19: {"cost": 1250000, "success": 15.75, "maintain": 0.0, "drop": 75.825, "destroy": 8.425},
    # 20성: 20성 방지턱이라 실패 시 유지, 파괴 발생 (10.275%)
    20: {"cost": 1700000, "success": 31.50, "maintain": 58.225, "drop": 0.0, "destroy": 10.275},
    # 21~24성: 실패 시 하락, 파괴 발생
    21: {"cost": 2300000, "success": 15.75, "maintain": 0.0, "drop": 71.6125, "destroy": 12.6375},
    22: {"cost": 3000000, "success": 15.75, "maintain": 0.0, "drop": 67.40, "destroy": 16.85},
    23: {"cost": 4000000, "success": 10.50, "maintain": 0.0, "drop": 71.60, "destroy": 17.90},
    24: {"cost": 5500000, "success": 10.50, "maintain": 0.0, "drop": 71.60, "destroy": 17.90},
    25: {"cost": 0, "success": 0.0, "maintain": 0.0, "drop": 0.0, "destroy": 0.0}
}

def get_pickaxe_info(level: int) -> Dict[str, Any]:
    lvl = max(0, min(25, int(level or 0)))

    if lvl >= 25:
        base_name = "🀄 역만 마작 곡괭이"
    elif lvl >= 22:
        base_name = "🌌 옵시디언 곡괭이"
    elif lvl >= 20:
        base_name = "💎 다이아 곡괭이"
    elif lvl >= 15:
        base_name = "🪙 황금 곡괭이"
    elif lvl >= 10:
        base_name = "⛓️ 철 곡괭이"
    elif lvl >= 5:
        base_name = "🪨 돌 곡괭이"
    else:
        base_name = "🪵 나무 곡괭이"

    name = f"{base_name} (★{lvl}성)"
    if lvl == 25:
        name = f"{base_name} (★25성 MAX)"

    t = STARFORCE_TIERS[lvl]

    # Mining yield multiplier calculation (BUFFED)
    # 0성 1.0x -> 10성 3.0x -> 15성 6.5x -> 20성 22.0x -> 22성 36.0x -> 25성 80.0x
    yield_table = {
        0: 1.00, 1: 1.15, 2: 1.30, 3: 1.45, 4: 1.60,
        5: 1.80, 6: 2.00, 7: 2.20, 8: 2.40, 9: 2.65,
        10: 3.00, 11: 3.50, 12: 4.00, 13: 4.60, 14: 5.30,
        15: 6.50, 16: 8.50, 17: 11.00, 18: 14.00, 19: 17.50,
        20: 22.00, 21: 28.00,
        22: 36.00, 23: 45.00, 24: 58.00,
        25: 80.00
    }
    yield_mult = yield_table.get(lvl, 1.00)

    # Guaranteed Bonus Points per Mine (BUFFED: 5성 돌 곡괭이부터 매 채굴마다 무조건 확정 지급되는 추가 현금)
    # 0~4성 0P -> 5성 5천P -> 10성 1.5만P -> 15성 6만P -> 20성 28만P -> 22성 50만P -> 25성 120만P
    bonus_points_table = {
        0: 0, 1: 0, 2: 0, 3: 0, 4: 0,
        5: 5000, 6: 6500, 7: 8000, 8: 10000, 9: 12000,
        10: 15000, 11: 20000, 12: 25000, 13: 32000, 14: 40000,
        15: 60000, 16: 85000, 17: 120000, 18: 160000, 19: 210000,
        20: 280000, 21: 380000,
        22: 500000, 23: 650000, 24: 850000,
        25: 1200000
    }
    bonus_points = bonus_points_table.get(lvl, 0)

    # Crit bonus (BUFFED)
    # 0성 0% -> 10성 20% -> 15성 45% -> 20성 85% -> 22성 100% -> 25성 150%
    crit_table = {
        0: 0.0, 1: 1.5, 2: 3.0, 3: 4.5, 4: 6.0,
        5: 8.0, 6: 10.0, 7: 12.0, 8: 14.0, 9: 16.0,
        10: 20.0, 11: 24.0, 12: 28.0, 13: 32.0, 14: 36.0,
        15: 45.0, 16: 52.0, 17: 60.0, 18: 68.0, 19: 76.0,
        20: 85.0, 21: 92.0,
        22: 100.0, 23: 110.0, 24: 120.0,
        25: 150.0
    }
    crit = crit_table.get(lvl, 0.0)

    # Cooldown minutes (BUFFED: 15분 -> 10분 -> 8분 -> 6분 -> 5분 -> 4분 -> 3분)
    if lvl >= 25:
        cd_min = 3
    elif lvl >= 22:
        cd_min = 4
    elif lvl >= 20:
        cd_min = 5
    elif lvl >= 17:
        cd_min = 6
    elif lvl >= 15:
        cd_min = 8
    elif lvl >= 10:
        cd_min = 10
    elif lvl >= 5:
        cd_min = 13
    else:
        cd_min = 15

    desc_parts = [f"채굴량 {yield_mult}배"]
    if bonus_points > 0:
        desc_parts.append(f"확정 +{bonus_points:,}P")
    desc_parts.append(f"크리 +{crit}%")
    desc_parts.append(f"쿨 {cd_min}분")
    desc = ", ".join(desc_parts)

    return {
        "level": lvl,
        "name": name,
        "base_name": base_name,
        "upgrade_cost": t["cost"],
        "yield_multiplier": yield_mult,
        "bonus_points": bonus_points,
        "crit_bonus": crit,
        "cooldown_minutes": cd_min,
        "cooldown_seconds": cd_min * 60,
        "success_rate": t["success"],
        "maintain_rate": t["maintain"],
        "drop_rate": t["drop"],
        "destroy_rate": t["destroy"],
        "desc": desc
    }

# Backwards compatibility dictionary mapping
PICKAXE_TIERS: Dict[int, Dict[str, Any]] = {i: get_pickaxe_info(i) for i in range(26)}

# 채굴 등급 및 크리티컬 확률/보상 테이블 (일확천금 신화급 잭팟 추가)
MINING_TIERS = [
    {
        "code": "EX",
        "name": "🀄🌟 [천화(天和) 신화급 국고 잭팟!! (0.2%)]",
        "prob": 0.2,
        "multiplier": 20.0,
        "bonus_cash_pct": 0.10,  # 국고 10% 일시불 (최소 5만P ~ 최대 30만P)
        "min_cash": 50000,
        "max_cash": 300000,
        "bonus_10x": 5.0,        # 10X 레버리지 5주!
        "cooldown_reduction": 15, # 쿨타임 즉시 초기화
    },
    {
        "code": "UR+",
        "name": "🀄 [순정 구련보등 더블역만 광맥!! (0.8%)]",
        "prob": 0.8,
        "multiplier": 10.0,
        "bonus_cash_pct": 0.05,  # 국고 5% (최소 2만P ~ 최대 10만P)
        "min_cash": 20000,
        "max_cash": 100000,
        "bonus_10x": 2.0,        # 10X 레버리지 2주!
        "cooldown_reduction": 10, # 쿨타임 10분 단축
    },
    {
        "code": "UR",
        "name": "🀄 [국사무쌍 13면대기 역만급 초대박 광맥!! (2.0%)]",
        "prob": 2.0,
        "multiplier": 5.0,
        "bonus_cash": 15000,
        "bonus_10x": 1.0,
        "cooldown_reduction": 7,  # 쿨타임 7분 단축
    },
    {
        "code": "SSR",
        "name": "💎 [다이아몬드 광맥 슈퍼 크리티컬! (5.0%)]",
        "prob": 5.0,
        "multiplier": 3.0,
        "bonus_cash": 7000,
        "bonus_10x": 0.0,
        "cooldown_reduction": 5,   # 쿨타임 5분 단축
    },
    {
        "code": "SR",
        "name": "⚡ [황금 광맥 더블 크리티컬! (14.0%)]",
        "prob": 14.0,
        "multiplier": 2.0,
        "bonus_cash": 2000,
        "bonus_10x": 0.0,
        "cooldown_reduction": 0,
    },
    {
        "code": "R",
        "name": "✨ [풍부한 은 광맥 보너스 채굴 (23.0%)]",
        "prob": 23.0,
        "multiplier_range": (1.3, 1.5),
        "bonus_cash": 0,
        "bonus_10x": 0.0,
        "cooldown_reduction": 0,
    },
    {
        "code": "N",
        "name": "⛏️ [평범한 구리 광맥 일반 채굴 (37.0%)]",
        "prob": 37.0,
        "multiplier": 1.0,
        "bonus_cash": 0,
        "bonus_10x": 0.0,
        "cooldown_reduction": 0,
    },
    {
        "code": "C",
        "name": "🪨 [석탄·자갈 광맥 소박 채굴 (18.0%)]",
        "prob": 18.0,
        "multiplier_range": (0.6, 0.8),
        "bonus_cash": 0,
        "bonus_10x": 0.0,
        "cooldown_reduction": 0,
    }
]

def roll_mining_tier(crit_bonus: float = 0.0) -> Dict[str, Any]:
    """
    Roll random mining tier based on weighted probabilities.
    Higher-level pickaxes grant a crit_bonus which boosts EX/UR+/UR/SSR/SR/R rates.
    """
    cb = max(0.0, float(crit_bonus or 0.0))

    # Calculate dynamic weights
    weights = []
    for tier in MINING_TIERS:
        code = tier["code"]
        base_prob = tier["prob"]
        if code == "EX":
            w = base_prob + cb * 0.08      # e.g. +8% at cb=100
        elif code == "UR+":
            w = base_prob + cb * 0.14     # e.g. +14% at cb=100
        elif code == "UR":
            w = base_prob + cb * 0.20     # e.g. +20% at cb=100
        elif code == "SSR":
            w = base_prob + cb * 0.28     # e.g. +28% at cb=100
        elif code == "SR":
            w = base_prob + cb * 0.20     # e.g. +20% at cb=100
        elif code == "R":
            w = base_prob + cb * 0.10     # e.g. +10% at cb=100
        elif code == "N":
            w = max(0.0, base_prob - cb * 0.40)
        elif code == "C":
            w = max(0.0, base_prob - cb * 0.50)
        else:
            w = base_prob
        weights.append(max(0.0, w))

    total_w = sum(weights)
    if total_w <= 0:
        tier_choice = MINING_TIERS[6]
    else:
        tier_choice = random.choices(MINING_TIERS, weights=weights, k=1)[0]

    t = dict(tier_choice)
    if "multiplier_range" in t:
        low, high = t["multiplier_range"]
        t["multiplier"] = round(random.uniform(low, high), 2)
    return t

def execute_mining(
    db: Session,
    user_id: str,
    username: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Execute !채굴 (Proof of Watch mining with pickaxe level, random critical hits & rewards).
    """
    state = get_market_state(db)
    user = get_or_create_user(db, user_id, username)
    now_utc = datetime.now(timezone.utc)

    # 1. Pickaxe Item Info
    curr_level = getattr(user, "pickaxe_level", 0)
    if curr_level is None:
        curr_level = 0
    pickaxe = get_pickaxe_info(curr_level)
    cooldown_sec = pickaxe["cooldown_seconds"]
    cooldown_min = pickaxe["cooldown_minutes"]
    pickaxe_bonus_cash = pickaxe.get("bonus_points", 0)

    # 2. Cooldown check based on pickaxe cooldown
    if user.last_mined_at:
        last_time = user.last_mined_at
        if last_time.tzinfo is None:
            last_time = last_time.replace(tzinfo=timezone.utc)
        elapsed = (now_utc - last_time).total_seconds()
        if elapsed < cooldown_sec:
            rem = int(cooldown_sec - elapsed)
            rem_m, rem_s = divmod(rem, 60)
            return False, f"⏳ [채굴 쿨타임] 다음 채굴까지 {rem_m}분 {rem_s}초 남았습니다. ({pickaxe['name']} 쿨타임: {cooldown_min}분)", {"remaining_seconds": rem}

    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL

    current_price = state.current_price
    # 3. Dynamic Base Reward based on Treasury Pool & Pickaxe Yield
    target_cash = min(float(current_price), max(current_price * 0.2, state.treasury_pool * 0.05))
    base_shares = round(target_cash / current_price, 2)
    if base_shares <= 0.05:
        base_shares = 0.1 # Minimum faucet floor
    base_shares = round(base_shares * pickaxe["yield_multiplier"], 2)

    # 4. Roll Random Mining Tier & Critical Hits (boosted by pickaxe crit_bonus)
    try:
        tier = roll_mining_tier(crit_bonus=pickaxe.get("crit_bonus", 0.0))
    except TypeError:
        try:
            tier = roll_mining_tier(pickaxe.get("crit_bonus", 0.0))
        except TypeError:
            tier = roll_mining_tier()
    multiplier = tier["multiplier"]
    if "bonus_cash_pct" in tier:
        treasury = float(state.treasury_pool or DEFAULT_TREASURY_POOL)
        pct = tier["bonus_cash_pct"]
        min_c = tier.get("min_cash", 10000)
        max_c = tier.get("max_cash", 300000)
        bonus_cash = int(max(min_c, min(max_c, round(treasury * pct))))
    else:
        bonus_cash = tier.get("bonus_cash", 0)

    total_bonus_cash = bonus_cash + pickaxe_bonus_cash

    bonus_10x = tier.get("bonus_10x", 0.0)
    cd_reduction = tier.get("cooldown_reduction", 0)
    tier_name = tier["name"]
    tier_code = tier["code"]

    shares_awarded = round(base_shares * multiplier, 2)
    if shares_awarded <= 0.05:
        shares_awarded = 0.05
    actual_cost = int(round(shares_awarded * current_price))
    bonus_10x_cost = int(round(bonus_10x * current_price))

    # Deduct total mining package cost from treasury pool
    total_mined_cost = actual_cost + total_bonus_cash + bonus_10x_cost
    state.treasury_pool = max(0.0, state.treasury_pool - total_mined_cost)

    # Cooldown setup (boosted on critical hit)
    if cd_reduction > 0:
        boosted_cd = max(0, cooldown_min - cd_reduction)
        if boosted_cd == 0:
            user.last_mined_at = None
            next_cd_msg = "⚡ 쿨타임 즉시 초기화!! (지금 바로 재채굴 가능)"
        else:
            user.last_mined_at = now_utc - timedelta(minutes=cd_reduction)
            next_cd_msg = f"{boosted_cd}분 (부스터 발동!)"
    else:
        user.last_mined_at = now_utc
        next_cd_msg = f"{cooldown_min}분"

    # 5. Check if user has debt -> Forced Labor Mode (탄광 노역 채굴)
    user_debt = getattr(user, "debt", 0) or 0
    if user_debt > 0:
        total_payout = actual_cost + total_bonus_cash
        repay_amt = min(user_debt, total_payout)
        user.debt = user_debt - repay_amt
        # Mined value returned to treasury as debt payoff
        state.treasury_pool += repay_amt

        # Excess cash if mined value exceeds remaining debt
        excess = total_payout - repay_amt
        if excess > 0:
            user.points += excess

        # Credit bonus 10X if won
        if bonus_10x > 0:
            pos_10x = db.query(Position).filter_by(user_id=user.id, product_type=ProductType.TEN_X).first()
            if pos_10x and pos_10x.quantity > 0:
                pos_10x.quantity += bonus_10x
                pos_10x.invested_cash += bonus_10x_cost
                pos_10x.entry_price = pos_10x.invested_cash / pos_10x.quantity
            else:
                if not pos_10x:
                    pos_10x = Position(
                        user_id=user.id,
                        product_type=ProductType.TEN_X,
                        quantity=bonus_10x,
                        entry_price=float(current_price),
                        invested_cash=float(bonus_10x_cost)
                    )
                    db.add(pos_10x)
                else:
                    pos_10x.quantity = bonus_10x
                    pos_10x.entry_price = float(current_price)
                    pos_10x.invested_cash = float(bonus_10x_cost)

        db.commit()
        db.refresh(user)
        db.refresh(state)

        bonus_10x_str = f" + 10X {format_quantity(bonus_10x)}주 획득!" if bonus_10x > 0 else ""
        excess_str = f" (빚 완제 후 잔여 {excess:,}P 현금 입금)" if excess > 0 else ""
        jackpot_tag = "🌟🎰 [탄광 노역 일확천금 대탈출!!] " if tier_code in ["EX", "UR+"] else ""
        msg = (
            f"{jackpot_tag}⛏️ [채굴 완료] [{pickaxe['name']}] [탄광 노역 채굴] {tier_name} {user.username}님 탄광 노역으로 총 {total_payout:,}P 상당 채굴! "
            f"수익 {repay_amt:,}P가 국고 빚 상환에 즉시 충당되었습니다!{bonus_10x_str}{excess_str} "
            f"(남은 빚: {user.debt:,}P | 다음 채굴: {next_cd_msg})"
        )
        return True, msg, {
            "user_id": user.id,
            "username": user.username,
            "pickaxe_level": curr_level,
            "pickaxe_name": pickaxe["name"],
            "tier": tier_code,
            "tier_name": tier_name,
            "multiplier": multiplier,
            "shares_awarded": shares_awarded,
            "cash_value": actual_cost,
            "bonus_cash": bonus_cash,
            "pickaxe_bonus_cash": pickaxe_bonus_cash,
            "total_bonus_cash": total_bonus_cash,
            "bonus_10x_shares": bonus_10x,
            "cooldown_reduction_minutes": cd_reduction,
            "repaid_debt": repay_amt,
            "remaining_debt": user.debt,
            "treasury_pool": state.treasury_pool,
            "is_forced_labor": True
        }

    # 6. Standard Mining Reward: Credit 1X position to user
    pos = db.query(Position).filter_by(user_id=user.id, product_type=ProductType.ONE_X).first()
    if pos and pos.quantity > 0:
        pos.quantity += shares_awarded
        pos.invested_cash += actual_cost
        pos.entry_price = pos.invested_cash / pos.quantity
    else:
        if not pos:
            pos = Position(
                user_id=user.id,
                product_type=ProductType.ONE_X,
                quantity=shares_awarded,
                entry_price=float(current_price),
                invested_cash=float(actual_cost)
            )
            db.add(pos)
        else:
            pos.quantity = shares_awarded
            pos.entry_price = float(current_price)
            pos.invested_cash = float(actual_cost)

    # Credit bonus cash (tier jackpot + pickaxe fixed cash)
    if total_bonus_cash > 0:
        user.points += total_bonus_cash

    # Credit bonus 10X share
    if bonus_10x > 0:
        pos_10x = db.query(Position).filter_by(user_id=user.id, product_type=ProductType.TEN_X).first()
        if pos_10x and pos_10x.quantity > 0:
            pos_10x.quantity += bonus_10x
            pos_10x.invested_cash += bonus_10x_cost
            pos_10x.entry_price = pos_10x.invested_cash / pos_10x.quantity
        else:
            if not pos_10x:
                pos_10x = Position(
                    user_id=user.id,
                    product_type=ProductType.TEN_X,
                    quantity=bonus_10x,
                    entry_price=float(current_price),
                    invested_cash=float(bonus_10x_cost)
                )
                db.add(pos_10x)
            else:
                pos_10x.quantity = bonus_10x
                pos_10x.entry_price = float(current_price)
                pos_10x.invested_cash = float(bonus_10x_cost)

    user.total_mined = (user.total_mined or 0.0) + shares_awarded

    db.commit()
    db.refresh(user)
    db.refresh(state)

    extras = []
    if bonus_cash > 0:
        extras.append(f"잭팟 현금 +{bonus_cash:,}P")
    if pickaxe_bonus_cash > 0:
        extras.append(f"곡괭이 보너스 +{pickaxe_bonus_cash:,}P")
    if bonus_10x > 0:
        extras.append(f"🔥 10X 레버리지 +{format_quantity(bonus_10x)}주")
    extras_str = f" + {' / '.join(extras)}" if extras else ""

    qty_str = format_quantity(shares_awarded)
    jackpot_tag = "🌟🎰 [일확천금 신화 탄생!!] " if tier_code in ["EX", "UR+"] else ""
    msg = (
        f"{jackpot_tag}⛏️ [채굴 완료] [{pickaxe['name']}] {tier_name} {user.username}님 1X {qty_str}주가 1X 보유에 합산되었습니다! "
        f"(+{actual_cost:,}P 상당{extras_str} | 보유 현금: {user.points:,}P | 국고 잔여: {int(state.treasury_pool):,}P | 다음 채굴: {next_cd_msg})"
    )
    return True, msg, {
        "user_id": user.id,
        "username": user.username,
        "pickaxe_level": curr_level,
        "pickaxe_name": pickaxe["name"],
        "tier": tier_code,
        "tier_name": tier_name,
        "multiplier": multiplier,
        "shares_awarded": shares_awarded,
        "cash_value": actual_cost,
        "bonus_cash": bonus_cash,
        "pickaxe_bonus_cash": pickaxe_bonus_cash,
        "total_bonus_cash": total_bonus_cash,
        "bonus_10x_shares": bonus_10x,
        "cooldown_reduction_minutes": cd_reduction,
        "treasury_pool": state.treasury_pool,
        "total_mined": user.total_mined,
        "is_forced_labor": False
    }

def execute_pickaxe_upgrade(
    db: Session,
    user_id: str,
    username: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Execute !강화 / !업그레이드 (MapleStory Star Force pickaxe enhancement).
    - 0성 ~ 14성: 파괴 확률 없음 (0%)
    - 15성 ~ 24성: 파괴 확률 존재 (파괴 시 메이플 룰에 따라 12성 장비의 흔적으로 복원)
    - 10성, 15성, 20성: 실패 시 하락 없는 안전 방지턱
    - 강화 비용은 성공/실패/파괴 무관 100% 국고 채굴풀로 환원
    """
    state = get_market_state(db)
    user = get_or_create_user(db, user_id, username)
    curr_level = getattr(user, "pickaxe_level", 0)
    if curr_level is None:
        curr_level = 0
    curr_level = max(0, min(25, int(curr_level)))

    if curr_level >= 25:
        max_item = get_pickaxe_info(25)
        return False, f"✨ 이미 최고 등급 종결 장비인 [{max_item['name']}]을(를) 장착하고 있습니다!", None

    current_item = get_pickaxe_info(curr_level)
    cost = current_item["upgrade_cost"]

    # Debt protection: Cannot spend borrowed money on luxury upgrades before repaying debt
    user_debt = getattr(user, "debt", 0) or 0
    if user_debt > 0 and (user.points - cost) < user_debt:
        return False, f"⚠️ 채무(빚: {user_debt:,}P)가 있는 상태에서는 빚보다 적은 잔여 현금을 남기는 강화를 할 수 없습니다! 먼저 !상환을 진행해주세요.", None

    if user.points < cost:
        return False, f"⚠️ 포인트가 부족합니다! (필요: {cost:,}P | 보유: {user.points:,}P | 부족: {cost - user.points:,}P)", None

    # Deduct cost and credit 100% to Treasury regardless of result
    user.points -= cost
    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL
    state.treasury_pool += cost

    # Roll outcome based on Star Force tier probabilities
    roll = random.uniform(0, 100)
    s_rate = current_item["success_rate"]
    m_rate = current_item["maintain_rate"]
    d_rate = current_item["drop_rate"]

    if roll < s_rate:
        outcome = "success"
        new_level = curr_level + 1
        user.pickaxe_level = new_level
        new_item = get_pickaxe_info(new_level)
        bp_info = f" + 확정 +{new_item['bonus_points']:,}P" if new_item.get('bonus_points', 0) > 0 else ""
        reply = (
            f"🔨✨ [스타포스 강화 대성공!!] {user.username}님 {cost:,}P를 소모하여 [{new_item['name']}] 강화에 성공했습니다! "
            f"(채굴량: {new_item['yield_multiplier']}배{bp_info} | 크리: +{new_item['crit_bonus']}% | 쿨: {new_item['cooldown_minutes']}분 | "
            f"국고 환원: +{cost:,}P | 잔여 현금: {user.points:,}P)"
        )
    elif roll < (s_rate + m_rate):
        outcome = "maintain"
        new_level = curr_level
        user.pickaxe_level = new_level
        new_item = current_item
        reply = (
            f"🔨💨 [강화 실패 (등급 유지)] {user.username}님 {cost:,}P를 소모하였으나 강화에 실패했습니다. (방지턱/안전 구간으로 등급 유지) "
            f"(현재: [{current_item['name']}] | 국고 환원: +{cost:,}P | 잔여 현금: {user.points:,}P)"
        )
    elif roll < (s_rate + m_rate + d_rate):
        outcome = "drop"
        new_level = max(0, curr_level - 1)
        user.pickaxe_level = new_level
        new_item = get_pickaxe_info(new_level)
        reply = (
            f"🔨📉 [강화 실패 (등급 하락!)] {user.username}님 {cost:,}P를 소모하였으나 강화 실패로 1성 하락했습니다! ㅠㅠ "
            f"([{current_item['name']}] ➔ [{new_item['name']}] | 국고 환원: +{cost:,}P | 잔여 현금: {user.points:,}P)"
        )
    else:
        # Destroyed / Blown up! (Only possible at 15성+)
        outcome = "destroyed"
        new_level = 12  # 메이플 스타포스 룰: 장비의 흔적 12성 복원!
        user.pickaxe_level = 12
        new_item = get_pickaxe_info(12)
        reply = (
            f"💥💥 [곡괭이 폭발 파괴!!] 굉음과 함께 곡괭이가 산산조각 났습니다!! {user.username}님의 [{current_item['name']}]이(가) "
            f"폭발 파괴되어 메이플 장비의 흔적 룰에 따라 [{new_item['name']}]으로 복원되었습니다! (국고 환원: +{cost:,}P | 잔여: {user.points:,}P)"
        )

    db.commit()
    db.refresh(user)
    db.refresh(state)

    details = {
        "user_id": user.id,
        "username": user.username,
        "previous_level": curr_level,
        "new_level": user.pickaxe_level,
        "outcome": outcome,
        "pickaxe_name": new_item["name"],
        "cost": cost,
        "remaining_points": user.points,
        "treasury_pool": state.treasury_pool
    }
    return True, reply, details

def get_user_pickaxe_status(db: Session, user_id: str, username: str) -> str:
    """Returns detailed pickaxe status for a user."""
    user = get_or_create_user(db, user_id, username)
    curr_lvl = getattr(user, "pickaxe_level", 0)
    if curr_lvl is None:
        curr_lvl = 0
    curr_lvl = max(0, min(25, int(curr_lvl)))
    item = get_pickaxe_info(curr_lvl)
    bp = item.get("bonus_points", 0)
    bp_str = f" | 매 채굴 확정: +{bp:,}P" if bp > 0 else ""

    if curr_lvl >= 25:
        return (
            f"⛏️ [내 곡괭이 정보] {user.username}님의 장비: {item['name']}\n"
            f"• 효과: 채굴량 {item['yield_multiplier']}배{bp_str} | 크리티컬 보너스: +{item['crit_bonus']}% | 쿨타임: {item['cooldown_minutes']}분\n"
            f"✨ 메이플 25성 종결 곡괭이를 달성한 전설의 광부입니다! (크리티컬 150% 확정 발동)"
        )
    else:
        next_item = get_pickaxe_info(curr_lvl + 1)
        cost = item["upgrade_cost"]

        s_rate = item["success_rate"]
        m_rate = item["maintain_rate"]
        d_rate = item["drop_rate"]
        dest_rate = item["destroy_rate"]

        rate_parts = [f"성공 {s_rate:.2f}%" if s_rate % 1 else f"성공 {int(s_rate)}%"]
        if m_rate > 0:
            rate_parts.append(f"유지 {m_rate:.3f}%" if m_rate % 1 else f"유지 {int(m_rate)}%")
        if d_rate > 0:
            rate_parts.append(f"하락 {d_rate:.3f}%" if d_rate % 1 else f"하락 {int(d_rate)}%")
        if dest_rate > 0:
            rate_parts.append(f"💥파괴 {dest_rate:.3f}%" if dest_rate % 1 else f"💥파괴 {int(dest_rate)}%")
        rate_str = " | ".join(rate_parts)

        destroy_warning = "\n  ⚠️ 15성 이상: 파괴(터짐) 위험 존재! (파괴 시 12성 복원)" if dest_rate > 0 else " (15성 미만: 절대 안 터짐!)"

        return (
            f"⛏️ [내 곡괭이 정보] {user.username}님의 장비: {item['name']}\n"
            f"• 현재 효과: 채굴량 {item['yield_multiplier']}배{bp_str} | 크리 보너스 +{item['crit_bonus']}% | 쿨타임: {item['cooldown_minutes']}분\n"
            f"• 다음 강화: ★{curr_lvl + 1}성 도전 [비용: {cost:,}P]\n"
            f"  └ 확률: {rate_str}{destroy_warning}\n"
            f"  └ 다음 효과: {next_item['desc']}\n"
            f"💡 강화 명령어: !강화 또는 !업그레이드"
        )

def get_pickaxe_table_guide() -> str:
    """Returns concise pickaxe tiers & Star Force rate guide."""
    return (
        "⛏️📋 [메이플 스타일 곡괭이 스타포스 강화표] (!강화로 업그레이드)\n"
        "• 0~10성: 안전 구간! 실패해도 하락/파괴 없음 (10성: 채굴 3배 + 1.5만P + 쿨 10분)\n"
        "• 11~14성: 하락 구간! 실패 시 1성 하락 (10성 세이프존 방지턱, 파괴 0%)\n"
        "• 15성: 15성 방지턱! 성공 31.5% / 유지 66.4% / 💥파괴 2.1% (채굴 6.5배 + 6만P + 쿨 8분)\n"
        "• 16~19성: 성공 15~31.5% / 하락 66~77% / 💥파괴 2~8.4% (17성: 채굴 11배 + 12만P + 쿨 6분)\n"
        "• 20성: 20성 방지턱! 성공 31.5% / 유지 58.2% / 💥파괴 10.3% (채굴 22배 + 28만P + 쿨 5분)\n"
        "• 21~22성: 성공 15.8% / 하락 67~72% / 💥파괴 12.6~16.9% (22성 국민졸업: 채굴 36배 + 50만P + 쿨 4분)\n"
        "• 23~25성: 극악의 종결! 성공 10.5% / 하락 71.6% / 💥파괴 17.9% (MAX: 채굴 80배 + 120만P + 크리 150% + 쿨 3분!)\n"
        "* 15강까진 절대 안 터집니다! 15성 이후 파괴 시 12성(흔적)으로 복원됩니다.\n"
        "* 강화비는 성공/실패/파괴 무관 100% 국고 채굴풀로 환원됩니다!"
    )

def execute_borrow(
    db: Session,
    user_id: str,
    username: str,
    amount_str: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Execute !대출 [금액/최대/올인] (Margin Loan from Treasury Pool).
    Allows viewers to borrow up to MAX_LOAN_LIMIT (50,000P) from the Treasury Pool.
    """
    state = get_market_state(db)
    user = get_or_create_user(db, user_id, username)
    current_debt = getattr(user, "debt", 0) or 0

    if current_debt >= MAX_LOAN_LIMIT:
        return False, f"⚠️ 이미 최대 대출 한도({MAX_LOAN_LIMIT:,}P)에 도달하여 추가 대출이 불가합니다. (현재 빚: {current_debt:,}P)", None

    max_possible = MAX_LOAN_LIMIT - current_debt

    cleaned = (amount_str or "").strip().lower()
    if cleaned in ["최대", "올인", "max", "all", "전액", "풀대출", "전부"]:
        borrow_amount = min(max_possible, int(state.treasury_pool))
    else:
        try:
            val = int(cleaned.replace(",", "").replace("p", "").replace("원", ""))
            if val <= 0:
                return False, "⚠️ 대출 금액은 1P 이상이어야 합니다.", None
            if val > max_possible:
                return False, f"⚠️ 최대 대출 한도는 {MAX_LOAN_LIMIT:,}P입니다. 추가 대출 가능 한도: {max_possible:,}P (현재 빚: {current_debt:,}P)", None
            borrow_amount = val
        except ValueError:
            return False, "💡 대출 사용법: !대출 [금액/최대] (예: !대출 30000, !대출 최대)", None

    if borrow_amount <= 0:
        return False, "⚠️ 대출 가능한 금액이 없습니다.", None

    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL

    if state.treasury_pool < borrow_amount:
        return False, f"🏛️ 국고 잔고가 부족하여 대출을 실행할 수 없습니다. (현재 국고 대출 가능액: {int(state.treasury_pool):,}P)", None

    # Execute loan
    state.treasury_pool -= borrow_amount
    user.debt = current_debt + borrow_amount
    user.points += borrow_amount

    db.commit()
    db.refresh(user)
    db.refresh(state)

    reply = (
        f"💳 [국고 마진론 대출] {user.username}님 {borrow_amount:,}P 대출 실행 완료! | "
        f"보유 현금: {user.points:,}P | 총 채무(빚): {user.debt:,}P (경기당 이자: 2% 국고 납부)"
    )
    details = {
        "user_id": user.id,
        "username": user.username,
        "amount": borrow_amount,
        "total_debt": user.debt,
        "cash": user.points,
        "treasury_pool": state.treasury_pool
    }
    return True, reply, details

def execute_repay(
    db: Session,
    user_id: str,
    username: str,
    amount_str: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Execute !상환 [금액/전액/올인] (Repay Margin Loan).
    """
    state = get_market_state(db)
    user = get_or_create_user(db, user_id, username)
    current_debt = getattr(user, "debt", 0) or 0

    if current_debt <= 0:
        return False, f"💡 {user.username}님은 갚아야 할 대출금(빚)이 없습니다. (빚: 0P)", None

    if user.points <= 0:
        return False, "⚠️ 보유 현금이 0P라 상환할 수 없습니다. (주식 매도/청산 또는 !채굴 후 상환 가능)", None

    cleaned = (amount_str or "").strip().lower()
    if cleaned in ["전액", "올인", "all", "max", "최대"] or not cleaned:
        repay_amount = min(current_debt, user.points)
    else:
        try:
            val = int(cleaned.replace(",", "").replace("p", "").replace("원", ""))
            if val <= 0:
                return False, "⚠️ 상환 금액은 1P 이상이어야 합니다.", None
            if user.points < val:
                return False, f"⚠️ 보유 현금({user.points:,}P)이 부족합니다.", None
            repay_amount = min(current_debt, val)
        except ValueError:
            return False, "💡 상환 사용법: !상환 [금액/전액] (예: !상환 20000, !상환 전액)", None

    if repay_amount <= 0:
        return False, "⚠️ 상환 가능한 금액이 없습니다.", None

    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL

    user.points -= repay_amount
    user.debt = current_debt - repay_amount
    state.treasury_pool += repay_amount

    db.commit()
    db.refresh(user)
    db.refresh(state)

    if user.debt == 0:
        reply = (
            f"🎉 [빚 전액 청산] {user.username}님 {repay_amount:,}P 전액 상환 완료! "
            f"국고 채무를 모두 청산하여 자유의 몸이 되었습니다! (보유 현금: {user.points:,}P)"
        )
    else:
        reply = (
            f"💰 [대출 상환] {user.username}님 {repay_amount:,}P 상환 완료! | "
            f"잔여 빚: {user.debt:,}P | 보유 현금: {user.points:,}P"
        )

    details = {
        "user_id": user.id,
        "username": user.username,
        "amount": repay_amount,
        "remaining_debt": user.debt,
        "cash": user.points,
        "treasury_pool": state.treasury_pool
    }
    return True, reply, details

def execute_transfer(
    db: Session,
    sender_id: str,
    sender_username: str,
    target_name: str,
    amount_str: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Execute account transfer between users:
    !송금 [상대닉네임] [금액] / !이체 [상대닉네임] [금액]
    - If transfer amount >= 10,000P, transfer tax is levied and credited to National Treasury Pool.
    - If sender has debt, borrowed money cannot be transferred out to prevent bankruptcy laundering.
    """
    state = get_market_state(db)
    sender = get_or_create_user(db, sender_id, sender_username)

    clean_target = (target_name or "").strip().lstrip("@").strip()
    if not clean_target:
        return False, "💡 계좌이체 사용법: !송금 [닉네임] [금액/올인] (예: !송금 치즈나베 10000, !이체 @CYTFT 5만)", None

    # Prevent self-transfer by input name
    if clean_target.lower() == sender.username.lower() or clean_target == sender.id:
        return False, "⚠️ 본인 계좌로는 이체할 수 없습니다.", None

    # Find recipient in database
    recipient = db.query(User).filter(func.lower(User.username) == clean_target.lower()).first()
    if not recipient:
        recipient = db.query(User).filter(User.id == clean_target).first()
    if not recipient:
        candidates = db.query(User).filter(User.username.ilike(f"%{clean_target}%")).all()
        if len(candidates) == 1:
            recipient = candidates[0]

    if not recipient:
        return False, f"⚠️ 받으실 유저 '{clean_target}' 님을 찾을 수 없습니다. (채팅에 참여하여 등록된 유저에게만 이체 가능)", None

    if recipient.id == sender.id:
        return False, "⚠️ 본인 계좌로는 이체할 수 없습니다.", None

    # Debt protection: Cannot transfer borrowed funds out to launder before bankruptcy
    sender_debt = getattr(sender, "debt", 0) or 0
    if sender_debt > 0 and sender.points <= sender_debt:
        return False, f"⚠️ 채무(빚: {sender_debt:,}P)가 보유 현금({sender.points:,}P) 이상입니다. 파산 악용 방지를 위해 먼저 !상환을 진행해주세요.", None

    max_sendable = sender.points - sender_debt if sender_debt > 0 else sender.points

    clean_amount_str = (amount_str or "").strip().lower()
    if clean_amount_str in ["올인", "all", "전액", "전부", "다", "최대"]:
        amount = max_sendable
    else:
        amount = parse_korean_amount(clean_amount_str)
        if amount is None:
            return False, f"⚠️ 유효하지 않은 이체 금액입니다: '{amount_str}' (예: !송금 {clean_target} 10000, 5만, 올인)", None

    if amount <= 0:
        return False, "⚠️ 이체 금액은 최소 1P 이상이어야 합니다.", None

    if amount > sender.points:
        return False, f"⚠️ 보유 현금이 부족합니다! (현재 잔액: {sender.points:,}P | 요청 금액: {amount:,}P)", None

    if sender_debt > 0 and amount > max_sendable:
        return False, f"⚠️ 채무(빚: {sender_debt:,}P)를 제외한 순수 이체 가능 한도는 {max_sendable:,}P입니다. 먼저 !상환을 진행해주세요.", None

    # Calculate Tax
    tax, tax_rate, tax_label = calculate_transfer_tax(amount)
    tax_rate_pct = int(round(tax_rate * 100))
    recipient_net = amount - tax

    # Execute transfer
    sender.points -= amount
    recipient.points += recipient_net

    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL
    state.treasury_pool += tax

    db.commit()
    db.refresh(sender)
    db.refresh(recipient)
    db.refresh(state)

    if tax > 0:
        reply = (
            f"💸 [계좌이체 완료] {sender.username}님 ➡️ {recipient.username}님께 {amount:,}P 이체 완료! "
            f"(실수령: {recipient_net:,}P | {tax_label}({tax_rate_pct}%): {tax:,}P 국고 적립 | "
            f"보낸 분 잔액: {sender.points:,}P)"
        )
    else:
        reply = (
            f"💸 [계좌이체 완료] {sender.username}님 ➡️ {recipient.username}님께 {amount:,}P 이체 완료! "
            f"(1만P 미만 면세 | 실수령: {recipient_net:,}P | 보낸 분 잔액: {sender.points:,}P)"
        )

    details = {
        "sender_id": sender.id,
        "sender_username": sender.username,
        "recipient_id": recipient.id,
        "recipient_username": recipient.username,
        "amount": amount,
        "tax": tax,
        "tax_rate_pct": tax_rate_pct,
        "tax_label": tax_label,
        "recipient_net": recipient_net,
        "sender_remaining": sender.points,
        "recipient_remaining": recipient.points,
        "treasury_pool": state.treasury_pool
    }
    return True, reply, details

def submit_bankruptcy_application(
    db: Session,
    user_id: str,
    username: str,
    reason: str = ""
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Submit bankruptcy / rehabilitation application to the Streamer's Court.
    Enters PENDING status waiting for Streamer's verdict on Admin Panel.
    """
    state = get_market_state(db)
    user = get_or_create_user(db, user_id, username)
    current_debt = getattr(user, "debt", 0) or 0

    if current_debt <= 0:
        return False, f"💡 {user.username}님은 갚아야 할 대출금(빚)이 없어 파산 대상이 아닙니다. (빚: 0P) 국고 대출(!대출 최대)이나 채굴(!채굴)을 이용해주세요!", None

    # Check if user already has an active pending application
    pending_app = db.query(BankruptcyApplication).filter_by(
        user_id=user.id,
        status=BankruptcyStatus.PENDING
    ).first()
    if pending_app:
        return False, f"⚖️ 이미 접수되어 심사 대기 중인 회생 신청(사건 #{pending_app.id})이 있습니다. 나베 판사님의 판결을 기다려주세요!", None

    # Calculate total gross assets (cash + active positions valuation)
    portfolio_val = 0
    for p in user.positions:
        if p.quantity > 0:
            val = calculate_position_valuation(p, state.current_price)
            portfolio_val += int(round(val["current_value"]))

    gross_assets = user.points + portfolio_val

    # If user still has enough assets to pay the debt, reject bankruptcy request
    if gross_assets >= current_debt:
        return False, f"⚖️ [신청 불가] 보유 총자산({gross_assets:,}P)이 빚({current_debt:,}P) 이상입니다. !청산 또는 !상환으로 직접 변제 가능합니다.", None

    # Cooldown check (15 minutes = 900 seconds)
    now_utc = datetime.now(timezone.utc)
    if user.last_bankrupt_at:
        last_b = user.last_bankrupt_at
        if last_b.tzinfo is None:
            last_b = last_b.replace(tzinfo=timezone.utc)
        elapsed = (now_utc - last_b).total_seconds()
        if elapsed < 900:
            rem_m = max(1, int(900 - elapsed) // 60)
            return False, f"⏳ [회생 신청 대기] 최근 파산 심사 이력이 있습니다. 다음 신청까지 약 {rem_m}분 남았습니다.", None

    clean_reason = (reason or "").strip()
    if not clean_reason:
        clean_reason = "10X 타다가 전재산 날렸습니다. 살려주세요!"
    if len(clean_reason) > 150:
        clean_reason = clean_reason[:150] + "..."

    app = BankruptcyApplication(
        user_id=user.id,
        username=user.username,
        debt=current_debt,
        gross_assets=gross_assets,
        cash=user.points,
        portfolio_value=portfolio_val,
        reason=clean_reason,
        status=BankruptcyStatus.PENDING,
        created_at=now_utc
    )
    db.add(app)
    db.commit()
    db.refresh(app)

    reply = (
        f"🏛️ [개인회생 접수] {user.username}님의 회생 신청(사건 #{app.id})이 나베 판사의 법정에 접수되었습니다! "
        f"(채무: {current_debt:,}P | 사유: \"{clean_reason}\") 판사님의 판결을 기다려주세요."
    )
    details = {
        "id": app.id,
        "user_id": user.id,
        "username": user.username,
        "debt": app.debt,
        "gross_assets": app.gross_assets,
        "cash": app.cash,
        "portfolio_value": app.portfolio_value,
        "reason": app.reason,
        "status": app.status.value,
        "created_at": app.created_at.strftime("%H:%M:%S") if app.created_at else ""
    }
    return True, reply, details

def get_pending_bankruptcy_applications(db: Session) -> List[Dict[str, Any]]:
    """Return all pending bankruptcy applications for streamer court review."""
    apps = (
        db.query(BankruptcyApplication)
        .filter_by(status=BankruptcyStatus.PENDING)
        .order_by(BankruptcyApplication.created_at.asc())
        .all()
    )
    res = []
    for a in apps:
        res.append({
            "id": a.id,
            "user_id": a.user_id,
            "username": a.username,
            "debt": a.debt,
            "gross_assets": a.gross_assets,
            "cash": a.cash,
            "portfolio_value": a.portfolio_value,
            "reason": a.reason,
            "status": a.status.value,
            "created_at": a.created_at.strftime("%H:%M:%S") if a.created_at else ""
        })
    return res

def judge_bankruptcy_application(
    db: Session,
    app_id: int,
    verdict: str,
    admin_comment: str = ""
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Judge a pending bankruptcy application.
    verdict:
      - 'full': 100% debt forgiven, points set to 10,000P survival fund, positions wiped.
      - 'half': 50% debt forgiven, remaining 50% debt preserved.
      - 'reject': 0% debt forgiven, request dismissed with cooldown ("탄광 노역형").
    """
    app = db.query(BankruptcyApplication).filter_by(id=app_id).first()
    if not app or app.status != BankruptcyStatus.PENDING:
        return False, "⚠️ 대기 중인 회생 신청 사건을 찾을 수 없거나 이미 판결이 완료되었습니다.", None

    user = db.query(User).filter_by(id=app.user_id).first()
    if not user:
        return False, "⚠️ 신청 유저 정보를 찾을 수 없습니다.", None

    state = get_market_state(db)
    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL

    now_utc = datetime.now(timezone.utc)
    comment = (admin_comment or "").strip()
    v = (verdict or "").strip().lower()

    if v in ["full", "전액", "전액탕감", "인가"]:
        # 1. Liquidate lingering positions
        for p in user.positions:
            p.quantity = 0.0
            p.invested_cash = 0.0
            p.entry_price = 0.0

        # 2. Absorb remaining cash into treasury
        absorbed = max(0, user.points)
        state.treasury_pool += absorbed

        forgiven = user.debt
        user.debt = 0
        user.points = 10000  # Basic survival fund
        user.last_bankrupt_at = now_utc

        app.status = BankruptcyStatus.APPROVED_FULL
        app.verdict = "full"
        app.admin_comment = comment if comment else None
        app.resolved_at = now_utc

        db.commit()
        db.refresh(user)
        db.refresh(state)

        c_str = f" [판사 판결문: \"{comment}\"]" if comment else ""
        reply = (
            f"⚖️ [회생 인가] 나베 판사님이 {user.username}님의 회생을 인가했습니다! "
            f"채무 {forgiven:,}P 전액 탕감 & 기본 생계 자금 10,000P 지급!{c_str}"
        )
        details = {
            "app_id": app.id,
            "user_id": user.id,
            "username": user.username,
            "verdict": "full",
            "verdict_title": "전액 탕감 (인가)",
            "forgiven_debt": forgiven,
            "remaining_debt": 0,
            "points": user.points,
            "comment": comment,
            "treasury_pool": state.treasury_pool
        }
        return True, reply, details

    elif v in ["half", "50%", "절반", "워크아웃"]:
        forgiven = user.debt // 2
        user.debt = user.debt - forgiven
        user.last_bankrupt_at = now_utc

        app.status = BankruptcyStatus.APPROVED_HALF
        app.verdict = "half"
        app.admin_comment = comment if comment else None
        app.resolved_at = now_utc

        db.commit()
        db.refresh(user)

        c_str = f" [판사 판결문: \"{comment}\"]" if comment else ""
        reply = (
            f"⚖️ [조건부 워크아웃] 나베 판사님이 {user.username}님의 채무 {forgiven:,}P(50%)를 감면했습니다! "
            f"(남은 빚: {user.debt:,}P - 채굴과 건전한 투자로 변제하세요){c_str}"
        )
        details = {
            "app_id": app.id,
            "user_id": user.id,
            "username": user.username,
            "verdict": "half",
            "verdict_title": "조건부 50% 탕감 (워크아웃)",
            "forgiven_debt": forgiven,
            "remaining_debt": user.debt,
            "points": user.points,
            "comment": comment,
            "treasury_pool": state.treasury_pool
        }
        return True, reply, details

    elif v in ["reject", "기각", "탄광", "노역"]:
        user.last_bankrupt_at = now_utc

        app.status = BankruptcyStatus.REJECTED
        app.verdict = "reject"
        app.admin_comment = comment if comment else None
        app.resolved_at = now_utc

        db.commit()
        db.refresh(user)

        c_str = f" [판사 판결문: \"{comment}\"]" if comment else " \"탄광 가서 !채굴로 갚아라!\""
        reply = (
            f"🔨 [파산 기각] 나베 판사님이 {user.username}님의 파산 신청을 기각했습니다! "
            f"채무 {user.debt:,}P 전액 유지!{c_str}"
        )
        details = {
            "app_id": app.id,
            "user_id": user.id,
            "username": user.username,
            "verdict": "reject",
            "verdict_title": "파산 기각 (탄광 노역형)",
            "forgiven_debt": 0,
            "remaining_debt": user.debt,
            "points": user.points,
            "comment": comment,
            "treasury_pool": state.treasury_pool
        }
        return True, reply, details

    else:
        return False, f"⚠️ 알 수 없는 판결입니다: {verdict} (가능한 판결: full, half, reject)", None

def execute_bankruptcy(
    db: Session,
    user_id: str,
    username: str,
    reason: str = ""
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Compatibility alias to submit_bankruptcy_application."""
    return submit_bankruptcy_application(db, user_id, username, reason)

def get_treasury_info(db: Session) -> Dict[str, Any]:
    state = get_market_state(db)
    pool = getattr(state, "treasury_pool", DEFAULT_TREASURY_POOL) or DEFAULT_TREASURY_POOL
    return {
        "treasury_pool": pool,
        "fee_rate": TRADING_FEE_RATE,
        "fee_rate_pct": TRADING_FEE_RATE * 100.0,
        "victory_dividend_rate": 0.05,
        "second_dividend_rate": 0.01,
        "mining_cooldown_seconds": 900,
        "max_loan_limit": MAX_LOAN_LIMIT,
        "loan_interest_rate": LOAN_INTEREST_RATE,
        "loan_interest_pct": LOAN_INTEREST_RATE * 100.0
    }

def get_leaderboard(db: Session, top_n: int = 3) -> List[Dict[str, Any]]:
    """Calculate and return top richest shareholders by net asset valuation (cash + positions - debt)."""
    state = get_market_state(db)
    users = db.query(User).all()
    records = []

    for u in users:
        # Exclude dummy and test accounts from leaderboard rankings
        uid_lower = (u.id or "").lower()
        uname_lower = (u.username or "").lower()
        if (
            any(uid_lower.startswith(p) for p in ("fresh_", "test_", "viewer_", "strictly_", "dummy_", "sim_", "bug_", "user_temp", "u_"))
            or any(uname_lower.startswith(p) for p in ("테스터", "유저_", "새유저", "철통잠금", "더미", "테스트", "임시유저", "임시"))
            or uname_lower in ("테스트유저", "시청자1", "타이머만료유저", "후원테스터", "마진유저", "임시유저")
            or uid_lower in ("user_temp_123", "u_매수_10x_올인")
        ):
            continue

        portfolio_val = 0
        active_positions = []
        for p in u.positions:
            if p.quantity > 0:
                val = calculate_position_valuation(p, state.current_price)
                p_val = int(round(val["current_value"]))
                portfolio_val += p_val
                active_positions.append({
                    "product": p.product_type.value,
                    "quantity": p.quantity,
                    "value": p_val,
                    "pnl_pct": val["pnl_pct"]
                })

        debt = getattr(u, "debt", 0) or 0
        gross_assets = u.points + portfolio_val
        net_assets = gross_assets - debt
        total_pnl = net_assets - STARTING_POINTS  # Starting fund 50,000P
        total_pnl_pct = (total_pnl / float(STARTING_POINTS)) * 100.0

        records.append({
            "user_id": u.id,
            "username": u.username,
            "cash": u.points,
            "debt": debt,
            "gross_assets": gross_assets,
            "portfolio_value": portfolio_val,
            "total_assets": net_assets,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "positions": active_positions
        })

    records.sort(key=lambda r: r["total_assets"], reverse=True)

    ranked = []
    for idx, r in enumerate(records[:top_n], start=1):
        r["rank"] = idx
        ranked.append(r)

    return ranked

def get_current_buyers(db: Session, limit: int = 100) -> Dict[str, Any]:
    """
    Retrieve all current shareholders/buyers holding active positions (quantity > 0).
    Includes detailed per-position information, valuation, PnL, and market breakdown summary.
    """
    state = get_market_state(db)
    current_price = state.current_price

    positions = db.query(Position).filter(Position.quantity > 0).all()

    buyers = []
    unique_users = set()
    total_invested = 0
    total_current_val = 0
    long_count = 0
    short_count = 0
    long_value = 0
    short_value = 0

    # Friendly Korean labels for each product
    product_names = {
        ProductType.ONE_X: "1X 본주",
        ProductType.TWO_X: "2X 레버리지",
        ProductType.THREE_X: "3X 레버리지",
        ProductType.FIVE_X: "5X 레버리지",
        ProductType.TEN_X: "10X 레버리지 (10배 롱)",
        ProductType.INV: "1X 인버스 (1배 숏)",
        ProductType.TWO_X_INV: "2X 곱버스 (2배 숏)",
        ProductType.THREE_X_INV: "3X 인버스",
        ProductType.FIVE_X_INV: "5X 인버스",
        ProductType.TEN_X_INV: "10X 인버스 (10배 숏)",
    }

    for pos in positions:
        user = pos.user
        if not user:
            continue
        uid_lower = (user.id or "").lower()
        uname_lower = (user.username or "").lower()
        if (
            any(uid_lower.startswith(p) for p in ("fresh_", "test_", "viewer_", "strictly_", "dummy_", "sim_", "bug_", "user_temp", "u_"))
            or any(uname_lower.startswith(p) for p in ("테스터", "유저_", "새유저", "철통잠금", "더미", "테스트", "임시유저", "임시"))
            or uname_lower in ("테스트유저", "시청자1", "타이머만료유저", "후원테스터", "마진유저", "임시유저")
            or uid_lower in ("user_temp_123", "u_매수_10x_올인")
        ):
            continue

        val = calculate_position_valuation(pos, current_price)
        curr_val = int(round(val["current_value"]))
        invested = int(round(pos.invested_cash))
        unrealized = int(round(val["unrealized_pnl"]))
        pnl_pct = round(val["pnl_pct"], 2)

        unique_users.add(user.id)
        total_invested += invested
        total_current_val += curr_val

        is_short = ("_INV" in pos.product_type.value) or (pos.product_type == ProductType.INV)
        if is_short:
            short_count += 1
            short_value += curr_val
        else:
            long_count += 1
            long_value += curr_val

        qty_display = int(pos.quantity) if float(pos.quantity).is_integer() else round(float(pos.quantity), 2)
        entry_p = int(round(pos.entry_price)) if pos.entry_price else current_price

        buyers.append({
            "user_id": user.id,
            "username": user.username,
            "product_type": pos.product_type.value,
            "product_name": product_names.get(pos.product_type, pos.product_type.value),
            "is_short": is_short,
            "quantity": qty_display,
            "entry_price": entry_p,
            "invested_cash": invested,
            "current_value": curr_val,
            "unrealized_pnl": unrealized,
            "pnl_pct": pnl_pct,
            "user_cash": user.points,
            "has_debt": (getattr(user, "debt", 0) or 0) > 0,
            "debt": getattr(user, "debt", 0) or 0
        })

    # Sort buyers by current valuation descending
    buyers.sort(key=lambda b: b["current_value"], reverse=True)
    if limit > 0:
        buyers = buyers[:limit]

    total_val_all = long_value + short_value
    long_ratio = round((long_value / total_val_all * 100.0), 1) if total_val_all > 0 else 50.0
    short_ratio = round(100.0 - long_ratio, 1) if total_val_all > 0 else 50.0

    day_open = getattr(state, "day_open_price", current_price) or current_price
    day_diff = current_price - day_open
    day_diff_pct = round((day_diff / float(day_open)) * 100.0, 2) if day_open > 0 else 0.0

    return {
        "buyers": buyers,
        "summary": {
            "total_buyers": len(unique_users),
            "total_positions": len(buyers),
            "total_invested": total_invested,
            "total_current_value": total_current_val,
            "long_count": long_count,
            "short_count": short_count,
            "long_value": long_value,
            "short_value": short_value,
            "long_ratio": long_ratio,
            "short_ratio": short_ratio,
            "current_price": current_price,
            "day_open_price": day_open,
            "day_diff": day_diff,
            "day_diff_pct": day_diff_pct,
            "is_market_locked": is_market_locked(db, state)
        }
    }

# ---------------------------------------------------------
# Chzzk Donation -> Point Charging (1 KRW : 100 Points)
# ---------------------------------------------------------
POINT_PER_KRW = 100  # 1 KRW = 100 Points

def validate_and_process_donation(
    db: Session,
    donation_data: Dict[str, Any]
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Validates a Chzzk Session DONATION event and credits points at 1:100 ratio.
    Ensures idempotency/deduplication, atomic transaction, and auto-backup.
    """
    if not isinstance(donation_data, dict):
        return False, "⚠️ 후원 데이터 형식이 올바르지 않습니다.", None

    # 1. Parse and validate payAmount
    raw_amount = donation_data.get("payAmount") or donation_data.get("pay_amount")
    if raw_amount is None:
        return False, "⚠️ 후원 금액(payAmount)이 누락되었습니다.", None

    try:
        clean_amount_str = str(raw_amount).replace(",", "").strip()
        pay_amount = int(float(clean_amount_str))
    except (ValueError, TypeError):
        return False, f"⚠️ 유효하지 않은 후원 금액입니다: '{raw_amount}'", None

    if pay_amount <= 0:
        return False, f"⚠️ 후원 금액은 0원보다 커야 합니다. (입력: {pay_amount:,}원)", None

    if pay_amount > 50_000_000:
        return False, f"⚠️ 1회 최대 후원 한도(50,000,000원)를 초과했습니다. (입력: {pay_amount:,}원)", None

    # 2. Extract and sanitize donator info
    donator_nickname = str(donation_data.get("donatorNickname") or donation_data.get("donator_nickname") or "익명후원자").strip()
    if not donator_nickname:
        donator_nickname = "익명후원자"

    donator_channel_id = str(donation_data.get("donatorChannelId") or donation_data.get("donator_channel_id") or "").strip()

    # Resolve real existing user by channel ID or nickname
    existing_user = None
    if donator_channel_id:
        existing_user = get_user_by_identifier(db, donator_channel_id)
    if not existing_user and donator_nickname and donator_nickname != "익명후원자":
        existing_user = get_user_by_identifier(db, donator_nickname)

    if existing_user:
        user_id = existing_user.id
    else:
        user_id = donator_channel_id if donator_channel_id else f"chzzk_{donator_nickname}"

    channel_id = str(donation_data.get("channelId") or donation_data.get("channel_id") or "")
    donation_type = str(donation_data.get("donationType") or donation_data.get("donation_type") or "CHAT")
    donation_text = str(donation_data.get("donationText") or donation_data.get("donation_text") or "").strip()
    message_time = str(donation_data.get("messageTime") or donation_data.get("message_time") or "")

    # 3. Deduplication Key Generation (Idempotency)
    explicit_id = donation_data.get("donationId") or donation_data.get("donation_id")
    if explicit_id:
        donation_id = str(explicit_id)
    else:
        raw_hash_seed = f"{channel_id}:{user_id}:{pay_amount}:{donation_text}:{message_time}"
        donation_id = f"don_{hashlib.sha256(raw_hash_seed.encode('utf-8')).hexdigest()[:24]}"

    # Check for duplicate processing
    existing = db.query(DonationRecord).filter_by(donation_id=donation_id).first()
    if existing:
        return False, f"⚠️ 이미 충전 처리된 후원 내역입니다 (후원ID: {donation_id}, 충전포인트: {existing.points_credited:,}P)", None

    # Secondary idempotency check: prevent duplicate charging if both official and unofficial sockets receive same donation within 60 seconds
    try:
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=60)
        recent = db.query(DonationRecord).filter(
            DonationRecord.user_id == user_id,
            DonationRecord.pay_amount == pay_amount,
            DonationRecord.created_at >= cutoff
        ).all()
        for r in recent:
            if r.donation_text == donation_text:
                return False, f"⚠️ 최근 60초 내 이미 처리된 동일 후원 내역입니다 (기존 후원ID: {r.donation_id})", None
    except Exception as e:
        print(f"[TradingEngine] ⚠️ 최근 중복 후원 검사 예외: {e}")

    # 4. Point calculation (1 KRW : 100 Points)
    points_to_credit = pay_amount * POINT_PER_KRW

    # 5. Database safety auto-backup before point mutation
    try:
        from db_backup import create_backup
        create_backup(reason="pre_donation")
    except Exception as e:
        print(f"[TradingEngine] ⚠️ 사전 백업 경고 (충전은 계속 진행): {e}")

    # 6. Execute atomic user update and log creation
    try:
        user = get_or_create_user(db, user_id, donator_nickname)
        if user.username != donator_nickname and donator_nickname != "익명후원자":
            user.username = donator_nickname

        # Overflow boundary check
        if user.points + points_to_credit > 2_000_000_000:
            return False, "⚠️ 보유 포인트 상한(20억P)을 초과하여 충전할 수 없습니다.", None

        user.points += points_to_credit

        record = DonationRecord(
            donation_id=donation_id,
            channel_id=channel_id,
            donator_channel_id=donator_channel_id if donator_channel_id else None,
            donator_nickname=donator_nickname,
            pay_amount=pay_amount,
            points_credited=points_to_credit,
            user_id=user.id,
            donation_type=donation_type,
            donation_text=donation_text,
            raw_payload=json.dumps(donation_data, ensure_ascii=False)
        )
        db.add(record)
        db.commit()
        db.refresh(user)
        db.refresh(record)

        msg = (
            f"🎉 [후원 포인트 충전] {donator_nickname}님이 {pay_amount:,}원을 후원하셨습니다! "
            f"(1:100 비율로 +{points_to_credit:,}P 충전 완료! 현재 잔고: {user.points:,}P)"
        )
        details = {
            "donation_id": donation_id,
            "user_id": user.id,
            "username": user.username,
            "pay_amount": pay_amount,
            "points_credited": points_to_credit,
            "remaining_points": user.points,
            "donation_text": donation_text,
            "donation_type": donation_type
        }
        return True, msg, details
    except Exception as e:
        db.rollback()
        return False, f"⚠️ 후원 포인트 충전 처리 중 DB 트랜잭션 에러: {e}", None

def get_donation_history(db: Session, limit: int = 20) -> List[Dict[str, Any]]:
    """Fetch recent donation history records."""
    records = db.query(DonationRecord).order_by(DonationRecord.id.desc()).limit(limit).all()
    res = []
    for r in records:
        res.append({
            "id": r.id,
            "donation_id": r.donation_id,
            "donator_nickname": r.donator_nickname,
            "donator_channel_id": r.donator_channel_id,
            "pay_amount": r.pay_amount,
            "points_credited": r.points_credited,
            "donation_type": r.donation_type,
            "donation_text": r.donation_text,
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else ""
        })
    return res

# =========================================================
# Community Treasury Casino & Gambling Engine (국고 카지노)
# =========================================================
DEFAULT_CASINO_MAX_BET: int = 100000
MIN_CASINO_BET: int = 100
MAX_CASINO_PAYOUT: int = 100000  # 1회 주사위 도박 등 국고 최대 순지급액 상한선 (국고 보호)

SLOT_SYMBOLS = ["💣", "🍒", "🍇", "🔔", "💎", "🀄", "7️⃣"]
SLOT_WEIGHTS = [10, 30, 25, 20, 9, 4, 2]

def get_casino_state(db: Session) -> Dict[str, Any]:
    """Retrieve current casino state with automatic time expiry handling."""
    state = get_market_state(db)
    is_open = bool(getattr(state, "casino_is_open", False))
    end_time = float(getattr(state, "casino_end_time", 0.0) or 0.0)
    raw_max = getattr(state, "casino_max_bet", DEFAULT_CASINO_MAX_BET)
    max_bet = int(raw_max) if raw_max and int(raw_max) > 0 else DEFAULT_CASINO_MAX_BET
    if max_bet <= 10000:
        max_bet = 100000
        state.casino_max_bet = 100000
        try:
            db.commit()
        except Exception:
            pass

    now = time.time()
    if is_open and end_time > 0 and now >= end_time:
        state.casino_is_open = False
        state.casino_end_time = 0.0
        try:
            db.commit()
            db.refresh(state)
        except Exception:
            pass
        is_open = False

    remaining_sec = max(0, int(end_time - now)) if (is_open and end_time > 0) else (999999 if (is_open and end_time == 0) else 0)

    return {
        "is_open": is_open,
        "end_time": end_time,
        "remaining_sec": remaining_sec,
        "remaining_seconds": remaining_sec,
        "max_bet": max_bet,
        "treasury_pool": getattr(state, "treasury_pool", DEFAULT_TREASURY_POOL)
    }

def open_casino(db: Session, duration_minutes: float = 3.0, max_bet: int = 100000) -> Tuple[bool, str, Dict[str, Any]]:
    """Open community treasury casino for specified minutes (0 = unlimited)."""
    state = get_market_state(db)
    now = time.time()
    end_time = (now + duration_minutes * 60.0) if duration_minutes > 0 else 0.0
    if not max_bet or max_bet <= 10000:
        max_bet = 100000
    max_bet = max(MIN_CASINO_BET, int(max_bet))

    state.casino_is_open = True
    state.casino_end_time = end_time
    state.casino_max_bet = max_bet
    db.commit()
    db.refresh(state)

    duration_str = f"{int(duration_minutes)}분 동안" if duration_minutes > 0 else "무제한"
    msg = (
        f"🎰 [국고 카지노 OPEN] 스트리머가 국고 도박장을 열었습니다! ({duration_str}, 1회 최대: {max_bet:,}P) "
        f"지금 채팅창에 '!슬롯 [베팅금]' 또는 '!주사위 [홀/짝] [베팅금]'으로 국고를 털어보세요! (현재 국고: {int(state.treasury_pool):,}P)"
    )
    details = {
        "is_open": True,
        "duration_minutes": duration_minutes,
        "end_time": end_time,
        "max_bet": max_bet,
        "treasury_pool": state.treasury_pool
    }
    return True, msg, details

def close_casino(db: Session) -> Tuple[bool, str, Dict[str, Any]]:
    """Close community treasury casino immediately."""
    state = get_market_state(db)
    state.casino_is_open = False
    state.casino_end_time = 0.0
    db.commit()
    db.refresh(state)

    msg = f"🔒 [국고 카지노 CLOSED] 국고 도박장이 마감되었습니다! (현재 국고 잔고: {int(state.treasury_pool):,}P)"
    details = {
        "is_open": False,
        "treasury_pool": state.treasury_pool
    }
    return True, msg, details

def execute_slot_gamble(
    db: Session,
    user_id: str,
    username: str,
    bet_token: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Execute 3-reel Jackpot Slot (Uncapped Payouts!):
    Payouts:
    - 7️⃣ 7️⃣ 7️⃣ : MEGA JACKPOT (20% of treasury pool, uncapped, min 15x bet)
    - 🀄 🀄 🀄 : 10x Yakuman Jackpot (Net +9x, uncapped)
    - 💎 💎 💎 : 6x Diamond Triple (Net +5x, uncapped)
    - 🔔 🔔 🔔 : 4x Golden Bell (Net +3x, uncapped)
    - 🍇 🍇 🍇 : 3x Grape Triple (Net +2x, uncapped)
    - 🍒 🍒 🍒 : 2x Cherry Triple (Net +1x, uncapped)
    - High 2-pair (7, 🀄, 💎): 2.0x payout (+1.0x net, uncapped)
    - Standard 2-pair (🔔, 🍇, 🍒): 1.5x payout (+0.5x net, uncapped)
    - Non-matched / 💣: Loss (100% absorbed into Treasury Pool)
    """
    c_state = get_casino_state(db)
    if not c_state["is_open"]:
        return False, "⚠️ 현재 국고 카지노가 오픈되어 있지 않습니다! 스트리머가 열 때까지 기다려주세요.", None

    user = get_or_create_user(db, user_id, username)
    state = get_market_state(db)

    # Parse bet amount
    clean_bet = str(bet_token).strip().lower()
    max_bet = c_state.get("max_bet", 100000)
    if max_bet <= 10000:
        max_bet = 100000
    if clean_bet in ["올인", "all", "풀베팅", "전액", "최대"]:
        bet = min(user.points, max_bet)
    else:
        try:
            bet = int(float(clean_bet))
        except ValueError:
            return False, f"⚠️ 올바른 베팅 금액을 입력해주세요: '{bet_token}' (예: !슬롯 1000, !슬롯 올인)", None

    if bet < MIN_CASINO_BET:
        return False, f"⚠️ 최소 베팅 금액은 {MIN_CASINO_BET:,}P입니다.", None

    if bet > max_bet:
        return False, f"⚠️ 1회 최대 베팅 한도는 {max_bet:,}P입니다. (입력: {bet:,}P)", None

    if user.points < bet:
        return False, f"⚠️ 보유 포인트가 부족합니다! (보유: {user.points:,}P, 베팅: {bet:,}P)", None

    # Spin 3 reels
    s1, s2, s3 = random.choices(SLOT_SYMBOLS, weights=SLOT_WEIGHTS, k=3)
    display_reels = f"[ {s1} | {s2} | {s3} ]"

    is_jackpot = False
    won = False
    multiplier = 0.0
    net_payout = 0

    if s1 == s2 == s3:
        if s1 == "7️⃣":
            is_jackpot = True
            won = True
            pool_share = int(round(state.treasury_pool * 0.20))
            guaranteed = bet * 15
            net_payout = max(guaranteed, pool_share)
            multiplier = round((net_payout + bet) / bet, 1) if bet > 0 else 15.0
        elif s1 == "🀄":
            is_jackpot = True
            won = True
            multiplier = 10.0
            net_payout = int(round(bet * 9.0))
        elif s1 == "💎":
            won = True
            multiplier = 6.0
            net_payout = int(round(bet * 5.0))
        elif s1 == "🔔":
            won = True
            multiplier = 4.0
            net_payout = int(round(bet * 3.0))
        elif s1 == "🍇":
            won = True
            multiplier = 3.0
            net_payout = int(round(bet * 2.0))
        elif s1 == "🍒":
            won = True
            multiplier = 2.0
            net_payout = int(round(bet * 1.0))
        elif s1 == "💣":
            won = False
            net_payout = -bet
    elif (s1 == s2 and s1 != "💣") or (s2 == s3 and s2 != "💣") or (s1 == s3 and s1 != "💣"):
        # 2 matching symbols (not bomb pair)
        won = True
        matched_sym = s1 if (s1 == s2 or s1 == s3) else s2
        if matched_sym in ["7️⃣", "🀄", "💎"]:
            multiplier = 2.0
            net_payout = max(10, int(round(bet * 1.0))) # Net gain +1.0x (2.0x total payout)
        else: # 🔔, 🍇, 🍒
            multiplier = 1.5
            net_payout = max(10, int(round(bet * 0.5))) # Net gain +0.5x (1.5x total payout)
    else:
        won = False
        net_payout = -bet

    if won:
        user.points += net_payout
        state.treasury_pool = max(10000.0, state.treasury_pool - net_payout)
        if is_jackpot and s1 == "7️⃣":
            msg = (
                f"🚨🚨🚨 [MEGA 777 JACKPOT!] {user.username}님이 {display_reels} 대박 터짐! "
                f"국고의 20%인 +{net_payout:,}P를 싹쓸이 강탈했습니다! (잔여: {user.points:,}P | 남은 국고: {int(state.treasury_pool):,}P)"
            )
        elif is_jackpot and s1 == "🀄":
            msg = (
                f"🀄🔥 [역만 잭팟 당첨!] {user.username}님이 {display_reels} 적중! "
                f"배팅금 10배인 +{net_payout:,}P를 국고에서 출금 지급! (잔여: {user.points:,}P)"
            )
        else:
            gain_label = f"{multiplier}배" if multiplier > 0 else "보너스"
            msg = (
                f"🎉 [슬롯 당첨!] {user.username}님이 {display_reels} 적중! "
                f"({gain_label} 당첨으로 +{net_payout:,}P 획득! 잔여: {user.points:,}P)"
            )
    else:
        user.points -= bet
        state.treasury_pool += bet
        msg = (
            f"💣 [슬롯 꽝!] {user.username}님이 {display_reels} 꽝! "
            f"베팅금 {bet:,}P는 국고로 압류되었습니다! 꺼~억 (잔여: {user.points:,}P | 현재 국고: {int(state.treasury_pool):,}P)"
        )

    db.commit()
    db.refresh(user)
    db.refresh(state)

    details = {
        "game_type": "slot",
        "user_id": user.id,
        "username": user.username,
        "bet": bet,
        "reels": [s1, s2, s3],
        "won": won,
        "is_jackpot": is_jackpot,
        "net_payout": net_payout,
        "remaining_points": user.points,
        "treasury_pool": state.treasury_pool
    }
    return True, msg, details

def execute_dice_gamble(
    db: Session,
    user_id: str,
    username: str,
    choice_token: str,
    bet_token: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Execute 2-Dice High-Roller Gamble (Uncapped Payouts!):
    Choices: '홀' (Odd - 2.0x), '짝' (Even - 2.0x), '대' (8~12 High - 2.0x), '소' (2~6 Low - 2.0x).
    Sum 7 on High/Low: PUSH (무승부 - 베팅금 100% 전액 환급, 원금 보존).
    Special: Double 1-1 or 6-6 gives 3.0x CRITICAL JACKPOT! (Uncapped)
    """
    c_state = get_casino_state(db)
    if not c_state["is_open"]:
        return False, "⚠️ 현재 국고 카지노가 오픈되어 있지 않습니다! 스트리머가 열 때까지 기다려주세요.", None

    user = get_or_create_user(db, user_id, username)
    state = get_market_state(db)

    # Normalize choice
    choice = str(choice_token).strip().lower()
    choice_map = {
        "홀": "ODD", "odd": "ODD", "홀수": "ODD",
        "짝": "EVEN", "even": "EVEN", "짝수": "EVEN",
        "대": "HIGH", "high": "HIGH", "크다": "HIGH",
        "소": "LOW", "low": "LOW", "작다": "LOW",
    }
    if choice not in choice_map:
        return False, f"⚠️ 올바른 주사위 선택을 입력해주세요: '{choice_token}' (선택 가능: 홀, 짝, 대, 소. 예: !주사위 홀 5000)", None
    target_choice = choice_map[choice]

    # Parse bet amount
    clean_bet = str(bet_token).strip().lower()
    max_bet = c_state.get("max_bet", 100000)
    if max_bet <= 10000:
        max_bet = 100000
    if clean_bet in ["올인", "all", "풀베팅", "전액", "최대"]:
        bet = min(user.points, max_bet)
    else:
        try:
            bet = int(float(clean_bet))
        except ValueError:
            return False, f"⚠️ 올바른 베팅 금액을 입력해주세요: '{bet_token}' (예: !주사위 홀 1000, !주사위 짝 올인)", None

    if bet < MIN_CASINO_BET:
        return False, f"⚠️ 최소 베팅 금액은 {MIN_CASINO_BET:,}P입니다.", None

    if bet > max_bet:
        return False, f"⚠️ 1회 최대 베팅 한도는 {max_bet:,}P입니다. (입력: {bet:,}P)", None

    if user.points < bet:
        return False, f"⚠️ 보유 포인트가 부족합니다! (보유: {user.points:,}P, 베팅: {bet:,}P)", None

    # Roll two dice
    d1 = random.randint(1, 6)
    d2 = random.randint(1, 6)
    total = d1 + d2
    is_odd = (total % 2 == 1)
    is_high = (total >= 8)
    is_low = (total <= 6)
    is_seven = (total == 7)

    is_push = False
    is_correct = False
    if target_choice == "ODD" and is_odd:
        is_correct = True
    elif target_choice == "EVEN" and not is_odd:
        is_correct = True
    elif target_choice == "HIGH":
        if is_high:
            is_correct = True
        elif is_seven:
            is_push = True
    elif target_choice == "LOW":
        if is_low:
            is_correct = True
        elif is_seven:
            is_push = True

    is_critical = is_correct and ((d1 == 1 and d2 == 1) or (d1 == 6 and d2 == 6))

    if is_critical:
        # 3.0x Critical Payout (Net profit 2.0x, uncapped)
        net_payout = int(round(bet * 2.0))
        user.points += net_payout
        state.treasury_pool = max(10000.0, state.treasury_pool - net_payout)
        msg = (
            f"🎲🔥 [주사위 3배 크리티컬 잭팟!] {user.username}님이 더블 잭팟 적중! "
            f"[ 🎲{d1} + 🎲{d2} = {total} ] 3배 크리티컬 당첨으로 +{net_payout:,}P 국고 획득! (잔여: {user.points:,}P)"
        )
    elif is_correct:
        # 2.0x Payout (Net profit 1.0x, uncapped)
        net_payout = bet
        gain_label = "2배"
        user.points += net_payout
        state.treasury_pool = max(10000.0, state.treasury_pool - net_payout)
        odd_label = "홀" if is_odd else "짝"
        msg = (
            f"🎲✨ [주사위 적중!] {user.username}님이 '{choice}' 선택 적중! "
            f"[ 🎲{d1} + 🎲{d2} = {total} ({odd_label}) ] {gain_label} 당첨으로 +{net_payout:,}P 획득! (잔여: {user.points:,}P)"
        )
    elif is_push:
        net_payout = 0
        msg = (
            f"🎲⚖️ [주사위 무승부!] {user.username}님의 대/소 예측 중 럭키 7 발생! "
            f"[ 🎲{d1} + 🎲{d2} = 7 ] 베팅금 {bet:,}P는 전액 환급됩니다! (잔여: {user.points:,}P)"
        )
    else:
        net_payout = -bet
        user.points -= bet
        state.treasury_pool += bet
        odd_label = "홀" if is_odd else "짝"
        msg = (
            f"🎲💀 [주사위 실패!] {user.username}님의 예측 빗나감! "
            f"[ 🎲{d1} + 🎲{d2} = {total} ({odd_label}) ] 베팅금 {bet:,}P는 국고로 귀속되었습니다! (잔여: {user.points:,}P)"
        )

    db.commit()
    db.refresh(user)
    db.refresh(state)

    details = {
        "game_type": "dice",
        "user_id": user.id,
        "username": user.username,
        "bet": bet,
        "choice": target_choice,
        "dice": [d1, d2],
        "total": total,
        "won": is_correct,
        "is_push": is_push,
        "is_critical": is_critical,
        "net_payout": net_payout,
        "remaining_points": user.points,
        "treasury_pool": state.treasury_pool
    }
    return True, msg, details


