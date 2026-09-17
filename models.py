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
    INV = "INV"
    TWO_X_INV = "2X_INV"
    THREE_X_INV = "3X_INV"
    FIVE_X_INV = "5X_INV"
    TEN_X_INV = "10X_INV"

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
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    positions = relationship("Position", back_populates="user", cascade="all, delete-orphan")
    orders = relationship("LimitOrder", back_populates="user", cascade="all, delete-orphan")

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
    casino_max_bet = Column(Integer, default=10000, nullable=False)

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

    user = relationship("User", backref="bankruptcy_applications")

class DonationRecord(Base):
    __tablename__ = "donation_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    donation_id = Column(String, unique=True, index=True, nullable=False) # Deduplication key
    channel_id = Column(String, nullable=True)
    donator_channel_id = Column(String, index=True, nullable=True)
    donator_nickname = Column(String, nullable=False)
    pay_amount = Column(Integer, nullable=False) # KRW donation amount (원)
    points_credited = Column(Integer, nullable=False) # Charged points (1:100 ratio)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    donation_type = Column(String, default="CHAT") # CHAT or VIDEO
    donation_text = Column(String, nullable=True)
    raw_payload = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User", backref="donations")

