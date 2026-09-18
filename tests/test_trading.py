import os
import time
import json
import random
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base
from models import (
    User, Position, MarketState, LimitOrder, ProductType,
    OrderType, OrderStatus, UserEquipment, EquipmentListing, ItemListing,
    UserAssetHistory, ArenaMatchLog
)
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

    # 2. Try to borrow exceeds MAX_LOAN_LIMIT -> rejected
    ok2, msg2, details2 = te.execute_borrow(db_session, u, "빚쟁이", str(te.MAX_LOAN_LIMIT + 1000))
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
    assert user.debt > 0
    assert user.debt <= te.MAX_LOAN_LIMIT
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

def test_donation_charging_one_to_thousand(db_session):
    # 1. 1,000 KRW donation -> 1,000,000 Points (1:1000)
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
    assert "1,000,000P 충전 완료" in reply
    assert details["points_credited"] == 1000000
    assert details["pay_amount"] == 1000

    user = te.get_or_create_user(db_session, "donor_001", "큰손나베팬")
    assert user.points >= 1000000

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
    assert d2["points_credited"] == 5000000
    assert user.points >= 6000000

    # 4. Check donation history
    hist = te.get_donation_history(db_session, limit=10)
    assert len(hist) >= 2
    assert hist[0]["pay_amount"] == 5000
    assert hist[0]["points_credited"] == 5000000

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
    assert details_jackpot["net_payout"] == 75000  # 15% of 500k treasury pool = 75,000P
    db_session.refresh(user)
    assert user.points > 50000

    # 5. Rig slot spin to Yakuman 8x: ['🀄', '🀄', '🀄']
    user.points = 50000
    db_session.commit()
    monkeypatch.setattr("random.choices", lambda *args, **kwargs: ["🀄", "🀄", "🀄"])
    ok_yaku, reply_yaku, details_yaku = te.execute_slot_gamble(db_session, uid, uname, "1000")
    assert ok_yaku is True
    assert details_yaku["net_payout"] == 7000  # 8x total payout (net +7,000P)
    db_session.refresh(user)
    assert user.points == 50000 + 7000

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

    # 7. Rig slot spin to 2-matching standard pair: ['🍒', '🍒', '💣'] -> 1.6x payout (net +0.6x)
    user.points = 50000
    db_session.commit()
    monkeypatch.setattr("random.choices", lambda *args, **kwargs: ["🍒", "🍒", "💣"])
    ok_pair, reply_pair, details_pair = te.execute_slot_gamble(db_session, uid, uname, "1000")
    assert ok_pair is True
    assert details_pair["won"] is True
    assert details_pair["net_payout"] == 600 # 1.6x total payout (net +0.6x)
    db_session.refresh(user)
    assert user.points == 50600

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
    assert details_100k["net_payout"] == 700000  # 8x total payout (net +700,000P uncapped!)
    db_session.refresh(user)
    assert user.points == 200000 + 700000

    # 10. Bet over 100,000P on slot is rejected
    ok_over, reply_over, _ = te.execute_slot_gamble(db_session, uid, uname, "100001")
    assert ok_over is False
    assert "최대 베팅 한도" in reply_over

def test_casino_dice_gamble(db_session, monkeypatch):
    """Test 2-dice high-roller battle mechanics including odd/even/high/low and double 2.2x critical."""
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
    assert details["net_payout"] == 800 # 1.8x payout (net +0.8x)
    db_session.refresh(user)
    assert user.points == 50800

    # 2. Critical Double 2.2x jackpot: roll (6, 6) -> sum = 12
    dice_double = iter([6, 6])
    monkeypatch.setattr("random.randint", lambda a, b: next(dice_double))
    ok_d, reply_d, details_d = te.execute_dice_gamble(db_session, uid, uname, "대", "2000")
    assert ok_d is True
    assert details_d["won"] is True
    assert details_d["is_critical"] is True
    assert details_d["net_payout"] == 2400 # 2.2x payout (net +1.2x)
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
    assert det_100k["net_payout"] == 120000  # 2.2x payout -> net +120,000P uncapped!
    db_session.refresh(user)
    assert user.points == 200000 + 120000

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

    # Streamer opening casino with default max bet -> 10,000,000P
    r2, ev2 = ch.handle_chat_command(db_session, streamer_id, streamer_name, "!카지노오픈 5")
    assert "OPEN" in r2 or "열었습니다" in r2
    assert "10,000,000P" in r2
    assert ev2 is not None
    assert ev2["type"] == "casino_open"
    assert ev2["data"]["max_bet"] == 10000000

    # Viewer querying casino status shows 10,000,000P limit
    r3, _ = ch.handle_chat_command(db_session, viewer_id, viewer_name, "!카지노")
    assert "영업중" in r3
    assert "10,000,000P" in r3

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
    assert user.debt == 500000
    assert user.points == 510000

    # 5. Loan repay (!상환 10000) also allowed during games
    r_repay, ev_repay = ch.handle_chat_command(db_session, uid, uname, "!상환 10000")
    assert r_repay is not None
    assert "상환 완료" in r_repay
    db_session.refresh(user)
    assert user.debt == 490000
    assert user.points == 500000

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

    # Streamer opening casino with !카지노오픈 defaults to 10,000,000P
    r_open, _ = ch.handle_chat_command(db_session, "admin", "스트리머", "!카지노오픈")
    assert "10,000,000P" in r_open

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

    # 10,000P ~ 99,999P: 0.1% tax (이체 수수료)
    tax, rate, label = te.calculate_transfer_tax(10000)
    assert tax == 10
    assert rate == 0.001
    assert label == "이체 수수료"

    tax, rate, label = te.calculate_transfer_tax(50000)
    assert tax == 50

    # 100,000P+: 0.2% tax (이체 수수료)
    tax, rate, label = te.calculate_transfer_tax(100000)
    assert tax == 200
    assert rate == 0.002
    assert label == "이체 수수료"

    tax, rate, label = te.calculate_transfer_tax(200000)
    assert tax == 400

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

    # 2. Transfer with 0.1% tax (>= 10,000P): e.g. 20,000P (tax = 20P, net = 19,980P)
    ok, reply, details = te.execute_transfer(db_session, "u1_transfer", "보내는사람", "받는사람", "20000")
    assert ok is True
    assert details["amount"] == 20000
    assert details["tax"] == 20
    assert details["recipient_net"] == 19980
    assert u1.points == 175000
    assert u2.points == 34980
    assert state.treasury_pool == treasury_initial + 20
    assert "이체 수수료(0.1%): 20P 국고 적립" in reply

    # 3. Transfer with 0.2% tax (>= 100,000P): e.g. 100,000P (tax = 200P, net = 99,800P)
    ok, reply, details = te.execute_transfer(db_session, "u1_transfer", "보내는사람", "받는사람", "10만")
    assert ok is True
    assert details["amount"] == 100000
    assert details["tax"] == 200
    assert details["recipient_net"] == 99800
    assert u1.points == 75000
    assert u2.points == 134780
    assert state.treasury_pool == treasury_initial + 20 + 200
    assert "이체 수수료(0.2%): 200P 국고 적립" in reply

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

def test_mining_tier_coal_immunity_and_jackpot_rate():
    # 1. Test 15+ pickaxe level never rolls Coal (C) and has generous high tier rates
    results = []
    random.seed(42)
    for _ in range(500):
        t = te.roll_mining_tier(crit_bonus=45.0, pickaxe_level=15)
        assert t["code"] != "C", "15성 이상 곡괭이는 석탄(C) 광맥이 나오지 않아야 합니다."
        results.append(t["code"])

    # 15성 여유로운 보정: 잭팟(EX+UR++UR) >= 12% 및 고등급(SR+) >= 45%
    jackpot_count = sum(1 for c in results if c in ["EX", "UR+", "UR"])
    high_tier_count = sum(1 for c in results if c in ["EX", "UR+", "UR", "SSR", "SR"])
    assert jackpot_count / len(results) >= 0.12, f"15성 잭팟 확률({jackpot_count/len(results):.2%})이 기대치보다 낮습니다."
    assert high_tier_count / len(results) >= 0.45, f"15성 고등급 출현율({high_tier_count/len(results):.2%})이 기대치보다 낮습니다."

    # 2. Test pickaxe info contains coal immunity description for 15+
    info_14 = te.get_pickaxe_info(14)
    info_15 = te.get_pickaxe_info(15)
    assert "석탄 면제" not in info_14["desc"]
    assert "석탄 면제" in info_15["desc"]

    # 3. Test 17-star + unique potential (crit_bonus=74.0, pickaxe_level=17)
    # Never rolls Coal (C)
    for _ in range(200):
        t = te.roll_mining_tier(crit_bonus=74.0, pickaxe_level=17)
        assert t["code"] != "C"

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

    # 5. Test 11성 failure (MapleStory rule: No drop, maintains 11성)
    user.pickaxe_level = 11
    db_session.commit()
    # 11성: success 47.25, maintain 52.75 -> roll 60 is maintain
    monkeypatch.setattr(random, "uniform", lambda a, b: 60.0)
    ok11, rep11, det11 = te.execute_pickaxe_upgrade(db_session, u, "스타포스장인")
    assert ok11 is True
    assert det11["outcome"] == "maintain"
    assert det11["new_level"] == 11
    assert user.pickaxe_level == 11

    # 6. Test 17성 destruction (15+ stars blow-up -> restores to 12성)
    user.pickaxe_level = 17
    db_session.commit()
    # 17성: success 15.75, maintain 77.51 (cumul 93.26), destroy 6.74 (roll 95 is destroy)
    monkeypatch.setattr(random, "uniform", lambda a, b: 95.0)
    ok17, rep17, det17 = te.execute_pickaxe_upgrade(db_session, u, "스타포스장인")
    assert ok17 is True
    assert det17["outcome"] == "destroyed"
    assert det17["new_level"] == 12  # MapleStory trace restoration!
    assert user.pickaxe_level == 12
    assert "폭발 파괴" in rep17
    assert "12성" in rep17

    # 7. Debt test: indebted user can upgrade freely
    user.points = 150000
    user.debt = 100000
    db_session.commit()
    ok_debt, msg_debt, _ = te.execute_pickaxe_upgrade(db_session, u, "스타포스장인")
    assert ok_debt is True

    # 8. Max level 30 check
    user.debt = 0
    user.pickaxe_level = 30
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

    # 2. Alice buys a new equipment (5성 돌 곡괭이 for 80,000P)
    ok_b, rep_b, det_b = te.execute_buy_equipment(db_session, alice_id, "엘리스", "5")
    assert ok_b is True
    assert det_b["cost"] == 80000
    assert det_b["starforce"] == 5
    assert det_b["is_equipped"] is False # Goes to inventory since Alice already had equipped item
    assert state.treasury_pool == 580000
    db_session.refresh(alice)
    assert alice.points == 920000

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


def test_starforce_fever_frequent_intervals(db_session):
    """Test that Star Force Fever event intervals are set to 15~30 mins and durations 5~10 mins."""
    assert te.STARFORCE_EVENT_MIN_INTERVAL_MINUTES == 15.0
    assert te.STARFORCE_EVENT_MAX_INTERVAL_MINUTES == 30.0
    assert te.STARFORCE_EVENT_DURATIONS == [5.0, 7.0, 10.0]

    # Check guide text
    guide = te.get_starforce_event_guide(db_session)
    assert "15~30분" in guide

    # Test open event
    now = time.time()
    ok, reply, details = te.open_starforce_event(db_session, duration_minutes=7.0, event_type_str="할인")
    assert ok is True
    assert details["is_active"] is True
    assert details["event_type"] == "DISCOUNT_30"

    state = te.get_market_state(db_session)
    assert state.sf_next_event_time >= state.sf_event_end_time + (15.0 * 60.0) - 1.0
    assert state.sf_next_event_time <= state.sf_event_end_time + (30.0 * 60.0) + 1.0

    # Test close event
    ok_close, _, _ = te.close_starforce_event(db_session)
    assert ok_close is True
    db_session.refresh(state)
    assert state.sf_event_type is None
    assert state.sf_next_event_time >= now + (15.0 * 60.0) - 1.0
    assert state.sf_next_event_time <= now + (30.0 * 60.0) + 1.0



