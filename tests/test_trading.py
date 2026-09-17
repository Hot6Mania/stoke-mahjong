import os
import time
import json
import random
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base
from models import User, Position, MarketState, LimitOrder, ProductType, OrderType, OrderStatus, UserEquipment, EquipmentListing
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

def test_second_place_dividend_1pct(db_session):
    u = "investor_2nd"
    te.execute_buy(db_session, u, "존버러", "1X", "10") # 10 shares of 1X
    user_before = db_session.query(User).filter_by(id=u).first()
    points_before = user_before.points

    # Streamer finishes 2nd place (rank 2)
    settle_res = te.settle_match(db_session, rank=2, point_delta=20)
    assert len(settle_res["dividends"]) >= 1
    d = next(item for item in settle_res["dividends"] if item["user_id"] == u)
    assert d["rate_pct"] == 1.0
    assert d["payout"] > 0

    user_after = db_session.query(User).filter_by(id=u).first()
    assert user_after.points == points_before + d["payout"]
    assert user_after.total_dividends >= d["payout"]

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
    assert details_jackpot["net_payout"] == 100000  # 20% of 500k treasury pool = 100,000P
    db_session.refresh(user)
    assert user.points > 100000

    # 5. Rig slot spin to Yakuman 10x: ['🀄', '🀄', '🀄']
    user.points = 50000
    db_session.commit()
    monkeypatch.setattr("random.choices", lambda *args, **kwargs: ["🀄", "🀄", "🀄"])
    ok_yaku, reply_yaku, details_yaku = te.execute_slot_gamble(db_session, uid, uname, "1000")
    assert ok_yaku is True
    assert details_yaku["net_payout"] == 9000  # 10x total payout (net +9,000P)
    db_session.refresh(user)
    assert user.points == 50000 + 9000

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

    # 7. Rig slot spin to 2-matching standard pair: ['🍒', '🍒', '💣'] -> 1.5x payout (net +0.5x)
    user.points = 50000
    db_session.commit()
    monkeypatch.setattr("random.choices", lambda *args, **kwargs: ["🍒", "🍒", "💣"])
    ok_pair, reply_pair, details_pair = te.execute_slot_gamble(db_session, uid, uname, "1000")
    assert ok_pair is True
    assert details_pair["won"] is True
    assert details_pair["net_payout"] == 500 # 1.5x total payout (net +0.5x)
    db_session.refresh(user)
    assert user.points == 50500

    # 8. Rig slot spin to 2-matching high pair: ['💎', '💎', '🍒'] -> 2.0x payout (net +1.0x)
    user.points = 50000
    db_session.commit()
    monkeypatch.setattr("random.choices", lambda *args, **kwargs: ["💎", "💎", "🍒"])
    ok_hpair, reply_hpair, details_hpair = te.execute_slot_gamble(db_session, uid, uname, "1000")
    assert ok_hpair is True
    assert details_hpair["won"] is True
    assert details_hpair["net_payout"] == 1000 # 2.0x total payout (net +1.0x)
    db_session.refresh(user)
    assert user.points == 51000

    # 9. Bet up to 100,000P on slot succeeds and net payout is NOT capped at 100k (uncapped big win!)
    user.points = 200000
    db_session.commit()
    monkeypatch.setattr("random.choices", lambda *args, **kwargs: ["🀄", "🀄", "🀄"])
    ok_100k, reply_100k, details_100k = te.execute_slot_gamble(db_session, uid, uname, "100000")
    assert ok_100k is True
    assert details_100k["net_payout"] == 900000  # 10x total payout (net +900,000P uncapped!)
    db_session.refresh(user)
    assert user.points == 200000 + 900000

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
    assert details["net_payout"] == 1000 # 2.0x payout (net +1.0x)
    db_session.refresh(user)
    assert user.points == 51000

    # 2. Critical Double 3.0x jackpot: roll (6, 6) -> sum = 12
    dice_double = iter([6, 6])
    monkeypatch.setattr("random.randint", lambda a, b: next(dice_double))
    ok_d, reply_d, details_d = te.execute_dice_gamble(db_session, uid, uname, "대", "2000")
    assert ok_d is True
    assert details_d["won"] is True
    assert details_d["is_critical"] is True
    assert details_d["net_payout"] == 4000 # 3.0x payout (net +2.0x)
    assert "크리티컬 잭팟" in reply_d

    # 3. High/Low push refund on 7: roll (3, 4) -> sum = 7
    dice_seven = iter([3, 4])
    monkeypatch.setattr("random.randint", lambda a, b: next(dice_seven))
    ok_7, reply_7, details_7 = te.execute_dice_gamble(db_session, uid, uname, "소", "1000")
    assert ok_7 is True
    assert details_7["won"] is False
    assert details_7["is_push"] is True
    assert details_7["net_payout"] == 0
    assert "무승부" in reply_7 or "환급" in reply_7

    # 4. Bet up to 100,000P on dice succeeds and critical double is NOT capped at 100k (uncapped!)
    user.points = 200000
    db_session.commit()
    dice_100k = iter([6, 6])
    monkeypatch.setattr("random.randint", lambda a, b: next(dice_100k))
    ok_100k, _, det_100k = te.execute_dice_gamble(db_session, uid, uname, "짝", "100000")
    assert ok_100k is True
    assert det_100k["is_critical"] is True
    assert det_100k["net_payout"] == 200000  # 3.0x payout -> net +200,000P uncapped!
    db_session.refresh(user)
    assert user.points == 200000 + 200000

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
    assert "50.5%" in r_odds
    assert "777" in r_odds
    assert ev_odds is None

    # Streamer closing casino
    r6, ev6 = ch.handle_chat_command(db_session, streamer_id, streamer_name, "!카지노마감")
    assert "마감" in r6
    assert ev6["type"] == "casino_close"

def test_streamer_chat_settle_command(db_session):
    """Test streamer chat settlement command !정산 [등수] [변동점수]."""
    viewer_id = "normal_viewer_55"
    viewer_name = "일반시청자"
    streamer_id = ch.CHANNEL_ID
    streamer_name = "치즈나베"

    # Setup 1X stock shareholder
    te.execute_buy(db_session, viewer_id, viewer_name, "1X", "20")
    user_before = db_session.query(User).filter_by(id=viewer_id).first()
    div_before = user_before.total_dividends or 0

    # Non-streamer attempting to settle -> blocked
    r_no, ev_no = ch.handle_chat_command(db_session, viewer_id, viewer_name, "!정산 2 0")
    assert "🚫" in r_no
    assert ev_no is None

    # Streamer settling 2nd place with 0pt (!정산 2 0)
    r_yes, ev_yes = ch.handle_chat_command(db_session, streamer_id, streamer_name, "!정산 2 0")
    assert "2위" in r_yes
    assert "정산 완료" in r_yes
    assert "1X 배당" in r_yes
    assert ev_yes is not None
    assert ev_yes["type"] == "settlement"

    # Check that 1X shareholder received 1% dividend
    db_session.refresh(user_before)
    assert user_before.total_dividends > div_before

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

def test_format_quantity_compatibility():
    # Test integer inputs (e.g. from math.floor or int casts)
    assert te.format_quantity(5) == "5"
    assert te.format_quantity(0) == "0"
    assert te.format_quantity(12345) == "12345"

    # Test float inputs
    assert te.format_quantity(5.0) == "5"
    assert te.format_quantity(5.25) == "5.25"
    assert te.format_quantity(5.20) == "5.20"
    assert te.format_quantity(0.0) == "0"

    # Test string / edge cases
    assert te.format_quantity("10") == "10"
    assert te.format_quantity("10.5") == "10.50"
    assert te.format_quantity("invalid") == "invalid"

def test_allin_and_int_quantity_trading_pipeline(db_session):
    uid = "int_compat_user"
    uname = "정수유저"

    # 1. Buy all-in (returns integer quantity)
    r_allin, ev_allin = ch.handle_chat_command(db_session, uid, uname, "!매수 1X 올인")
    assert "매수 체결" in r_allin or "구매 완료" in r_allin
    assert ev_allin is not None
    assert isinstance(ev_allin["data"]["quantity"], (int, float))

    # 2. Check info (!내정보) with integer position quantity
    r_info, _ = ch.handle_chat_command(db_session, uid, uname, "!내정보")
    assert "보유:" in r_info
    assert "1X:" in r_info

    # 3. Test get_current_buyers
    buyers_data = te.get_current_buyers(db_session)
    assert buyers_data["summary"]["total_buyers"] >= 1
    found = [b for b in buyers_data["buyers"] if b["user_id"] == uid]
    assert len(found) == 1
    assert isinstance(found[0]["quantity"], int)

    # 4. Limit order with integer quantity
    r_limit, _ = ch.handle_chat_command(db_session, uid, uname, "!지정가 매도 1X 3000 5")
    assert "예약 완료" in r_limit or "체결" in r_limit

    # 5. Sell all (!매도 1X 전량)
    r_sell, ev_sell = ch.handle_chat_command(db_session, uid, uname, "!매도 1X 전량")
    assert "매도 체결" in r_sell or "판매 완료" in r_sell

