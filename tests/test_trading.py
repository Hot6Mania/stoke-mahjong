import os
import time
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base
from models import User, Position, MarketState, LimitOrder, ProductType, OrderType, OrderStatus
import trading_engine as te
import command_handler as ch

TEST_DB_URL = "sqlite:///:memory:"

@pytest.fixture
def db_session():
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()

    # Create initial market state
    state = MarketState(
        id=1,
        current_rank_point=2340,
        current_price=2340,
        previous_price=2340,
        is_trading_locked=False,
        last_settlement_delta=0
    )
    session.add(state)
    session.commit()

    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)

def test_base_stock_price_formula():
    assert te.calculate_stock_price(2340) == 2340
    assert te.calculate_stock_price(2340 + 270) == 2610
    assert te.calculate_stock_price(2340 - 330) == 2010
    assert te.calculate_stock_price(-2000) == 100 # min floor 100

def test_buy_and_sell(db_session):
    user_id = "user_123"
    username = "마작왕"

    # 1. Buy 10 shares of 2X (2340 * 10 = 23,400P, 1% fee = 234P)
    ok, msg, details = te.execute_buy(db_session, user_id, username, "2X", "10")
    assert ok is True
    assert details["quantity"] == 10.0
    assert details["price"] == 2340
    assert details["cost"] == 23400
    assert details["fee"] == 234
    assert details["total_cost"] == 23634
    assert details["remaining_points"] == 50000 - 23634

    user = db_session.query(User).filter_by(id=user_id).first()
    assert user.points == 26366
    pos = db_session.query(Position).filter_by(user_id=user_id, product_type=ProductType.TWO_X).first()
    assert pos.quantity == 10.0
    assert pos.entry_price == 2340.0
    assert pos.invested_cash == 23400.0

    # 2. Sell 5 shares (gross 2340 * 5 = 11,700P, 1% fee = 117P, net = 11,583P)
    ok, msg, details = te.execute_sell(db_session, user_id, username, "2X", "5")
    assert ok is True
    assert details["quantity"] == 5.0
    assert details["fee"] == 117
    assert details["payout"] == 11583
    assert user.points == 26366 + 11583
    assert pos.quantity == 5.0

    # 3. Sell remaining with '전량' (gross 11,700P, fee 117P, net 11,583P)
    ok, msg, details = te.execute_sell(db_session, user_id, username, "2X", "전량")
    assert ok is True
    assert pos.quantity == 0.0
    assert user.points == 26366 + 11583 + 11583

def test_buy_allin(db_session):
    user_id = "user_allin"
    username = "올인러"
    ok, msg, details = te.execute_buy(db_session, user_id, username, "1X", "올인")
    assert ok is True
    user = db_session.query(User).filter_by(id=user_id).first()
    # 50000 // (2340 * 1.01 = 2363.4) = 21 shares, cost = 21 * 2340 = 49140, fee = 491
    assert details["quantity"] == 21
    assert details["fee"] == 491
    assert user.points == 50000 - (49140 + 491)

def test_trading_fee_funds_treasury(db_session):
    state = te.get_market_state(db_session)
    treasury_before = state.treasury_pool

    # Buy trade generates fee
    ok, _, details_buy = te.execute_buy(db_session, "fee_user", "수수료러", "1X", "10")
    assert ok is True
    fee_buy = details_buy["fee"]
    assert fee_buy == 234
    assert state.treasury_pool == treasury_before + fee_buy

    # Sell trade generates fee
    ok, _, details_sell = te.execute_sell(db_session, "fee_user", "수수료러", "1X", "10")
    assert ok is True
    fee_sell = details_sell["fee"]
    assert fee_sell == 234
    assert state.treasury_pool == treasury_before + fee_buy + fee_sell

def test_market_locked_rejection(db_session):
    state = te.get_market_state(db_session)
    state.is_trading_locked = True
    db_session.commit()

    ok, msg, _ = te.execute_buy(db_session, "u1", "테스터", "1X", "5")
    assert ok is False
    assert "거래 마감" in msg

    ok, msg, _ = te.execute_sell(db_session, "u1", "테스터", "1X", "5")
    assert ok is False
    assert "거래 마감" in msg

    ok, msg, _ = te.execute_liquidate(db_session, "u1", "테스터", "전량")
    assert ok is False
    assert "거래 마감" in msg

def test_settlement_and_leverage(db_session):
    u1 = "bull_user"
    u2 = "inv_user"
    te.execute_buy(db_session, u1, "불베어", "2X", "10") # 23,400P invested at 2340
    te.execute_buy(db_session, u2, "인버스장인", "INV", "10") # 23,400P invested at 2340

    # Streamer wins 1st place (+270pt)
    # Old price: 2340, new rank: 2610, new price: 2610 (+11.54%)
    settle_res = te.settle_match(db_session, rank=1, point_delta=270)
    assert settle_res["old_price"] == 2340
    assert settle_res["new_price"] == 2610
    assert settle_res["is_trading_locked"] is False

    # Check bull position gained ~23.08%
    p1 = db_session.query(Position).filter_by(user_id=u1).first()
    v1 = te.calculate_position_valuation(p1, settle_res["new_price"])
    assert v1["current_value"] > 23400 # Value increased
    assert p1.entry_price == 2340.0 # Entry price preserved!
    assert v1["unrealized_pnl"] > 0

    # Check inverse position lost ~11.54%
    p2 = db_session.query(Position).filter_by(user_id=u2).first()
    v2 = te.calculate_position_valuation(p2, settle_res["new_price"])
    assert v2["current_value"] < 23400 # Value decreased
    assert p2.entry_price == 2340.0 # Entry price preserved!
    assert v2["unrealized_pnl"] < 0

def test_margin_call_liquidation(db_session):
    # Buy 2X position
    u = "gambler"
    te.execute_buy(db_session, u, "갬블러", "2X", "10") # entry: 2340

    # Catastrophic drop: rank drops by -1800 points
    # new rank: 540, new price: 540 (price drops by ~76.9%)
    # For 2X, drop is 2x * -76.9% = -153.8% <= -100% -> LIQUIDATION!
    settle_res = te.settle_match(db_session, rank=3, point_delta=-1800)
    assert len(settle_res["liquidations"]) == 1
    liq = settle_res["liquidations"][0]
    assert liq["user_id"] == u
    assert liq["product_type"] == "2X"

    p = db_session.query(Position).filter_by(user_id=u).first()
    assert p.quantity == 0.0
    assert p.invested_cash == 0.0

def test_command_handler_help(db_session):
    reply, event = ch.handle_chat_command(db_session, "u1", "테스터", "!주식명령어")
    assert reply is not None
    assert "📈 [마작 주식 명령어 안내]" in reply
    assert "!매수 [종목] [수량/올인]" in reply
    assert "1X, 2X, 3X, 5X, 10X (레버리지)" in reply

    reply2, _ = ch.handle_chat_command(db_session, "u1", "테스터", "!주식도움말")
    assert reply2 == reply

def test_command_handler_inline_guides(db_session):
    reply, _ = ch.handle_chat_command(db_session, "u1", "테스터", "!매수")
    assert "💡 매수 사용법:" in reply

    reply, _ = ch.handle_chat_command(db_session, "u1", "테스터", "!매도")
    assert "💡 매도 사용법:" in reply

    reply, _ = ch.handle_chat_command(db_session, "u1", "테스터", "!지정가")
    assert "💡 지정가 사용법:" in reply

    reply, _ = ch.handle_chat_command(db_session, "u1", "테스터", "!청산")
    assert "💡 청산 사용법:" in reply