def test_cooldown_command(db_session, monkeypatch):
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

    # Mine once to put pickaxe on cooldown (mock to N tier so EX cooldown reduction doesn't reset it)
    monkeypatch.setattr(te, "roll_mining_tier", lambda *a, **kw: {
        "code": "N",
        "name": "⛏️ [평범한 구리 광맥 일반 채굴 (37.0%)]",
        "multiplier": 1.0,
        "bonus_cash": 0,
        "bonus_10x": 0.0,
        "cooldown_reduction": 0,
    })
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

    # 1. Slot gamble win with winning boost potential (capped at 35%)
    te.open_casino(db_session, 100000)
    monkeypatch.setattr(random, "choices", lambda syms, weights, k: ["🀄", "🀄", "🀄"])
    initial_pts = user.points
    ok_slot, reply_slot, det_slot = te.execute_slot_gamble(db_session, uid, uname, "10000")
    assert ok_slot is True
    assert det_slot["won"] is True
    assert "잠재 당첨 보너스 +35% 발동" in reply_slot
    # Base 8x total payout = 80,000P (net 70,000P). With 35% boost: 80,000 * 0.35 = 28,000P bonus. Net = 98,000P.
    assert det_slot["net_payout"] == 98000
    assert user.points == initial_pts + 98000

    # 2. Dice gamble payback on loss (40% capped at 30%)
    monkeypatch.setattr(random, "randint", lambda a, b: 1) # 1+1 = 2 (Even)
    # Bet on "홀" (Odd) -> Loss!
    initial_pts = user.points
    ok_dice, reply_dice, det_dice = te.execute_dice_gamble(db_session, uid, uname, "홀", "10000")
    assert ok_dice is True
    assert det_dice["won"] is False
    assert "잠재 환급 30% 발동" in reply_dice
    # Net loss should be 10000 - 3000 = 7000 (40% capped at 30%)
    assert user.points == initial_pts - 7000

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
    assert det_mine["goblin_reward"] == 3500000
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

def test_leverage_20x_unlock_and_mechanics(db_session):
    """Test 20X, 40X, 60X & INV parsing, stacking lines (1: 20X, 2: 40X, 3: 60X), and settlement liquidations."""
    # 1. Parsing tests
    assert te.parse_product_type("20X") == ProductType.TWENTY_X
    assert te.parse_product_type("20x") == ProductType.TWENTY_X
    assert te.parse_product_type("20배") == ProductType.TWENTY_X
    assert te.parse_product_type("20레버") == ProductType.TWENTY_X
    assert te.parse_product_type("20롱") == ProductType.TWENTY_X
    assert te.parse_product_type("20X_INV") == ProductType.TWENTY_X_INV
    assert te.parse_product_type("20숏") == ProductType.TWENTY_X_INV
    assert te.parse_product_type("20곱") == ProductType.TWENTY_X_INV
    assert te.parse_product_type("20인") == ProductType.TWENTY_X_INV
    assert te.parse_product_type("인버스20X") == ProductType.TWENTY_X_INV

    # 40X & 60X Parsing tests
    assert te.parse_product_type("40X") == ProductType.FORTY_X
    assert te.parse_product_type("40x") == ProductType.FORTY_X
    assert te.parse_product_type("40배") == ProductType.FORTY_X
    assert te.parse_product_type("40레버") == ProductType.FORTY_X
    assert te.parse_product_type("40롱") == ProductType.FORTY_X
    assert te.parse_product_type("40X_INV") == ProductType.FORTY_X_INV
    assert te.parse_product_type("40숏") == ProductType.FORTY_X_INV
    assert te.parse_product_type("40곱") == ProductType.FORTY_X_INV
    assert te.parse_product_type("40인") == ProductType.FORTY_X_INV
    assert te.parse_product_type("인버스40X") == ProductType.FORTY_X_INV

    assert te.parse_product_type("60X") == ProductType.SIXTY_X
    assert te.parse_product_type("60x") == ProductType.SIXTY_X
    assert te.parse_product_type("60배") == ProductType.SIXTY_X
    assert te.parse_product_type("60레버") == ProductType.SIXTY_X
    assert te.parse_product_type("60롱") == ProductType.SIXTY_X
    assert te.parse_product_type("60X_INV") == ProductType.SIXTY_X_INV
    assert te.parse_product_type("60숏") == ProductType.SIXTY_X_INV
    assert te.parse_product_type("60곱") == ProductType.SIXTY_X_INV
    assert te.parse_product_type("60인") == ProductType.SIXTY_X_INV
    assert te.parse_product_type("인버스60X") == ProductType.SIXTY_X_INV

    # 2. Legendary-only roll test: RARE, EPIC, UNIQUE never roll LEVERAGE_20X_UNLOCK
    for _ in range(100):
        assert te.roll_single_potential_line("RARE")["code"] != "LEVERAGE_20X_UNLOCK"
        assert te.roll_single_potential_line("EPIC")["code"] != "LEVERAGE_20X_UNLOCK"
        assert te.roll_single_potential_line("UNIQUE")["code"] != "LEVERAGE_20X_UNLOCK"

    # 3. User without unlock (0 lines): cannot buy 20X, 40X, or 60X
    uid = "beast_tester"
    uname = "야수테스터"
    user = te.get_or_create_user(db_session, uid, uname)
    user.points = 1000000
    items = te.ensure_user_equipment(db_session, user)
    eq = items[0]
    eq.potential_tier = "EPIC"
    eq.potential_line_1 = None
    eq.potential_line_2 = None
    eq.potential_line_3 = None
    db_session.commit()

    ok_buy, msg_buy, _ = te.execute_buy(db_session, uid, uname, "20X", "1")
    assert ok_buy is False
    assert "야수의 심장" in msg_buy

    ok_40, msg_40, _ = te.execute_buy(db_session, uid, uname, "40X", "1")
    assert ok_40 is False
    assert "야수의 심장" in msg_40

    ok_60, msg_60, _ = te.execute_buy(db_session, uid, uname, "60X", "1")
    assert ok_60 is False
    assert "야수의 심장" in msg_60

    # 4. User equips 1 line of LEVERAGE_20X_UNLOCK -> Can trade 20X, but NOT 40X or 60X
    eq.potential_tier = "LEGENDARY"
    beast_line = json.dumps({"code": "LEVERAGE_20X_UNLOCK", "val": 20.0, "text": "🦁 야수의 심장 (1줄: 20배, 2줄: 40배, 3줄: 60배 해금)"})
    eq.potential_line_1 = beast_line
    eq.potential_line_2 = None
    eq.potential_line_3 = None
    db_session.commit()

    assert te.get_user_max_leverage_multiplier(db_session, user) == 20
    ok_20, _, det_20 = te.execute_buy(db_session, uid, uname, "20X", "1")
    assert ok_20 is True
    assert det_20["product_type"] == "20X"

    ok_40_1, msg_40_1, _ = te.execute_buy(db_session, uid, uname, "40X", "1")
    assert ok_40_1 is False
    assert "2줄 이상" in msg_40_1

    ok_60_1, msg_60_1, _ = te.execute_buy(db_session, uid, uname, "60X", "1")
    assert ok_60_1 is False
    assert "3줄 이상" in msg_60_1

    # 5. User equips 2 lines of LEVERAGE_20X_UNLOCK -> Can trade 40X, but NOT 60X
    eq.potential_line_2 = beast_line
    db_session.commit()

    assert te.get_user_max_leverage_multiplier(db_session, user) == 40
    ok_40_2, _, det_40_2 = te.execute_buy(db_session, uid, uname, "40X", "1")
    assert ok_40_2 is True
    assert det_40_2["product_type"] == "40X"

    ok_60_2, msg_60_2, _ = te.execute_buy(db_session, uid, uname, "60X", "1")
    assert ok_60_2 is False
    assert "3줄 이상" in msg_60_2

    # 6. User equips 3 lines of LEVERAGE_20X_UNLOCK -> Can trade 60X!
    eq.potential_line_3 = beast_line
    db_session.commit()

    assert te.get_user_max_leverage_multiplier(db_session, user) == 60
    ok_60_3, _, det_60_3 = te.execute_buy(db_session, uid, uname, "60X", "1")
    assert ok_60_3 is True
    assert det_60_3["product_type"] == "60X"

    # 7. Test 40X & 60X settlement liquidation:
    # 40X: -2.5% drop causes liquidation
    mstate = te.get_market_state(db_session)
    mstate.current_rank_point = 1000
    mstate.current_price = 1000
    pos40 = db_session.query(Position).filter_by(user_id=uid, product_type=ProductType.FORTY_X).first()
    pos40.entry_price = 1000.0
    pos40.invested_cash = 1000.0
    pos40.quantity = 1.0
    db_session.commit()

    # Drop rank points by 25 (-2.5% drop from 1000 to 975 -> product_ret = -2.5% * 40 = -100%)
    det_settle40 = te.settle_match(db_session, rank=4, point_delta=-25)
    assert any(liq["user_id"] == uid and liq["product_type"] == "40X" for liq in det_settle40["liquidations"])

    # 60X: -1.67% drop causes liquidation (-20 drop from 1000 to 980 -> product_ret = -2.0% * 60 = -120% <= -100%)
    mstate.current_rank_point = 1000
    mstate.current_price = 1000
    pos60 = db_session.query(Position).filter_by(user_id=uid, product_type=ProductType.SIXTY_X).first()
    pos60.entry_price = 1000.0
    pos60.invested_cash = 1000.0
    pos60.quantity = 1.0
    db_session.commit()

    det_settle60 = te.settle_match(db_session, rank=4, point_delta=-20)
    assert any(liq["user_id"] == uid and liq["product_type"] == "60X" for liq in det_settle60["liquidations"])

def test_starforce_safeguard_65_and_failure_reduction(db_session, monkeypatch):
    """Test STARFORCE_SAFEGUARD (Unique 30%, Legendary 65%) and failure rate reduction by success boost."""
    opt_sg = te.POTENTIAL_OPTIONS["STARFORCE_SAFEGUARD"]
    assert opt_sg["tiers"]["UNIQUE"][0] == 30.0
    assert opt_sg["tiers"]["LEGENDARY"][0] == 65.0

    opt_sb = te.POTENTIAL_OPTIONS["STARFORCE_SUCCESS_BOOST"]
    assert opt_sb["tiers"]["EPIC"][0] == 2.0
    assert opt_sb["tiers"]["UNIQUE"][0] == 4.0
    assert opt_sb["tiers"]["LEGENDARY"][0] == 8.0

    uid = "sf_safeguard_tester"
    uname = "세이프가드테스터"
    user = te.get_or_create_user(db_session, uid, uname)
    user.points = 10000000
    user.pickaxe_level = 16
    items = te.ensure_user_equipment(db_session, user)
    eq = items[0]
    eq.starforce = 16
    eq.potential_tier = "LEGENDARY"
    eq.potential_line_1 = json.dumps({"code": "STARFORCE_SAFEGUARD", "val": 65.0, "text": "65%"})
    eq.potential_line_2 = json.dumps({"code": "STARFORCE_SUCCESS_BOOST", "val": 8.0, "text": "+8.0%"})
    db_session.commit()

    # Check status display reflects success boost and failure rate deduction & safeguard defense
    status_msg = te.get_user_pickaxe_status(db_session, uid, uname)
    assert "+8.0%" in status_msg or "39.5%" in status_msg
    assert "🔻-8.0%" in status_msg
    assert "🛡️방어 65%" in status_msg
    assert "실질 0.719%" in status_msg
    assert "세이프가드 65%" in status_msg

    mstate = te.get_market_state(db_session)
    mstate.sf_next_event_time = time.time() + 1000.0
    db_session.commit()

    # Base at 16성: success=31.5, maintain=0.0, drop=66.445, destroy=2.055
    # With boost +8.0%:
    # success becomes 39.5%, drop becomes 66.445 - 8.0 = 58.445%
    # destroy threshold is at 39.5 + 0.0 + 58.445 = 97.945% (same 2.055% width)
    # 1. Roll 98.5 (above 97.945 -> destruction)
    # Safeguard roll < 65.0 -> protected! (safeguarded_drop, drops to 15 instead of 12)
    uniform_vals = [98.5, 50.0]
    monkeypatch.setattr(random, "uniform", lambda a, b: uniform_vals.pop(0))

    ok_up, reply_up, det_up = te.execute_pickaxe_upgrade(db_session, uid, uname)
    assert ok_up is True
    assert det_up["outcome"] == "safeguarded_drop"
    assert det_up["previous_level"] == 16
    assert det_up["new_level"] == 15
    assert "파괴 방지" in reply_up

    # 2. Test success boost allowing success in the boosted range [31.5, 34.02)
    # Roll 33.0: Base 31.5% would fail/drop, but with multiplicative +8.0% boost (34.02%), it succeeds!
    user.pickaxe_level = 16
    eq.starforce = 16
    db_session.commit()

    uniform_vals = [33.0]
    ok_boost, reply_boost, det_boost = te.execute_pickaxe_upgrade(db_session, uid, uname)
    assert ok_boost is True
    assert det_boost["outcome"] == "success"
    assert det_boost["previous_level"] == 16
    assert det_boost["new_level"] == 17
    assert "성공률" in reply_boost