def test_parse_korean_amount():
    assert te.parse_korean_amount("10000") == 10000
    assert te.parse_korean_amount("10,000") == 10000
    assert te.parse_korean_amount("10000P") == 10000
    assert te.parse_korean_amount("10000원") == 10000
    assert te.parse_korean_amount("1만") == 10000
    assert te.parse_korean_amount("5만") == 50000
    assert te.parse_korean_amount("10만") == 100000
    assert te.parse_korean_amount("1.5만") == 15000
    assert te.parse_korean_amount("5천") == 5000
    assert te.parse_korean_amount("1억") == 100000000
    assert te.parse_korean_amount("invalid") is None
    assert te.parse_korean_amount("") is None
    assert te.parse_korean_amount(None) is None

def test_calculate_transfer_tax():
    # Below 10,000P: 0% tax (면세)
    tax, rate, label = te.calculate_transfer_tax(5000)
    assert tax == 0
    assert rate == 0.0
    assert label == "면세"

    tax, rate, label = te.calculate_transfer_tax(9999)
    assert tax == 0

    # 10,000P ~ 99,999P: 5% tax (고액 이체세)
    tax, rate, label = te.calculate_transfer_tax(10000)
    assert tax == 500
    assert rate == 0.05
    assert label == "고액 이체세"

    tax, rate, label = te.calculate_transfer_tax(50000)
    assert tax == 2500

    # 100,000P+: 10% tax (초고액 증여세)
    tax, rate, label = te.calculate_transfer_tax(100000)
    assert tax == 10000
    assert rate == 0.10
    assert label == "초고액 증여세"

    tax, rate, label = te.calculate_transfer_tax(200000)
    assert tax == 20000

def test_execute_transfer_tax_and_protection(db_session):
    u1 = te.get_or_create_user(db_session, "u1_transfer", "보내는사람")
    u2 = te.get_or_create_user(db_session, "u2_transfer", "받는사람")
    u1.points = 200000
    u2.points = 10000
    db_session.commit()

    state = te.get_market_state(db_session)
    treasury_initial = state.treasury_pool

    # 1. Tax-free transfer (< 10,000P): e.g. 5,000P
    ok, reply, details = te.execute_transfer(db_session, "u1_transfer", "보내는사람", "받는사람", "5000")
    assert ok is True
    assert details["amount"] == 5000
    assert details["tax"] == 0
    assert details["recipient_net"] == 5000
    assert u1.points == 195000
    assert u2.points == 15000
    assert state.treasury_pool == treasury_initial
    assert "면세" in reply

    # 2. Transfer with 5% tax (>= 10,000P): e.g. 20,000P (tax = 1,000P, net = 19,000P)
    ok, reply, details = te.execute_transfer(db_session, "u1_transfer", "보내는사람", "받는사람", "20000")
    assert ok is True
    assert details["amount"] == 20000
    assert details["tax"] == 1000
    assert details["recipient_net"] == 19000
    assert u1.points == 175000
    assert u2.points == 34000
    assert state.treasury_pool == treasury_initial + 1000
    assert "고액 이체세(5%): 1,000P 국고 적립" in reply

    # 3. Super high transfer with 10% tax (>= 100,000P): e.g. 100,000P (tax = 10,000P, net = 90,000P)
    ok, reply, details = te.execute_transfer(db_session, "u1_transfer", "보내는사람", "받는사람", "10만")
    assert ok is True
    assert details["amount"] == 100000
    assert details["tax"] == 10000
    assert details["recipient_net"] == 90000
    assert u1.points == 75000
    assert u2.points == 124000
    assert state.treasury_pool == treasury_initial + 1000 + 10000
    assert "초고액 증여세(10%): 10,000P 국고 적립" in reply

    # 4. Self-transfer protection
    ok, reply, _ = te.execute_transfer(db_session, "u1_transfer", "보내는사람", "보내는사람", "10000")
    assert ok is False
    assert "본인 계좌" in reply

    # 5. Non-existent recipient
    ok, reply, _ = te.execute_transfer(db_session, "u1_transfer", "보내는사람", "존재하지않는유저", "10000")
    assert ok is False
    assert "찾을 수 없습니다" in reply

    # 6. Insufficient funds
    ok, reply, _ = te.execute_transfer(db_session, "u1_transfer", "보내는사람", "받는사람", "99999999")
    assert ok is False
    assert "부족" in reply

    # 7. Debt protection: Cannot transfer borrowed funds out to launder before bankruptcy
    u1.debt = 50000
    u1.points = 60000 # Own net cash = 10,000P
    db_session.commit()

    # Attempt to transfer 20,000P (> max_sendable 10,000P) -> rejected
    ok, reply, _ = te.execute_transfer(db_session, "u1_transfer", "보내는사람", "받는사람", "20000")
    assert ok is False
    assert "채무" in reply or "빚" in reply

    # Attempt to transfer 10,000P (<= max_sendable 10,000P) -> accepted
    ok, reply, details = te.execute_transfer(db_session, "u1_transfer", "보내는사람", "받는사람", "10000")
    assert ok is True

def test_transfer_chat_commands(db_session):
    u1 = te.get_or_create_user(db_session, "cmd_sender", "송금러")
    u2 = te.get_or_create_user(db_session, "cmd_receiver", "수신러")
    u1.points = 100000
    u2.points = 10000
    db_session.commit()

    # 1. Standard syntax: !송금 [닉네임] [금액]
    r, ev = ch.handle_chat_command(db_session, "cmd_sender", "송금러", "!송금 수신러 5000")
    assert "이체 완료" in r
    assert ev is not None
    assert ev["type"] == "account_transfer"

    # 2. Syntax with @ mention and Korean amount: !이체 @수신러 2만
    r, ev = ch.handle_chat_command(db_session, "cmd_sender", "송금러", "!이체 @수신러 2만")
    assert "이체 완료" in r
    assert ev["data"]["amount"] == 20000

    # 3. Reversed syntax: !송금 [금액] [닉네임]
    r, ev = ch.handle_chat_command(db_session, "cmd_sender", "송금러", "!송금 10000 수신러")
    assert "이체 완료" in r
    assert ev["data"]["amount"] == 10000

    # 4. Incomplete syntax: !송금
    r, ev = ch.handle_chat_command(db_session, "cmd_sender", "송금러", "!송금")
    assert "계좌이체 사용법" in r
    assert ev is None

def test_random_mining_tiers_structure():
    assert len(te.MINING_TIERS) == 8
    total_prob = sum(t["prob"] for t in te.MINING_TIERS)
    assert abs(total_prob - 100.0) < 1e-6

    # Test rolling multiple times returns valid tiers
    for _ in range(50):
        t = te.roll_mining_tier()
        assert t["code"] in ["EX", "UR+", "UR", "SSR", "SR", "R", "N", "C"]
        assert t["multiplier"] > 0

def test_random_mining_and_critical_hits(db_session, monkeypatch):
    u = "lucky_miner"
    user = te.get_or_create_user(db_session, u, "럭키광부")
    user.points = 1000
    db_session.commit()

    # 1. Force roll UR Tier (역만급 초대박)
    ur_tier = {
        "code": "UR",
        "name": "🀄 [역만급 초대박 광맥!! (1.5%)]",
        "prob": 1.5,
        "multiplier": 5.0,
        "bonus_cash": 10000,
        "bonus_10x": 1.0,
        "cooldown_reduction": 10,
    }
    monkeypatch.setattr(te, "roll_mining_tier", lambda: dict(ur_tier))

    ok, msg, details = te.execute_mining(db_session, u, "럭키광부")
    assert ok is True
    assert "역만급 초대박" in msg
    assert details["tier"] == "UR"
    assert details["multiplier"] == 5.0
    assert details["bonus_cash"] == 10000
    assert details["bonus_10x_shares"] == 1.0
    assert details["cooldown_reduction_minutes"] == 10

    # Verify user received 1X shares, bonus cash, and 10X bonus share
    user_db = db_session.query(User).filter_by(id=u).first()
    assert user_db.points == 1000 + 10000 # Got 10,000P bonus cash
    pos_1x = db_session.query(Position).filter_by(user_id=u, product_type=ProductType.ONE_X).first()
    assert pos_1x is not None and pos_1x.quantity == details["shares_awarded"]
    pos_10x = db_session.query(Position).filter_by(user_id=u, product_type=ProductType.TEN_X).first()
    assert pos_10x is not None and pos_10x.quantity == 1.0

    # Verify cooldown booster was applied: last_mined_at was shifted back by 10 minutes,
    # so elapsed is treated as >= 600s, leaving only 5 minutes remaining
    now_utc = datetime.now(timezone.utc)
    last_t = user_db.last_mined_at
    if last_t.tzinfo is None:
        last_t = last_t.replace(tzinfo=timezone.utc)
    elapsed = (now_utc - last_t).total_seconds()
    assert elapsed >= 590 # Within ~10 min back shift

    # 2. Test Debt (Forced labor) with Critical SSR Tier
    u_debt = "debt_miner"
    user_d = te.get_or_create_user(db_session, u_debt, "빚쟁이광부")
    user_d.debt = 50000
    db_session.commit()

    ssr_tier = {
        "code": "SSR",
        "name": "💎 [다이아몬드 광맥 슈퍼 크리티컬! (4.5%)]",
        "prob": 4.5,
        "multiplier": 3.0,
        "bonus_cash": 5000,
        "bonus_10x": 0.0,
        "cooldown_reduction": 5,
    }
    monkeypatch.setattr(te, "roll_mining_tier", lambda: dict(ssr_tier))

    ok_d, msg_d, det_d = te.execute_mining(db_session, u_debt, "빚쟁이광부")
    assert ok_d is True
    assert det_d["is_forced_labor"] is True
    assert det_d["repaid_debt"] > 5000 # At least bonus cash + shares value
    assert user_d.debt < 50000

