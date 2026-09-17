import time
import math
import json
import hashlib
import random
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, List, Optional
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
    "기본": ProductType.ONE_X,
    "기본주": ProductType.ONE_X,
    "현물": ProductType.ONE_X,

    "2X": ProductType.TWO_X,
    "2x": ProductType.TWO_X,
    "2배": ProductType.TWO_X,
    "2레": ProductType.TWO_X,
    "2버": ProductType.TWO_X,
    "2레버": ProductType.TWO_X,
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
    "3배레버": ProductType.THREE_X,
    "3배레버리지": ProductType.THREE_X,
    "3X레버": ProductType.THREE_X,

    "5X": ProductType.FIVE_X,
    "5x": ProductType.FIVE_X,
    "5배": ProductType.FIVE_X,
    "5레": ProductType.FIVE_X,
    "5버": ProductType.FIVE_X,
    "5레버": ProductType.FIVE_X,
    "5배레버": ProductType.FIVE_X,
    "5배레버리지": ProductType.FIVE_X,
    "5X레버": ProductType.FIVE_X,

    "10X": ProductType.TEN_X,
    "10x": ProductType.TEN_X,
    "10배": ProductType.TEN_X,
    "10레": ProductType.TEN_X,
    "10버": ProductType.TEN_X,
    "10레버": ProductType.TEN_X,
    "10배레버": ProductType.TEN_X,
    "10배레버리지": ProductType.TEN_X,
    "10X레버": ProductType.TEN_X,

    "INV": ProductType.INV,
    "inv": ProductType.INV,
    "1X_INV": ProductType.INV,
    "1XINV": ProductType.INV,
    "1배인버스": ProductType.INV,
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

    # Handle forms like "10x", "5x", "10배", "5배", "10레", "10버", "10레버"
    upper_c = cleaned.upper()
    for suffix in ["X", "배", "레", "버", "레버", "배레버"]:
        if upper_c.endswith(suffix):
            prefix = upper_c[:-len(suffix)].strip()
            if prefix in ["1", "2", "3", "5", "10"]:
                return PRODUCT_SYNONYMS.get(f"{prefix}X")

    return None