def test_starforce_fever_sanity_clamp_and_frequent_cycle(db_session):
    """Test that a distant-future (e.g. 27h+) sf_next_event_time is automatically clamped to 15~30m."""
    state = te.get_market_state(db_session)
    now = time.time()

    # Corrupt or huge future value (e.g. 27 hours)
    state.sf_next_event_time = now + 99000.0
    state.sf_event_type = None
    state.sf_event_end_time = 0.0
    db_session.commit()

    # Querying state must immediately clamp next_time to [15, 30] minutes
    sf = te.get_starforce_event_state(db_session)
    assert not sf["is_active"]
    assert sf["next_remaining_sec"] <= (30.0 * 60.0) + 60.0
    assert sf["next_remaining_sec"] >= (15.0 * 60.0) - 1.0

    # Cooldown status formatting check: must not say '27시간'
    cd_status = te.get_user_cooldown_status(db_session, "user_fever_test", "피버체커")
    assert "27시간" not in cd_status
    assert "분 후 예정" in cd_status or "곧 발생" in cd_status

def test_multi_equipment_cooldown_abuse_prevention(db_session, monkeypatch):
    """
    Test that having multiple pickaxes cannot be exploited to bypass mining cooldown.
    - Cooldown is tracked per User account (last_mined_at), not per equipment.
    - Swapping to another pickaxe keeps the user on cooldown.
    - Multiple auto-mining sessions cannot be spawned.
    """
    uid = "multi_pickaxe_user"
    uname = "곡괭이다수보유자"
    user = te.get_or_create_user(db_session, uid, uname)
    items = te.ensure_user_equipment(db_session, user)
    default_item = items[0]
    assert default_item.is_equipped is True

    # Add second pickaxe (15-star, 8m cooldown) and third pickaxe (20-star, 3m cooldown)
    now_utc = datetime.now(timezone.utc)
    pickaxe_15 = te.UserEquipment(
        user_id=user.id,
        equipment_type="PICKAXE",
        name="황금 곡괭이 (★15성)",
        starforce=15,
        is_equipped=False,
        created_at=now_utc
    )
    pickaxe_20 = te.UserEquipment(
        user_id=user.id,
        equipment_type="PICKAXE",
        name="다이아몬드 곡괭이 (★20성)",
        starforce=20,
        is_equipped=False,
        created_at=now_utc
    )
    db_session.add_all([pickaxe_15, pickaxe_20])
    db_session.commit()

    # Mock tier to normal N so EX/UR cooldown reduction doesn't alter baseline cooldown
    monkeypatch.setattr(te, "roll_mining_tier", lambda *a, **kw: {
        "code": "N",
        "name": "⛏️ [평범한 구리 광맥 일반 채굴]",
        "multiplier": 1.0,
        "bonus_cash": 0,
        "bonus_10x": 0.0,
        "cooldown_reduction": 0,
    })

    # 1. Mine with initial equipped pickaxe (0-star, 15m cooldown)
    ok1, rep1, _ = te.execute_mining(db_session, uid, uname)
    assert ok1 is True
    assert user.last_mined_at is not None

    # 2. Re-mine attempt with same pickaxe must be blocked by cooldown
    ok2, rep2, det2 = te.execute_mining(db_session, uid, uname)
    assert ok2 is False
    assert "채굴 쿨타임" in rep2

    # 3. Swap to second pickaxe (15-star)
    ok_swap1, _, _ = te.execute_equip_item(db_session, uid, uname, str(pickaxe_15.id))
    assert ok_swap1 is True
    assert pickaxe_15.is_equipped is True
    assert default_item.is_equipped is False

    # 4. Attempting to mine with second pickaxe must STILL be blocked!
    ok3, rep3, det3 = te.execute_mining(db_session, uid, uname)
    assert ok3 is False
    assert "채굴 쿨타임" in rep3
    assert det3["remaining_seconds"] > 0

    # 5. Swap to third pickaxe (20-star)
    ok_swap2, _, _ = te.execute_equip_item(db_session, uid, uname, str(pickaxe_20.id))
    assert ok_swap2 is True

    # 6. Attempting to mine with third pickaxe must STILL be blocked!
    ok4, rep4, det4 = te.execute_mining(db_session, uid, uname)
    assert ok4 is False
    assert "채굴 쿨타임" in rep4
    assert det4["remaining_seconds"] > 0

    # 7. Cooldown status correctly inspects currently equipped pickaxe
    cd_status = te.get_user_cooldown_status(db_session, uid, uname)
    assert "다이아몬드 곡괭이 (★20성)" in cd_status
    assert "남음" in cd_status

    # 8. Auto-mining tick also cannot mine while cooldown is active
    te.set_auto_mining(db_session, uid, uname, enable=True)
    tick = te.execute_auto_mining_tick(db_session, user)
    assert tick is None  # Blocked by cooldown

def test_casino_debuff_and_payback_cap(db_session, monkeypatch):
    """Test debuffed casino multipliers and 40% maximum payback cap."""
    uid = "debuff_casino_user"
    uname = "카지노디버프검증"
    user = te.get_or_create_user(db_session, uid, uname)
    user.points = 100000
    items = te.ensure_user_equipment(db_session, user)
    eq = items[0]

    # Equip item with 1x Legendary dice payback (20%) -> exactly break-even (100% RTP) with 1.8x win on 50/50
    eq.potential_tier = "LEGENDARY"
    eq.potential_line_1 = json.dumps({"code": "CASINO_DICE_PAYBACK", "val": 20.0, "text": "20%"})
    eq.potential_line_2 = None
    eq.potential_line_3 = None
    db_session.commit()

    te.open_casino(db_session, duration_minutes=5.0, max_bet=100000)

    # 1. Test loss with 20% payback (Single line Legendary = 20% payback)
    monkeypatch.setattr(random, "randint", lambda a, b: 1) # 1+1 = 2 (Even)
    # Bet on "홀" (Odd) -> Loss!
    initial_pts = user.points
    ok, reply, det = te.execute_dice_gamble(db_session, uid, uname, "홀", "10000")
    assert ok is True
    assert det["won"] is False
    assert "잠재 환급 20% 발동" in reply
    # Net loss must be 10000 - 2000 = 8000
    assert user.points == initial_pts - 8000

    # 2. Test standard win payout is 1.8x (+80% net)
    dice_res = iter([2, 4])
    monkeypatch.setattr(random, "randint", lambda a, b: next(dice_res))
    ok_w, reply_w, det_w = te.execute_dice_gamble(db_session, uid, uname, "짝", "10000")
    assert ok_w is True
    assert det_w["won"] is True
    assert det_w["net_payout"] == 8000 # 1.8x payout
    assert "1.8배 당첨" in reply_w

    # 3. Test critical win payout is 2.2x (+120% net)
    dice_crit = iter([6, 6])
    monkeypatch.setattr(random, "randint", lambda a, b: next(dice_crit))
    ok_c, reply_c, det_c = te.execute_dice_gamble(db_session, uid, uname, "대", "10000")
    assert ok_c is True
    assert det_c["won"] is True
    assert det_c["is_critical"] is True
    assert det_c["net_payout"] == 12000 # 2.2x payout
    assert "2.2배 크리티컬" in reply_c

def test_slot_boost_potential(db_session, monkeypatch):
    """Test slot winning boost potential (Slot has winning bonus, Dice has payback; 1 Legendary line achieves break-even)."""
    uid = "slot_boost_tester"
    uname = "슬롯보너스"
    user = te.get_or_create_user(db_session, uid, uname)
    user.points = 100000
    items = te.ensure_user_equipment(db_session, user)
    eq = items[0]
    eq.potential_tier = "LEGENDARY"

    # Single Legendary line: 14% boost (break-even with ~87.7% base RTP)
    boost_line = json.dumps({"code": "CASINO_SLOT_BOOST", "val": 14.0, "text": "+14%"})
    eq.potential_line_1 = boost_line
    eq.potential_line_2 = None
    eq.potential_line_3 = None
    db_session.commit()

    te.open_casino(db_session, duration_minutes=5.0, max_bet=100000)

    # 1. Slot loss: no payback on loss (Slot potential is winning bonus)
    monkeypatch.setattr(random, "choices", lambda syms, weights, k: ["💣", "🍒", "🍇"])
    init_pts = user.points
    ok, reply, det = te.execute_slot_gamble(db_session, uid, uname, "10000")
    assert ok is True
    assert det["won"] is False
    assert det["net_payout"] == -10000
    assert user.points == init_pts - 10000

    # 2. Slot win with 8x Yakuman: 14% bonus on total payout
    # Total payout = 80,000P. 14% of 80,000 = 11,200P. Net payout = 70,000 + 11,200 = 81,200P.
    monkeypatch.setattr(random, "choices", lambda syms, weights, k: ["🀄", "🀄", "🀄"])
    init_pts2 = user.points
    ok2, reply2, det2 = te.execute_slot_gamble(db_session, uid, uname, "10000")
    assert ok2 is True
    assert det2["won"] is True
    assert "잠재 당첨 보너스 +14% 발동" in reply2
    assert det2["net_payout"] == 81200
    assert user.points == init_pts2 + 81200

    # 3. Slot win with standard 2-pair: 1.6x total payout (16,000P, net 6,000P)
    # With 14% boost: 16,000 * 0.14 = 2,240P. Net payout = 6,000 + 2,240 = 8,240P.
    monkeypatch.setattr(random, "choices", lambda syms, weights, k: ["🔔", "🔔", "🍇"])
    init_pts3 = user.points
    ok3, reply3, det3 = te.execute_slot_gamble(db_session, uid, uname, "10000")
    assert ok3 is True
    assert det3["won"] is True
    assert "잠재 당첨 보너스 +14% 발동" in reply3
    assert det3["net_payout"] == 8240
    assert user.points == init_pts3 + 8240

def test_beast_heart_chat_commands(db_session):
    """Test chat command handling for 40X, 60X, and inverse counterparts."""
    uid = "cmd_beast_user"
    uname = "채팅야수"
    user = te.get_or_create_user(db_session, uid, uname)
    user.points = 5000000
    items = te.ensure_user_equipment(db_session, user)
    eq = items[0]
    eq.potential_tier = "LEGENDARY"
    beast_line = json.dumps({"code": "LEVERAGE_20X_UNLOCK", "val": 20.0, "text": "🦁 야수의 심장"})
    # 2 lines -> 40X unlocked, 60X locked
    eq.potential_line_1 = beast_line
    eq.potential_line_2 = beast_line
    eq.potential_line_3 = None
    db_session.commit()

    # 40X buy command should succeed
    rep40, evt40 = ch.handle_chat_command(db_session, uid, uname, "!40X 1")
    assert evt40 is not None
    assert evt40["data"]["product_type"] == "40X"

    # 60X buy command should be rejected (needs 3 lines)
    rep60, evt60 = ch.handle_chat_command(db_session, uid, uname, "!60배 1")
    assert evt60 is None
    assert "3줄 이상" in rep60

    # 40배 sell command should work
    rep_sell, evt_sell = ch.handle_chat_command(db_session, uid, uname, "!40배 전량")
    assert evt_sell is not None
    assert evt_sell["type"] == "trade_sell"

    # Now equip 3 lines -> 60X should succeed
    eq.potential_line_3 = beast_line
    db_session.commit()

    rep60_ok, evt60_ok = ch.handle_chat_command(db_session, uid, uname, "!60X 1")
    assert evt60_ok is not None
    assert evt60_ok["data"]["product_type"] == "60X"

def test_web_site_url_commands(db_session):
    # Test !사이트, !주소, !웹, !설명서, !가이드, !링크 etc.
    uid = "test_url_user"
    uname = "주소확인자"
    for cmd in ["!사이트", "!주소", "!웹", "!웹사이트", "!설명서", "!가이드", "!링크", "!site", "!url"]:
        reply, evt = ch.handle_chat_command(db_session, uid, uname, cmd)
        assert reply is not None
        assert "https://hot6mania.github.io/stoke-mahjong/" in reply
        assert evt is None

def test_streamer_day_open_price_commands(db_session):
    streamer_id = ch.CHANNEL_ID
    viewer_id = "random_viewer_123"

    # 1. Non-streamer tries !시가설정 -> blocked
    rep_fail, evt_fail = ch.handle_chat_command(db_session, viewer_id, "시청자", "!시가설정 2137")
    assert "스트리머" in rep_fail
    assert evt_fail is None

    # 2. Streamer sets day open price to 2137
    rep_ok, evt_ok = ch.handle_chat_command(db_session, streamer_id, "치즈나베", "!시가설정 2137")
    assert "2,137P" in rep_ok
    assert evt_ok is not None
    assert evt_ok["type"] == "market_update"
    assert evt_ok["data"]["day_open_price"] == 2137

    state = te.get_market_state(db_session)
    assert state.day_open_price == 2137

    # 3. Streamer resets to current price: !시가재설정
    rep_reset, evt_reset = ch.handle_chat_command(db_session, streamer_id, "치즈나베", "!시가재설정")
    assert f"{state.current_price:,}P" in rep_reset
    assert evt_reset is not None
    assert evt_reset["data"]["day_open_price"] == state.current_price

    # 4. Test extract_day_start_points
    from main import extract_day_start_points
    assert extract_day_start_points("2145/9000 (2137)") == 2137
    assert extract_day_start_points("2145/9000 (2,137)") == 2137
    assert extract_day_start_points("2145/9000 (+15)") is None  # no digits without signs or extract correctly
    assert extract_day_start_points("") is None