def test_mythical_ex_jackpot(db_session, monkeypatch):
    u = "jackpot_winner"
    user = te.get_or_create_user(db_session, u, "천화당첨자")
    user.points = 10000
    user.pickaxe_level = 25 # MAX pickaxe (6.0x multiplier)
    state = te.get_market_state(db_session)
    state.treasury_pool = 1000000 # 100만P treasury
    db_session.commit()

    # Force roll EX tier
    ex_tier = dict(te.MINING_TIERS[0])
    monkeypatch.setattr(te, "roll_mining_tier", lambda *a, **kw: dict(ex_tier))

    ok, msg, details = te.execute_mining(db_session, u, "천화당첨자")
    assert ok is True
    assert "일확천금" in msg
    assert "천화" in msg
    assert details["tier"] == "EX"
    assert details["bonus_cash"] == 100000 # 10% of 1,000,000P!
    assert details["bonus_10x_shares"] == 5.0
    # Cooldown immediately reset (last_mined_at is None)
    user_db = db_session.query(User).filter_by(id=u).first()
    assert user_db.last_mined_at is None
    assert user_db.points >= 110000 # 10,000 + 100,000 bonus cash

def test_mining_commands_and_probability_guide(db_session):
    u = "cmd_miner"
    # Command: !채굴확률
    r_prob, ev_prob = ch.handle_chat_command(db_session, u, "광부", "!채굴확률")
    assert "랜덤 채굴 & 크리티컬 확률 안내" in r_prob
    assert "역만급 초대박" in r_prob
    assert "다이아몬드" in r_prob
    assert "황금 광맥" in r_prob
    assert ev_prob is None

    # Alias: !채굴안내
    r_guide, _ = ch.handle_chat_command(db_session, u, "광부", "!채굴안내")
    assert "랜덤 채굴 & 크리티컬 확률 안내" in r_guide

    # Regular !채굴
    r_mine, ev_mine = ch.handle_chat_command(db_session, u, "광부", "!채굴")
    assert "채굴 완료" in r_mine
    assert ev_mine is not None
    assert ev_mine["type"] == "mining"

def test_pickaxe_upgrade_and_treasury_recycle(db_session, monkeypatch):
    import random
    u = "starforce_tester"
    user = te.get_or_create_user(db_session, u, "스타포스장인")
    user.points = 10000000 # 1,000만P
    state = te.get_market_state(db_session)
    state.treasury_pool = 500000
    db_session.commit()

    # Initial level should be 0 or 1
    user.pickaxe_level = 0
    db_session.commit()
    info0 = te.get_pickaxe_info(0)
    assert info0["level"] == 0
    assert "★0성" in info0["name"]

    # 1. 0성 -> 1성 (Force roll success: roll = 10 < 99.75)
    monkeypatch.setattr(random, "uniform", lambda a, b: 10.0)
    ok, reply, details = te.execute_pickaxe_upgrade(db_session, u, "스타포스장인")
    assert ok is True
    assert details["outcome"] == "success"
    assert details["new_level"] == 1
    assert details["cost"] == 2000
    assert details["treasury_pool"] == 502000
    assert user.pickaxe_level == 1

    # 2. Check 0~14성 has 0% destroy rate guarantee
    for lvl in range(15):
        it = te.get_pickaxe_info(lvl)
        assert it["destroy_rate"] == 0.0, f"Level {lvl} must have 0% destroy rate!"

    # 3. Check 15성+ has destroy rate
    info15 = te.get_pickaxe_info(15)
    assert info15["destroy_rate"] == 2.055
    info22 = te.get_pickaxe_info(22)
    assert info22["destroy_rate"] == 16.85

    # 4. Test 10성 safety bracket (Maintain on fail)
    user.pickaxe_level = 10
    db_session.commit()
    info10 = te.get_pickaxe_info(10)
    # roll between success (52.5) and 100 -> maintain
    monkeypatch.setattr(random, "uniform", lambda a, b: 70.0)
    ok10, rep10, det10 = te.execute_pickaxe_upgrade(db_session, u, "스타포스장인")
    assert ok10 is True
    assert det10["outcome"] == "maintain"
    assert det10["new_level"] == 10
    assert user.pickaxe_level == 10

    # 5. Test 11성 failure (Drop 1 level to 10성)
    user.pickaxe_level = 11
    db_session.commit()
    # 11성: success 47.25, drop 52.75 -> roll 60 is drop
    monkeypatch.setattr(random, "uniform", lambda a, b: 60.0)
    ok11, rep11, det11 = te.execute_pickaxe_upgrade(db_session, u, "스타포스장인")
    assert ok11 is True
    assert det11["outcome"] == "drop"
    assert det11["new_level"] == 10
    assert user.pickaxe_level == 10

    # 6. Test 17성 destruction (15+ stars blow-up -> restores to 12성)
    user.pickaxe_level = 17
    db_session.commit()
    # 17성: success 15.75, drop 77.51 (cumul 93.26), destroy 6.74 (roll 95 is destroy)
    monkeypatch.setattr(random, "uniform", lambda a, b: 95.0)
    ok17, rep17, det17 = te.execute_pickaxe_upgrade(db_session, u, "스타포스장인")
    assert ok17 is True
    assert det17["outcome"] == "destroyed"
    assert det17["new_level"] == 12  # MapleStory trace restoration!
    assert user.pickaxe_level == 12
    assert "폭발 파괴" in rep17
    assert "12성" in rep17

    # 7. Debt protection check
    user.points = 150000
    user.debt = 100000 # Cost for 12성 is 100,000 -> remaining 50,000 < debt 100,000
    db_session.commit()
    ok_debt, msg_debt, _ = te.execute_pickaxe_upgrade(db_session, u, "스타포스장인")
    assert ok_debt is False
    assert "채무" in msg_debt

    # 8. Max level 25 check
    user.debt = 0
    user.pickaxe_level = 25
    db_session.commit()
    ok_max, msg_max, _ = te.execute_pickaxe_upgrade(db_session, u, "스타포스장인")
    assert ok_max is False
    assert "최고 등급" in msg_max

def test_pickaxe_chat_commands(db_session, monkeypatch):
    import random
    u = "pickaxe_chatter"
    user = te.get_or_create_user(db_session, u, "광석수집가")
    user.points = 50000
    user.pickaxe_level = 0
    db_session.commit()

    # 1. Query !곡괭이
    r_pick, _ = ch.handle_chat_command(db_session, u, "광석수집가", "!곡괭이")
    assert "내 곡괭이 정보" in r_pick
    assert "나무 곡괭이 (★0성)" in r_pick
    assert "비용: 2,000P" in r_pick

    # 2. Check !내정보 includes equipped equipment
    r_info, _ = ch.handle_chat_command(db_session, u, "광석수집가", "!내정보")
    assert "장비: 🪵 나무 곡괭이 (★0성)" in r_info

    # 3. Upgrade via chat command !강화 (Force success)
    monkeypatch.setattr(random, "uniform", lambda a, b: 1.0)
    r_up, ev_up = ch.handle_chat_command(db_session, u, "광석수집가", "!강화")
    assert "스타포스 강화 대성공" in r_up
    assert "★1성" in r_up
    assert ev_up is not None
    assert ev_up["type"] == "pickaxe_upgrade"
    assert ev_up["data"]["new_level"] == 1

    # 4. Check !내정보 reflects upgraded pickaxe
    r_info2, _ = ch.handle_chat_command(db_session, u, "광석수집가", "!내정보")
    assert "장비: 🪵 나무 곡괭이 (★1성)" in r_info2

    # 5. Query !강화표 guide
    r_guide, _ = ch.handle_chat_command(db_session, u, "광석수집가", "!강화표")
    assert "스타포스 강화표" in r_guide
    assert "15강까진 절대 안 터집니다" in r_guide
    assert "국고 채굴풀로 환원" in r_guide