def test_command_handler_orders(db_session):
    reply, evt = ch.handle_chat_command(db_session, "u1", "테스터", "!매수 2X 5")
    assert "✅ [매수 체결]" in reply

    reply, _ = ch.handle_chat_command(db_session, "u1", "테스터", "!내정보")
    assert "2X: 5주" in reply

    reply, evt = ch.handle_chat_command(db_session, "u1", "테스터", "!청산 전량")
    assert "⚡ [전량 청산 완료]" in reply

def test_mining_and_cooldown(db_session):
    u = "miner_1"
    ok, msg, details = te.execute_mining(db_session, u, "채굴자")
    assert ok is True
    assert "채굴 완료" in msg
    assert details["shares_awarded"] > 0

    # Check user received 1X shares
    pos = db_session.query(Position).filter_by(user_id=u, product_type=ProductType.ONE_X).first()
    assert pos is not None
    assert pos.quantity == details["shares_awarded"]

    # Try mining again immediately (should fail with cooldown)
    ok2, msg2, details2 = te.execute_mining(db_session, u, "채굴자")
    assert ok2 is False
    assert "채굴 쿨타임" in msg2

def test_victory_dividend_and_treasury(db_session):
    u = "investor"
    te.execute_buy(db_session, u, "가치투자자", "1X", "10") # 10 shares of 1X

    user_before = db_session.query(User).filter_by(id=u).first()
    points_before = user_before.points

    # Streamer wins 1st place
    settle_res = te.settle_match(db_session, rank=1, point_delta=270)
    assert len(settle_res["dividends"]) >= 1

    # User points should have increased by 5% dividend
    user_after = db_session.query(User).filter_by(id=u).first()
    assert user_after.points > points_before
    assert user_after.total_dividends > 0

def test_command_handler_mining_and_treasury(db_session):
    reply, evt = ch.handle_chat_command(db_session, "u_mine", "마이너", "!채굴")
    assert "채굴 완료" in reply

    reply_treasury, _ = ch.handle_chat_command(db_session, "u_mine", "마이너", "!국고")
    assert "마작 국고 현황" in reply_treasury

    reply_dividend, _ = ch.handle_chat_command(db_session, "u_mine", "마이너", "!배당")
    assert "승리 배당 안내" in reply_dividend

def test_3x_and_10x_trading_and_liquidation(db_session):
    u = "degen_trader"
    # Buy 10X shares
    ok, msg, details = te.execute_buy(db_session, u, "야수", "10X", "5")
    assert ok is True
    assert details["product_type"] == "10X"

    # Buy 5X shares
    ok5, msg5, details5 = te.execute_buy(db_session, u, "야수", "5X", "5")
    assert ok5 is True
    assert details5["product_type"] == "5X"

    # Buy 3X shares
    ok3, msg3, details3 = te.execute_buy(db_session, u, "야수", "3X", "5")
    assert ok3 is True
    assert details3["product_type"] == "3X"

    # Price drops by 10% (current_price 2340 -> drops ~240pt)
    settle_res = te.settle_match(db_session, rank=4, point_delta=-240)
    # 10X position: -10% * 10 = -100% loss -> Liquidated!
    liq_types = [l["product_type"] for l in settle_res["liquidations"]]
    assert "10X" in liq_types

    # 5X position: -10% * 5 = -50% loss -> NOT liquidated
    assert "5X" not in liq_types
    # 3X position: -10% * 3 = -30% loss -> NOT liquidated
    assert "3X" not in liq_types

def test_margin_loan_borrow_repay(db_session):
    u = "borrower_1"
    # 1. Borrow 30,000P
    ok, msg, details = te.execute_borrow(db_session, u, "빚쟁이", "30000")
    assert ok is True
    assert details["total_debt"] == 30000
    assert details["cash"] == 50000 + 30000

    user = db_session.query(User).filter_by(id=u).first()
    assert user.debt == 30000
    assert user.points == 80000

    # 2. Try to borrow 30,000 more (exceeds 50,000 limit) -> rejected
    ok2, msg2, details2 = te.execute_borrow(db_session, u, "빚쟁이", "30000")
    assert ok2 is False
    assert "최대 대출 한도" in msg2

    # 3. Repay 10,000P
    ok3, msg3, details3 = te.execute_repay(db_session, u, "빚쟁이", "10000")
    assert ok3 is True
    assert details3["remaining_debt"] == 20000
    assert user.debt == 20000

    # 4. Repay full remaining amount
    ok4, msg4, details4 = te.execute_repay(db_session, u, "빚쟁이", "전액")
    assert ok4 is True
    assert details4["remaining_debt"] == 0
    assert user.debt == 0
    assert "자유의 몸" in msg4

def test_loan_interest_and_forced_labor_mining(db_session):
    u = "debtor_labor"
    # Borrow 20,000P
    te.execute_borrow(db_session, u, "노역자", "20000")
    user = db_session.query(User).filter_by(id=u).first()
    assert user.debt == 20000
    points_before = user.points

    # Match settlement charges 2% interest (20,000 * 0.02 = 400P)
    settle_res = te.settle_match(db_session, rank=3, point_delta=0)
    assert settle_res["interest_collected"] == 400
    assert user.points == points_before - 400

    # Forced labor mining: reward goes directly to paying off debt
    ok_mine, msg_mine, det_mine = te.execute_mining(db_session, u, "노역자")
    assert ok_mine is True
    assert det_mine.get("is_forced_labor") is True
    assert det_mine["repaid_debt"] > 0
    assert user.debt < 20000
    # Forced labor should NOT increment total_mined since shares are seized for debt
    assert (getattr(user, "total_mined", 0.0) or 0.0) == 0.0

def test_bankruptcy_and_rehabilitation(db_session):
    u = "bankrupt_user"
    # Borrow 50,000P
    te.execute_borrow(db_session, u, "파산자", "50000")
    user = db_session.query(User).filter_by(id=u).first()
    # Buy 10X all-in
    te.execute_buy(db_session, u, "파산자", "10X", "올인")

    # Match drops 10% -> 10X liquidated -> cash 0, positions 0, debt >= 50,000 (including interest)
    te.settle_match(db_session, rank=4, point_delta=-240)
    assert user.debt >= 50000

    # 1. Submit bankruptcy application to court
    ok, msg, details = te.submit_bankruptcy_application(db_session, u, "파산자", "10X 몰빵하다 망했습니다 살려주세요")
    assert ok is True
    assert "법정에 접수되었습니다" in msg
    assert details["reason"] == "10X 몰빵하다 망했습니다 살려주세요"

    # Duplicate pending check
    ok2, msg2, _ = te.submit_bankruptcy_application(db_session, u, "파산자", "또 신청")
    assert ok2 is False
    assert "이미 접수되어" in msg2

    # Verify pending list
    pending = te.get_pending_bankruptcy_applications(db_session)
    assert len(pending) == 1
    app_id = pending[0]["id"]
    assert pending[0]["username"] == "파산자"

    # 2. Judge delivers verdict: 'full' (전액 탕감 인가)
    j_ok, j_msg, j_details = te.judge_bankruptcy_application(db_session, app_id, "full", "다음부턴 10X 타지 마라")
    assert j_ok is True
    assert "회생을 인가했습니다" in j_msg
    assert user.debt == 0
    assert user.points == 10000  # Basic survival fund
    assert j_details["comment"] == "다음부턴 10X 타지 마라"