def test_pickaxe_shop_prices_and_expected_costs(db_session):
    # Verify 0-star (10,000P), 5-star (80,000P), and 10-star (350,000P)
    uid = "shop_tester_u1"
    u = te.get_or_create_user(db_session, uid, "상점테스터")
    u.points = 1000000
    db_session.commit()

    # Buy 0-star
    ok0, rep0, det0 = te.execute_buy_equipment(db_session, uid, "상점테스터", "0")
    assert ok0 is True
    assert det0["cost"] == 10000
    assert det0["starforce"] == 0

    # Buy 5-star (80,000P - above expected direct upgrade cost ~46,210P)
    ok5, rep5, det5 = te.execute_buy_equipment(db_session, uid, "상점테스터", "5")
    assert ok5 is True
    assert det5["cost"] == 80000
    assert det5["starforce"] == 5

    # Buy 10-star (350,000P - above expected direct upgrade cost ~247,251P)
    ok10, rep10, det10 = te.execute_buy_equipment(db_session, uid, "상점테스터", "10")
    assert ok10 is True
    assert det10["cost"] == 350000
    assert det10["starforce"] == 10

def test_delisting_and_relist_wipes_all_positions_and_resets_to_master2(db_session):
    """
    Test that delisting:
    1. Wipes all existing shareholder stock positions to 0 (휴짓조각)
    2. Refunds pending BUY limit orders and cancels pending SELL limit orders
    3. Starts brand new stock pegged to Master 2 (작성2) at 3,500P
    4. Allows immediate new trading at 3,500P
    """
    u1 = "shareholder_1"
    u2 = "shareholder_2"
    te.get_or_create_user(db_session, u1, "주주1")
    te.get_or_create_user(db_session, u2, "주주2")

    # Buy various positions
    te.execute_buy(db_session, u1, "주주1", "1X", "2")
    te.execute_buy(db_session, u1, "주주1", "5X", "1")
    te.execute_buy(db_session, u2, "주주2", "INV", "3")

    pos1 = db_session.query(Position).filter(Position.user_id == u1, Position.quantity > 0).all()
    assert len(pos1) == 2

    # Place a pending BUY limit order for u2 (reserving points)
    user2 = db_session.query(User).filter_by(id=u2).first()
    points_before_order = user2.points
    te.register_limit_order(db_session, u2, "주주2", "BUY", "1X", "2000", "1")
    db_session.refresh(user2)
    assert user2.points < points_before_order

    # Place a pending SELL limit order for u1
    te.register_limit_order(db_session, u1, "주주1", "SELL", "1X", "3000", "1")

    # Execute delisting from 작성3 to 작성2
    delist_res = te.execute_delisting_and_relist(
        db_session,
        old_rank="작성3",
        new_rank="작성2",
        starting_points=3000
    )

    assert delist_res["old_rank"] == "작성3"
    assert delist_res["new_rank"] == "작성2"
    assert delist_res["new_price"] == 3000
    assert delist_res["wiped_positions_count"] >= 3

    # Verify ALL positions are completely wiped to 0 (휴짓조각)
    active_positions = db_session.query(Position).filter(Position.quantity > 0).all()
    assert len(active_positions) == 0

    all_positions = db_session.query(Position).all()
    for p in all_positions:
        assert p.quantity == 0.0
        assert p.invested_cash == 0.0
        assert p.entry_price == 0.0

    # Verify pending limit orders were cancelled and BUY order reserved points refunded
    pending = db_session.query(LimitOrder).filter_by(status=OrderStatus.PENDING).all()
    assert len(pending) == 0

    db_session.refresh(user2)
    assert user2.points == points_before_order

    # Verify MarketState is now Master 2 at 3,000P
    mstate = te.get_market_state(db_session)
    assert mstate.current_rank_name == "작성2"
    assert mstate.current_rank_point == 3000
    assert mstate.current_price == 3000
    assert mstate.previous_price == 3000
    assert mstate.day_open_price == 3000
    assert mstate.is_trading_locked is False

    # Verify users can immediately buy the new Master 2 stock at 3,000P
    ok_buy, msg_buy, det_buy = te.execute_buy(db_session, u1, "주주1", "1X", "1")
    assert ok_buy is True
    assert det_buy["price"] == 3000
    new_pos = db_session.query(Position).filter_by(user_id=u1, product_type=ProductType.ONE_X).first()
    assert new_pos.quantity == 1.0
    assert new_pos.entry_price == 3000.0

def test_settle_match_demotion_triggers_delisting_when_points_drop_to_zero(db_session):
    """
    Test that when match settlement results in points <= 0:
    It automatically triggers demotion to 작성2, delisting existing stock, and resetting to 3,000P.
    """
    uid = "victim_u1"
    te.get_or_create_user(db_session, uid, "피해자")
    te.execute_buy(db_session, uid, "피해자", "1X", "3")

    mstate = te.get_market_state(db_session)
    assert mstate.current_rank_name == "작성3"
    assert mstate.current_rank_point == 2340

    # Match loss: point delta drops points to <= 0 (e.g. -2500)
    settle_res = te.settle_match(db_session, rank=3, point_delta=-2500)

    assert settle_res["delisted"] is True
    assert settle_res["current_rank_name"] == "작성2"
    assert settle_res["new_price"] == 3000
    assert settle_res["new_rank_points"] == 3000
    assert settle_res["return_pct"] == -1.0

    # Position is wiped to 0
    pos = db_session.query(Position).filter_by(user_id=uid).first()
    assert pos.quantity == 0.0

def test_chat_commands_demotion_and_rank_display(db_session):
    """
    Test streamer !강등 command, non-streamer permission rejection, and !주식/!주가/!트래커 rank names.
    """
    streamer_id = "streamer"
    viewer_id = "viewer_1"

    # Non-streamer tries !강등 -> rejected
    rep_rej, _ = ch.handle_chat_command(db_session, viewer_id, "일반시청자", "!강등")
    assert "🚫" in rep_rej

    # Check !주식 / !주가 shows 작성3
    rep_price, _ = ch.handle_chat_command(db_session, viewer_id, "일반시청자", "!주가")
    assert "나베주가 (작성3) 시세" in rep_price

    # Streamer triggers !강등
    rep_demote, event = ch.handle_chat_command(db_session, streamer_id, "치즈나베", "!강등")
    assert "상장폐지" in rep_demote
    assert "작성2" in rep_demote
    assert "3,000P" in rep_demote
    assert event is not None
    assert event["type"] == "delisting"

    # Check !주식 / !주가 now shows 작성2
    rep_price2, _ = ch.handle_chat_command(db_session, viewer_id, "일반시청자", "!주식")
    assert "나베주가 (작성2) 시세" in rep_price2
    assert "3,000P" in rep_price2

    # Check !트래커 shows 작성2
    rep_tr, _ = ch.handle_chat_command(db_session, viewer_id, "일반시청자", "!트래커")
    assert "나베주가 (작성2) 현황" in rep_tr
    assert "3,000pt" in rep_tr


def test_lottery_event_mechanics_and_scratch(db_session):
    u = te.get_or_create_user(db_session, "lotto_user", "복권러")
    u.points = 50000
    db_session.commit()

    # 1. When lottery is closed, buying is blocked
    te.close_lottery_event(db_session)
    ok, rep, details = te.execute_buy_lottery(db_session, "lotto_user", "복권러", 1)
    assert ok is False
    assert "지금은 복권 이벤트 기간이 아닙니다" in rep

    # 2. Open lottery event
    ok_open, msg_open, det_open = te.open_lottery_event(db_session, duration_minutes=15, title="국가 복지 복권")
    assert ok_open is True
    assert det_open["is_active"] is True
    assert det_open["duration_minutes"] == 15
    assert det_open["title"] == "국가 복지 복권"

    ev_state = te.get_lottery_event_state(db_session)
    assert ev_state["is_active"] is True
    assert ev_state["remaining_sec"] > 0

    # 3. Buy 1 ticket successfully
    pts_before = u.points
    ok_buy, rep_buy, det_buy = te.execute_buy_lottery(db_session, "lotto_user", "복권러", 1)
    assert ok_buy is True
    assert det_buy["ticket_count"] == 1
    assert det_buy["total_cost"] == 1000
    assert det_buy["total_prize"] >= 0
    assert u.points == pts_before - 1000 + det_buy["total_prize"]
    assert "복권" in rep_buy

    # 4. Buy 5 tickets (batch scratch)
    pts_before2 = u.points
    ok_buy5, rep_buy5, det_buy5 = te.execute_buy_lottery(db_session, "lotto_user", "복권러", 5)
    assert ok_buy5 is True
    assert det_buy5["ticket_count"] == 5
    assert det_buy5["total_cost"] == 5000
    assert det_buy5["total_prize"] >= 0
    assert u.points == pts_before2 - 5000 + det_buy5["total_prize"]

    # 5. Over max purchase limit (> 10)
    ok_limit, rep_limit, _ = te.execute_buy_lottery(db_session, "lotto_user", "복권러", 11)
    assert ok_limit is False
    assert "최대 10장" in rep_limit

    # 6. Insufficient funds
    u.points = 500
    db_session.commit()
    ok_nofund, rep_nofund, _ = te.execute_buy_lottery(db_session, "lotto_user", "복권러", 1)
    assert ok_nofund is False
    assert "보유 현금이 부족합니다" in rep_nofund

    # 7. Close lottery event
    ok_close, msg_close, det_close = te.close_lottery_event(db_session)
    assert ok_close is True
    assert det_close["is_active"] is False

    ev_state_closed = te.get_lottery_event_state(db_session)
    assert ev_state_closed["is_active"] is False


def test_lottery_chat_commands_and_permissions(db_session):
    streamer_id = "4495f96624a2c60bd1ed5a6139014d20"
    viewer_id = "viewer_lotto"

    u = te.get_or_create_user(db_session, viewer_id, "시청자")
    u.points = 30000
    db_session.commit()

    te.close_lottery_event(db_session)

    # 1. Non-streamer tries !복권오픈 -> blocked
    rep_rej, _ = ch.handle_chat_command(db_session, viewer_id, "시청자", "!복권오픈 10")
    assert "🚫" in rep_rej

    # 2. Check !복권상태 / !복권확률 when closed
    rep_odds, _ = ch.handle_chat_command(db_session, viewer_id, "시청자", "!복권확률")
    assert "복권" in rep_odds
    assert "1등" in rep_odds
    assert "50,000P" in rep_odds

    # 3. Streamer opens lottery: !복권오픈 10
    rep_open, ev_open = ch.handle_chat_command(db_session, streamer_id, "치즈나베", "!복권오픈 10")
    assert "복권" in rep_open
    assert ev_open is not None
    assert ev_open["type"] == "lottery_event_started"

    # 4. Viewer scratches lottery: !복권
    pts_before = u.points
    rep_scratch, ev_scratch = ch.handle_chat_command(db_session, viewer_id, "시청자", "!복권")
    assert "복권" in rep_scratch
    assert ev_scratch is not None
    assert ev_scratch["type"] in ["lottery_scratch", "lottery_jackpot"]
    assert u.points >= pts_before - 1000

    # 5. Viewer scratches 10 tickets: !복권 10
    rep_scratch10, ev_scratch10 = ch.handle_chat_command(db_session, viewer_id, "시청자", "!복권 10")
    assert "10장 일괄 긁기" in rep_scratch10
    assert ev_scratch10 is not None

    # 6. Non-streamer tries !복권마감 -> blocked
    rep_close_rej, _ = ch.handle_chat_command(db_session, viewer_id, "시청자", "!복권마감")
    assert "🚫" in rep_close_rej

    # 7. Streamer closes lottery: !복권마감
    rep_close, ev_close = ch.handle_chat_command(db_session, streamer_id, "치즈나베", "!복권마감")
    assert "마감" in rep_close
    assert ev_close is not None
    assert ev_close["type"] == "lottery_event_ended"