def test_multi_equipment_buy_swap_upgrade_and_p2p_trade(db_session, monkeypatch):
    """Test purchasing multiple equipments, swapping active equipment, enhancing selected equipment, and P2P marketplace trading with 5% tax."""
    import random
    alice_id = "trader_alice"
    alice = te.get_or_create_user(db_session, alice_id, "엘리스")
    alice.points = 1000000 # 100만P

    bob_id = "trader_bob"
    bob = te.get_or_create_user(db_session, bob_id, "밥")
    bob.points = 1000000 # 100만P

    state = te.get_market_state(db_session)
    state.treasury_pool = 500000
    db_session.commit()

    # 1. Check initial equipment for Alice (starts with 1 default pickaxe)
    alice_items = te.ensure_user_equipment(db_session, alice)
    assert len(alice_items) == 1
    default_eq = alice_items[0]
    assert default_eq.is_equipped is True

    # 2. Alice buys a new equipment (5성 돌 곡괭이 for 60,000P)
    ok_b, rep_b, det_b = te.execute_buy_equipment(db_session, alice_id, "엘리스", "5")
    assert ok_b is True
    assert det_b["cost"] == 60000
    assert det_b["starforce"] == 5
    assert det_b["is_equipped"] is False # Goes to inventory since Alice already had equipped item
    assert state.treasury_pool == 560000
    db_session.refresh(alice)
    assert alice.points == 940000

    alice_items = te.ensure_user_equipment(db_session, alice)
    assert len(alice_items) == 2
    stone_eq = next(it for it in alice_items if it.starforce == 5)
    assert stone_eq.id != default_eq.id

    # 3. Alice swaps equipment: equips the 5-star stone pickaxe
    ok_eq, rep_eq, det_eq = te.execute_equip_item(db_session, alice_id, "엘리스", str(stone_eq.id))
    assert ok_eq is True
    db_session.refresh(default_eq)
    db_session.refresh(stone_eq)
    assert default_eq.is_equipped is False
    assert stone_eq.is_equipped is True
    db_session.refresh(alice)
    assert alice.pickaxe_level == 5

    # 4. Enhance selected equipment: enhance default_eq (currently in inventory, not equipped)
    monkeypatch.setattr(random, "uniform", lambda a, b: 1.0) # Force success
    ok_up, rep_up, det_up = te.execute_pickaxe_upgrade(db_session, alice_id, "엘리스", str(default_eq.id))
    assert ok_up is True
    db_session.refresh(default_eq)
    assert default_eq.starforce == 2
    # Stone eq is still 5 stars and remains equipped
    db_session.refresh(stone_eq)
    assert stone_eq.starforce == 5
    assert alice.pickaxe_level == 5 # Still 5 since stone_eq is equipped

    # 5. Check Inventory string format
    inv_str = te.get_user_inventory_status(db_session, alice_id, "엘리스")
    assert "내 장비 인벤토리" in inv_str
    assert "🟢장착중" in inv_str
    assert "📦보관" in inv_str

    # 6. Public Marketplace Listing: Alice lists stone_eq for 100,000P
    ok_list, rep_list, det_list = te.execute_list_equipment(db_session, alice_id, "엘리스", str(stone_eq.id), "100000")
    assert ok_list is True
    listing_id = det_list["listing_id"]
    assert det_list["price"] == 100000
    assert det_list["tax_fee"] == 5000 # 5% tax
    # Since stone_eq was equipped, default_eq (2성) should be automatically equipped
    db_session.refresh(default_eq)
    db_session.refresh(stone_eq)
    assert stone_eq.is_equipped is False
    assert default_eq.is_equipped is True
    db_session.refresh(alice)
    assert alice.pickaxe_level == 2

    # 7. Check listed item cannot be enhanced while on sale
    ok_blocked, rep_blocked, _ = te.execute_pickaxe_upgrade(db_session, alice_id, "엘리스", str(stone_eq.id))
    assert ok_blocked is False
    assert "판매 등록 중" in rep_blocked

    # 8. Check Marketplace listings
    market_str = te.get_equipment_market_listings(db_session)
    assert "나베 장비 거래소" in market_str
    assert "100,000P" in market_str
    assert f"거래 #{listing_id}" in market_str

    # 9. Alice cannot buy her own listing
    ok_self, rep_self, _ = te.execute_buy_equipment_listing(db_session, alice_id, "엘리스", str(listing_id))
    assert ok_self is False
    assert "본인이 등록한 장비" in rep_self

    # 10. Bob buys Alice's listing from the marketplace
    bob_initial_points = bob.points
    alice_points_before_sale = alice.points
    treasury_before = state.treasury_pool

    ok_buy, rep_buy, det_buy = te.execute_buy_equipment_listing(db_session, bob_id, "밥", str(listing_id))
    assert ok_buy is True
    assert "장비 거래 성사" in rep_buy

    db_session.refresh(bob)
    db_session.refresh(alice)
    db_session.refresh(state)
    db_session.refresh(stone_eq)

    # Bob paid 100,000P
    assert bob.points == bob_initial_points - 100000
    # Treasury received 5,000P (5% tax)
    assert state.treasury_pool == treasury_before + 5000
    # Alice received 95,000P (net)
    assert alice.points == alice_points_before_sale + 95000
    # stone_eq ownership transferred to Bob
    assert stone_eq.user_id == bob_id

    # 11. 1:1 Direct Trade: Bob sells stone_eq directly to Alice for 50,000P
    ok_dir, rep_dir, det_dir = te.execute_list_equipment(db_session, bob_id, "밥", str(stone_eq.id), "50000", target_buyer_token="엘리스")
    assert ok_dir is True
    assert "1:1 직거래" in rep_dir
    dir_listing_id = det_dir["listing_id"]

    # Charlie tries to buy it -> blocked because it is reserved for Alice
    charlie = te.get_or_create_user(db_session, "trader_charlie", "찰리")
    charlie.points = 100000
    db_session.commit()
    ok_blocked_c, rep_blocked_c, _ = te.execute_buy_equipment_listing(db_session, "trader_charlie", "찰리", str(dir_listing_id))
    assert ok_blocked_c is False
    assert "전용 1:1 직거래" in rep_blocked_c

    # Alice buys the reserved trade
    ok_alice_buy, rep_alice_buy, _ = te.execute_buy_equipment_listing(db_session, alice_id, "엘리스", str(dir_listing_id))
    assert ok_alice_buy is True
    db_session.refresh(stone_eq)
    assert stone_eq.user_id == alice_id

    # 12. Chat command integration test
    r_chat_inv, _ = ch.handle_chat_command(db_session, alice_id, "엘리스", "!내장비")
    assert "내 장비 인벤토리" in r_chat_inv

    r_chat_market, _ = ch.handle_chat_command(db_session, alice_id, "엘리스", "!장비장터")
    assert "나베 장비 거래소" in r_chat_market

