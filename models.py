import enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
from database import Base

class ProductType(str, enum.Enum):
    ONE_X = "1X"
    TWO_X = "2X"
    THREE_X = "3X"
    FIVE_X = "5X"
    TEN_X = "10X"
    TWENTY_X = "20X"
    FORTY_X = "40X"
    SIXTY_X = "60X"
    INV = "INV"
    TWO_X_INV = "2X_INV"
    THREE_X_INV = "3X_INV"
    FIVE_X_INV = "5X_INV"
    TEN_X_INV = "10X_INV"
    TWENTY_X_INV = "20X_INV"
    FORTY_X_INV = "40X_INV"
    SIXTY_X_INV = "60X_INV"

class OrderType(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"

class OrderStatus(str, enum.Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"

class BankruptcyStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED_FULL = "APPROVED_FULL"
    APPROVED_HALF = "APPROVED_HALF"
    REJECTED = "REJECTED"

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)
    username = Column(String, nullable=False)
    points = Column(Integer, default=10000, nullable=False)
    debt = Column(Integer, default=0, nullable=False)
    last_bankrupt_at = Column(DateTime, nullable=True)
    last_mined_at = Column(DateTime, nullable=True)
    total_mined = Column(Float, default=0.0, nullable=False)
    total_dividends = Column(Integer, default=0, nullable=False)
    pickaxe_level = Column(Integer, default=1, nullable=False)
    auto_mining_enabled = Column(Boolean, default=False, nullable=False)
    auto_mining_end_time = Column(Float, default=0.0, nullable=True)
    auto_mining_session_mined = Column(Float, default=0.0, nullable=False)
    auto_mining_session_points = Column(Integer, default=0, nullable=False)
    cube_count = Column(Integer, default=0, nullable=False)
    cube_fragments = Column(Integer, default=0, nullable=False)
    shield_scroll_count = Column(Integer, default=0, nullable=False)
    boost_scroll_count = Column(Integer, default=0, nullable=False)
    downgrade_scroll_count = Column(Integer, default=0, nullable=False)
    snipe_scroll_count = Column(Integer, default=0, nullable=False)
    arm_shield = Column(Boolean, default=True, nullable=False)
    arm_boost = Column(Boolean, default=False, nullable=False)
    arm_downgrade = Column(Boolean, default=True, nullable=False)
    arm_snipe = Column(Boolean, default=False, nullable=False)
    repay_count = Column(Integer, default=0, nullable=False)
    total_repaid = Column(Integer, default=0, nullable=False)
    bank_balance = Column(Integer, default=0, nullable=False)
    bank_data = Column(String, default="{}", nullable=True)
    special_snipe_scrolls = Column(String, default="{}", nullable=True)
    web_pin = Column(String, nullable=True)
    web_token = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    positions = relationship("Position", back_populates="user", cascade="all, delete-orphan")
    orders = relationship("LimitOrder", back_populates="user", cascade="all, delete-orphan")
    equipments = relationship("UserEquipment", back_populates="user", cascade="all, delete-orphan")
    bankruptcy_applications = relationship("BankruptcyApplication", back_populates="user", cascade="all, delete-orphan")
    donations = relationship("DonationRecord", back_populates="user", cascade="all, delete-orphan")
    equipment_listings = relationship("EquipmentListing", foreign_keys="EquipmentListing.seller_id", back_populates="seller", cascade="all, delete-orphan")
    asset_history = relationship("UserAssetHistory", foreign_keys="UserAssetHistory.user_id", back_populates="user", cascade="all, delete-orphan", order_by="UserAssetHistory.id")

class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    product_type = Column(Enum(ProductType), nullable=False)
    quantity = Column(Float, default=0.0, nullable=False)
    entry_price = Column(Float, default=0.0, nullable=False)
    invested_cash = Column(Float, default=0.0, nullable=False)

    user = relationship("User", back_populates="positions")

class MarketState(Base):
    __tablename__ = "market_state"

    id = Column(Integer, primary_key=True, default=1)
    current_rank_name = Column(String, default="작성3", nullable=True)
    current_rank_point = Column(Integer, default=2340, nullable=False)
    current_price = Column(Integer, default=2340, nullable=False)
    previous_price = Column(Integer, default=2340, nullable=False)
    day_open_price = Column(Integer, default=2340, nullable=False)
    is_trading_locked = Column(Boolean, default=False, nullable=False)
    last_settlement_delta = Column(Integer, default=0, nullable=False)
    treasury_pool = Column(Float, default=500000.0, nullable=False)
    free_trading_end_time = Column(Float, default=0.0, nullable=True)
    casino_is_open = Column(Boolean, default=False, nullable=False)
    casino_end_time = Column(Float, default=0.0, nullable=True)
    casino_max_bet = Column(Integer, default=10000000, nullable=False)
    sf_event_type = Column(String, nullable=True) # None, "DISCOUNT_30", "FEVER_100", "SHINING"
    sf_event_end_time = Column(Float, default=0.0, nullable=True)
    sf_event_title = Column(String, nullable=True)
    sf_next_event_time = Column(Float, default=0.0, nullable=True)
    lottery_is_open = Column(Boolean, default=False, nullable=False)
    lottery_end_time = Column(Float, default=0.0, nullable=True)
    lottery_title = Column(String, default="국가 복지 복권", nullable=True)
    lottery_next_event_time = Column(Float, default=0.0, nullable=True)
    merchant_is_open = Column(Boolean, default=False, nullable=False)
    merchant_end_time = Column(Float, default=0.0, nullable=True)
    merchant_name = Column(String, default="신비상인", nullable=True)
    merchant_next_time = Column(Float, default=0.0, nullable=True)
    merchant_shield_price = Column(Integer, default=500000, nullable=False)
    merchant_shield_stock = Column(Integer, default=5, nullable=False)
    merchant_boost_price = Column(Integer, default=350000, nullable=False)
    merchant_boost_stock = Column(Integer, default=10, nullable=False)
    merchant_downgrade_price = Column(Integer, default=400000, nullable=False)
    merchant_downgrade_stock = Column(Integer, default=8, nullable=False)
    merchant_snipe_price = Column(Integer, default=500000, nullable=False)
    merchant_snipe_stock = Column(Integer, default=4, nullable=False)
    merchant_special_snipe_code = Column(String, nullable=True)
    merchant_special_snipe_name = Column(String, nullable=True)
    merchant_special_snipe_desc = Column(String, nullable=True)
    merchant_special_snipe_price = Column(Integer, default=750000, nullable=False)
    merchant_special_snipe_stock = Column(Integer, default=0, nullable=False)
    fund_nav = Column(Float, default=1000.0, nullable=False)
    fund_navs_json = Column(String, default="{}", nullable=True)

class LimitOrder(Base):
    __tablename__ = "orders_limit"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    order_type = Column(Enum(OrderType), nullable=False)
    product_type = Column(Enum(ProductType), nullable=False)
    target_price = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)
    status = Column(Enum(OrderStatus), default=OrderStatus.PENDING, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User", back_populates="orders")
 
class BankruptcyApplication(Base):
    __tablename__ = "bankruptcy_applications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    username = Column(String, nullable=False)
    debt = Column(Integer, nullable=False)
    gross_assets = Column(Integer, default=0, nullable=False)
    cash = Column(Integer, default=0, nullable=False)
    portfolio_value = Column(Integer, default=0, nullable=False)
    reason = Column(String, nullable=False)
    status = Column(Enum(BankruptcyStatus), default=BankruptcyStatus.PENDING, nullable=False)
    verdict = Column(String, nullable=True)
    admin_comment = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    resolved_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="bankruptcy_applications")