def test_merchant_system_lifecycle_and_purchases(db_session):
    u = te.get_or_create_user(db_session, "user_merchant_1", "상인테스터")
    u.points = 5000000
    db_session.commit()

    # 1. Close merchant first
    te.close_merchant(db_session)
    m_state = te.get_merchant_state(db_session)
    assert m_state["is_active"] is False

    # Try to buy when closed
    ok, rep, _ = te.execute_buy_merchant_item(db_session, u.id, u.username, "1", "1")
    assert ok is False
    assert "신비상인이 마을에 없습니다" in rep

    # 2. Open merchant
    ok_open, msg_open, details_open = te.open_merchant(db_session, duration_minutes=15)
    assert ok_open is True
    assert "신비상인 등장" in msg_open
    m_state_open = te.get_merchant_state(db_session)
    assert m_state_open["is_active"] is True
    assert m_state_open["remaining_sec"] > 0
    assert "shield" in m_state_open["items"]
    assert "boost" in m_state_open["items"]
    assert "downgrade" in m_state_open["items"]

    # 3. Buy 1 파괴방어권 (shield)
    treasury_before = te.get_market_state(db_session).treasury_pool
    shield_price = m_state_open["items"]["shield"]["price"]
    shield_stock = m_state_open["items"]["shield"]["stock"]
    ok_buy1, rep_buy1, det_buy1 = te.execute_buy_merchant_item(db_session, u.id, u.username, "1", "1")
    assert ok_buy1 is True
    assert "구매 완료" in rep_buy1
    assert det_buy1["item_type"] == "shield"
    assert u.shield_scroll_count == 1
    assert te.get_market_state(db_session).treasury_pool == treasury_before + shield_price
    assert te.get_market_state(db_session).merchant_shield_stock == shield_stock - 1

    # 4. Buy 2 강화확률상승권 (boost)
    boost_price = m_state_open["items"]["boost"]["price"]
    ok_buy2, rep_buy2, det_buy2 = te.execute_buy_merchant_item(db_session, u.id, u.username, "boost", "2")
    assert ok_buy2 is True
    assert det_buy2["item_type"] == "boost"
    assert u.boost_scroll_count == 2
    assert det_buy2["total_cost"] == boost_price * 2

    # 5. Buy 1 하강방지권 (downgrade)
    ok_buy3, rep_buy3, det_buy3 = te.execute_buy_merchant_item(db_session, u.id, u.username, "하강방지권", "1")
    assert ok_buy3 is True
    assert det_buy3["item_type"] == "downgrade"
    assert u.downgrade_scroll_count == 1

    # 6. Verify user inventory
    inven = te.get_user_item_inventory(db_session, u)
    assert inven["shield_scroll_count"] == 1
    assert inven["boost_scroll_count"] == 2
    assert inven["downgrade_scroll_count"] == 1

    # 7. Close merchant
    ok_close, msg_close, _ = te.close_merchant(db_session)
    assert ok_close is True
    assert "마을을 떠났습니다" in msg_close


def test_scroll_protections_in_starforce_upgrade(db_session, monkeypatch):
    import random
    u = te.get_or_create_user(db_session, "user_scroll_test", "강화테스터")
    u.points = 10000000
    u.pickaxe_level = 15
    u.shield_scroll_count = 1
    u.boost_scroll_count = 1
    u.downgrade_scroll_count = 1

    eq = te.UserEquipment(
        user_id=u.id,
        equipment_type="PICKAXE",
        name="황금 곡괭이 (★15성)",
        starforce=15,
        is_equipped=True
    )
    db_session.add(eq)
    u.points = 2000000
    u.boost_scroll_count = 1
    u.downgrade_scroll_count = 1
    u.shield_scroll_count = 1
    eq.starforce = 15
    db_session.commit()

    # 0. Test when scrolls are NOT designated: they must NOT be consumed!
    monkeypatch.setattr(random, "uniform", lambda a, b: 35.0)
    ok0, rep0, det0 = te.execute_pickaxe_upgrade(db_session, u.id, u.username, str(eq.id))
    assert ok0 is True
    assert det0["used_boost_scroll"] is False
    assert u.boost_scroll_count == 1  # Not consumed!

    # 1. Test Boost Scroll: designated via use_boost=True
    # Base success is 30% (30.0). With boost (+10), success is 40% (40.0).
    # 35.0 < 40.0 -> SUCCESS!
    monkeypatch.setattr(random, "uniform", lambda a, b: 35.0)
    ok, rep, det = te.execute_pickaxe_upgrade(db_session, u.id, u.username, str(eq.id), use_boost=True)
    assert ok is True
    assert det["used_boost_scroll"] is True
    assert det["remaining_boost_scrolls"] == 0
    assert u.boost_scroll_count == 0
    assert det["new_level"] == 16
    assert eq.starforce == 16

    # 2. Test Downgrade Scroll: under modern 30-star rules drop rate is 0.0%.
    # When drop > 0 (e.g. customized event/tier), downgrade scroll prevents the drop:
    monkeypatch.setitem(te.STARFORCE_TIERS[16], "drop", 50.0)
    monkeypatch.setitem(te.STARFORCE_TIERS[16], "maintain", 16.445)
    monkeypatch.setattr(random, "uniform", lambda a, b: 50.0)
    ok2, rep2, det2 = te.execute_pickaxe_upgrade(db_session, u.id, u.username, str(eq.id), use_downgrade=True)
    assert ok2 is True
    assert det2["used_downgrade_scroll"] is True
    assert det2["outcome"] == "downgrade_prevented"
    assert det2["remaining_downgrade_scrolls"] == 0
    assert eq.starforce == 16 # Not reduced to 15!
    assert u.downgrade_scroll_count == 0

    # 3. Test Shield Scroll: at 16성, roll of 99.0 hits destroy tier (>= 97.9).
    # designated with use_shield=True
    monkeypatch.setattr(random, "uniform", lambda a, b: 99.0)
    ok3, rep3, det3 = te.execute_pickaxe_upgrade(db_session, u.id, u.username, str(eq.id), use_shield=True)
    assert ok3 is True
    assert det3["used_shield_scroll"] is True
    assert det3["outcome"] == "destruction_prevented"
    assert det3["remaining_shield_scrolls"] == 0
    assert u.shield_scroll_count == 0
    assert eq.starforce == 16 # Item was NOT destroyed to level 12 trace!


def test_merchant_chat_commands(db_session):
    streamer_id = "4495f96624a2c60bd1ed5a6139014d20"
    viewer_id = "viewer_merchant_cmd"

    u = te.get_or_create_user(db_session, viewer_id, "상인시청자")
    u.points = 2000000
    db_session.commit()

    te.close_merchant(db_session)

    # 1. Non-streamer tries !신비상인오픈 -> blocked
    rep_rej, _ = ch.handle_chat_command(db_session, viewer_id, "상인시청자", "!신비상인오픈 10")
    assert "🚫" in rep_rej

    # 2. Check !신비상인 when closed
    rep_guide_closed, _ = ch.handle_chat_command(db_session, viewer_id, "상인시청자", "!신비상인")
    assert "부재중" in rep_guide_closed

    # 3. Streamer opens merchant: !신비상인오픈 15
    rep_open, ev_open = ch.handle_chat_command(db_session, streamer_id, "치즈나베", "!신비상인오픈 15")
    assert "신비상인 등장" in rep_open
    assert ev_open is not None
    assert ev_open["type"] == "merchant_appeared"

    # 4. Viewer checks !신비상인 when open
    rep_guide_open, _ = ch.handle_chat_command(db_session, viewer_id, "상인시청자", "!신비상인")
    assert "비밀 보따리 상점" in rep_guide_open
    assert "파괴방어권" in rep_guide_open
    assert "강화확률상승권" in rep_guide_open
    assert "하강방지권" in rep_guide_open

    # 5. Viewer buys items via dedicated chat command: !상인구매 1 1, !상인구매 2 1
    rep_buy1, ev_buy1 = ch.handle_chat_command(db_session, viewer_id, "상인시청자", "!상인구매 1 1")
    assert "구매 완료" in rep_buy1
    assert ev_buy1 is not None
    assert ev_buy1["type"] == "merchant_bought"
    assert u.shield_scroll_count == 1

    rep_buy2, ev_buy2 = ch.handle_chat_command(db_session, viewer_id, "상인시청자", "!상인구매 2 1")
    assert "구매 완료" in rep_buy2
    assert u.boost_scroll_count == 1

    # 5-1. Verify that !구매 is strictly stock purchase and not merchant purchase!
    rep_stock_buy, _ = ch.handle_chat_command(db_session, viewer_id, "상인시청자", "!구매")
    assert "매수 사용법" in rep_stock_buy

    # 6. Viewer checks inventory: !아이템 / !내아이템 / !가방
    rep_item, _ = ch.handle_chat_command(db_session, viewer_id, "상인시청자", "!아이템")
    assert "소비 아이템 보따리" in rep_item
    assert "파괴방어권: 1장" in rep_item
    assert "강화확률상승권: 1장" in rep_item

    # 7. Non-streamer tries !신비상인마감 -> blocked
    rep_close_rej, _ = ch.handle_chat_command(db_session, viewer_id, "상인시청자", "!신비상인마감")
    assert "🚫" in rep_close_rej

    # 8. Streamer closes merchant: !신비상인마감
    rep_close, ev_close = ch.handle_chat_command(db_session, streamer_id, "치즈나베", "!신비상인마감")
    assert "퇴장" in rep_close
    assert ev_close is not None
    assert ev_close["type"] == "merchant_left"


def test_legendary_potential_guarantee(db_session):
    """Ensures that when rolling cube on a LEGENDARY tier item, at least 1 line is 100% guaranteed to be LEGENDARY."""
    for _ in range(100):
        l1, l2, l3 = te.roll_cube_potential("LEGENDARY")
        tiers = [l1["tier"], l2["tier"], l3["tier"]]
        assert "LEGENDARY" in tiers
        assert l1["tier"] == "LEGENDARY"
        assert any(l["tier"] == "LEGENDARY" for l in [l1, l2, l3])


def test_lottery_three_tiers(db_session):
    u = te.get_or_create_user(db_session, "user_lotto_3tiers", "복권마니아")
    u.points = 1000000
    db_session.commit()

    te.open_lottery_event(db_session, duration_minutes=30)

    # 1. Basic (1,000P)
    ok, rep, det = te.execute_buy_lottery(db_session, "user_lotto_3tiers", "복권마니아", count=2, lottery_type="basic")
    assert ok is True
    assert det["ticket_price"] == 1000
    assert det["total_cost"] == 2000
    assert det["lottery_type"] == "basic"

    # 2. Silver (5,000P)
    ok, rep, det = te.execute_buy_lottery(db_session, "user_lotto_3tiers", "복권마니아", count=2, lottery_type="silver")
    assert ok is True
    assert det["ticket_price"] == 5000
    assert det["total_cost"] == 10000
    assert det["lottery_type"] == "silver"

    # 3. Gold (20,000P)
    ok, rep, det = te.execute_buy_lottery(db_session, "user_lotto_3tiers", "복권마니아", count=3, lottery_type="gold")
    assert ok is True
    assert det["ticket_price"] == 20000
    assert det["total_cost"] == 60000
    assert det["lottery_type"] == "gold"

    # 4. Chat command !복권 금 1 and !복권 은 2
    r_gold, ev_gold = ch.handle_chat_command(db_session, "user_lotto_3tiers", "복권마니아", "!복권 금 1")
    assert "금 복권" in r_gold
    assert ev_gold is not None

    r_silver, ev_silver = ch.handle_chat_command(db_session, "user_lotto_3tiers", "복권마니아", "!복권 은 2")
    assert "은 복권" in r_silver
    assert ev_silver is not None


def test_mahjong_tile_gamble_and_chat(db_session):
    u = te.get_or_create_user(db_session, "mahjong_player", "마작달인")
    u.points = 100000
    db_session.commit()

    # Casino must be open
    te.open_casino(db_session, duration_minutes=30)

    # 1. Suit gamble (만)
    ok, rep, det = te.execute_mahjong_tile_gamble(db_session, "mahjong_player", "마작달인", "만", 1000)
    assert ok is True
    assert det["bet"] == 1000
    assert det["bet_type"] == "suit"
    assert det["choice"] == "만"
    assert det["drawn_suit"] in ["만", "삭", "통"]
    if det["won"]:
        assert det["multiplier"] == 2.7
        assert det["net_payout"] == 1700
    else:
        assert det["net_payout"] == -1000

    # 2. Exact tile gamble (7통)
    ok2, rep2, det2 = te.execute_mahjong_tile_gamble(db_session, "mahjong_player", "마작달인", "7통", 1000)
    assert ok2 is True
    assert det2["bet_type"] == "exact"
    assert det2["choice"] == "7통"
    if det2["won"]:
        assert det2["multiplier"] == 24.3
        assert det2["net_payout"] == 23300
    else:
        assert det2["net_payout"] == -1000

    # 3. Chat command !마작
    r_chat, ev_chat = ch.handle_chat_command(db_session, "mahjong_player", "마작달인", "!마작 통 2000")
    assert "마작패" in r_chat
    assert ev_chat is not None