STARTING_POINTS: int = 50000
DEFAULT_TREASURY_POOL: float = 500000.0
TRADING_FEE_RATE: float = 0.01  # 1% 거래 수수료 -> 국고 채굴풀 자동 적립
MAX_LOAN_LIMIT: int = 50000     # 최대 50,000P 신용 대출 한도
LOAN_INTEREST_RATE: float = 0.02 # 경기당 2% 대출 이자 (국고 환수)

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

    qty_display = f"{int(quantity)}" if quantity.is_integer() else f"{quantity:.2f}"
    msg = f"✅ [매수 체결] [구매 완료] {user.username}님이 {product_type.value} {qty_display}주를 구매했습니다! (매수 완료 | 체결가: {current_price:,}P, 수수료: {fee:,}P 국고 적립, 잔여: {user.points:,}P)"
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

    qty_display = f"{int(quantity)}" if quantity.is_integer() else f"{quantity:.2f}"
    if borrow_amount > 0:
        msg = (
            f"💳🔥 [빚투 / 신용 올인 체결] {user.username}님 국고 대출 {borrow_amount:,}P 실행 후 "
            f"{product_type.value} {qty_display}주를 올인 구매했습니다! (풀매수 완료 | "
            f"체결가: {current_price:,}P | 총 채무: {user.debt:,}P | 잔여 현금: {user.points:,}P)"
        )
    else:
        msg = (
            f"✅ [매수 체결] [구매 완료] {user.username}님이 {product_type.value} {qty_display}주를 올인 구매했습니다! (매수 완료 | "
            f"체결가: {current_price:,}P, 수수료: {fee:,}P 국고 적립, 잔여: {user.points:,}P)"
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
    if clean_qty in ["전량", "all", "모두", "올인", "전부", "다", "최대", "풀매도", "전액"]:
        sell_qty = pos.quantity
    else:
        try:
            sell_qty = float(clean_qty)
            if sell_qty <= 0:
                return False, "⚠️ 매도 수량은 0보다 커야 합니다.", None
            if sell_qty > pos.quantity + 1e-9:
                qty_has = f"{int(pos.quantity)}" if pos.quantity.is_integer() else f"{pos.quantity:.2f}"
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

    qty_display = f"{int(sell_qty)}" if sell_qty.is_integer() else f"{sell_qty:.2f}"
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
            qty_display = f"{int(quantity)}" if quantity.is_integer() else f"{quantity:.2f}"
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
            qty_display = f"{int(quantity)}" if quantity.is_integer() else f"{quantity:.2f}"
            msg = f"📌 [지정가 매수 예약] #{order.id} {product_type.value} {qty_display}주 @ 목표가 {target_price:g}P 예약 완료 (예약금: {total_reserved:,}P 차감)"
            return True, msg, {"order_id": order.id, "status": "PENDING"}

    else: # SELL
        pos = db.query(Position).filter_by(user_id=user.id, product_type=product_type).first()
        if not pos or pos.quantity < quantity - 1e-9:
            has_q = pos.quantity if pos else 0
            qty_has = f"{int(has_q)}" if isinstance(has_q, (int, float)) and float(has_q).is_integer() else f"{has_q:.2f}"
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
            qty_display = f"{int(quantity)}" if quantity.is_integer() else f"{quantity:.2f}"
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
            qty_display = f"{int(quantity)}" if quantity.is_integer() else f"{quantity:.2f}"
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
    div_rate = 0.05 if rank == 1 else (0.01 if rank == 2 else 0.0)

    if div_rate > 0:
        one_x_positions = db.query(Position).filter(
            Position.product_type == ProductType.ONE_X,
            Position.quantity > 0
        ).all()
        for p in one_x_positions:
            u = p.user
            if u:
                payout = int(round(p.quantity * new_price * div_rate))
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

def execute_mining(
    db: Session,
    user_id: str,
    username: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Execute !채굴 (Proof of Watch mining).
    Mines 1X base shares funded by the liquidation Treasury pool without inflation.
    Cooldown: 15 minutes (900 seconds).
    """
    state = get_market_state(db)
    user = get_or_create_user(db, user_id, username)
    now_utc = datetime.now(timezone.utc)

    # 1. Cooldown check (15 minutes = 900 seconds)
    if user.last_mined_at:
        last_time = user.last_mined_at
        if last_time.tzinfo is None:
            last_time = last_time.replace(tzinfo=timezone.utc)
        elapsed = (now_utc - last_time).total_seconds()
        if elapsed < 900:
            rem = int(900 - elapsed)
            rem_m, rem_s = divmod(rem, 60)
            return False, f"⏳ [채굴 쿨타임] 다음 채굴까지 {rem_m}분 {rem_s}초 남았습니다.", {"remaining_seconds": rem}

    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL

    current_price = state.current_price
    # 2. Dynamic Mining Reward based on Treasury Pool
    # Grants 5% of pool, clamped between 0.1 and 1.0 share
    target_cash = min(float(current_price), max(current_price * 0.2, state.treasury_pool * 0.05))
    shares_awarded = round(target_cash / current_price, 2)
    if shares_awarded <= 0.05:
        shares_awarded = 0.1 # Minimum faucet floor
    actual_cost = int(round(shares_awarded * current_price))

    # Deduct from treasury pool
    state.treasury_pool = max(0.0, state.treasury_pool - actual_cost)

    # 3. Check if user has debt -> Forced Labor Mode (탄광 노역 채굴)
    user_debt = getattr(user, "debt", 0) or 0
    if user_debt > 0:
        repay_amt = min(user_debt, actual_cost)
        user.debt = user_debt - repay_amt
        # Mined value returned to treasury as debt payoff
        state.treasury_pool += repay_amt

        # Excess cash if mined value exceeds remaining debt
        excess = actual_cost - repay_amt
        if excess > 0:
            user.points += excess

        user.last_mined_at = now_utc
        # Note: Do not add to user.total_mined during forced labor,
        # because the mined shares were immediately seized to repay debt.

        db.commit()
        db.refresh(user)
        db.refresh(state)

        msg = (
            f"⛏️ [탄광 노역 채굴] {user.username}님 탄광 노역으로 {actual_cost:,}P 상당 채굴 완료! "
            f"수익 {repay_amt:,}P가 국고 빚 상환에 즉시 충당되었습니다! (남은 빚: {user.debt:,}P | 쿨타임: 15분)"
        )
        return True, msg, {
            "user_id": user.id,
            "username": user.username,
            "shares_awarded": shares_awarded,
            "cash_value": actual_cost,
            "repaid_debt": repay_amt,
            "remaining_debt": user.debt,
            "treasury_pool": state.treasury_pool,
            "is_forced_labor": True
        }

    # Standard Mining Reward: Credit 1X position to user
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

    user.last_mined_at = now_utc
    user.total_mined = (user.total_mined or 0.0) + shares_awarded

    db.commit()
    db.refresh(user)
    db.refresh(state)

    msg = (
        f"⛏️ [채굴 완료] {user.username}님 1X {shares_awarded:g}주가 1X 보유에 합산되었습니다! "
        f"(+{actual_cost:,}P 상당 | 국고 잔여: {int(state.treasury_pool):,}P | 다음 채굴: 15분 후)"
    )
    return True, msg, {
        "user_id": user.id,
        "username": user.username,
        "shares_awarded": shares_awarded,
        "cash_value": actual_cost,
        "treasury_pool": state.treasury_pool,
        "total_mined": user.total_mined
    }

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
            any(uid_lower.startswith(p) for p in ("fresh_", "test_", "viewer_", "strictly_", "dummy_", "sim_", "bug_"))
            or any(uname_lower.startswith(p) for p in ("테스터", "유저_", "새유저", "철통잠금", "더미", "테스트"))
            or uname_lower in ("테스트유저", "시청자1", "타이머만료유저", "후원테스터", "마진유저")
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
DEFAULT_CASINO_MAX_BET: int = 10000
MIN_CASINO_BET: int = 100

SLOT_SYMBOLS = ["💣", "🍒", "🍇", "🔔", "💎", "🀄", "7️⃣"]
SLOT_WEIGHTS = [15, 30, 24, 16, 9, 4, 2]

def get_casino_state(db: Session) -> Dict[str, Any]:
    """Retrieve current casino state with automatic time expiry handling."""
    state = get_market_state(db)
    is_open = bool(getattr(state, "casino_is_open", False))
    end_time = float(getattr(state, "casino_end_time", 0.0) or 0.0)
    max_bet = int(getattr(state, "casino_max_bet", DEFAULT_CASINO_MAX_BET) or DEFAULT_CASINO_MAX_BET)

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

def open_casino(db: Session, duration_minutes: float = 3.0, max_bet: int = 10000) -> Tuple[bool, str, Dict[str, Any]]:
    """Open community treasury casino for specified minutes (0 = unlimited)."""
    state = get_market_state(db)
    now = time.time()
    end_time = (now + duration_minutes * 60.0) if duration_minutes > 0 else 0.0
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
    Execute 3-reel high-dopamine Jackpot Slot:
    Payouts:
    - 7️⃣ 7️⃣ 7️⃣ : MEGA JACKPOT (30% of entire treasury pool, min 20x bet)
    - 🀄 🀄 🀄 : 10x Yakuman Jackpot
    - 💎 💎 💎 : 6x Diamond Triple
    - 🔔 🔔 🔔 : 4x Golden Bell
    - 🍇 🍇 🍇 : 2.5x Grape Triple
    - 🍒 🍒 🍒 : 2.0x Cherry Triple
    - High 2-pair (7, 🀄, 💎): 2.5x payout (+1.5x net)
    - Standard 2-pair (🔔, 🍇, 🍒): 2.0x payout (+1.0x net, matching dice!)
    - Non-matched / 💣: Loss (100% absorbed into Treasury Pool)
    """
    c_state = get_casino_state(db)
    if not c_state["is_open"]:
        return False, "⚠️ 현재 국고 카지노가 오픈되어 있지 않습니다! 스트리머가 열 때까지 기다려주세요.", None

    user = get_or_create_user(db, user_id, username)
    state = get_market_state(db)

    # Parse bet amount
    clean_bet = str(bet_token).strip().lower()
    max_bet = c_state["max_bet"]
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
            pool_share = int(round(state.treasury_pool * 0.30))
            guaranteed = bet * 20
            net_payout = max(guaranteed, pool_share)
            # Ensure treasury safety cap
            net_payout = min(net_payout, max(1000, int(state.treasury_pool - 10000)))
            multiplier = round(net_payout / bet, 1) if bet > 0 else 20.0
        elif s1 == "🀄":
            is_jackpot = True
            won = True
            multiplier = 10.0
            net_payout = int(round(bet * multiplier))
        elif s1 == "💎":
            won = True
            multiplier = 6.0
            net_payout = int(round(bet * multiplier))
        elif s1 == "🔔":
            won = True
            multiplier = 4.0
            net_payout = int(round(bet * multiplier))
        elif s1 == "🍇":
            won = True
            multiplier = 2.5
            net_payout = int(round(bet * multiplier))
        elif s1 == "🍒":
            won = True
            multiplier = 2.0
            net_payout = int(round(bet * multiplier))
        elif s1 == "💣":
            won = False
            net_payout = -bet
    elif (s1 == s2 and s1 != "💣") or (s2 == s3 and s2 != "💣") or (s1 == s3 and s1 != "💣"):
        # 2 matching symbols (not bomb pair)
        won = True
        matched_sym = s1 if (s1 == s2 or s1 == s3) else s2
        if matched_sym in ["7️⃣", "🀄", "💎"]:
            multiplier = 2.5
            net_payout = int(round(bet * 1.5)) # Net gain +1.5x (2.5x total payout)
        else: # 🔔, 🍇, 🍒
            multiplier = 2.0
            net_payout = bet # Net gain +1.0x (2.0x total payout, exactly like dice!)
    else:
        won = False
        net_payout = -bet

    if won:
        user.points += net_payout
        state.treasury_pool = max(10000.0, state.treasury_pool - net_payout)
        if is_jackpot and s1 == "7️⃣":
            msg = (
                f"🚨🚨🚨 [MEGA 777 JACKPOT!] {user.username}님이 {display_reels} 대박 터짐! "
                f"국고의 30%인 +{net_payout:,}P를 싹쓸이 강탈했습니다! (잔여: {user.points:,}P | 남은 국고: {int(state.treasury_pool):,}P)"
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
    Execute 2-Dice High-Roller Gamble:
    Choices: '홀' (Odd), '짝' (Even), '대' (8~12 High), '소' (2~6 Low).
    Special: Double 1-1 or 6-6 gives 5x CRITICAL JACKPOT!
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
    max_bet = c_state["max_bet"]
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
    is_low = (total <= 6) # 7 is house draw/loss for high-low

    is_correct = False
    if target_choice == "ODD" and is_odd:
        is_correct = True
    elif target_choice == "EVEN" and not is_odd:
        is_correct = True
    elif target_choice == "HIGH" and is_high:
        is_correct = True
    elif target_choice == "LOW" and is_low:
        is_correct = True

    is_critical = is_correct and ((d1 == 1 and d2 == 1) or (d1 == 6 and d2 == 6))

    if is_critical:
        # 5x Critical Payout (Net profit 4x)
        net_payout = bet * 4
        user.points += net_payout
        state.treasury_pool = max(10000.0, state.treasury_pool - net_payout)
        msg = (
            f"🎲🔥 [주사위 5배 크리티컬 잭팟!] {user.username}님이 더블 잭팟 적중! "
            f"[ 🎲{d1} + 🎲{d2} = {total} ] 5배 크리티컬 당첨으로 +{net_payout:,}P 국고 강탈! (잔여: {user.points:,}P)"
        )
    elif is_correct:
        # 2x Payout (Net profit 1x)
        net_payout = bet
        user.points += net_payout
        state.treasury_pool = max(10000.0, state.treasury_pool - net_payout)
        odd_label = "홀" if is_odd else "짝"
        msg = (
            f"🎲✨ [주사위 적중!] {user.username}님이 '{choice}' 선택 적중! "
            f"[ 🎲{d1} + 🎲{d2} = {total} ({odd_label}) ] 2배 당첨으로 +{bet:,}P 획득! (잔여: {user.points:,}P)"
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
        "is_critical": is_critical,
        "net_payout": net_payout,
        "remaining_points": user.points,
        "treasury_pool": state.treasury_pool
    }
    return True, msg, details