def test_bankruptcy_court_half_and_reject(db_session):
    # Test half (50% workout)
    u_half = "half_user"
    te.execute_borrow(db_session, u_half, "반토막", "40000")
    user_half = db_session.query(User).filter_by(id=u_half).first()
    user_half.points = 0  # insolvent

    ok, _, _ = te.submit_bankruptcy_application(db_session, u_half, "반토막", "살려주세요")
    assert ok is True
    pending = te.get_pending_bankruptcy_applications(db_session)
    app_id = pending[0]["id"]

    j_ok, j_msg, j_details = te.judge_bankruptcy_application(db_session, app_id, "half", "절반만 깎아준다")
    assert j_ok is True
    assert "조건부 워크아웃" in j_msg
    assert user_half.debt == 20000  # 40,000 -> 20,000

    # Test reject (forced labor)
    u_rej = "reject_user"
    te.execute_borrow(db_session, u_rej, "기각자", "30000")
    user_rej = db_session.query(User).filter_by(id=u_rej).first()
    user_rej.points = 0

    ok_rej, _, _ = te.submit_bankruptcy_application(db_session, u_rej, "기각자", "망했어요")
    assert ok_rej is True
    pending_rej = te.get_pending_bankruptcy_applications(db_session)
    app_id_rej = pending_rej[0]["id"]

    j_ok_rej, j_msg_rej, _ = te.judge_bankruptcy_application(db_session, app_id_rej, "reject", "탄광으로 가라")
    assert j_ok_rej is True
    assert "파산 신청을 기각했습니다" in j_msg_rej
    assert user_rej.debt == 30000  # debt preserved!

def test_chat_commands_for_loans(db_session):
    u = "chat_borrower"
    # Borrow command via chat
    reply, evt = ch.handle_chat_command(db_session, u, "채팅차용자", "!대출 20000")
    assert "대출 실행 완료" in reply
    assert evt["type"] == "loan_borrow"

    # Info shows debt
    reply_info, _ = ch.handle_chat_command(db_session, u, "채팅차용자", "!내정보")
    assert "빚(대출): 20,000P" in reply_info

    # Repay command via chat
    reply_repay, evt_repay = ch.handle_chat_command(db_session, u, "채팅차용자", "!상환 10000")
    assert "상환 완료" in reply_repay
    assert evt_repay["type"] == "loan_repay"

def test_margin_buy_and_rehabilitation_commands(db_session):
    u = "margin_trader"
    user = te.get_or_create_user(db_session, u, "빚올인러")
    user.points = 0  # 0 cash, but 50,000P credit available
    db_session.commit()

    # 1. Normal buy all-in with 0 points suggests 빚올인
    reply_fail, _ = ch.handle_chat_command(db_session, u, "빚올인러", "!매수 10X 올인")
    assert "보유 포인트가 부족하여" in reply_fail
    assert "빚(국고 대출)으로 올인하시려면" in reply_fail
    assert "!매수 10X 빚올인" in reply_fail

    # 2. Test !매수 10X 빚올인
    reply_buy, evt_buy = ch.handle_chat_command(db_session, u, "빚올인러", "!매수 10X 빚올인")
    assert "빚투 / 신용 올인 체결" in reply_buy
    assert evt_buy is not None
    assert evt_buy["type"] == "trade_buy"
    assert user.debt == 50000
    pos = db_session.query(Position).filter_by(user_id=u).first()
    assert pos is not None
    assert pos.quantity > 0

    # 3. Another user tests !빚올인 1X directly
    u2 = "margin_trader_2"
    reply2, evt2 = ch.handle_chat_command(db_session, u2, "직접빚올인", "!빚올인 1X")
    assert "빚투 / 신용 올인 체결" in reply2
    assert evt2["type"] == "trade_buy"

    # 4. Another user tests !대출 10X 올인
    u3 = "margin_trader_3"
    reply3, evt3 = ch.handle_chat_command(db_session, u3, "대출매수러", "!대출 10X 올인")
    assert "빚투 / 신용 올인 체결" in reply3
    assert evt3["type"] == "trade_buy"

    # 5. Test !회생신청 alias
    u_broke = "broke_debtor"
    user_b = te.get_or_create_user(db_session, u_broke, "회생신청자")
    user_b.debt = 50000
    user_b.points = 0
    db_session.commit()

    reply_rehab, evt_rehab = ch.handle_chat_command(db_session, u_broke, "회생신청자", "!회생신청 살려주세요")
    assert "법정에 접수되었습니다" in reply_rehab
    assert evt_rehab["type"] == "bankruptcy_requested"

def test_buy_and_sell_korean_aliases(db_session):
    u = "buyer_user_1"
    user = te.get_or_create_user(db_session, u, "구매자")
    user.points = 100000
    db_session.commit()

    # 1. Test !구매 10X 2
    reply_buy, evt_buy = ch.handle_chat_command(db_session, u, "구매자", "!구매 10X 2")
    assert "구매했습니다" in reply_buy
    assert "구매 완료" in reply_buy
    assert evt_buy is not None
    assert evt_buy["type"] == "trade_buy"
    assert evt_buy["data"]["quantity"] == 2.0

    # 2. Test !구매 10X (default quantity 1)
    reply_buy2, evt_buy2 = ch.handle_chat_command(db_session, u, "구매자", "!구매 10X")
    assert "구매했습니다" in reply_buy2
    assert evt_buy2["data"]["quantity"] == 1.0

    # 3. Test !판매 10X 1
    reply_sell, evt_sell = ch.handle_chat_command(db_session, u, "구매자", "!판매 10X 1")
    assert "판매했습니다" in reply_sell
    assert "판매 완료" in reply_sell
    assert evt_sell is not None
    assert evt_sell["type"] == "trade_sell"

    # 4. Test !판매 10X (default quantity 전량)
    reply_sell2, evt_sell2 = ch.handle_chat_command(db_session, u, "구매자", "!판매 10X")
    assert "판매했습니다" in reply_sell2
    assert evt_sell2["data"]["quantity"] == 2.0