def test_yakuman_race_gamble_and_chat(db_session):
    u = te.get_or_create_user(db_session, "race_bettor", "경마팬")
    u.points = 100000
    db_session.commit()

    te.open_casino(db_session, duration_minutes=30)

    # 1. Direct function call: bet on 대삼원
    ok, rep, det = te.execute_yakuman_race_gamble(db_session, "race_bettor", "경마팬", "대삼원", 2000)
    assert ok is True
    assert det["bet"] == 2000
    assert det["choice"] == "대삼원"
    assert det["p1"] in ["대삼원", "사안커", "국사무쌍", "구련보등"]
    if det["won"]:
        assert det["net_payout"] == int(round(2000 * 3.6)) - 2000
    else:
        assert det["net_payout"] == -2000

    # 2. Chat command: !경마 국사무쌍 3000
    r_chat, ev_chat = ch.handle_chat_command(db_session, "race_bettor", "경마팬", "!경마 국사무쌍 3000")
    assert "역만 레이스" in r_chat
    assert ev_chat is not None

    # 3. Chat command alias !레이스 4 1000
    r_race, ev_race = ch.handle_chat_command(db_session, "race_bettor", "경마팬", "!레이스 4 1000")
    assert "역만 레이스" in r_race
    assert ev_race is not None


def test_casino_new_potential_bonuses(db_session):
    u = te.get_or_create_user(db_session, "pot_casino_user", "잠재카지노")
    u.points = 500000
    db_session.commit()

    te.open_casino(db_session, duration_minutes=30)

    # Create equipment with MAHJONG_TILE_BOOST and RACE_SAFETY_PAYBACK
    eq = te.get_user_equipped_item(db_session, u)
    if not eq:
        eq = te.UserEquipment(user_id=u.id, starforce=15, is_equipped=True)
        db_session.add(eq)
    eq.potential_tier = "LEGENDARY"
    eq.potential_line_1 = json.dumps({"code": "MAHJONG_TILE_BOOST", "val": 11.1, "text": "+11.1%"})
    eq.potential_line_2 = json.dumps({"code": "RACE_SAFETY_PAYBACK", "val": 40.0, "text": "40%"})
    db_session.commit()

    effects = te.get_equipment_potential_effects(eq)
    assert effects["mahjong_boost_pct"] == 11.1
    assert effects["race_safety_pct"] == 40.0


def test_designated_scroll_chat_commands(db_session, monkeypatch):
    """Test designated scroll usage via !강화 [옵션] and !주문서 settings."""
    uid = "user_scroll_chat"
    u = te.get_or_create_user(db_session, uid, "주문서유저")
    u.points = 3000000
    u.shield_scroll_count = 2
    u.boost_scroll_count = 1
    u.downgrade_scroll_count = 1
    db_session.commit()

    u.pickaxe_level = 15
    db_session.commit()

    eq = te.get_user_equipped_item(db_session, u)
    eq.starforce = 15
    eq.name = te.get_pickaxe_info(15)["name"]
    db_session.commit()

    # 1. Plain !강화 does NOT consume boost scroll
    monkeypatch.setattr(random, "uniform", lambda a, b: 35.0)
    rep0, _ = ch.handle_chat_command(db_session, uid, "주문서유저", "!강화")
    db_session.refresh(u)
    assert u.boost_scroll_count == 1

    # 2. !강화 파방 with destruction roll (99.0): consumes shield scroll and saves item
    monkeypatch.setattr(random, "uniform", lambda a, b: 99.0)
    rep_shield, ev_shield = ch.handle_chat_command(db_session, uid, "주문서유저", "!강화 파방")
    assert "파괴방어권 발동" in rep_shield
    db_session.refresh(u)
    db_session.refresh(eq)
    assert u.shield_scroll_count == 1
    assert eq.starforce == 15

    # 3. Setting toggle via !주문서
    rep_stat, _ = ch.handle_chat_command(db_session, uid, "주문서유저", "!주문서")
    assert "주문서 상시 사용 설정" in rep_stat
    assert "파괴방어권" in rep_stat

    rep_arm_on, _ = ch.handle_chat_command(db_session, uid, "주문서유저", "!주문서 파방 on")
    assert "활성화" in rep_arm_on
    assert u.arm_shield is True

    rep_arm_all_off, _ = ch.handle_chat_command(db_session, uid, "주문서유저", "!주문서 전체 off")
    assert "비활성화" in rep_arm_all_off
    assert u.arm_shield is False
    assert u.arm_boost is False
    assert u.arm_downgrade is False


def test_exchange_and_item_listings(db_session):
    """Test player marketplace item listing, buying, and cancelling (!거래소, !아이템판매, !거래소구매, !거래소취소)."""
    seller_id = "exchange_seller"
    buyer_id = "exchange_buyer"

    seller = te.get_or_create_user(db_session, seller_id, "상인판매자")
    seller.points = 100000
    seller.shield_scroll_count = 5
    seller.cube_count = 5

    buyer = te.get_or_create_user(db_session, buyer_id, "상인구매자")
    buyer.points = 1000000
    db_session.commit()

    state = te.get_market_state(db_session)
    init_treasury = state.treasury_pool

    # 1. Seller lists 2 shield scrolls for 600,000P
    rep_list, ev_list = ch.handle_chat_command(db_session, seller_id, "상인판매자", "!아이템판매 파방 2 600000")
    assert "등록했습니다" in rep_list
    assert ev_list is not None
    assert seller.shield_scroll_count == 3  # 2 escrowed!

    # 2. View exchange market
    rep_market, _ = ch.handle_chat_command(db_session, buyer_id, "상인구매자", "!거래소")
    assert "나베 통합 거래소" in rep_market
    assert "파괴방어권 x2개" in rep_market

    # 3. Buyer buys listing #I1
    rep_buy, ev_buy = ch.handle_chat_command(db_session, buyer_id, "상인구매자", "!거래소구매 I1")
    assert "구매 완료" in rep_buy
    assert ev_buy is not None
    assert buyer.shield_scroll_count == 2
    assert buyer.points == 400000  # 1,000,000 - 600,000
    assert seller.points == 100000 + (600000 - 30000)  # 5% fee (30,000P) deducted
    assert state.treasury_pool == init_treasury + 30000

    # 4. Seller lists 1 cube and cancels it
    rep_cube_list, _ = ch.handle_chat_command(db_session, seller_id, "상인판매자", "!아이템판매 큐브 1 20000")
    assert seller.cube_count == 4
    # Cancel listing
    rep_cancel, _ = ch.handle_chat_command(db_session, seller_id, "상인판매자", "!거래소취소 I2")
    assert "취소되어" in rep_cancel
    assert seller.cube_count == 5  # Refunded!


def test_direct_lottery_commands(db_session):
    """Test dedicated !동복권, !은복권, !금복권 commands."""
    uid = "lottery_direct_user"
    u = te.get_or_create_user(db_session, uid, "복권직구매자")
    u.points = 1000000
    db_session.commit()

    te.open_lottery_event(db_session, duration_minutes=30)

    # 1. Direct Bronze Lottery: !동복권 2 (Cost 2,000P)
    rep_bronze, ev_bronze = ch.handle_chat_command(db_session, uid, "복권직구매자", "!동복권 2")
    assert "동 복권(일반)" in rep_bronze
    assert ev_bronze is not None
    assert "본전" not in rep_bronze

    # 2. Direct Silver Lottery: !은복권 1 (Cost 5,000P)
    rep_silver, ev_silver = ch.handle_chat_command(db_session, uid, "복권직구매자", "!은복권 1")
    assert "은 복권(고급)" in rep_silver
    assert ev_silver is not None
    assert "본전" not in rep_silver

    # 3. Direct Gold Lottery: !금복권 2 (Cost 40,000P)
    rep_gold, ev_gold = ch.handle_chat_command(db_session, uid, "복권직구매자", "!금복권 2")
    assert "금 복권" in rep_gold
    assert ev_gold is not None
    assert "본전" not in rep_gold


def test_heavy_mining_and_buffed_goblin(db_session):
    """Verify heavy mining potential (increased CD & rewards) and buffed golden goblin potential."""
    uid = "test_heavy_miner"
    user = te.get_or_create_user(db_session, uid, "과충전채굴러")
    user.points = 1000000
    db_session.commit()

    # 1. Setup pickaxe with HEAVY_MINING (LEGENDARY: +7m CD, +400% reward) and GOBLIN (LEGENDARY: 15%, 1,000,000P)
    eq = te.get_user_equipped_item(db_session, user)
    if not eq:
        te.execute_buy_equipment(db_session, uid, "과충전채굴러", 0)
        eq = te.get_user_equipped_item(db_session, user)

    eq.potential_tier = "LEGENDARY"
    eq.potential_line_1 = json.dumps({"code": "HEAVY_MINING", "val": 7, "tier": "LEGENDARY", "text": "쿨타임 +7분 / 채굴 보상 +400%"})
    eq.potential_line_2 = json.dumps({"code": "GOBLIN_JACKPOT_CHANCE", "val": 15.0, "tier": "LEGENDARY", "text": "황금 고블린 토벌 (+1,000,000P)"})
    eq.potential_line_3 = json.dumps({"code": "MINING_BONUS_CASH", "val": 60000, "tier": "LEGENDARY", "text": "+60,000P"})
    db_session.commit()

    effects = te.get_equipment_potential_effects(eq)
    assert effects["heavy_mining_cd_add"] == 7
    assert effects["heavy_mining_reward_pct"] == 400.0
    assert effects["goblin_chance"] == 15.0
    assert effects["goblin_reward"] == 3500000

    # 2. Execute mining and verify cooldown is lengthened and reward boosted
    user.last_mining_at = None
    db_session.commit()

    success, reply, details = te.execute_mining(db_session, uid, "과충전채굴러")
    assert success is True
    assert "과충전" in reply or "🌋" in reply
    assert details is not None
    assert details.get("heavy_mult", 1.0) == 5.0  # 1.0 + 400% = 5.0x

    # Check cooldown status includes heavy CD add
    cd_status = te.get_user_cooldown_status(db_session, uid, "과충전채굴러")
    assert "분" in cd_status


def test_snipe_scroll_merchant_and_cubing(db_session):
    """Verify Wandering Merchant snipe scroll purchase, exchange trading, and cubing with non-100% targeting."""
    uid = "test_sniper_user"
    user = te.get_or_create_user(db_session, uid, "저격마스터")
    user.points = 2000000
    user.cube_count = 10
    db_session.commit()

    # Ensure user has equipment
    eq = te.get_user_equipped_item(db_session, user)
    if not eq:
        te.execute_buy_equipment(db_session, uid, "저격마스터", 0)
        eq = te.get_user_equipped_item(db_session, user)

    # 1. Open wandering merchant
    ok_open, msg_open, details_open = te.open_merchant(db_session, duration_minutes=30)
    assert ok_open is True
    m_state = te.get_merchant_state(db_session)
    assert m_state["is_active"] is True
    assert m_state["items"]["snipe"]["stock"] > 0
    assert m_state["items"]["snipe"]["price"] > 0

    # 2. Buy snipe scroll via !상인구매 4 1
    rep_buy, ev_buy = ch.handle_chat_command(db_session, uid, "저격마스터", "!상인구매 4 1")
    assert "잠재저격주문서" in rep_buy
    assert user.snipe_scroll_count >= 1

    # 3. Check inventory via !아이템
    rep_items, _ = ch.handle_chat_command(db_session, uid, "저격마스터", "!아이템")
    assert "잠재저격주문서" in rep_items

    # 4. Test Marketplace registration and cancellation
    rep_sell, _ = ch.handle_chat_command(db_session, uid, "저격마스터", "!아이템판매 저격 1 350000")
    assert "성공적으로 등록" in rep_sell or "I" in rep_sell
    assert user.snipe_scroll_count == 0  # in escrow

    # Cancel marketplace listing to get it back
    listing = db_session.query(ItemListing).filter_by(seller_id=uid, status="ACTIVE").first()
    assert listing is not None
    rep_cancel, _ = ch.handle_chat_command(db_session, uid, "저격마스터", f"!거래소취소 I{listing.id}")
    assert "반환되었습니다" in rep_cancel or "취소되어" in rep_cancel
    assert user.snipe_scroll_count == 1

    # 5. Execute cubing with snipe targeting: !큐브 저격 고블린
    initial_cubes = user.cube_count
    initial_snipes = user.snipe_scroll_count
    rep_cube, ev_cube = ch.handle_chat_command(db_session, uid, "저격마스터", "!큐브 저격 고블린")
    assert "미라클 큐브" in rep_cube
    assert "잠재 저격" in rep_cube
    assert user.cube_count == initial_cubes - 1
    assert user.snipe_scroll_count == initial_snipes - 1

    # 6. Verify strictly NOT 100% deterministic (user requirement: "100%저격 주문서는 안돼 확률 100%는 안돼 더 낮게")
    # Run 25 rolls with snipe targeting: there must be some misses on Line 1!
    target_codes = ["GOBLIN_JACKPOT_CHANCE"]
    line1_hits = 0
    total_rolls = 25
    for _ in range(total_rolls):
        l1, _, _ = te.roll_cube_potential("EPIC", target_codes=target_codes)
        if any(target in l1.get("text", "") for target in ["고블린", "토벌"]):
            line1_hits += 1

    assert line1_hits < total_rolls, "Target snipe must NOT be 100% guaranteed!"