def test_starforce_fever_random_events_and_guaranteed_success(db_session, monkeypatch):
    """
    Test Star Force fever events:
    1. Spontaneous random trigger and automatic expiration.
    2. DISCOUNT_30: 30% discount on upgrade costs.
    3. FEVER_100: 100% guaranteed success on ★5, ★10, ★15 (no destruction!).
    4. SHINING: Both 30% discount and 100% guaranteed success.
    5. Streamer commands (!피버 10, !피버마감) and viewer queries (!피버, !남은시간, !내곡괭이).
    """
    uid = "sf_fever_tester"
    uname = "스타포스러너"
    user = te.get_or_create_user(db_session, uid, uname)
    user.points = 10000000
    db_session.commit()

    eqs = te.ensure_user_equipment(db_session, user)
    eq = eqs[0]

    # 1. Check initial fever state (inactive, next event scheduled)
    st = te.get_starforce_event_state(db_session)
    assert st["is_active"] is False
    assert st["next_event_time"] > 0

    # 2. Spontaneous trigger via force_trigger
    st_trig = te.get_starforce_event_state(db_session, force_trigger=True, manual_type="DISCOUNT_30", manual_duration=10.0)
    assert st_trig["is_active"] is True
    assert st_trig["event_type"] == "DISCOUNT_30"
    assert st_trig["has_discount"] is True
    assert st_trig["has_100_percent"] is False

    # 3. Test 30% discount on upgrade
    # 0성 upgrade cost is normally 2,000P -> with 30% off, cost is 1,400P
    user.pickaxe_level = 0
    eq.starforce = 0
    db_session.commit()
    info_0 = te.get_pickaxe_info(0, event_state=st_trig)
    assert info_0["upgrade_cost"] == 1400
    assert info_0["base_cost"] == 2000
    assert info_0["is_discounted"] is True

    points_before = user.points
    treasury_before = te.get_market_state(db_session).treasury_pool
    # Roll success
    monkeypatch.setattr("random.uniform", lambda a, b: 0.1)
    ok_upg, rep_upg, det_upg = te.execute_pickaxe_upgrade(db_session, uid, uname, str(eq.id))
    assert ok_upg is True
    assert det_upg["cost"] == 1400
    assert det_upg["discount_applied"] is True
    db_session.refresh(user)
    assert user.points == points_before - 1400
    assert te.get_market_state(db_session).treasury_pool == treasury_before + 1400

    # 4. Streamer opens FEVER_100 (5, 10, 15-star 100% success)
    ok_open, rep_open, det_open = te.open_starforce_event(db_session, duration_minutes=15.0, event_type_str="100퍼")
    assert ok_open is True
    assert det_open["event_type"] == "FEVER_100"

    st_fever = te.get_starforce_event_state(db_session)
    assert st_fever["is_active"] is True
    assert st_fever["has_100_percent"] is True
    assert st_fever["has_discount"] is False

    # Check 5-star (5->6성) has 100% success rate
    info_5 = te.get_pickaxe_info(5, event_state=st_fever)
    assert info_5["success_rate"] == 100.0
    assert info_5["is_guaranteed_100"] is True
    assert info_5["maintain_rate"] == 0.0

    # Check 10-star (10->11성) has 100% success rate
    info_10 = te.get_pickaxe_info(10, event_state=st_fever)
    assert info_10["success_rate"] == 100.0
    assert info_10["is_guaranteed_100"] is True

    # Check 15-star (15->16성) has 100% success rate and 0% destruction rate!
    info_15 = te.get_pickaxe_info(15, event_state=st_fever)
    assert info_15["success_rate"] == 100.0
    assert info_15["destroy_rate"] == 0.0
    assert info_15["maintain_rate"] == 0.0
    assert info_15["drop_rate"] == 0.0
    assert info_15["is_guaranteed_100"] is True

    # Perform upgrade at 15-star with high roll (99.0): should STILL succeed with 100% guaranteed success!
    user.pickaxe_level = 15
    eq.starforce = 15
    db_session.commit()
    monkeypatch.setattr("random.uniform", lambda a, b: 99.0)
    ok_15, rep_15, det_15 = te.execute_pickaxe_upgrade(db_session, uid, uname, str(eq.id))
    assert ok_15 is True
    assert det_15["outcome"] == "success"
    assert det_15["new_level"] == 16
    assert det_15["guaranteed_100"] is True
    assert "100% 확정 성공 피버" in rep_15

    # 5. Test SHINING (Shining Star Force: 30% discount AND 100% success)
    ok_shining, _, _ = te.open_starforce_event(db_session, duration_minutes=10.0, event_type_str="샤이닝")
    assert ok_shining is True
    st_shining = te.get_starforce_event_state(db_session)
    assert st_shining["has_discount"] is True
    assert st_shining["has_100_percent"] is True

    # Check 15-star under Shining: 30% discount (300k -> 210k) AND 100% success
    user.pickaxe_level = 15
    eq.starforce = 15
    db_session.commit()
    info_shining_15 = te.get_pickaxe_info(15, event_state=st_shining)
    assert info_shining_15["upgrade_cost"] == 210000
    assert info_shining_15["success_rate"] == 100.0
    assert info_shining_15["destroy_rate"] == 0.0

    monkeypatch.setattr("random.uniform", lambda a, b: 88.8)
    ok_shin_upg, rep_shin_upg, det_shin_upg = te.execute_pickaxe_upgrade(db_session, uid, uname, str(eq.id))
    assert ok_shin_upg is True
    assert det_shin_upg["cost"] == 210000
    assert det_shin_upg["discount_applied"] is True
    assert det_shin_upg["guaranteed_100"] is True
    assert det_shin_upg["new_level"] == 16

    # 6. Test Expiration
    # Set end_time in the past
    state = te.get_market_state(db_session)
    state.sf_event_end_time = time.time() - 10.0
    db_session.commit()
    st_expired = te.get_starforce_event_state(db_session)
    assert st_expired["is_active"] is False

    # 7. Test Chat Commands
    viewer_id = "test_viewer_1"
    streamer_id = ch.CHANNEL_ID

    # Viewer queries !피버
    r_guide, _ = ch.handle_chat_command(db_session, viewer_id, "시청자1", "!피버")
    assert "스타포스 돌발 피버 이벤트 안내" in r_guide or "스타포스 피버" in r_guide

    # Viewer queries !남은시간
    r_time, _ = ch.handle_chat_command(db_session, viewer_id, "시청자1", "!남은시간")
    assert "스타포스:" in r_time

    # Viewer attempts to open fever -> blocked
    r_block, _ = ch.handle_chat_command(db_session, viewer_id, "시청자1", "!피버 10")
    assert "🚫 피버 이벤트 강제 개장은 스트리머" in r_block

    # Streamer opens fever: !피버 10 할인
    r_streamer_open, ev_open = ch.handle_chat_command(db_session, streamer_id, "치즈나베", "!피버 10 할인")
    assert "스타포스 피버 OPEN" in r_streamer_open
    assert ev_open is not None
    assert ev_open["type"] == "starforce_fever_open"

    # Viewer queries !남은시간 during fever
    r_time_active, _ = ch.handle_chat_command(db_session, viewer_id, "시청자1", "!남은시간")
    assert "피버 오픈!" in r_time_active or "비용 30% 할인" in r_time_active

    # Viewer checks !내곡괭이 during fever
    r_pickaxe, _ = ch.handle_chat_command(db_session, viewer_id, "시청자1", "!곡괭이")
    assert "피버 진행중" in r_pickaxe or "30% 할인" in r_pickaxe

    # Streamer closes fever: !피버마감
    r_close, ev_close = ch.handle_chat_command(db_session, streamer_id, "치즈나베", "!피버마감")
    assert "스타포스 피버 종료" in r_close
    assert ev_close["type"] == "starforce_fever_close"

def test_auto_mining_system_and_commands(db_session, monkeypatch):
    """
    Test Auto-Mining system:
    1. Duration scaling based on pickaxe tier (0성 30m, 5성 2h, 10성 4h, 15성 8h, 25성 24h).
    2. Auto-mining tier restrictions: maximum is SR (황금 광맥). Never rolls EX, UR+, UR, SSR.
    3. ON / OFF / Renew operations.
    4. Auto-mining tick execution, share awarding, debt payoff, cooldown check, session tracking.
    5. Expiration handling.
    6. Chat commands: !자동채굴 on/off/갱신/상태, !남은시간, !내정보.
    """
    uid = "auto_miner_1"
    uname = "오토광부"
    user = te.get_or_create_user(db_session, uid, uname)
    user.points = 100000
    db_session.commit()

    # 1. Test Duration Table
    assert te.get_auto_mining_duration_hours(0) == 0.5
    assert te.get_auto_mining_duration_hours(5) == 2.0
    assert te.get_auto_mining_duration_hours(10) == 4.0
    assert te.get_auto_mining_duration_hours(15) == 8.0
    assert te.get_auto_mining_duration_hours(20) == 14.0
    assert te.get_auto_mining_duration_hours(25) == 24.0

    # 2. Test Tier restrictions: maximum is SR (황금 광맥), never rolls higher tiers
    valid_codes = {"SR", "R", "N", "C"}
    for _ in range(100):
        t = te.roll_auto_mining_tier(crit_bonus=50.0)
        assert t["code"] in valid_codes
        assert t["code"] not in {"EX", "UR+", "UR", "SSR"}

    # 3. Test Turning ON
    eqs = te.ensure_user_equipment(db_session, user)
    eq = eqs[0]
    user.pickaxe_level = 5
    eq.starforce = 5
    db_session.commit()

    ok_on, rep_on, det_on = te.set_auto_mining(db_session, uid, uname, enable=True)
    assert ok_on is True
    assert det_on["auto_mining_enabled"] is True
    assert det_on["duration_hours"] == 2.0
    db_session.refresh(user)
    assert user.auto_mining_enabled is True
    assert user.auto_mining_end_time > time.time()

    # 4. Test Auto-Mining Tick Execution
    # Ensure cooldown is ready
    user.last_mined_at = None
    db_session.commit()

    # Mock tier to SR (황금 광맥)
    monkeypatch.setattr("trading_engine.roll_auto_mining_tier", lambda crit_bonus=0.0: {
        "code": "SR",
        "name": "⚡ [자동 채굴] 황금 광맥 크리티컬! (5.0%)",
        "multiplier": 1.6,
        "bonus_cash": 1000,
        "bonus_10x": 0.0,
        "cooldown_reduction": 0
    })

    tick = te.execute_auto_mining_tick(db_session, user)
    assert tick is not None
    assert tick["shares_awarded"] > 0
    assert tick["tier_code"] == "SR"
    db_session.refresh(user)
    assert user.auto_mining_session_mined > 0
    assert user.last_mined_at is not None

    # Immediate second tick should be blocked due to cooldown
    tick_blocked = te.execute_auto_mining_tick(db_session, user)
    assert tick_blocked is None

    # 5. Test Renew
    # Upgrade pickaxe to 15성
    user.pickaxe_level = 15
    eq.starforce = 15
    db_session.commit()

    ok_ren, rep_ren, det_ren = te.renew_auto_mining(db_session, uid, uname)
    assert ok_ren is True
    assert det_ren["duration_hours"] == 8.0
    db_session.refresh(user)
    assert user.auto_mining_end_time > time.time() + 7.9 * 3600

    # 6. Test Expiration
    user.auto_mining_end_time = time.time() - 10.0
    db_session.commit()
    tick_exp = te.execute_auto_mining_tick(db_session, user)
    assert tick_exp is None
    db_session.refresh(user)
    assert user.auto_mining_enabled is False

    # 7. Test Turning OFF
    # Turn back on then off
    te.set_auto_mining(db_session, uid, uname, enable=True)
    ok_off, rep_off, det_off = te.set_auto_mining(db_session, uid, uname, enable=False)
    assert ok_off is True
    assert det_off["auto_mining_enabled"] is False
    db_session.refresh(user)
    assert user.auto_mining_enabled is False

    # Turning OFF when already off
    ok_off2, rep_off2, _ = te.set_auto_mining(db_session, uid, uname, enable=False)
    assert ok_off2 is False
    assert "켜져 있지 않습니다" in rep_off2

    # 8. Test Chat Commands
    r_chat_off, _ = ch.handle_chat_command(db_session, uid, uname, "!자동채굴")
    assert "자동 채굴 상태: 정지" in r_chat_off

    r_cmd_on, ev_on = ch.handle_chat_command(db_session, uid, uname, "!자동채굴 on")
    assert "자동 채굴 활성화" in r_cmd_on
    assert ev_on["type"] == "auto_mining_toggle"

    r_chat_on, _ = ch.handle_chat_command(db_session, uid, uname, "!자동채굴")
    assert "자동 채굴 상태: 가동 중" in r_chat_on

    r_cmd_ren, ev_ren = ch.handle_chat_command(db_session, uid, uname, "!자동채굴 갱신")
    assert "자동 채굴 갱신 완료" in r_cmd_ren
    assert ev_ren["type"] == "auto_mining_renew"

    r_time, _ = ch.handle_chat_command(db_session, uid, uname, "!남은시간")
    assert "자동채굴: 🟢 가동중" in r_time

    r_info, _ = ch.handle_chat_command(db_session, uid, uname, "!내정보")
    assert "자동채굴: 🟢ON" in r_info

    r_cmd_off, ev_off = ch.handle_chat_command(db_session, uid, uname, "!자동채굴 off")
    assert "자동 채굴 비활성화" in r_cmd_off
    assert ev_off["type"] == "auto_mining_toggle"