def test_donation_charging_one_to_hundred(db_session):
    # 1. 1,000 KRW donation -> 100,000 Points (1:100)
    d_payload = {
        "donationType": "CHAT",
        "channelId": "chan_test",
        "donatorChannelId": "donor_001",
        "donatorNickname": "큰손나베팬",
        "payAmount": "1000",
        "donationText": "1,000원 쏩니다!",
        "messageTime": "12345678"
    }
    success, reply, details = te.validate_and_process_donation(db_session, d_payload)
    assert success is True
    assert "100,000P 충전 완료" in reply
    assert details["points_credited"] == 100000
    assert details["pay_amount"] == 1000

    user = te.get_or_create_user(db_session, "donor_001", "큰손나베팬")
    # Starting points (10000) + 100,000 = 110,000P
    assert user.points >= 100000

    # 2. Idempotency test (Same donation cannot be credited twice)
    dup_success, dup_reply, _ = te.validate_and_process_donation(db_session, d_payload)
    assert dup_success is False
    assert "이미 충전 처리된 후원" in dup_reply

    # 3. Another donation: 5,000 KRW -> 500,000 Points
    d_payload2 = {
        "donationType": "VIDEO",
        "channelId": "chan_test",
        "donatorChannelId": "donor_001",
        "donatorNickname": "큰손나베팬",
        "payAmount": 5000,
        "donationText": "영도 5천원!",
        "messageTime": "87654321"
    }
    s2, r2, d2 = te.validate_and_process_donation(db_session, d_payload2)
    assert s2 is True
    assert d2["points_credited"] == 500000
    assert user.points >= 600000

    # 4. Check donation history
    hist = te.get_donation_history(db_session, limit=10)
    assert len(hist) >= 2
    assert hist[0]["pay_amount"] == 5000
    assert hist[0]["points_credited"] == 500000

    # 5. Invalid amount validation
    invalid_payload = {
        "payAmount": "-500",
        "donatorNickname": "나쁜유저"
    }
    s_inv, r_inv, _ = te.validate_and_process_donation(db_session, invalid_payload)
    assert s_inv is False
    assert "0원보다 커야 합니다" in r_inv

def test_db_backup_and_integrity(db_session):
    import db_backup
    # 1. Verify DB integrity
    res = db_backup.verify_db_integrity()
    assert res["is_healthy"] is True
    assert res["file_size_bytes"] > 0
    assert "users" in res["table_counts"]

    # 2. Create manual backup
    ok, msg, b_path = db_backup.create_backup(reason="test_unit")
    assert ok is True
    assert b_path is not None

    # 3. List backups
    backups = db_backup.list_backups()
    assert len(backups) > 0
    assert any("test_unit" in b["filename"] for b in backups)

def test_allin_command_variations(db_session):
    """Test all all-in command variations producing buy confirmations."""
    # Ensure market is unlocked
    state = te.get_market_state(db_session)
    state.is_trading_locked = False
    db_session.commit()

    allin_cmds = [
        ("!올인 1X", ProductType.ONE_X),
        ("!올인", ProductType.ONE_X),
        ("!올인 10X", ProductType.TEN_X),
        ("!매수 올인 1X", ProductType.ONE_X),
        ("!구매 올인 1X", ProductType.ONE_X),
        ("!매수 1X 올인", ProductType.ONE_X),
        ("!구매 1X 올인", ProductType.ONE_X),
        ("!매수올인 1X", ProductType.ONE_X),
        ("!구매올인 1X", ProductType.ONE_X),
        ("!풀매수 1X", ProductType.ONE_X),
        ("!allin 1X", ProductType.ONE_X),
        ("!전액매수 1X", ProductType.ONE_X),
        ("!매수 올인", ProductType.ONE_X),
        ("!구매 올인", ProductType.ONE_X),
    ]

    for i, (cmd_text, expected_pt) in enumerate(allin_cmds):
        uid = f"allin_user_{i}"
        uname = f"올인러_{i}"
        reply, event = ch.handle_chat_command(db_session, uid, uname, cmd_text)
        assert reply is not None, f"Failed on {cmd_text}: reply is None"
        assert "매수 체결" in reply or "구매 완료" in reply, f"Failed on {cmd_text}: {reply}"
        assert f"{uname}님이" in reply
        assert event is not None, f"Failed on {cmd_text}: event is None"
        assert event["type"] == "trade_buy"
        assert event["data"]["product_type"] == expected_pt.value
        assert event["data"]["quantity"] > 0

def test_locked_market_allin_strictly_rejected(db_session):
    """Verify all-in and trade commands strictly reject and mutate 0 points/shares when locked."""
    state = te.get_market_state(db_session)
    state.is_trading_locked = True
    db_session.commit()

    allin_cmds = [
        "!올인",
        "!올인 1X",
        "!올인 10X",
        "!allin",
        "!allin 1X",
        "!풀매수",
        "!전액매수 1X",
        "!매수 1X 올인",
        "!구매 1X 올인",
        "!매수올인 1X",
        "!구매올인 1X",
        "!매수 올인 1X",
        "!구매 올인 1X",
        "!빚올인 1X",
        "!매수 1X 빚올인",
        "!대출 1X 올인",
        "!매도 1X 1",
        "!청산 전량"
    ]

    uid = "strictly_locked_tester"
    uname = "철통잠금테스터"
    user = te.get_or_create_user(db_session, uid, uname)
    init_pts = user.points
    init_debt = user.debt

    for cmd_text in allin_cmds:
        reply, event = ch.handle_chat_command(db_session, uid, uname, cmd_text)
        assert reply is not None, f"Expected rejection reply for '{cmd_text}', got None"
        assert "거래 마감" in reply, f"Expected '거래 마감' in rejection for '{cmd_text}', got: {reply}"
        assert event is None, f"Expected None event for '{cmd_text}', got: {event}"

        # Verify no cash or positions or debt changed
        db_session.refresh(user)
        assert user.points == init_pts, f"Points changed during '{cmd_text}': {user.points} vs {init_pts}"
        assert user.debt == init_debt, f"Debt changed during '{cmd_text}': {user.debt} vs {init_debt}"

        positions = db_session.query(Position).filter_by(user_id=uid).all()
        active_pos = [p for p in positions if p.quantity > 0]
        assert len(active_pos) == 0, f"Position created during '{cmd_text}'"

    # Query commands should still work when locked
    info_reply, _ = ch.handle_chat_command(db_session, uid, uname, "!내정보")
    assert info_reply is not None
    assert uname in info_reply

    stock_reply, _ = ch.handle_chat_command(db_session, uid, uname, "!주식")
    assert stock_reply is not None
    assert "시세" in stock_reply

def test_expired_free_trading_auto_lock(db_session):
    """Verify expired free trading window automatically locks market and rejects all-in."""
    import time
    state = te.get_market_state(db_session)
    state.is_trading_locked = False
    # Set expired end time (5 seconds in the past)
    state.free_trading_end_time = time.time() - 5.0
    db_session.commit()

    uid = "expired_timer_user"
    uname = "타이머만료유저"
    user = te.get_or_create_user(db_session, uid, uname)
    init_pts = user.points

    reply, event = ch.handle_chat_command(db_session, uid, uname, "!올인 1X")
    assert reply is not None
    assert "거래 마감" in reply
    assert event is None

    # Verify market state is now locked in DB
    db_session.refresh(state)
    assert state.is_trading_locked is True

    # Verify no points or shares were bought
    db_session.refresh(user)
    assert user.points == init_pts
    pos = db_session.query(Position).filter_by(user_id=uid).first()
    assert pos is None or pos.quantity == 0