def test_multi_pickaxe_inventory_potential_display(db_session):
    """Verify that multiple pickaxes in inventory display their full potential lines cleanly."""
    uid = "test_multi_pickaxe_user"
    user = te.get_or_create_user(db_session, uid, "곡괭이콜렉터")
    user.points = 1000000
    db_session.commit()

    # Buy 2 pickaxes
    te.execute_buy_equipment(db_session, uid, "곡괭이콜렉터", 0)
    te.execute_buy_equipment(db_session, uid, "곡괭이콜렉터", 0)

    pickaxes = db_session.query(te.UserEquipment).filter_by(user_id=uid).all()
    assert len(pickaxes) >= 2

    p1, p2 = pickaxes[0], pickaxes[1]
    p1.potential_tier = "EPIC"
    p1.potential_line_1 = "채굴 쿨타임 +2분 / 채굴 보상 +100%"
    p1.potential_line_2 = "채굴 성공 시 4.0% 확률로 쿨타임 즉시 초기화"
    p1.potential_line_3 = "채굴 시 순수 포인트 +10,000P 확정 지급"

    p2.potential_tier = "UNIQUE"
    p2.potential_line_1 = "채굴 시 8.0% 확률로 황금 고블린 토벌 (+400,000P)"
    p2.potential_line_2 = "채굴 크리티컬 확률 +14.0%"
    p2.potential_line_3 = "스타포스 강화 비용 상시 10.0% 할인"
    db_session.commit()

    # Query inventory
    rep, _ = ch.handle_chat_command(db_session, uid, "곡괭이콜렉터", "!인벤토리")
    assert f"#{p1.id}" in rep
    assert f"#{p2.id}" in rep
    assert "에픽" in rep
    assert "유니크" in rep
    assert "과충전" in rep or "+100%" in rep or "쿨타임 +2분" in rep
    assert "황금 고블린" in rep or "고블린" in rep

def test_user_requested_updates_september_19(db_session, monkeypatch):
    """
    Comprehensive test for:
    1. Direct usage of 잠재저격주문서 via !주문서 저격 [옵션] and !주문서 저격 on/off
    2. Starforce multiplicative success rate boost (+25%)
    3. Multiplicative mining crit scaling
    4. Confirmed auto-use of 파방 and 하강
    5. Batch exchange of 큐브조각 (all sets at once)
    6. Indebted user unblocked enhancement & cubing
    7. Casino default 10M max bet
    """
    import random
    uid = "update_test_user_19"
    uname = "패치검증러"
    user = te.get_or_create_user(db_session, uid, uname)
    user.points = 10000000
    user.cube_count = 5
    user.cube_fragments = 35
    user.snipe_scroll_count = 3
    user.shield_scroll_count = 2
    user.downgrade_scroll_count = 2
    user.boost_scroll_count = 2
    user.arm_shield = True
    user.arm_downgrade = True
    user.debt = 500000
    db_session.commit()

    # 1. Test !주문서 display includes snipe scroll and auto-confirmed protection
    r_scroll, _ = ch.handle_chat_command(db_session, uid, uname, "!주문서")
    assert "잠재저격주문서" in r_scroll
    assert "파괴방어권" in r_scroll
    assert "확정" in r_scroll or "ON" in r_scroll

    # 2. Test !주문서 저격 on / off
    r_on, _ = ch.handle_chat_command(db_session, uid, uname, "!주문서 저격 on")
    assert "활성화" in r_on
    db_session.refresh(user)
    assert user.arm_snipe is True

    r_off, _ = ch.handle_chat_command(db_session, uid, uname, "!주문서 저격 off")
    assert "비활성화" in r_off
    db_session.refresh(user)
    assert user.arm_snipe is False

    # 3. Test direct usage of 잠재저격주문서 via !주문서 저격 고블린
    init_snipe = user.snipe_scroll_count
    init_cubes = user.cube_count
    r_use_snipe, ev_snipe = ch.handle_chat_command(db_session, uid, uname, "!주문서 저격 고블린")
    assert "잠재" in r_use_snipe
    assert ev_snipe is not None
    assert ev_snipe["type"] == "cube_use"
    db_session.refresh(user)
    assert user.snipe_scroll_count == init_snipe - 1
    assert user.cube_count == init_cubes - 1

    # 4. Test batch cube fragment exchange: 36 frags (35 + 1 gained from cube use) -> 3 sets (30 frags) exchanged
    assert user.cube_fragments == 36
    r_frags, ev_frags = ch.handle_chat_command(db_session, uid, uname, "!큐브조각")
    assert "일괄 교환 완료" in r_frags
    assert "3세트" in r_frags or "30개" in r_frags
    db_session.refresh(user)
    assert user.cube_fragments == 6  # 36 - 30 = 6
    assert user.points == 10000000 + 45000  # 3 * 15,000P

    # 5. Test confirmed auto-use of 파방 and 하강 on !강화 (even with debt!)
    user.pickaxe_level = 15
    db_session.commit()
    # Force roll to destroy (> 90%)
    monkeypatch.setattr(random, "uniform", lambda a, b: 99.0)
    r_sf, ev_sf = ch.handle_chat_command(db_session, uid, uname, "!강화")
    assert "파괴방어권 발동" in r_sf or "방어" in r_sf
    db_session.refresh(user)
    assert user.shield_scroll_count == 1  # 2 - 1 consumed

    # 6. Test multiplicative starforce boost: base 30% * 1.25 = 37.5% (+7.5%p boost, not +10%p)
    user.pickaxe_level = 10
    db_session.commit()
    monkeypatch.setattr(random, "uniform", lambda a, b: 10.0)
    r_boost_sf, _ = ch.handle_chat_command(db_session, uid, uname, "!강화 상승")
    assert "곱연산" in r_boost_sf or "+25%" in r_boost_sf

    # 7. Test casino default max bet is 10M
    c_state = te.get_casino_state(db_session)
    assert c_state["max_bet"] == 10000000


def test_user_requested_updates_september_19_part2(db_session):
    """
    Test suite for:
    1. Mysterious merchant closes and leaves automatically when all items are sold out
    2. Mining cooldown in !남은시간 matches !채굴 and accounts for potential cooldown reductions
    3. Legendary tier cubing has boosted Legendary option rates (Line 2 80%, Line 3 60%)
    4. 20-star pickaxe Yakuman rates are enhanced
    """
    import datetime
    from datetime import timezone
    uid = "update_test_user_pt2"
    uname = "패치검증러2"
    user = te.get_or_create_user(db_session, uid, uname)
    user.points = 10000000
    db_session.commit()

    # 1. Test merchant leaves when all items are sold out
    ok_open, _, _ = te.open_merchant(db_session, duration_minutes=30)
    assert ok_open is True
    m_state = te.get_market_state(db_session)
    m_state.merchant_shield_stock = 1
    m_state.merchant_boost_stock = 0
    m_state.merchant_downgrade_stock = 0
    m_state.merchant_snipe_stock = 0
    db_session.commit()

    r_buy, ev_buy = ch.handle_chat_command(db_session, uid, uname, "!상인구매 1 1")
    assert "완판" in r_buy or "떠났습니다" in r_buy
    m_state_after = te.get_merchant_state(db_session)
    assert m_state_after["is_active"] is False

    # 2. Test mining cooldown in !남은시간 matches !채굴 and accounts for potential reduction
    eq = te.get_user_equipped_item(db_session, user)
    if not eq:
        te.execute_buy_equipment(db_session, uid, uname, 0)
    user.pickaxe_level = 10
    eq.starforce = 10  # Base cooldown: 10 minutes
    eq.potential_line_1 = json.dumps({"code": "MINING_CD_REDUCTION", "val": 2, "text": "-2분"})
    eq.potential_line_2 = ""
    eq.potential_line_3 = ""
    db_session.commit()

    # User mined 1 minute ago (effective cooldown is 10 - 2 = 8 minutes -> 7 minutes remaining)
    now_utc = datetime.datetime.now(timezone.utc)
    user.last_mined_at = now_utc - datetime.timedelta(minutes=1)
    db_session.commit()

    r_time, _ = ch.handle_chat_command(db_session, uid, uname, "!남은시간")
    assert "6분" in r_time or "7분" in r_time
    assert "9분" not in r_time  # Must NOT use unreduced 10-minute cooldown!

    r_mine, ev_mine = ch.handle_chat_command(db_session, uid, uname, "!채굴")
    assert "6분" in r_mine or "7분" in r_mine
    assert "9분" not in r_mine

    # 3. Test boosted Legendary potential rates (Line 2 80%, Line 3 60%)
    l2_leg_count = 0
    l3_leg_count = 0
    sample_size = 300
    for _ in range(sample_size):
        l1, l2, l3 = te.roll_cube_potential("LEGENDARY")
        assert l1["tier"] == "LEGENDARY"
        if l2["tier"] == "LEGENDARY":
            l2_leg_count += 1
        if l3["tier"] == "LEGENDARY":
            l3_leg_count += 1

    l2_rate = l2_leg_count / sample_size
    l3_rate = l3_leg_count / sample_size
    assert l2_rate >= 0.70, f"Expected Line 2 to be ~80% LEGENDARY, got {l2_rate:.2f}"
    assert l3_rate >= 0.50, f"Expected Line 3 to be ~60% LEGENDARY, got {l3_rate:.2f}"


def test_equipment_cube_lock_and_unlock(db_session):
    """Test equipment cube lock preventing accidental cube rolls (!큐브잠금, !큐브해제)."""
    user_id = "test_eq_lock_user"
    user = te.get_or_create_user(db_session, user_id, "큐브락유저")
    user.cube_count = 5
    db_session.commit()

    eq = te.get_user_equipped_item(db_session, user)
    assert eq.is_cube_locked is False

    # 1. Lock equipment
    rep1, _ = ch.handle_chat_command(db_session, user_id, "큐브락유저", "!큐브잠금")
    assert "큐브 잠금(보호)이 활성화" in rep1
    db_session.refresh(eq)
    assert eq.is_cube_locked is True

    # 2. Try using cube while locked - must be blocked
    rep2, ev2 = ch.handle_chat_command(db_session, user_id, "큐브락유저", "!큐브")
    assert "큐브 잠금(보호) 상태입니다" in rep2
    assert ev2 is None
    assert user.cube_count == 5

    # 3. Unlock equipment
    rep3, _ = ch.handle_chat_command(db_session, user_id, "큐브락유저", "!큐브해제")
    assert "큐브 잠금이 해제" in rep3
    db_session.refresh(eq)
    assert eq.is_cube_locked is False

    # 4. Cube now works
    rep4, ev4 = ch.handle_chat_command(db_session, user_id, "큐브락유저", "!큐브")
    assert "큐브를 사용했습니다" in rep4
    assert ev4 is not None
    assert user.cube_count == 4