def test_starforce_fever_extended_intervals(db_session):
    """Test that Star Force Fever event intervals are set to 0.5~1.5 hours (30~90 min) and durations 5~10 mins."""
    assert te.STARFORCE_EVENT_MIN_INTERVAL_MINUTES == 30.0
    assert te.STARFORCE_EVENT_MAX_INTERVAL_MINUTES == 90.0
    assert te.STARFORCE_EVENT_DURATIONS == [5.0, 7.0, 10.0]

    # Check guide text
    guide = te.get_starforce_event_guide(db_session)
    assert "0.5~1.5시간" in guide

    # Test open event
    now = time.time()
    ok, reply, details = te.open_starforce_event(db_session, duration_minutes=7.0, event_type_str="할인")
    assert ok is True
    assert details["is_active"] is True
    assert details["event_type"] == "DISCOUNT_30"

    state = te.get_market_state(db_session)
    assert state.sf_next_event_time >= state.sf_event_end_time + (30.0 * 60.0) - 1.0
    assert state.sf_next_event_time <= state.sf_event_end_time + (90.0 * 60.0) + 1.0

    # Test close event
    ok_close, _, _ = te.close_starforce_event(db_session)
    assert ok_close is True
    db_session.refresh(state)
    assert state.sf_event_type is None
    assert state.sf_next_event_time >= now + (30.0 * 60.0) - 1.0
    assert state.sf_next_event_time <= now + (90.0 * 60.0) + 1.0



def test_cooldown_command(db_session):
    """Test !쿨타임 command and its aliases (!쿨, !cooldown, !cd, !채굴쿨)."""
    uid = "cooldown_tester"
    uname = "쿨타임체커"
    user = te.get_or_create_user(db_session, uid, uname)

    # Initial state: ready to mine, auto-mining OFF
    reply, event = ch.handle_chat_command(db_session, uid, uname, "!쿨타임")
    assert event is None
    assert "쿨타임 & 타이머 현황" in reply
    assert "채굴 쿨:" in reply
    assert "즉시 채굴 가능" in reply
    assert "자동 채굴: 💤 OFF" in reply
    assert "주식장:" in reply
    assert "스타포스 피버:" in reply

    # Aliases
    for alias in ["!쿨", "!cooldown", "!cd", "!채굴쿨"]:
        r_alias, _ = ch.handle_chat_command(db_session, uid, uname, alias)
        assert "쿨타임 & 타이머 현황" in r_alias

    # Mine once to put pickaxe on cooldown
    ok_mine, r_mine, _ = te.execute_mining(db_session, uid, uname)
    assert ok_mine is True

    # Now !쿨타임 should report remaining cooldown
    reply_cd, _ = ch.handle_chat_command(db_session, uid, uname, "!쿨타임")
    assert "남음" in reply_cd
    assert "즉시 채굴 가능" not in reply_cd

    # Enable auto-mining
    te.set_auto_mining(db_session, uid, uname, enable=True)
    reply_am, _ = ch.handle_chat_command(db_session, uid, uname, "!쿨타임")
    assert "자동 채굴: 🟢 가동 중" in reply_am


def test_equipment_listing_starforce_preservation(db_session):
    """Test that listing an equipment does not reset its starforce to 0, even if it's the user's only item."""
    uid = "seller_preserve_test"
    uname = "스타포스보존자"
    user = te.get_or_create_user(db_session, uid, uname)

    # Give user a single 8-star equipment (just like 메루1's bug report)
    items = te.ensure_user_equipment(db_session, user)
    assert len(items) == 1
    items[0].starforce = 8
    items[0].name = te.get_pickaxe_info(8)["name"]
    user.pickaxe_level = 8
    db_session.commit()
    target_eq_id = items[0].id

    # List the equipment on the marketplace
    ok, reply, details = te.execute_list_equipment(db_session, uid, uname, str(target_eq_id), "50000")
    assert ok is True
    assert details["starforce"] == 8
    listing_id = details["listing_id"]

    # Refresh equipment from db and verify its starforce is STILL 8
    eq_in_db = db_session.query(UserEquipment).filter_by(id=target_eq_id).first()
    assert eq_in_db.starforce == 8, f"Expected 8, got {eq_in_db.starforce}"
    assert "★8성" in eq_in_db.name
    assert eq_in_db.is_equipped is False

    # Check inventory query (!내장비)
    inv_reply = te.get_user_inventory_status(db_session, uid, uname)
    assert "★8성" in inv_reply
    assert f"거래#{listing_id}판매중" in inv_reply

    # Check marketplace listings query (!장비장터)
    mkt_reply = te.get_equipment_market_listings(db_session)
    assert "★8성" in mkt_reply
    assert f"거래 #{listing_id}" in mkt_reply

    # Verify calling ensure_user_equipment again does NOT reset the item's starforce
    items_again = te.ensure_user_equipment(db_session, user)
    db_session.refresh(eq_in_db)
    assert eq_in_db.starforce == 8

    # Reclaim/cancel listing (!장비회수)
    ok_cancel, r_cancel, _ = te.execute_cancel_equipment_listing(db_session, uid, uname, str(listing_id))
    assert ok_cancel is True
    db_session.refresh(eq_in_db)
    assert eq_in_db.starforce == 8
    assert eq_in_db.is_equipped is True
    assert user.pickaxe_level == 8


def test_equipment_listing_buy_transfer_starforce(db_session):
    """Test that buying a listed equipment transfers the item with full starforce and equips it on buyer."""
    seller_id = "seller_user"
    buyer_id = "buyer_user"
    seller = te.get_or_create_user(db_session, seller_id, "판매자")
    buyer = te.get_or_create_user(db_session, buyer_id, "구매자")
    buyer.points = 100000
    db_session.commit()

    # Seller has 15-star golden pickaxe
    seller_items = te.ensure_user_equipment(db_session, seller)
    seller_items[0].starforce = 15
    seller_items[0].name = te.get_pickaxe_info(15)["name"]
    seller.pickaxe_level = 15
    db_session.commit()
    target_id = seller_items[0].id

    # Record initial seller points
    initial_seller_pts = seller.points

    # Seller lists item for 20000P
    ok_list, _, details = te.execute_list_equipment(db_session, seller_id, "판매자", str(target_id), "20000")
    assert ok_list is True
    listing_id = details["listing_id"]

    # Buyer buys the item
    ok_buy, reply_buy, _ = te.execute_buy_equipment_listing(db_session, buyer_id, "구매자", str(listing_id))
    assert ok_buy is True

    # Buyer now has the 15-star golden pickaxe equipped
    bought_eq = db_session.query(UserEquipment).filter_by(id=target_id).first()
    assert bought_eq.user_id == buyer_id
    assert bought_eq.starforce == 15
    assert bought_eq.is_equipped is True
    assert buyer.pickaxe_level == 15

    # Seller has received points minus tax
    assert seller.points == initial_seller_pts + (20000 - details["tax_fee"])