def test_leaderboard_dummy_filtering(db_session):
    """Ensure dummy/tester users are strictly excluded from leaderboard rankings."""
    te.get_or_create_user(db_session, "fresh_uid_2", "유저_2")
    te.get_or_create_user(db_session, "test_user_dummy", "테스터")
    te.get_or_create_user(db_session, "user_temp_123", "임시유저")
    te.get_or_create_user(db_session, "real_user_999", "진짜주주")

    # Give them points/positions
    ok, _, _ = te.execute_buy(db_session, "fresh_uid_2", "유저_2", "10X", "5")
    assert ok is True
    ok, _, _ = te.execute_buy(db_session, "test_user_dummy", "테스터", "10X", "5")
    assert ok is True
    ok, _, _ = te.execute_buy(db_session, "user_temp_123", "임시유저", "10X", "5")
    assert ok is True
    ok, _, _ = te.execute_buy(db_session, "real_user_999", "진짜주주", "1X", "5")
    assert ok is True

    leaderboard = te.get_leaderboard(db_session, top_n=10)
    usernames = [r["username"] for r in leaderboard]

    assert "유저_2" not in usernames
    assert "테스터" not in usernames
    assert "임시유저" not in usernames
    assert "진짜주주" in usernames

def test_full_buy_command_and_mention_syntax(db_session):
    """Verify !풀매수 10X, mention syntax, numeric product shorthand, and chat reply generation."""
    state = te.get_market_state(db_session)
    state.is_trading_locked = False
    state.free_trading_end_time = 0.0
    db_session.commit()

    uid = "ppatrol_test"
    uname = "ppatrol"

    # 1. Standard !풀매수 10X
    reply, event = ch.handle_chat_command(db_session, uid, uname, "!풀매수 10X")
    assert reply is not None
    assert "✅ [매수 체결] [구매 완료]" in reply
    assert "10X" in reply
    assert event is not None
    assert event["type"] == "trade_buy"

    # 2. Mention syntax: "ppatrol !풀매수 10X"
    uid2 = "ppatrol_test2"
    uname2 = "ppatrol2"
    reply2, event2 = ch.handle_chat_command(db_session, uid2, uname2, "ppatrol !풀매수 10X")
    assert reply2 is not None
    assert "✅ [매수 체결] [구매 완료]" in reply2
    assert "10X" in reply2

    # 3. Numeric shorthand: "!풀매수 10"
    uid3 = "ppatrol_test3"
    uname3 = "ppatrol3"
    reply3, event3 = ch.handle_chat_command(db_session, uid3, uname3, "!풀매수 10")
    assert reply3 is not None
    assert "✅ [매수 체결] [구매 완료]" in reply3
    assert "10X" in reply3

    # 4. Direct product command: "!10X 올인"
    uid4 = "ppatrol_test4"
    uname4 = "ppatrol4"
    reply4, event4 = ch.handle_chat_command(db_session, uid4, uname4, "!10X 올인")
    assert reply4 is not None
    assert "✅ [매수 체결] [구매 완료]" in reply4
    assert "10X" in reply4

def test_mining_and_holding_unification(db_session):
    """Verify mined shares are unified into '보유' and '채굴:' is no longer separated in !내정보."""
    state = te.get_market_state(db_session)
    state.is_trading_locked = False
    state.free_trading_end_time = 0.0
    db_session.commit()

    uid = "miner_unify_user"
    uname = "채굴주주"

    # Execute mining
    reply, event = ch.handle_chat_command(db_session, uid, uname, "!채굴")
    assert reply is not None
    assert "⛏️ [채굴 완료]" in reply
    assert "1X 보유에 합산되었습니다" in reply

    # Query !내정보
    info_reply, _ = ch.handle_chat_command(db_session, uid, uname, "!내정보")
    assert info_reply is not None
    # Crucial: "채굴: 1X" should NOT be separated
    assert "채굴: 1X" not in info_reply
    # Mined 1X shares should be listed under "보유:"
    assert "보유: [1X:" in info_reply

def test_mining_available_when_market_locked(db_session):
    """Verify !채굴 succeeds even when market is locked (is_trading_locked == True)."""
    state = te.get_market_state(db_session)
    state.is_trading_locked = True
    state.free_trading_end_time = 0.0
    db_session.commit()

    uid = "locked_market_miner"
    uname = "탄광노동자"

    # Buy should be rejected because locked
    buy_reply, _ = ch.handle_chat_command(db_session, uid, uname, "!매수 1X 1")
    assert "거래 마감" in buy_reply

    # Mining should SUCCEED even when locked
    mine_reply, event = ch.handle_chat_command(db_session, uid, uname, "!채굴")
    assert mine_reply is not None
    assert "거래 마감" not in mine_reply
    assert "⛏️ [채굴 완료]" in mine_reply
    assert "1X 보유에 합산되었습니다" in mine_reply
    assert event is not None
    assert event["type"] == "mining"

    # Verify 1X position was granted
    user = db_session.query(User).filter_by(id=uid).first()
    pos = db_session.query(Position).filter_by(user_id=uid, product_type=ProductType.ONE_X).first()
    assert pos is not None
    assert pos.quantity > 0