class DonationRecord(Base):
    __tablename__ = "donation_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    donation_id = Column(String, unique=True, index=True, nullable=False) # Deduplication key
    channel_id = Column(String, nullable=True)
    donator_channel_id = Column(String, index=True, nullable=True)
    donator_nickname = Column(String, nullable=False)
    pay_amount = Column(Integer, nullable=False) # KRW donation amount (원)
    points_credited = Column(Integer, nullable=False) # Charged points (1:1000 ratio)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    donation_type = Column(String, default="CHAT") # CHAT or VIDEO
    donation_text = Column(String, nullable=True)
    raw_payload = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User", back_populates="donations")

class UserEquipment(Base):
    __tablename__ = "user_equipments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    equipment_type = Column(String, default="PICKAXE", nullable=False)
    name = Column(String, nullable=False)
    starforce = Column(Integer, default=0, nullable=False)
    is_equipped = Column(Boolean, default=False, nullable=False)
    potential_tier = Column(String, default="NONE", nullable=False) # NONE, RARE, EPIC, UNIQUE, LEGENDARY
    potential_line_1 = Column(String, nullable=True) # e.g. "MINING_CD_RESET:15"
    potential_line_2 = Column(String, nullable=True) # e.g. "MINING_BONUS_CASH:60000"
    potential_line_3 = Column(String, nullable=True) # e.g. "CASINO_SLOT_BOOST:50"
    pity_count = Column(Integer, default=0, nullable=False) # 등급 상승 보장 카운터
    is_cube_locked = Column(Boolean, default=False, nullable=False) # 실수 방지용 큐브 잠금
    is_line1_locked = Column(Boolean, default=False, nullable=False) # 1번줄 옵션 잠금 (20배 비용)
    is_line2_locked = Column(Boolean, default=False, nullable=False) # 2번줄 옵션 잠금 (20배 비용)
    is_line3_locked = Column(Boolean, default=False, nullable=False) # 3번줄 옵션 잠금 (20배 비용)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User", back_populates="equipments")
    listings = relationship("EquipmentListing", foreign_keys="EquipmentListing.equipment_id", back_populates="equipment", cascade="all, delete-orphan")