def test_cube_purchase_and_validation(db_session):
    """Test execute_buy_cubes validation, debt checking, batch buying, and treasury pool credit."""
    uid = "cube_buy_tester"
    uname = "큐브구매테스터"
    user = te.get_or_create_user(db_session, uid, uname)
    user.points = 100000
    state = te.get_market_state(db_session)
    init_treasury = state.treasury_pool

    # 1. Buy 2 cubes
    ok, reply, details = te.execute_buy_cubes(db_session, uid, uname, "2")
    assert ok is True
    assert details["quantity"] == 2
    assert details["total_cost"] == 30000
    assert user.cube_count == 2
    assert user.points == 70000
    assert state.treasury_pool == init_treasury + 30000
    assert "구매 완료" in reply

    # 2. Buy with invalid quantity
    ok_inv, reply_inv, _ = te.execute_buy_cubes(db_session, uid, uname, "abc")
    assert ok_inv is False
    assert "사용법" in reply_inv

    # 3. Buy with insufficient points
    ok_insuf, reply_insuf, _ = te.execute_buy_cubes(db_session, uid, uname, "100")
    assert ok_insuf is False
    assert "부족" in reply_insuf

    # 4. Buy all-in / 최대
    ok_max, reply_max, det_max = te.execute_buy_cubes(db_session, uid, uname, "최대")
    assert ok_max is True
    assert det_max["quantity"] == 70000 // te.CUBE_COST  # 4 cubes (60,000P)
    assert user.cube_count == 2 + 4


def test_cube_first_use_and_promotion(db_session):
    """Test pre-purchase requirement and first cube on NONE potential equipment promotes to RARE 100%."""
    uid = "cube_tester_1"
    uname = "큐브테스터1"
    user = te.get_or_create_user(db_session, uid, uname)
    user.points = 50000
    state = te.get_market_state(db_session)
    initial_treasury = state.treasury_pool
    items = te.ensure_user_equipment(db_session, user)
    eq = items[0]
    assert eq.potential_tier == "NONE"

    # 1. Use without cubes -> must fail with purchase guide
    ok_fail, reply_fail, _ = te.execute_cube_use(db_session, uid, uname)
    assert ok_fail is False
    assert "보유한 큐브가 없습니다" in reply_fail
    assert "!큐브구매" in reply_fail

    # 2. Purchase 1 cube
    ok_buy, reply_buy, det_buy = te.execute_buy_cubes(db_session, uid, uname, "1")
    assert ok_buy is True
    assert user.cube_count == 1
    assert user.points == 50000 - te.CUBE_COST
    assert state.treasury_pool == initial_treasury + te.CUBE_COST

    # 3. Use cube
    ok, reply, details = te.execute_cube_use(db_session, uid, uname)
    assert ok is True
    assert details["old_tier"] == "NONE"
    assert details["new_tier"] == "RARE"
    assert details["promoted"] is True
    assert user.cube_count == 0
    assert user.cube_fragments == 1
    assert eq.potential_tier == "RARE"
    assert eq.pity_count == 0

    # 3 lines must be present and valid JSON
    line1 = json.loads(eq.potential_line_1)
    line2 = json.loads(eq.potential_line_2)
    line3 = json.loads(eq.potential_line_3)
    assert line1["tier"] == "RARE"
    assert line2["tier"] == "RARE"
    assert line3["tier"] == "RARE"
    assert "code" in line1 and "val" in line1


def test_cube_pity_progression(db_session, monkeypatch):
    """Test pity guarantee ceilings (10 for RARE, 42 for EPIC, 107 for UNIQUE)."""
    uid = "cube_pity_tester"
    uname = "천장테스터"
    user = te.get_or_create_user(db_session, uid, uname)
    user.points = 10000000
    user.cube_count = 10
    items = te.ensure_user_equipment(db_session, user)
    eq = items[0]

    # Force probability roll to fail so only pity triggers promotion
    monkeypatch.setattr(random, "uniform", lambda a, b: 99.9)

    # 1. RARE -> EPIC at pity 10
    eq.potential_tier = "RARE"
    eq.pity_count = 9
    db_session.commit()

    ok, reply, details = te.execute_cube_use(db_session, uid, uname)
    assert ok is True
    assert details["new_tier"] == "EPIC"
    assert details["pity_triggered"] is True
    assert eq.potential_tier == "EPIC"
    assert eq.pity_count == 0

    # 2. EPIC -> UNIQUE at pity 42
    user.cube_count = 10
    eq.potential_tier = "EPIC"
    eq.pity_count = 41
    db_session.commit()

    ok, reply, details = te.execute_cube_use(db_session, uid, uname)
    assert ok is True
    assert details["new_tier"] == "UNIQUE"
    assert details["pity_triggered"] is True
    assert eq.potential_tier == "UNIQUE"
    assert eq.pity_count == 0

    # 3. UNIQUE -> LEGENDARY at pity 107
    user.cube_count = 10
    eq.potential_tier = "UNIQUE"
    eq.pity_count = 106
    db_session.commit()

    ok, reply, details = te.execute_cube_use(db_session, uid, uname)
    assert ok is True
    assert details["new_tier"] == "LEGENDARY"
    assert details["pity_triggered"] is True
    assert eq.potential_tier == "LEGENDARY"
    assert eq.pity_count == 0


def test_cube_fragment_exchange(db_session):
    """Test 10 Cube Fragments exchange for 15,000P refund."""
    uid = "frag_tester"
    uname = "조각테스터"
    user = te.get_or_create_user(db_session, uid, uname)
    user.points = 10000
    user.cube_fragments = 9
    db_session.commit()

    # 9 fragments -> fails
    ok, reply, _ = te.execute_cube_fragment_exchange(db_session, uid, uname)
    assert ok is False
    assert "부족" in reply

    # 10 fragments -> succeeds (+15,000P)
    user.cube_fragments = 10
    db_session.commit()
    ok, reply, details = te.execute_cube_fragment_exchange(db_session, uid, uname)
    assert ok is True
    assert user.points == 25000
    assert user.cube_fragments == 0
    assert "교환 완료" in reply


def test_cube_potential_effects_aggregation(db_session):
    """Test that get_equipment_potential_effects properly sums multiple lines and respects balance caps."""
    uid = "agg_user"
    uname = "합산유저"
    user = te.get_or_create_user(db_session, uid, uname)
    items = te.ensure_user_equipment(db_session, user)
    eq = items[0]

    eq.potential_tier = "LEGENDARY"
    eq.potential_line_1 = json.dumps({"code": "MINING_BONUS_CASH", "val": 60000, "text": "+60,000P"})
    eq.potential_line_2 = json.dumps({"code": "MINING_BONUS_CASH", "val": 25000, "text": "+25,000P"})
    eq.potential_line_3 = json.dumps({"code": "MINING_CD_RESET", "val": 15.0, "text": "15%"})
    db_session.commit()

    effects = te.get_equipment_potential_effects(eq)
    assert effects["bonus_cash"] == 85000
    assert effects["cd_reset_pct"] == 15.0
    assert effects["yield_boost"] == 0.0


def test_cube_mining_effects(db_session, monkeypatch):
    """Test mining bonuses and cooldown reset triggered by potential lines."""
    uid = "mine_cube_user"
    uname = "채굴큐브유저"
    user = te.get_or_create_user(db_session, uid, uname)
    user.points = 100000
    items = te.ensure_user_equipment(db_session, user)
    eq = items[0]

    eq.potential_tier = "LEGENDARY"
    eq.potential_line_1 = json.dumps({"code": "MINING_BONUS_CASH", "val": 60000, "text": "+60000P"})
    eq.potential_line_2 = json.dumps({"code": "MINING_YIELD_BOOST", "val": 2.0, "text": "+2.0x"})
    eq.potential_line_3 = json.dumps({"code": "MINING_CD_RESET", "val": 15.0, "text": "15%"})
    db_session.commit()

    # Test bonus cash awarded in mining
    ok, reply, details = te.execute_mining(db_session, uid, uname)
    assert ok is True
    assert details["potential_bonus_cash"] == 60000
    assert details["total_bonus_cash"] >= 60000
    assert "잠재 현금 +60,000P" in reply

    # Test CD reset hook by setting random to 0.01 (< 15%)
    monkeypatch.setattr(random, "uniform", lambda a, b: 0.01)
    user.last_mined_at = None
    db_session.commit()
    ok_reset, reply_reset, det_reset = te.execute_mining(db_session, uid, uname)
    assert ok_reset is True
    assert det_reset["cd_reset_triggered"] is True
    assert user.last_mined_at is None
    assert "⚡잠재 쿨초 발동" in reply_reset