def test_product_quote_stripping_and_10x_5x_trading(db_session):
    """Verify 10X, 5X, quoted symbols ('10X'', '5X'), numeric shorthand, and error messages."""
    state = te.get_market_state(db_session)
    state.is_trading_locked = False
    state.free_trading_end_time = 0.0
    db_session.commit()

    # 1. Product parser tests
    assert te.parse_product_type("10X") == ProductType.TEN_X
    assert te.parse_product_type("10x") == ProductType.TEN_X
    assert te.parse_product_type("10X'") == ProductType.TEN_X
    assert te.parse_product_type("'10X'") == ProductType.TEN_X
    assert te.parse_product_type("5X") == ProductType.FIVE_X
    assert te.parse_product_type("5x") == ProductType.FIVE_X
    assert te.parse_product_type("5X'") == ProductType.FIVE_X
    assert te.parse_product_type("10") is None  # Pure numbers represent quantities, not products
    assert te.parse_product_type("5") is None
    assert te.parse_product_type("5배") == ProductType.FIVE_X
    assert te.parse_product_type("10배") == ProductType.TEN_X
    assert te.parse_product_type("10레") == ProductType.TEN_X
    assert te.parse_product_type("10버") == ProductType.TEN_X
    assert te.parse_product_type("10롱") == ProductType.TEN_X
    assert te.parse_product_type("10레버") == ProductType.TEN_X
    assert te.parse_product_type("5레") == ProductType.FIVE_X
    assert te.parse_product_type("5버") == ProductType.FIVE_X
    assert te.parse_product_type("5롱") == ProductType.FIVE_X
    assert te.parse_product_type("10X_INV") == ProductType.TEN_X_INV
    assert te.parse_product_type("10숏") == ProductType.TEN_X_INV
    assert te.parse_product_type("10인") == ProductType.TEN_X_INV
    assert te.parse_product_type("10곱") == ProductType.TEN_X_INV
    assert te.parse_product_type("5X_INV") == ProductType.FIVE_X_INV
    assert te.parse_product_type("5숏") == ProductType.FIVE_X_INV
    assert te.parse_product_type("5인") == ProductType.FIVE_X_INV
    assert te.parse_product_type("곱버스") == ProductType.TWO_X_INV
    assert te.parse_product_type("2숏") == ProductType.TWO_X_INV
    assert te.parse_product_type("숏") == ProductType.INV
    assert te.parse_product_type("인버스") == ProductType.INV

    # 2. Buy commands with quotes and typos
    uid = "user_10x_5x"
    uname = "레버리지주주"

    # Buy 10X with trailing quote
    r1, ev1 = ch.handle_chat_command(db_session, uid, uname, "!매수 10X' 1")
    assert r1 is not None
    assert "✅ [매수 체결] [구매 완료]" in r1
    assert "10X" in r1

    # Buy 5X with surrounding quotes
    r2, ev2 = ch.handle_chat_command(db_session, uid, uname, "!매수 '5X' 1")
    assert r2 is not None
    assert "✅ [매수 체결] [구매 완료]" in r2
    assert "5X" in r2

    # Direct 5X allin
    r3, ev3 = ch.handle_chat_command(db_session, uid, uname, "!5X 올인")
    assert r3 is not None
    assert "✅ [매수 체결] [구매 완료]" in r3
    assert "5X" in r3

    # Reset balance for next tests
    user = te.get_or_create_user(db_session, uid, uname)
    user.points = 50000
    db_session.commit()

    # Buy with 10레 shorthand
    r_le, ev_le = ch.handle_chat_command(db_session, uid, uname, "!매수 10레 1")
    assert r_le is not None
    assert "✅ [매수 체결] [구매 완료]" in r_le
    assert "10X" in r_le

    # Direct buy with !10버 1
    r_beo, ev_beo = ch.handle_chat_command(db_session, uid, uname, "!10버 1")
    assert r_beo is not None
    assert "✅ [매수 체결] [구매 완료]" in r_beo
    assert "10X" in r_beo

    # Buy with 10롱 shorthand
    r_long, ev_long = ch.handle_chat_command(db_session, uid, uname, "!매수 10롱 1")
    assert r_long is not None
    assert "✅ [매수 체결] [구매 완료]" in r_long
    assert "10X" in r_long

    # Buy with 10배 shorthand with units ("2주")
    r_bae, ev_bae = ch.handle_chat_command(db_session, uid, uname, "!10배 2주")
    assert r_bae is not None
    assert "✅ [매수 체결] [구매 완료]" in r_bae
    assert "10X" in r_bae

    # Direct sell with 10배 전량
    r_sell_bae, ev_sell_bae = ch.handle_chat_command(db_session, uid, uname, "!10배 전량")
    assert r_sell_bae is not None
    assert "✅ [매도 체결 / 판매 완료]" in r_sell_bae
    assert ev_sell_bae["type"] == "trade_sell"

    # Attached form without space: !10배올인
    user.points = 50000
    db_session.commit()
    r_att, ev_att = ch.handle_chat_command(db_session, uid, uname, "!10배올인")
    assert r_att is not None
    assert "✅ [매수 체결] [구매 완료]" in r_att
    assert "10X" in r_att

    # Accidental space after ! and full-width: ! 10배 전량
    r_sp, ev_sp = ch.handle_chat_command(db_session, uid, uname, "! 10배 전량")
    assert r_sp is not None
    assert "✅ [매도 체결 / 판매 완료]" in r_sp

    # Full-width Unicode: ！１０배　올인
    user.points = 50000
    db_session.commit()
    r_uni, ev_uni = ch.handle_chat_command(db_session, uid, uname, "！１０배　올인")
    assert r_uni is not None
    assert "✅ [매수 체결] [구매 완료]" in r_uni

    # Sell 10X
    r4, ev4 = ch.handle_chat_command(db_session, uid, uname, "!매도 10X 1")
    assert r4 is not None
    assert "✅ [매도 체결 / 판매 완료]" in r4

    # Direct shorthand !10 1 with fresh user
    uid2 = "user_shorthand"
    r_direct, ev_direct = ch.handle_chat_command(db_session, uid2, "쇼트핸더", "!10 1")
    assert r_direct is not None
    assert "✅ [매수 체결] [구매 완료]" in r_direct
    assert "10X" in r_direct

    # Truly invalid product gives updated error message including 10X and 5X
    r_err, _ = ch.handle_chat_command(db_session, uid, uname, "!매수 비트코인 1")
    assert "⚠️ 알 수 없는 종목입니다" in r_err
    assert "10X" in r_err
    assert "5X" in r_err

def test_casino_open_and_close(db_session):
    """Test casino state management: opening, duration, and closing."""
    # Initially closed
    st = te.get_casino_state(db_session)
    assert st["is_open"] is False

    # Open casino for 5 minutes with 20,000P max bet
    ok, reply, details = te.open_casino(db_session, duration_minutes=5.0, max_bet=20000)
    assert ok is True
    assert details["is_open"] is True
    assert details["max_bet"] == 20000
    assert "OPEN" in reply or "열었습니다" in reply

    st2 = te.get_casino_state(db_session)
    assert st2["is_open"] is True
    assert st2["max_bet"] == 20000
    assert st2["remaining_sec"] > 0

    # Close casino
    ok_c, reply_c, details_c = te.close_casino(db_session)
    assert ok_c is True
    assert details_c["is_open"] is False
    assert "마감" in reply_c

    st3 = te.get_casino_state(db_session)
    assert st3["is_open"] is False

