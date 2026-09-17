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
    from models import MarketState, User, Position, LimitOrder, BankruptcyApplication, DonationRecord
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
                "ALTER TABLE market_state ADD COLUMN casino_max_bet INTEGER DEFAULT 10000",
                "ALTER TABLE users ADD COLUMN last_mined_at DATETIME",
                "ALTER TABLE users ADD COLUMN total_mined FLOAT DEFAULT 0.0",
                "ALTER TABLE users ADD COLUMN total_dividends INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN debt INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN last_bankrupt_at DATETIME",
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
                treasury_pool=500000.0
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
            if updated:
                db.commit()
    finally:
        db.close()