def test_potential_line_lock_twenty_times_cost(db_session):
    """Test potential line lock requiring 20x cube cost (300,000P or 20 cubes) and preserving lines."""
    user_id = "test_line_lock_user"
    user = te.get_or_create_user(db_session, user_id, "라인락유저")
    user.points = 10000000
    user.cube_count = 50
    db_session.commit()

    eq = te.get_user_equipped_item(db_session, user)
    eq.potential_tier = "LEGENDARY"
    l1 = {"code": "STARFORCE_SAFEGUARD", "name": "15성+ 파괴 방지", "icon": "🛡️", "tier": "LEGENDARY", "val": 65.0, "unit": "%", "text": "🛡️ 15성+ 파괴 방지 65%"}
    l2 = {"code": "CASINO_SLOT_BOOST", "name": "슬롯 보너스", "icon": "🎰", "tier": "LEGENDARY", "val": 50.0, "unit": "%", "text": "🎰 슬롯 보너스 50%"}
    l3 = {"code": "MAHJONG_TILE_BOOST", "name": "마작 보너스", "icon": "🀄", "tier": "LEGENDARY", "val": 15.0, "unit": "%", "text": "🀄 마작 보너스 15%"}
    eq.potential_line_1 = json.dumps(l1, ensure_ascii=False)
    eq.potential_line_2 = json.dumps(l2, ensure_ascii=False)
    eq.potential_line_3 = json.dumps(l3, ensure_ascii=False)
    db_session.commit()

    # 1. Lock line 1 via command
    rep1, _ = ch.handle_chat_command(db_session, user_id, "라인락유저", "!옵션잠금 1")
    assert "잠재 옵션 라인 잠금 설정 완료" in rep1
    db_session.refresh(eq)
    assert eq.is_line1_locked is True
    assert eq.is_line2_locked is False

    # 2. Cannot lock more than 1 line
    rep_fail, _ = ch.handle_chat_command(db_session, user_id, "라인락유저", "!옵션잠금 2 3")
    assert "최대 1줄까지만" in rep_fail

    # 2-1. Locking line 2 automatically switches from line 1 (only 1 line locked)
    rep_switch, _ = ch.handle_chat_command(db_session, user_id, "라인락유저", "!옵션잠금 2")
    assert "전환" in rep_switch or "잠금 설정 완료" in rep_switch
    db_session.refresh(eq)
    assert eq.is_line1_locked is False
    assert eq.is_line2_locked is True
    assert eq.is_line3_locked is False

    # Switch back to line 1 for subsequent cube tests
    ch.handle_chat_command(db_session, user_id, "라인락유저", "!옵션잠금 1")
    db_session.refresh(eq)
    assert eq.is_line1_locked is True
    assert eq.is_line2_locked is False

    # 3. Roll cube with line 1 locked: consumes 20 cubes and keeps line 1
    prev_cubes = user.cube_count
    prev_frags = user.cube_fragments or 0
    rep_cube, _ = ch.handle_chat_command(db_session, user_id, "라인락유저", "!큐브")
    assert "라인 1줄 잠금 적용" in rep_cube
    assert "보유 큐브 20개 소모" in rep_cube
    assert "🔒[잠금유지]" in rep_cube
    db_session.refresh(user)
    db_session.refresh(eq)
    assert user.cube_count == prev_cubes - 20
    assert user.cube_fragments == prev_frags + 20
    assert json.loads(eq.potential_line_1) == l1

    # 4. Roll cube with points when cubes < 20 (pays in points directly at 20x price)
    user.cube_count = 0
    user.points = 1000000
    db_session.commit()
    rep_cube2, _ = ch.handle_chat_command(db_session, user_id, "라인락유저", "!큐브")
    assert "300,000P 소모 (라인 잠금 20배)" in rep_cube2
    db_session.refresh(user)
    assert user.points == 700000
    assert user.cube_fragments == prev_frags + 40

    # 5. Reset line lock
    rep_clear, _ = ch.handle_chat_command(db_session, user_id, "라인락유저", "!옵션잠금 해제")
    assert "모든 잠재 옵션 라인 잠금이 해제" in rep_clear
    db_session.refresh(eq)
    assert eq.is_line1_locked is False
    assert eq.is_line2_locked is False
    assert eq.is_line3_locked is False


def test_second_place_dividend_payout_and_chat_reply(db_session):
    """Verify that 2nd place pays 1% dividend and chat message correctly displays the paid amount (not +0P)."""
    user_id = "test_holder_2nd_div"
    te.execute_buy(db_session, user_id, "배당주주", "1X", "20")
    user = db_session.query(User).filter_by(id=user_id).first()
    pts_before = user.points
    divs_before = user.total_dividends or 0

    # Streamer runs !정산 2 0 (or !정산 2)
    rep, evt = ch.handle_chat_command(db_session, "streamer", "치즈나베", "!정산 2 0")
    assert "2위" in rep
    assert "2위 준우승 1% 1X 배당: 1명(+" in rep
    assert "(+0P)" not in rep

    db_session.refresh(user)
    assert user.points > pts_before
    assert user.total_dividends > divs_before

    # Verify settle_match with negative delta still distributes 2nd place dividend
    settle_res = te.settle_match(db_session, rank=2, point_delta=-15)
    assert len(settle_res["dividends"]) >= 1
    d = next(item for item in settle_res["dividends"] if item["user_id"] == user_id)
    assert d["payout"] > 0
    assert d["amount"] == d["payout"]
    assert d["rate_pct"] == 1.0


def test_credit_rating_evaluation_and_limits(db_session):
    """Test dynamic credit scoring, tier determination, and personalized loan limits."""
    # 1. New user has Tier 5 (BB 보통) and 3,000,000P limit
    u_new = te.get_or_create_user(db_session, "credit_user_new", "새내기")
    c_new = te.get_user_credit_info(u_new, db=db_session)
    assert c_new["tier"] == 5
    assert c_new["grade"] == "BB"
    assert c_new["loan_limit"] == 3000000
    assert c_new["interest_rate_pct"] == 2.0
    assert c_new["available_borrow"] == 3000000

    # 2. Rich user with Diamond pickaxe 21-star and 100M+ assets gets Tier 1 (AAA)
    u_rich = te.get_or_create_user(db_session, "credit_user_rich", "재벌엘프")
    u_rich.points = 120000000
    u_rich.total_mined = 2000000
    eq_dia = UserEquipment(
        user_id="credit_user_rich",
        name="다이아몬드 곡괭이",
        starforce=21,
        is_equipped=True,
        potential_tier="LEGENDARY",
        potential_line_1='{"text": "채굴량 0.2배 증가", "tier": "LEGENDARY"}'
    )
    db_session.add(eq_dia)
    db_session.commit()
    db_session.refresh(u_rich)

    c_rich = te.get_user_credit_info(u_rich, db=db_session)
    assert c_rich["tier"] == 1
    assert c_rich["grade"] == "AAA"
    assert c_rich["loan_limit"] == 50000000
    assert c_rich["interest_rate_pct"] == 1.0

    # 3. Bankrupted user gets Tier 10 (D) and 0P limit
    u_bankrupt = te.get_or_create_user(db_session, "credit_user_bankrupt", "파산자")
    u_bankrupt.last_bankrupt_at = datetime.now(timezone.utc)
    u_bankrupt.debt = 1000000
    db_session.commit()
    db_session.refresh(u_bankrupt)

    c_bankrupt = te.get_user_credit_info(u_bankrupt, db=db_session)
    assert c_bankrupt["tier"] == 10
    assert c_bankrupt["loan_limit"] == 0
    assert c_bankrupt["available_borrow"] == 0

    # Bankrupt user cannot borrow
    ok_b, msg_b, _ = te.execute_borrow(db_session, "credit_user_bankrupt", "파산자", "10000")
    assert ok_b is False
    assert "신규 대출이 불가합니다" in msg_b or "대출 불가" in msg_b

    # 4. New user borrowing within 3,000,000P limit succeeds (fund treasury first)
    state = te.get_market_state(db_session)
    state.treasury_pool = 50000000.0
    db_session.commit()

    ok_borrow, msg_borrow, det_borrow = te.execute_borrow(db_session, "credit_user_new", "새내기", "2000000")
    assert ok_borrow is True
    assert det_borrow["amount"] == 2000000
    assert "5등급" in msg_borrow

    # 5. New user borrowing exceeding remaining limit fails
    ok_exceed, msg_exceed, _ = te.execute_borrow(db_session, "credit_user_new", "새내기", "2000000")
    assert ok_exceed is False
    assert "최대 대출 한도" in msg_exceed


def test_credit_repayment_bonus_and_settle(db_session):
    """Test repayment history increases credit score and settlement applies credit interest rate."""
    state = te.get_market_state(db_session)
    state.treasury_pool = 50000000.0
    db_session.commit()

    u = te.get_or_create_user(db_session, "credit_repay_user", "성실상환자")
    te.execute_borrow(db_session, "credit_repay_user", "성실상환자", "500000")
    db_session.refresh(u)
    assert u.debt == 500000

    # Repay partial
    ok_rep, msg_rep, det_rep = te.execute_repay(db_session, "credit_repay_user", "성실상환자", "200000")
    assert ok_rep is True
    assert u.repay_count == 1
    assert u.total_repaid == 200000
    assert "신용등급" in msg_rep

    # Settle match charges interest based on credit tier
    # User's debt ratio is 300,000 / 350,000 = 85.7% (Tier 6, B 일반 -> 2.2% interest)
    # Remaining debt 300,000 * 2.2% = 6,600P
    settle_res = te.settle_match(db_session, rank=3, point_delta=0)
    assert settle_res["interest_collected"] == 6600


def test_credit_rating_chat_commands(db_session):
    """Test !신용등급, !신용, !대출 without args, and !내정보 credit display."""
    uid = "credit_chat_user"
    uname = "신용러"
    te.get_or_create_user(db_session, uid, uname)

    # 1. !신용등급
    rep_cred, _ = ch.handle_chat_command(db_session, uid, uname, "!신용등급")
    assert "나베신용평가원" in rep_cred
    assert "신용등급" in rep_cred
    assert "대출 한도" in rep_cred
    assert "적용 금리" in rep_cred

    # 2. !신용 alias
    rep_alias, _ = ch.handle_chat_command(db_session, uid, uname, "!신용")
    assert "나베신용평가원" in rep_alias

    # 3. !대출 with no args shows credit tier & remaining capacity
    rep_loan_prompt, _ = ch.handle_chat_command(db_session, uid, uname, "!대출")
    assert "신용:" in rep_loan_prompt
    assert "추가 가능 한도" in rep_loan_prompt

    # 4. !내정보 includes credit rating
    rep_info, _ = ch.handle_chat_command(db_session, uid, uname, "!내정보")
    assert "신용:" in rep_info


def test_user_asset_history_and_seeding(db_session):
    u = te.get_or_create_user(db_session, "u_trend_test", "추이트렌드")
    u.points = 120000

    # 1. Seed history for user
    hist = te.seed_single_user_asset_history(db_session, u)
    assert len(hist) >= 5
    assert hist[0].net_worth == 50000
    assert hist[0].event_type == "INITIAL"
    assert hist[-1].net_worth == 120000

    # 2. Add manual snapshot
    snap = te.record_user_asset_snapshot(db_session, u, event_type="MINE", note="대박 채굴", force=True)
    assert snap is not None
    assert snap.net_worth == 120000

    # 3. Fetch history
    fetched = te.get_user_asset_history(db_session, u.id)
    assert len(fetched) >= 6
    assert fetched[-1]["event_type"] == "MINE"
    assert fetched[-1]["note"] == "대박 채굴"


def test_pvp_arena_duel_flow(db_session):
    p1 = te.get_or_create_user(db_session, "p1_fighter", "격투왕")
    p2 = te.get_or_create_user(db_session, "p2_challenger", "도전자")
    p1.points = 100000
    p2.points = 100000
    db_session.commit()

    # 1. Direct Challenge
    ok, reply, details = te.create_pvp_challenge(db_session, p1.id, p1.username, p2.username, "50000")
    assert ok is True
    assert "맞짱 신청" in reply
    assert details["bet"] == 50000
    assert details["pot_total"] == 100000

    # 2. Cannot challenge self
    ok_self, rep_self, _ = te.create_pvp_challenge(db_session, p1.id, p1.username, p1.username, "10000")
    assert ok_self is False
    assert "자기 자신" in rep_self

    # 3. Decline challenge
    ok_dec, rep_dec, _ = te.decline_pvp_challenge(db_session, p2.id, p2.username)
    assert ok_dec is True
    assert "도망" in rep_dec

    # 4. Challenge again and Accept
    ok, reply, details = te.create_pvp_challenge(db_session, p1.id, p1.username, p2.username, "50000")
    assert ok is True
    ok_acc, rep_acc, det_acc = te.accept_pvp_challenge(db_session, p2.id, p2.username)
    assert ok_acc is True
    assert "데스매치 결과" in rep_acc
    assert det_acc["winner_reward"] == 98000 # 98% of 100,000
    assert det_acc["tax_fee"] == 2000 # 2% tax
    assert (p1.points + p2.points) == 198000 # 200,000 - 2,000 tax

    # 5. Open public arena match
    ok_open, rep_open, det_open = te.open_public_arena_match(db_session, p1.id, p1.username, "30000")
    assert ok_open is True
    assert "공개 결투장 개설" in rep_open

    # 6. Join open match
    ok_join, rep_join, det_join = te.join_public_arena_match(db_session, p2.id, p2.username)
    assert ok_join is True
    assert "데스매치 결과" in rep_join
    assert det_join["bet"] == 30000


def test_scroll_arm_toggle_safe_against_cube(db_session):
    u = te.get_or_create_user(db_session, "u_scroll_safe", "주문서세이프")
    u.points = 100000
    u.cube_count = 5
    u.boost_scroll_count = 3
    db_session.commit()

    # 1. !주문서 강화 on -> must toggle arm_boost, ZERO cubes used
    rep1, evt1 = ch.handle_chat_command(db_session, u.id, u.username, "!주문서 강화 on")
    db_session.refresh(u)
    assert "강화확률상승권" in rep1
    assert "활성화" in rep1
    assert u.arm_boost is True
    assert u.cube_count == 5
    assert evt1 is None

    # 2. !주문서 2 off -> must toggle arm_boost to False, ZERO cubes used
    rep2, evt2 = ch.handle_chat_command(db_session, u.id, u.username, "!주문서 2 off")
    db_session.refresh(u)
    assert "비활성화" in rep2
    assert u.arm_boost is False
    assert u.cube_count == 5

    # 3. !주문서 2 on, -> handles trailing comma cleanly
    rep3, evt3 = ch.handle_chat_command(db_session, u.id, u.username, "!주문서 2 on,")
    db_session.refresh(u)
    assert "활성화" in rep3
    assert u.arm_boost is True
    assert u.cube_count == 5