def test_casino_slot_gamble(db_session, monkeypatch):
    """Test slot machine mechanics including payouts, losses, and 777 MEGA JACKPOT."""
    uid = "gambler_slot_1"
    uname = "슬롯장인"
    user = te.get_or_create_user(db_session, uid, uname)
    user.points = 50000
    db_session.commit()

    # 1. Closed test
    ok, reply, _ = te.execute_slot_gamble(db_session, uid, uname, "1000")
    assert ok is False
    assert "오픈" in reply

    # Open casino with 100,000P max bet
    te.open_casino(db_session, duration_minutes=5.0, max_bet=100000)

    # 2. Exceeding max bet
    ok2, reply2, _ = te.execute_slot_gamble(db_session, uid, uname, "150000")
    assert ok2 is False
    assert "최대 베팅 한도" in reply2

    # 3. Exceeding balance
    user.points = 500
    db_session.commit()
    ok3, reply3, _ = te.execute_slot_gamble(db_session, uid, uname, "1000")
    assert ok3 is False
    assert "보유 포인트가 부족합니다" in reply3

    # Reset points to 100,000 and treasury to 500,000
    user.points = 100000
    state = te.get_market_state(db_session)
    state.treasury_pool = 500000.0
    db_session.commit()

    # 4. Rig slot spin to 777 MEGA JACKPOT: ['7️⃣', '7️⃣', '7️⃣']
    monkeypatch.setattr("random.choices", lambda *args, **kwargs: ["7️⃣", "7️⃣", "7️⃣"])
    ok_jackpot, reply_jackpot, details_jackpot = te.execute_slot_gamble(db_session, uid, uname, "5000")
    assert ok_jackpot is True
    assert details_jackpot["is_jackpot"] is True
    assert "777 JACKPOT" in reply_jackpot
    assert details_jackpot["net_payout"] == 50000
    db_session.refresh(user)
    assert user.points > 100000

    # 5. Rig slot spin to Yakuman 6x: ['🀄', '🀄', '🀄']
    user.points = 50000
    db_session.commit()
    monkeypatch.setattr("random.choices", lambda *args, **kwargs: ["🀄", "🀄", "🀄"])
    ok_yaku, reply_yaku, details_yaku = te.execute_slot_gamble(db_session, uid, uname, "1000")
    assert ok_yaku is True
    assert details_yaku["net_payout"] == 5000
    db_session.refresh(user)
    assert user.points == 50000 + 5000

    # 6. Rig slot spin to Loss: ['💣', '🍒', '🍇']
    user.points = 50000
    treasury_before = te.get_market_state(db_session).treasury_pool
    db_session.commit()
    monkeypatch.setattr("random.choices", lambda *args, **kwargs: ["💣", "🍒", "🍇"])
    ok_loss, reply_loss, details_loss = te.execute_slot_gamble(db_session, uid, uname, "2000")
    assert ok_loss is True
    assert details_loss["won"] is False
    assert details_loss["net_payout"] == -2000
    db_session.refresh(user)
    assert user.points == 48000
    db_session.refresh(state)
    assert state.treasury_pool == treasury_before + 2000

    # 7. Rig slot spin to 2-matching standard pair: ['🍒', '🍒', '💣'] -> 1.2x payout (net +0.2x)
    user.points = 50000
    db_session.commit()
    monkeypatch.setattr("random.choices", lambda *args, **kwargs: ["🍒", "🍒", "💣"])
    ok_pair, reply_pair, details_pair = te.execute_slot_gamble(db_session, uid, uname, "1000")
    assert ok_pair is True
    assert details_pair["won"] is True
    assert details_pair["net_payout"] == 200 # 1.2x total payout (net +0.2x)
    db_session.refresh(user)
    assert user.points == 50200

    # 8. Rig slot spin to 2-matching high pair: ['💎', '💎', '🍒'] -> 1.6x payout (net +0.6x)
    user.points = 50000
    db_session.commit()
    monkeypatch.setattr("random.choices", lambda *args, **kwargs: ["💎", "💎", "🍒"])
    ok_hpair, reply_hpair, details_hpair = te.execute_slot_gamble(db_session, uid, uname, "1000")
    assert ok_hpair is True
    assert details_hpair["won"] is True
    assert details_hpair["net_payout"] == 600 # 1.6x total payout (net +0.6x)
    db_session.refresh(user)
    assert user.points == 50600

    # 9. Bet up to 100,000P on slot succeeds and net payout is capped at MAX_CASINO_PAYOUT (100,000P)
    user.points = 200000
    db_session.commit()
    monkeypatch.setattr("random.choices", lambda *args, **kwargs: ["🀄", "🀄", "🀄"])
    ok_100k, reply_100k, details_100k = te.execute_slot_gamble(db_session, uid, uname, "100000")
    assert ok_100k is True
    assert details_100k["net_payout"] == 100000  # Capped at 100,000P instead of 500,000P!

    # 10. Bet over 100,000P on slot is rejected
    ok_over, reply_over, _ = te.execute_slot_gamble(db_session, uid, uname, "100001")
    assert ok_over is False
    assert "최대 베팅 한도" in reply_over

def test_casino_dice_gamble(db_session, monkeypatch):
    """Test 2-dice high-roller battle mechanics including odd/even/high/low and double 2.5x critical."""
    uid = "gambler_dice_1"
    uname = "주사위의신"
    user = te.get_or_create_user(db_session, uid, uname)
    user.points = 50000
    te.open_casino(db_session, duration_minutes=5.0, max_bet=100000)

    # 1. Even win: roll (2, 4) -> sum = 6
    dice_results = iter([2, 4])
    monkeypatch.setattr("random.randint", lambda a, b: next(dice_results))
    ok, reply, details = te.execute_dice_gamble(db_session, uid, uname, "짝", "1000")
    assert ok is True
    assert details["won"] is True
    assert details["net_payout"] == 900 # 1.9x payout (net +0.9x)
    db_session.refresh(user)
    assert user.points == 50900

    # 2. Critical Double 2.5x jackpot: roll (6, 6) -> sum = 12
    dice_double = iter([6, 6])
    monkeypatch.setattr("random.randint", lambda a, b: next(dice_double))
    ok_d, reply_d, details_d = te.execute_dice_gamble(db_session, uid, uname, "대", "2000")
    assert ok_d is True
    assert details_d["won"] is True
    assert details_d["is_critical"] is True
    assert details_d["net_payout"] == 3000 # 2.5x payout (net +1.5x)
    assert "크리티컬 잭팟" in reply_d

    # 3. High/Low loss on 7: roll (3, 4) -> sum = 7
    dice_seven = iter([3, 4])
    monkeypatch.setattr("random.randint", lambda a, b: next(dice_seven))
    ok_7, reply_7, details_7 = te.execute_dice_gamble(db_session, uid, uname, "소", "1000")
    assert ok_7 is True
    assert details_7["won"] is False
    assert details_7["net_payout"] == -1000
    assert "국고로 귀속" in reply_7

    # 4. Bet up to 100,000P on dice succeeds and critical double is capped at MAX_CASINO_PAYOUT (100,000P)
    user.points = 200000
    db_session.commit()
    dice_100k = iter([6, 6])
    monkeypatch.setattr("random.randint", lambda a, b: next(dice_100k))
    ok_100k, _, det_100k = te.execute_dice_gamble(db_session, uid, uname, "짝", "100000")
    assert ok_100k is True
    assert det_100k["is_critical"] is True
    assert det_100k["net_payout"] == 100000  # Capped at 100,000P instead of 150,000P!

    # 5. Bet over 100,000P on dice is rejected
    ok_over, reply_over, _ = te.execute_dice_gamble(db_session, uid, uname, "짝", "100001")
    assert ok_over is False
    assert "최대 베팅 한도" in reply_over

def test_casino_chat_commands(db_session):
    """Test full chat command handling for streamer and viewers."""
    viewer_id = "normal_viewer_99"
    viewer_name = "시청자"
    streamer_id = ch.CHANNEL_ID
    streamer_name = "치즈나베"

    # Non-streamer attempting to open casino -> blocked
    r1, ev1 = ch.handle_chat_command(db_session, viewer_id, viewer_name, "!카지노오픈 3")
    assert "🚫 카지노 개장은 스트리머(치즈나베)만 진행할 수 있습니다!" in r1
    assert ev1 is None

    # Streamer opening casino with default max bet -> 100,000P
    r2, ev2 = ch.handle_chat_command(db_session, streamer_id, streamer_name, "!카지노오픈 5")
    assert "OPEN" in r2 or "열었습니다" in r2
    assert "100,000P" in r2
    assert ev2 is not None
    assert ev2["type"] == "casino_open"
    assert ev2["data"]["max_bet"] == 100000

    # Viewer querying casino status shows 100,000P limit
    r3, _ = ch.handle_chat_command(db_session, viewer_id, viewer_name, "!카지노")
    assert "영업중" in r3
    assert "100,000P" in r3

    # Viewer playing slot
    r4, ev4 = ch.handle_chat_command(db_session, viewer_id, viewer_name, "!슬롯 1000")
    assert r4 is not None
    assert ev4 is not None
    assert ev4["type"] in ["casino_spin", "casino_jackpot"]

    # Viewer playing dice with swapped argument syntax (!주사위 1000 홀)
    r5, ev5 = ch.handle_chat_command(db_session, viewer_id, viewer_name, "!주사위 1000 홀")
    assert r5 is not None
    assert ev5 is not None
    assert ev5["type"] in ["casino_dice", "casino_jackpot"]

    # Viewer querying slot odds
    r_odds, ev_odds = ch.handle_chat_command(db_session, viewer_id, viewer_name, "!슬롯확률")
    assert r_odds is not None
    assert "국고 슬롯 공식 확률" in r_odds
    assert "31.1%" in r_odds
    assert "777" in r_odds
    assert ev_odds is None

    # Streamer closing casino
    r6, ev6 = ch.handle_chat_command(db_session, streamer_id, streamer_name, "!카지노마감")
    assert "마감" in r6
    assert ev6["type"] == "casino_close"