def test_cube_casino_and_starforce_effects(db_session, monkeypatch):
    """Test slot boost, dice payback, starforce discount, and safeguard protection."""
    uid = "gamble_sf_user"
    uname = "도박강화유저"
    user = te.get_or_create_user(db_session, uid, uname)
    user.points = 500000
    items = te.ensure_user_equipment(db_session, user)
    eq = items[0]

    # Equip item with slot boost, dice payback, sf discount & safeguard
    eq.potential_tier = "LEGENDARY"
    eq.potential_line_1 = json.dumps({"code": "CASINO_SLOT_BOOST", "val": 50.0, "text": "+50%"})
    eq.potential_line_2 = json.dumps({"code": "CASINO_DICE_PAYBACK", "val": 40.0, "text": "40%"})
    eq.potential_line_3 = json.dumps({"code": "STARFORCE_SAFEGUARD", "val": 50.0, "text": "50%"})
    db_session.commit()

    # 1. Slot gamble boost
    te.open_casino(db_session, 100000)
    monkeypatch.setattr(random, "choices", lambda syms, weights, k: ["💎", "💎", "💎"])
    ok_slot, reply_slot, det_slot = te.execute_slot_gamble(db_session, uid, uname, "1000")
    assert ok_slot is True
    assert det_slot["won"] is True
    assert "잠재 배당 +50%" in reply_slot

    # 2. Dice gamble payback on loss
    monkeypatch.setattr(random, "randint", lambda a, b: 1) # 1+1 = 2 (Even)
    # Bet on "홀" (Odd) -> Loss!
    initial_pts = user.points
    ok_dice, reply_dice, det_dice = te.execute_dice_gamble(db_session, uid, uname, "홀", "10000")
    assert ok_dice is True
    assert det_dice["won"] is False
    assert "잠재 페이백 40% 발동" in reply_dice
    # Net loss should be 10000 - 4000 = 6000
    assert user.points == initial_pts - 6000

    # 3. Starforce Safeguard on 15성+ destruction
    eq.starforce = 15
    user.pickaxe_level = 15
    eq.name = te.get_pickaxe_info(15)["name"]
    db_session.commit()
    # Mock roll into destruction range (99.9) and safeguard roll (10.0 < 50%)
    sf_rolls = []
    def mock_roll(a, b):
        if a == 0 and b == 100:
            sf_rolls.append(1)
            if len(sf_rolls) == 1:
                return 99.9  # Destruction roll
            return 10.0      # Safeguard roll (< 50% safeguard succeeds!)
        return 60.0          # Event interval scheduling
    monkeypatch.setattr(random, "uniform", mock_roll)

    ok_sf, reply_sf, det_sf = te.execute_pickaxe_upgrade(db_session, uid, uname)
    assert ok_sf is True
    assert det_sf["outcome"] == "safeguarded_drop"
    assert eq.starforce == 14  # Dropped to 14 instead of being destroyed to 12!
    assert "세이프가드" in reply_sf


def test_cube_chat_commands(db_session):
    """Test !큐브구매, !큐브, and !큐브조각 via command_handler."""
    uid = "chat_cmd_cube_user"
    uname = "채팅큐브유저"
    user = te.get_or_create_user(db_session, uid, uname)
    user.points = 100000
    items = te.ensure_user_equipment(db_session, user)

    # 1. !큐브 command without cube -> should fail and guide to !큐브구매
    reply_fail, ev_fail = ch.handle_chat_command(db_session, uid, uname, "!큐브")
    assert "보유한 큐브가 없습니다" in reply_fail
    assert "!큐브구매" in reply_fail
    assert ev_fail is None

    # 2. !큐브구매 command
    reply_buy, ev_buy = ch.handle_chat_command(db_session, uid, uname, "!큐브구매 2")
    assert "미라클 큐브 구매 완료" in reply_buy
    assert ev_buy is not None
    assert ev_buy["type"] == "cube_buy"
    assert ev_buy["data"]["cube_count"] == 2

    # 3. !내정보 includes cube count
    reply_info, _ = ch.handle_chat_command(db_session, uid, uname, "!내정보")
    assert "큐브: 2개" in reply_info

    # 4. !큐브 command with cube -> succeeds and consumes 1 cube
    reply, event = ch.handle_chat_command(db_session, uid, uname, "!큐브")
    assert "미라클 큐브 사용" in reply
    assert event is not None
    assert event["type"] == "cube_use"
    assert event["data"]["cube_count"] == 1

    # 5. Check pickaxe view includes potential & cubes
    reply_pick, _ = ch.handle_chat_command(db_session, uid, uname, "!곡괭이")
    assert "잠재능력:" in reply_pick
    assert "보유 큐브:" in reply_pick
    assert "큐브 조각:" in reply_pick

    # 6. Exchange fragments command (!큐브조각)
    user.cube_fragments = 10
    db_session.commit()
    reply_frag, ev_frag = ch.handle_chat_command(db_session, uid, uname, "!큐브조각")
    assert "큐브 조각 교환 완료" in reply_frag
    assert ev_frag is not None
    assert ev_frag["type"] == "cube_fragment_exchange"


def test_status_window_aliases(db_session):
    """Test !상태창, !스테이터스, !스펙, !status command aliases."""
    uid = "status_window_user"
    uname = "상태창유저"
    user = te.get_or_create_user(db_session, uid, uname)
    user.points = 200000
    items = te.ensure_user_equipment(db_session, user)

    for alias in ["!상태창", "!스테이터스", "!스펙", "!status", "!spec"]:
        reply, event = ch.handle_chat_command(db_session, uid, uname, alias)
        assert "상태창" in reply or "내 곡괭이 정보" in reply
        assert "장비:" in reply
        assert "채굴량" in reply
        assert "보유 큐브:" in reply
        assert event is None


def test_new_potential_options_hooks(db_session, monkeypatch):
    """Test the 5 new potential options: Starforce success boost, mining CD reduction, treasury loot, dividend boost, and goblin jackpot."""
    uid = "new_opt_tester"
    uname = "신규옵션테스터"
    user = te.get_or_create_user(db_session, uid, uname)
    user.points = 500000
    state = te.get_market_state(db_session)
    state.treasury_pool = 10000000  # 10 million points
    items = te.ensure_user_equipment(db_session, user)
    eq = items[0]

    # 1. Test MINING_CD_REDUCTION (cooldown reduction from 15 min to 12 min)
    eq.potential_tier = "LEGENDARY"
    eq.potential_line_1 = json.dumps({"code": "MINING_CD_REDUCTION", "val": 3, "text": "-3분"})
    eq.potential_line_2 = json.dumps({"code": "TREASURY_LOOT_PCT", "val": 0.25, "text": "0.25%"})
    eq.potential_line_3 = json.dumps({"code": "GOBLIN_JACKPOT_CHANCE", "val": 3.0, "tier": "LEGENDARY", "text": "3%"})
    db_session.commit()

    cd_status = te.get_user_cooldown_status(db_session, uid, uname)
    assert "12분" in cd_status

    # 2. Test TREASURY_LOOT_PCT and GOBLIN_JACKPOT_CHANCE in mining
    # Force goblin roll to succeed (< 3%)
    monkeypatch.setattr(random, "uniform", lambda a, b: 0.5)
    ok_mine, reply_mine, det_mine = te.execute_mining(db_session, uid, uname)
    assert ok_mine is True
    assert det_mine["treasury_looted_cash"] == int(10000000 * 0.0025)  # 25,000P
    assert det_mine["goblin_triggered"] is True
    assert det_mine["goblin_reward"] == 300000
    assert "국고 털이" in reply_mine
    assert "황금고블린" in reply_mine

    # 3. Test STARFORCE_SUCCESS_BOOST
    eq.potential_line_1 = json.dumps({"code": "STARFORCE_SUCCESS_BOOST", "val": 6.0, "text": "+6.0%"})
    db_session.commit()
    # Starforce roll: pass if below (success_rate + 6.0%)
    sf_info = te.get_pickaxe_info(eq.starforce)
    base_s = sf_info["success_rate"]
    # Mock roll just above base_s but below base_s + 6.0
    monkeypatch.setattr(random, "uniform", lambda a, b: base_s + 1.0)
    ok_sf, reply_sf, det_sf = te.execute_pickaxe_upgrade(db_session, uid, uname)
    assert ok_sf is True
    assert det_sf["outcome"] == "success"
    assert "성공" in reply_sf

    # 4. Test DIVIDEND_BOOST_PCT in settlement
    eq.potential_line_1 = json.dumps({"code": "DIVIDEND_BOOST_PCT", "val": 100.0, "text": "+100%"})
    db_session.commit()
    # Buy 10 shares of 1X
    pos = Position(
        user_id=user.id,
        product_type=ProductType.ONE_X,
        quantity=10.0,
        entry_price=1000.0,
        invested_cash=10000.0
    )
    db_session.add(pos)
    mstate = te.get_market_state(db_session)
    mstate.current_rank_point = 1000
    mstate.current_price = 1000
    db_session.commit()
    det_settle = te.settle_match(db_session, rank=1, point_delta=0)
    div_entry = next((d for d in det_settle["dividends"] if d["user_id"] == user.id and d["shares"] == 10.0), None)
    assert div_entry is not None
    assert div_entry["payout"] == 1000
    assert div_entry["dividend_boost_pct"] == 100.0











