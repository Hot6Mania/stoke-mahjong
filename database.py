import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "stoke_mahjong.db"))
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable SQLite foreign keys and busy timeout for safe concurrency."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    from models import (
        MarketState, User, Position, LimitOrder, BankruptcyApplication,
        DonationRecord, UserEquipment, EquipmentListing
    )
    Base.metadata.create_all(bind=engine)
    
    # Ensure backup directory is ready
    try:
        from db_backup import ensure_backup_dir
        ensure_backup_dir()
    except Exception:
        pass
    
    # Initialize default MarketState if not exists
    db = SessionLocal()
    try:
        # Safe column migration for existing SQLite DB
        with engine.connect() as conn:
            import sqlalchemy
            for col_sql in [
                "ALTER TABLE market_state ADD COLUMN treasury_pool FLOAT DEFAULT 500000.0",
                "ALTER TABLE market_state ADD COLUMN day_open_price INTEGER DEFAULT 2340",
                "ALTER TABLE market_state ADD COLUMN free_trading_end_time FLOAT DEFAULT 0.0",
                "ALTER TABLE market_state ADD COLUMN casino_is_open BOOLEAN DEFAULT 0",
                "ALTER TABLE market_state ADD COLUMN casino_end_time FLOAT DEFAULT 0.0",
                "ALTER TABLE market_state ADD COLUMN casino_max_bet INTEGER DEFAULT 100000",
                "ALTER TABLE market_state ADD COLUMN sf_event_type VARCHAR",
                "ALTER TABLE market_state ADD COLUMN sf_event_end_time FLOAT DEFAULT 0.0",
                "ALTER TABLE market_state ADD COLUMN sf_event_title VARCHAR",
                "ALTER TABLE market_state ADD COLUMN sf_next_event_time FLOAT DEFAULT 0.0",
                "ALTER TABLE users ADD COLUMN last_mined_at DATETIME",
                "ALTER TABLE users ADD COLUMN total_mined FLOAT DEFAULT 0.0",
                "ALTER TABLE users ADD COLUMN total_dividends INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN debt INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN last_bankrupt_at DATETIME",
                "ALTER TABLE users ADD COLUMN pickaxe_level INTEGER DEFAULT 1",
                "ALTER TABLE users ADD COLUMN auto_mining_enabled BOOLEAN DEFAULT 0",
                "ALTER TABLE users ADD COLUMN auto_mining_end_time FLOAT DEFAULT 0.0",
                "ALTER TABLE users ADD COLUMN auto_mining_session_mined FLOAT DEFAULT 0.0",
                "ALTER TABLE users ADD COLUMN auto_mining_session_points INTEGER DEFAULT 0",
            ]:
                try:
                    conn.execute(sqlalchemy.text(col_sql))
                    conn.commit()
                except Exception:
                    pass

        state = db.query(MarketState).filter_by(id=1).first()
        if not state:
            initial_rank = 2340
            initial_price = max(100, int(initial_rank)) # 2340 (1:1 Rank Point Peg)
            state = MarketState(
                id=1,
                current_rank_point=initial_rank,
                current_price=initial_price,
                previous_price=initial_price,
                day_open_price=initial_price,
                is_trading_locked=False,
                last_settlement_delta=0,
                treasury_pool=500000.0,
                casino_max_bet=100000
            )
            db.add(state)
            db.commit()
        else:
            updated = False
            if getattr(state, "treasury_pool", None) is None or state.treasury_pool < 50000.0:
                state.treasury_pool = 500000.0
                updated = True
            if getattr(state, "day_open_price", None) is None or state.day_open_price <= 0:
                state.day_open_price = state.current_price or 2340
                updated = True
            if getattr(state, "casino_max_bet", None) is None or state.casino_max_bet < 100000:
                state.casino_max_bet = 100000
                updated = True
            if updated:
                db.commit()

        # Automatically purge legacy dummy/test users from production DB
        import sqlalchemy
        dummy_users = db.query(User).filter(
            sqlalchemy.or_(
                User.id.like("user_temp%"),
                User.id.like("fresh_%"),
                User.id.like("test_%"),
                User.id.like("dummy_%"),
                User.id.like("sim_%"),
                User.id.like("strictly_%"),
                User.id.like("u_매수%"),
                User.username.like("임시%"),
                User.username.like("유저_%"),
                User.username.like("테스터%"),
                User.username.like("더미%")
            )
        ).all()
        if dummy_users:
            for du in dummy_users:
                for dp in du.positions:
                    db.delete(dp)
                db.delete(du)
            db.commit()
    finally:
        db.close()