def test_borrow_allowed_during_game_market_lock(db_session):
    """Verify that pure loan (!대출) is allowed even when the market is locked during games."""
    uid = "borrower_during_game"
    uname = "경기중대출러"
    user = te.get_or_create_user(db_session, uid, uname)
    user.points = 10000
    user.debt = 0
    
    state = te.get_market_state(db_session)
    state.is_trading_locked = True
    state.free_trading_end_time = 0.0
    state.treasury_pool = 500000.0
    db_session.commit()

    # 1. Stock buy is locked during games
    r_buy, _ = ch.handle_chat_command(db_session, uid, uname, "!매수 1X 1")
    assert "거래 마감" in r_buy

    # 2. Stock margin buy is also locked during games
    r_mbuy, _ = ch.handle_chat_command(db_session, uid, uname, "!매수 10X 빚올인")
    assert "거래 마감" in r_mbuy

    # 3. Pure cash loan (!대출 20000) is allowed during games!
    r_borrow, ev_borrow = ch.handle_chat_command(db_session, uid, uname, "!대출 20000")
    assert r_borrow is not None
    assert "대출 실행 완료" in r_borrow
    assert ev_borrow is not None
    assert ev_borrow["type"] == "loan_borrow"
    db_session.refresh(user)
    assert user.points == 30000
    assert user.debt == 20000

    # 4. Pure cash loan (!대출 최대) borrows remaining limit
    r_max, ev_max = ch.handle_chat_command(db_session, uid, uname, "!대출 최대")
    assert r_max is not None
    assert "대출 실행 완료" in r_max
    db_session.refresh(user)
    assert user.debt == 50000
    assert user.points == 60000

    # 5. Loan repay (!상환 10000) also allowed during games
    r_repay, ev_repay = ch.handle_chat_command(db_session, uid, uname, "!상환 10000")
    assert r_repay is not None
    assert "상환 완료" in r_repay
    db_session.refresh(user)
    assert user.debt == 40000
    assert user.points == 50000

def test_remaining_time_command(db_session):
    """Verify !남은시간 and !시간 command displaying free trading time, casino time, and mining cooldown."""
    uid = "time_checker_user"
    uname = "시간확인러"
    user = te.get_or_create_user(db_session, uid, uname)
    state = te.get_market_state(db_session)

    # 1. When market is locked and casino closed
    state.is_trading_locked = True
    state.free_trading_end_time = 0.0
    state.casino_is_open = False
    db_session.commit()

    r1, _ = ch.handle_chat_command(db_session, uid, uname, "!남은시간")
    assert r1 is not None
    assert "⏱️ [현재 남은 시간]" in r1
    assert "거래 마감" in r1
    assert "카지노 마감" in r1
    assert "즉시 가능" in r1

    # 2. When market is open with 180s countdown and casino open with 300s
    state.is_trading_locked = False
    state.free_trading_end_time = time.time() + 180.0
    state.casino_is_open = True
    state.casino_end_time = time.time() + 300.0
    db_session.commit()

    r2, _ = ch.handle_chat_command(db_session, uid, uname, "!시간")
    assert r2 is not None
    assert "장 열림" in r2
    assert "카지노 오픈" in r2

    # 3. When user recently mined (cooldown active)
    user.last_mined_at = datetime.now(timezone.utc)
    db_session.commit()

    r3, _ = ch.handle_chat_command(db_session, uid, uname, "!time")
    assert r3 is not None
    assert "쿨타임" in r3

def test_abbreviation_guide_command(db_session):
    """Verify !약어 and aliases displaying shorthand stock guides."""
    uid = "abbr_viewer"
    uname = "약어질문러"

    aliases = ["!약어", "!단축어", "!종목약어", "!줄임말", "!은어", "!별칭", "!alias"]
    for cmd in aliases:
        reply, ev = ch.handle_chat_command(db_session, uid, uname, cmd)
        assert reply is not None, f"Failed for {cmd}"
        assert "🏷️ [종목 약어 & 단축어 가이드]" in reply
        assert "10롱" in reply
        assert "10숏" in reply
        assert "곱버스" in reply
        assert ev is None

    # Verify HELP_MESSAGE includes guidance to !약어
    help_reply, _ = ch.handle_chat_command(db_session, uid, uname, "!명령어")
    assert "!약어" in help_reply

def test_allin_purchase_message_and_casino_limit_100k(db_session):
    """Verify all-in purchases display total amount (총 얼마P) and casino limit defaults to 100,000P."""
    uid = "allin_msg_user"
    uname = "올인메시지러"
    user = te.get_or_create_user(db_session, uid, uname)
    user.points = 50000
    db_session.commit()

    # 1. Buying by count displays total purchase amount
    r_cnt, ev_cnt = ch.handle_chat_command(db_session, uid, uname, "!10배 1주")
    assert "구매 완료" in r_cnt
    assert "총" in r_cnt
    assert "P" in r_cnt

    # 2. Buying with all-in (!10배 올인) displays total purchase amount and all-in label
    user.points = 50000
    db_session.commit()
    r_allin1, ev_allin1 = ch.handle_chat_command(db_session, uid, uname, "!10배 올인")
    assert "구매 완료" in r_allin1
    assert "전액 올인" in r_allin1
    assert "총" in r_allin1
    assert "P" in r_allin1

    # 3. Attached form !10배올인 displays total amount and all-in label
    user.points = 50000
    db_session.commit()
    r_allin2, ev_allin2 = ch.handle_chat_command(db_session, uid, uname, "!10배올인")
    assert "구매 완료" in r_allin2
    assert "전액 올인" in r_allin2
    assert "총" in r_allin2

    # 4. !올인10배 and !풀매수10X attached forms
    user.points = 50000
    db_session.commit()
    r_allin3, ev_allin3 = ch.handle_chat_command(db_session, uid, uname, "!올인10배")
    assert "구매 완료" in r_allin3
    assert "전액 올인" in r_allin3
    assert "10X" in r_allin3

    # 5. !매수 10배올인 attached form
    user.points = 50000
    db_session.commit()
    r_allin4, ev_allin4 = ch.handle_chat_command(db_session, uid, uname, "!매수 10배올인")
    assert "구매 완료" in r_allin4
    assert "전액 올인" in r_allin4

    # 6. Casino limit: legacy 10,000 in DB is auto-upgraded to 100,000
    state = te.get_market_state(db_session)
    state.casino_max_bet = 10000
    state.casino_is_open = True
    db_session.commit()

    c_state = te.get_casino_state(db_session)
    assert c_state["max_bet"] >= 100000

    # Streamer opening casino with !카지노오픈 defaults to 100,000P
    r_open, _ = ch.handle_chat_command(db_session, "admin", "스트리머", "!카지노오픈")
    assert "100,000P" in r_open

    # Streamer opening casino with Korean unit: !카지노오픈 10만
    r_open2, _ = ch.handle_chat_command(db_session, "admin", "스트리머", "!카지노오픈 10만")
    assert "100,000P" in r_open2