class EquipmentListing(Base):
    __tablename__ = "equipment_listings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    seller_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    seller_name = Column(String, nullable=False)
    buyer_id = Column(String, nullable=True, index=True) # None for public market, or specific user_id
    buyer_name = Column(String, nullable=True)
    equipment_id = Column(Integer, ForeignKey("user_equipments.id"), nullable=False, index=True)
    price = Column(Integer, nullable=False)
    tax_fee = Column(Integer, default=0, nullable=False)
    status = Column(String, default="ACTIVE", nullable=False) # ACTIVE, SOLD, CANCELLED
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    resolved_at = Column(DateTime, nullable=True)

    equipment = relationship("UserEquipment", foreign_keys=[equipment_id], back_populates="listings")
    seller = relationship("User", foreign_keys=[seller_id], back_populates="equipment_listings")


class ItemListing(Base):
    __tablename__ = "item_listings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    seller_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    seller_name = Column(String, nullable=False)
    buyer_id = Column(String, nullable=True, index=True)
    buyer_name = Column(String, nullable=True)
    item_type = Column(String, nullable=False)  # "shield", "boost", "downgrade"
    item_name = Column(String, nullable=False)
    quantity = Column(Integer, default=1, nullable=False)
    price = Column(Integer, nullable=False)
    tax_fee = Column(Integer, default=0, nullable=False)
    status = Column(String, default="ACTIVE", nullable=False)  # ACTIVE, SOLD, CANCELLED
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    resolved_at = Column(DateTime, nullable=True)

    seller = relationship("User", foreign_keys=[seller_id])


class UserAssetHistory(Base):
    __tablename__ = "user_asset_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    net_worth = Column(Integer, default=0, nullable=False)
    cash = Column(Integer, default=0, nullable=False)
    stock_value = Column(Float, default=0.0, nullable=False)
    debt = Column(Integer, default=0, nullable=False)
    credit_score = Column(Integer, default=500, nullable=False)
    event_type = Column(String, default="SNAPSHOT", nullable=False)  # INITIAL, SETTLEMENT, TRADE, MINE, PVP_WIN, PVP_LOSS, LOAN, SNAPSHOT
    note = Column(String, default="", nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    user = relationship("User", foreign_keys=[user_id], back_populates="asset_history")


class ArenaMatchLog(Base):
    __tablename__ = "arena_match_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    challenger_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    challenger_name = Column(String, nullable=False)
    defender_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    defender_name = Column(String, nullable=False)
    bet_amount = Column(Integer, nullable=False)
    winner_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    winner_name = Column(String, nullable=False)
    loser_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    loser_name = Column(String, nullable=False)
    challenger_roll = Column(Integer, nullable=False)
    defender_roll = Column(Integer, nullable=False)
    pot_total = Column(Integer, nullable=False)
    winner_reward = Column(Integer, nullable=False)
    tax_fee = Column(Integer, default=0, nullable=False)
    match_type = Column(String, default="DIRECT", nullable=False)  # DIRECT or OPEN
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

