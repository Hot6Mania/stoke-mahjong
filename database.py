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
        DonationRecord, UserEquipment, EquipmentListing, ItemListing,
        UserAssetHistory, ArenaMatchLog
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
                "ALTER TABLE market_state ADD COLUMN current_rank_name VARCHAR DEFAULT '작성3'",
                "ALTER TABLE market_state ADD COLUMN lottery_is_open BOOLEAN DEFAULT 0",
                "ALTER TABLE market_state ADD COLUMN lottery_end_time FLOAT DEFAULT 0.0",
                "ALTER TABLE market_state ADD COLUMN lottery_title VARCHAR DEFAULT '국가 복지 복권'",
                "ALTER TABLE market_state ADD COLUMN lottery_next_event_time FLOAT DEFAULT 0.0",
                "ALTER TABLE market_state ADD COLUMN merchant_is_open BOOLEAN DEFAULT 0",
                "ALTER TABLE market_state ADD COLUMN merchant_end_time FLOAT DEFAULT 0.0",
                "ALTER TABLE market_state ADD COLUMN merchant_name VARCHAR DEFAULT '신비상인'",
                "ALTER TABLE market_state ADD COLUMN merchant_next_time FLOAT DEFAULT 0.0",
                "ALTER TABLE market_state ADD COLUMN merchant_shield_price INTEGER DEFAULT 500000",
                "ALTER TABLE market_state ADD COLUMN merchant_shield_stock INTEGER DEFAULT 5",
                "ALTER TABLE market_state ADD COLUMN merchant_boost_price INTEGER DEFAULT 350000",
                "ALTER TABLE market_state ADD COLUMN merchant_boost_stock INTEGER DEFAULT 10",
                "ALTER TABLE market_state ADD COLUMN merchant_downgrade_price INTEGER DEFAULT 400000",
                "ALTER TABLE market_state ADD COLUMN merchant_downgrade_stock INTEGER DEFAULT 8",
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
                "ALTER TABLE users ADD COLUMN cube_count INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN cube_fragments INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN shield_scroll_count INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN boost_scroll_count INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN downgrade_scroll_count INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN snipe_scroll_count INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN arm_shield BOOLEAN DEFAULT 1",
                "ALTER TABLE users ADD COLUMN arm_boost BOOLEAN DEFAULT 0",
                "ALTER TABLE users ADD COLUMN arm_downgrade BOOLEAN DEFAULT 1",
                "ALTER TABLE users ADD COLUMN arm_snipe BOOLEAN DEFAULT 0",
                "ALTER TABLE market_state ADD COLUMN merchant_snipe_price INTEGER DEFAULT 500000",
                "ALTER TABLE market_state ADD COLUMN merchant_snipe_stock INTEGER DEFAULT 4",
                "ALTER TABLE user_equipments ADD COLUMN potential_tier VARCHAR DEFAULT 'NONE'",
                "ALTER TABLE user_equipments ADD COLUMN potential_line_1 VARCHAR",
                "ALTER TABLE user_equipments ADD COLUMN potential_line_2 VARCHAR",
                "ALTER TABLE user_equipments ADD COLUMN potential_line_3 VARCHAR",
                "ALTER TABLE user_equipments ADD COLUMN pity_count INTEGER DEFAULT 0",
                "ALTER TABLE user_equipments ADD COLUMN is_cube_locked BOOLEAN DEFAULT 0",
                "ALTER TABLE user_equipments ADD COLUMN is_line1_locked BOOLEAN DEFAULT 0",
                "ALTER TABLE user_equipments ADD COLUMN is_line2_locked BOOLEAN DEFAULT 0",
                "ALTER TABLE user_equipments ADD COLUMN is_line3_locked BOOLEAN DEFAULT 0",
                "ALTER TABLE users ADD COLUMN repay_count INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN total_repaid INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN web_pin VARCHAR",
                "ALTER TABLE users ADD COLUMN web_token VARCHAR",
                "ALTER TABLE users ADD COLUMN bank_balance INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN bank_data VARCHAR DEFAULT '{}'",
                "ALTER TABLE users ADD COLUMN special_snipe_scrolls VARCHAR DEFAULT '{}'",
                "ALTER TABLE users ADD COLUMN shield_100_scroll_count INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN downgrade_100_scroll_count INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN arm_shield_100 BOOLEAN DEFAULT 1",
                "ALTER TABLE users ADD COLUMN arm_downgrade_100 BOOLEAN DEFAULT 1",
                "ALTER TABLE market_state ADD COLUMN merchant_special_snipe_code VARCHAR",
                "ALTER TABLE market_state ADD COLUMN merchant_special_snipe_name VARCHAR",
                "ALTER TABLE market_state ADD COLUMN merchant_special_snipe_desc VARCHAR",
                "ALTER TABLE market_state ADD COLUMN merchant_special_snipe_price INTEGER DEFAULT 750000",
                "ALTER TABLE market_state ADD COLUMN merchant_special_snipe_stock INTEGER DEFAULT 0",
                "ALTER TABLE market_state ADD COLUMN merchant_shield_100_price INTEGER DEFAULT 15000000",
                "ALTER TABLE market_state ADD COLUMN merchant_shield_100_stock INTEGER DEFAULT 0",
                "ALTER TABLE market_state ADD COLUMN merchant_downgrade_100_price INTEGER DEFAULT 10000000",
                "ALTER TABLE market_state ADD COLUMN merchant_downgrade_100_stock INTEGER DEFAULT 0",
                "ALTER TABLE market_state ADD COLUMN fund_nav FLOAT DEFAULT 1000.0",
                "ALTER TABLE market_state ADD COLUMN fund_navs_json VARCHAR DEFAULT '{}'",
                "UPDATE market_state SET casino_max_bet = 10000000 WHERE casino_max_bet < 10000000",
                "UPDATE market_state SET merchant_shield_price = 500000 WHERE merchant_shield_price < 350000",
                "UPDATE market_state SET merchant_boost_price = 350000 WHERE merchant_boost_price < 250000",
                "UPDATE market_state SET merchant_downgrade_price = 400000 WHERE merchant_downgrade_price < 300000",
                "UPDATE market_state SET merchant_snipe_price = 500000 WHERE merchant_snipe_price < 350000",
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
                current_rank_name="작성3",
                current_rank_point=initial_rank,
                current_price=initial_price,
                previous_price=initial_price,
                day_open_price=initial_price,
                is_trading_locked=False,
                last_settlement_delta=0,
                treasury_pool=500000.0,
                casino_max_bet=10000000
            )
            db.add(state)
            db.commit()
        else:
            updated = False
            if not getattr(state, "current_rank_name", None):
                state.current_rank_name = "작성3"
                updated = True
            if getattr(state, "treasury_pool", None) is None or state.treasury_pool < 50000.0:
                state.treasury_pool = 500000.0
                updated = True
            if getattr(state, "day_open_price", None) is None or state.day_open_price <= 0:
                state.day_open_price = state.current_price or 2340
                updated = True
            if getattr(state, "casino_max_bet", None) is None or state.casino_max_bet < 10000000:
                state.casino_max_bet = 10000000
                updated = True
            if getattr(state, "merchant_shield_price", None) is None or state.merchant_shield_price < 350000:
                state.merchant_shield_price = 500000
                updated = True
            if getattr(state, "merchant_boost_price", None) is None or state.merchant_boost_price < 250000:
                state.merchant_boost_price = 350000
                updated = True
            if getattr(state, "merchant_downgrade_price", None) is None or state.merchant_downgrade_price < 300000:
                state.merchant_downgrade_price = 400000
                updated = True
            if getattr(state, "merchant_snipe_price", None) is None or state.merchant_snipe_price < 350000:
                state.merchant_snipe_price = 500000
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
                User.id.like("diag_%"),
                User.id.like("new_opt_%"),
                User.id.like("u_check%"),
                User.username.like("임시%"),
                User.username.like("유저_%"),
                User.username.like("테스터%"),
                User.username.like("더미%"),
                User.username.in_(["세이프가드", "신규옵션테스터", "체커"])
            )
        ).all()
        if dummy_users:
            for du in dummy_users:
                # 1. Clean up equipment listings associated with dummy seller or dummy equipments
                eq_ids = [eq.id for eq in getattr(du, "equipments", [])]
                if eq_ids:
                    db.query(EquipmentListing).filter(EquipmentListing.equipment_id.in_(eq_ids)).delete(synchronize_session=False)
                db.query(EquipmentListing).filter(EquipmentListing.seller_id == du.id).delete(synchronize_session=False)

                # 2. Clean up equipments
                for eq in list(getattr(du, "equipments", [])):
                    db.delete(eq)

                # 3. Clean up other child records
                for dp in list(du.positions):
                    db.delete(dp)
                for o in list(du.orders):
                    db.delete(o)
                for b in list(getattr(du, "bankruptcy_applications", [])):
                    db.delete(b)
                for d in list(getattr(du, "donations", [])):
                    db.delete(d)
                db.delete(du)
            db.commit()

        # Clean up any orphaned equipment or listings (if previous incomplete runs left dangling rows)
        all_user_ids = [u[0] for u in db.query(User.id).all()]
        if all_user_ids:
            orphaned_eqs = db.query(UserEquipment).filter(~UserEquipment.user_id.in_(all_user_ids)).all()
            for o_eq in orphaned_eqs:
                db.query(EquipmentListing).filter_by(equipment_id=o_eq.id).delete(synchronize_session=False)
                db.delete(o_eq)
            db.query(EquipmentListing).filter(~EquipmentListing.seller_id.in_(all_user_ids)).delete(synchronize_session=False)
            db.commit()
    finally:
        db.close()
