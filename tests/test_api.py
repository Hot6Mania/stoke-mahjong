import os
import pytest
from starlette.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base
from models import User, Position, LimitOrder, MarketState
import trading_engine as te
from main import app, get_db
import main

TEST_DB_PATH = "test_api_temp.db"
test_engine = create_engine(f"sqlite:///{TEST_DB_PATH}", connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

@pytest.fixture(scope="module", autouse=True)
def setup_db():
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    Base.metadata.create_all(bind=test_engine)
    with TestingSessionLocal() as s:
        st = MarketState(
            id=1,
            current_rank_point=2340,
            current_price=2340,
            previous_price=2340,
            day_open_price=2340,
            is_trading_locked=False,
            last_settlement_delta=0,
            treasury_pool=500000.0
        )
        s.add(st)
        s.commit()

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    orig_session_local = main.SessionLocal
    main.SessionLocal = TestingSessionLocal

    yield

    app.dependency_overrides.clear()
    main.SessionLocal = orig_session_local
    Base.metadata.drop_all(bind=test_engine)
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

@pytest.fixture
def client():
    return TestClient(app)

def test_pages(client):
    res_overlay = client.get("/overlay")
    assert res_overlay.status_code == 200
    assert "나베주가" in res_overlay.text
    assert "주주 랭킹 TOP 3" in res_overlay.text
    assert "rank-container" in res_overlay.text
    assert "stats-container" in res_overlay.text

    res_admin = client.get("/admin")
    assert res_admin.status_code == 200
    assert "마작 주식 & 파생상품 거래 관리 패널" in res_admin.text

    res_tracker = client.get("/api/tracker/data")
    assert res_tracker.status_code == 200
    assert "score" in res_tracker.json()

    # Test dedicated stock overlay
    res_stock = client.get("/overlay/stock")
    assert res_stock.status_code == 200
    assert "나베주가" in res_stock.text
    assert "stock-container" in res_stock.text
    assert "rank-container" not in res_stock.text

    res_stock_alias = client.get("/stock-overlay")
    assert res_stock_alias.status_code == 200

    # Test dedicated mahjong overlay
    res_mahjong = client.get("/overlay/mahjong")
    assert res_mahjong.status_code == 200
    assert "rank-container" in res_mahjong.text
    assert "stock-container" not in res_mahjong.text

    res_mahjong_alias = client.get("/tracker-overlay")
    assert res_mahjong_alias.status_code == 200

def test_chzzk_api_endpoints(client):
    from chzzk_api import chzzk_api
    orig_tokens = dict(chzzk_api.tokens or {})

    try:
        res_status = client.get("/api/chzzk/status")
        assert res_status.status_code == 200
        data = res_status.json()
        assert data["has_client_id"] is True
        assert data["has_client_secret"] is True
        assert "bot_websocket_connected" in data

        res_login = client.get("/api/chzzk/login", follow_redirects=False)
        assert res_login.status_code in [302, 307]
        assert "account-interlock" in res_login.headers["location"]
        assert "localhost%3A7700%2Fcallback" in res_login.headers["location"] or "localhost:7700/callback" in res_login.headers["location"]

        # Test both callback routes without code
        res_cb1 = client.get("/callback")
        assert res_cb1.status_code == 400
        res_cb2 = client.get("/api/chzzk/callback")
        assert res_cb2.status_code == 400

        # Test set-tokens
        res_set = client.post("/api/chzzk/set-tokens", json={"accessToken": "test_tok", "refreshToken": "test_ref"})
        assert res_set.status_code == 200
        assert res_set.json()["success"] is True

        # Test subscribe-donation endpoint
        res_sub = client.post("/api/chzzk/subscribe-donation")
        assert res_sub.status_code == 200
        assert "success" in res_sub.json()

        # Test exchange-code endpoint with empty code
        res_exc = client.post("/api/chzzk/exchange-code", json={"code": ""})
        assert res_exc.status_code == 200
        assert res_exc.json()["success"] is False
    finally:
        chzzk_api.tokens = orig_tokens
        try:
            import json, os
            tok_file = os.path.join(os.path.dirname(__file__), "..", "tokens.json")
            with open(tok_file, "w", encoding="utf-8") as f:
                json.dump(orig_tokens, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

def test_admin_lock_market(client):
    # Set to locked
    res = client.post("/api/admin/lock-market", json={"locked": True})
    assert res.status_code == 200
    assert res.json()["is_trading_locked"] is True

    # Check that buy is rejected while locked
    res_buy = client.post("/api/chat/command", json={
        "user_id": "test_user_api",
        "username": "테스터",
        "message": "!매수 1X 10"
    })
    assert res_buy.status_code == 200
    assert "거래 마감" in res_buy.json()["reply"]

    # Unlock market
    res_unlock = client.post("/api/admin/lock-market", json={"locked": False})
    assert res_unlock.status_code == 200
    assert res_unlock.json()["is_trading_locked"] is False

def test_free_trading_window(client):
    # 1. Start free trading window (300 seconds)
    res_start = client.post("/api/admin/start-free-trading", json={"seconds": 300})
    assert res_start.status_code == 200
    data = res_start.json()
    assert data["success"] is True
    assert data["is_trading_locked"] is False
    assert data["remaining_seconds"] == 300

    # 2. Check market state reflects free trading remaining
    res_state = client.get("/api/market/state")
    assert res_state.status_code == 200
    state_data = res_state.json()
    assert state_data["is_trading_locked"] is False
    assert state_data["free_trading_remaining"] > 290

    # 3. Manual lock cancels the window and zeroes remaining time
    res_lock = client.post("/api/admin/lock-market", json={"locked": True})
    assert res_lock.status_code == 200
    assert res_lock.json()["is_trading_locked"] is True
    assert res_lock.json()["free_trading_remaining"] == 0

    res_state_locked = client.get("/api/market/state")
    assert res_state_locked.json()["free_trading_remaining"] == 0

    # Restore unlock for subsequent tests
    client.post("/api/admin/lock-market", json={"locked": False})

def test_chat_command_help(client):
    res = client.post("/api/chat/command", json={
        "user_id": "test_user_api",
        "username": "테스터",
        "message": "!주식명령어"
    })
    assert res.status_code == 200
    reply = res.json()["reply"]
    assert "📈 [마작 주식 명령어 안내]" in reply
    assert "• 거래: !매수" in reply
    assert "• 금융: !내정보" in reply
    assert "• 도박: !슬롯" in reply
    assert "• 종목: 1X, 2X, 3X, 5X, 10X" in reply
    assert "📖 상세 웹 가이드:" in reply

def test_chat_flow_and_settlement(client):
    # 1. Check market state
    res_market = client.get("/api/market/state")
    assert res_market.status_code == 200
    assert res_market.json()["current_price"] >= 10

    # 2. Grant points
    res_grant = client.post("/api/admin/grant-points", json={
        "user_id": "trader_kim",
        "username": "김트레이더",
        "points": 50000,
        "mode": "set"
    })
    assert res_grant.status_code == 200
    assert res_grant.json()["points"] == 50000

    # 3. Buy 2X shares
    res_buy = client.post("/api/chat/command", json={
        "user_id": "trader_kim",
        "username": "김트레이더",
        "message": "!매수 2X 20"
    })
    assert res_buy.status_code == 200
    assert "매수 완료" in res_buy.json()["reply"]

    # 4. Check user info
    res_info = client.post("/api/chat/command", json={
        "user_id": "trader_kim",
        "username": "김트레이더",
        "message": "!내정보"
    })
    assert res_info.status_code == 200
    assert "2X: 20주" in res_info.json()["reply"]

    # 5. Settle match (1st place +270pt)
    res_settle = client.post("/api/admin/settle-match", json={
        "rank": 1,
        "point_delta": 270
    })
    assert res_settle.status_code == 200
    assert res_settle.json()["is_trading_locked"] is False

    # 6. Check leaderboard
    res_lb = client.get("/api/leaderboard")
    assert res_lb.status_code == 200
    leaders = res_lb.json()
    assert len(leaders) >= 1
    assert leaders[0]["username"] == "김트레이더"

    # 7. Liquidate user holdings
    res_liq = client.post("/api/chat/command", json={
        "user_id": "trader_kim",
        "username": "김트레이더",
        "message": "!청산 전량"
    })
    assert res_liq.status_code == 200
    assert "전량 청산 완료" in res_liq.json()["reply"]

def test_second_place_settlement_api(client):
    # Grant points and buy 1X
    client.post("/api/admin/grant-points", json={
        "user_id": "div_user_2nd",
        "username": "이등주주",
        "points": 50000,
        "mode": "set"
    })
    res_buy = client.post("/api/chat/command", json={
        "user_id": "div_user_2nd",
        "username": "이등주주",
        "message": "!매수 1X 10"
    })
    assert res_buy.status_code == 200

    # Settle match for 2nd place (rank 2)
    res_settle = client.post("/api/admin/settle-match", json={
        "rank": 2,
        "point_delta": 20
    })
    assert res_settle.status_code == 200
    data = res_settle.json()
    assert data["rank"] == 2
    assert "dividends" in data
    assert len(data["dividends"]) >= 1
    d = next(item for item in data["dividends"] if item["user_id"] == "div_user_2nd")
    assert d["rate_pct"] in [1.0, 3.0]
    assert d["payout"] > 0

def test_refill_treasury_and_day_open(client):
    # Test market state includes day_open_price, day_diff, day_diff_pct, treasury_pool
    res_state = client.get("/api/market/state")
    assert res_state.status_code == 200
    data = res_state.json()
    assert "day_open_price" in data
    assert "day_diff" in data
    assert "day_diff_pct" in data
    assert data["treasury_pool"] >= 500000.0

    # Test refill treasury endpoint
    res_refill = client.post("/api/admin/refill-treasury", json={"amount": 600000.0})
    assert res_refill.status_code == 200
    refill_data = res_refill.json()
    assert refill_data["success"] is True
    assert refill_data["treasury_pool"] == 600000.0

def test_set_day_open_api(client):
    # 1. Set explicit day open price
    res = client.post("/api/admin/set-day-open", json={"price": 2137})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["day_open_price"] == 2137

    # Verify market state reflects 2137
    res_state = client.get("/api/market/state")
    assert res_state.status_code == 200
    state_data = res_state.json()
    assert state_data["day_open_price"] == 2137

    # 2. Reset day open price to current_price when price is None
    res_curr = client.post("/api/admin/set-day-open", json={})
    assert res_curr.status_code == 200
    assert res_curr.json()["day_open_price"] == state_data["current_price"]

def test_bankruptcy_court_api(client):
    u = "court_applicant"
    name = "신청자A"

    # 1. Borrow 50,000P
    res_borrow = client.post("/api/chat/command", json={
        "user_id": u,
        "username": name,
        "message": "!대출 50000"
    })
    assert res_borrow.status_code == 200

    # 2. Buy 10X all-in and drop match to lose assets
    client.post("/api/chat/command", json={
        "user_id": u,
        "username": name,
        "message": "!매수 10X 올인"
    })
    client.post("/api/admin/settle-match", json={"rank": 4, "point_delta": -300})

    # 3. Submit bankruptcy application via chat
    res_apply = client.post("/api/chat/command", json={
        "user_id": u,
        "username": name,
        "message": "!파산신청 10X 타다가 전재산 날렸습니다 살려주세요"
    })
    assert res_apply.status_code == 200
    apply_data = res_apply.json()
    assert "법정에 접수되었습니다" in apply_data["reply"]
    assert apply_data["event"]["type"] == "bankruptcy_requested"

    # 4. Check pending list on admin API
    res_pending = client.get("/api/admin/bankruptcy/pending")
    assert res_pending.status_code == 200
    pending_list = res_pending.json()["applications"]
    assert len(pending_list) >= 1
    target = [a for a in pending_list if a["user_id"] == u][0]
    assert target["debt"] >= 50000
    assert "살려주세요" in target["reason"]
    app_id = target["id"]

    # 5. Admin judges the application with 'full' verdict
    res_judge = client.post("/api/admin/bankruptcy/judge", json={
        "app_id": app_id,
        "verdict": "full",
        "comment": "살려줄테니 열심히 채굴해라"
    })
    assert res_judge.status_code == 200
    judge_data = res_judge.json()
    assert judge_data["success"] is True
    assert "회생을 인가했습니다" in judge_data["reply"]
    assert judge_data["data"]["remaining_debt"] == 0
    assert judge_data["data"]["points"] == 10000

    # 6. Check pending list is now cleared
    res_pending_after = client.get("/api/admin/bankruptcy/pending")
    rem_targets = [a for a in res_pending_after.json()["applications"] if a["user_id"] == u]
    assert len(rem_targets) == 0

def test_margin_buy_and_admin_page(client):
    # 1. Check admin page HTML loads successfully
    res_admin = client.get("/admin")
    assert res_admin.status_code == 200
    assert "나베 판사의 회생 법정" in res_admin.text
    assert "!매수 10X 빚올인" in res_admin.text

    # 2. Test margin buy via HTTP chat command
    u_margin = "api_margin_user"
    res_buy = client.post("/api/chat/command", json={
        "user_id": u_margin,
        "username": "마진유저",
        "message": "!매수 10X 빚올인"
    })
    assert res_buy.status_code == 200
    data = res_buy.json()
    assert "빚투 / 신용 올인 체결" in data["reply"]
    assert data["event"]["type"] == "trade_buy"

    # 3. Test bankruptcy application with alias '!회생신청'
    # Drop stock to lose money
    client.post("/api/admin/settle-match", json={"rank": 4, "point_delta": -300})
    res_rehab = client.post("/api/chat/command", json={
        "user_id": u_margin,
        "username": "마진유저",
        "message": "!회생신청 10X 탔다가 빚만 남았습니다"
    })
    assert res_rehab.status_code == 200
    assert "법정에 접수되었습니다" in res_rehab.json()["reply"]

    # 4. Check that pending list returns this application
    res_pending = client.get("/api/admin/bankruptcy/pending")
    assert res_pending.status_code == 200
    pending_apps = res_pending.json()["applications"]
    found = [a for a in pending_apps if a["user_id"] == u_margin]
    assert len(found) == 1
    assert "빚만 남았습니다" in found[0]["reason"]

def test_donation_api_and_db_management(client):
    # 1. Test POST /api/chzzk/donation (1:1000 ratio)
    res_don = client.post("/api/chzzk/donation", json={
        "donationType": "CHAT",
        "channelId": "ch_api_test",
        "donatorChannelId": "donor_api_1",
        "donatorNickname": "후원테스터",
        "payAmount": 10000,
        "donationText": "만 원 후원합니다!",
        "messageTime": "99998888"
    })
    assert res_don.status_code == 200
    data = res_don.json()
    assert data["success"] is True
    # 10,000 KRW * 1000 = 10,000,000 Points
    assert data["details"]["points_credited"] == 10000000
    assert "10,000,000P 충전 완료" in data["message"]

    # 2. Check user points
    res_user = client.get("/api/user/donor_api_1")
    assert res_user.status_code == 200
    assert res_user.json()["points"] >= 10000000

    # 3. Duplicate donation rejection test
    res_dup = client.post("/api/chzzk/donation", json={
        "donationType": "CHAT",
        "channelId": "ch_api_test",
        "donatorChannelId": "donor_api_1",
        "donatorNickname": "후원테스터",
        "payAmount": 10000,
        "donationText": "만 원 후원합니다!",
        "messageTime": "99998888"
    })
    assert res_dup.status_code == 200
    assert res_dup.json()["success"] is False
    assert "이미 충전 처리된 후원" in res_dup.json()["message"]

    # 4. GET /api/donations/history
    res_hist = client.get("/api/donations/history?limit=5")
    assert res_hist.status_code == 200
    assert len(res_hist.json()["donations"]) > 0

    # 5. DB Backup & Verification endpoints
    res_verify = client.get("/api/admin/db/verify")
    assert res_verify.status_code == 200
    assert res_verify.json()["is_healthy"] is True

    res_backup = client.post("/api/admin/db/backup", json={"reason": "api_test"})
    assert res_backup.status_code == 200
    assert res_backup.json()["success"] is True

    res_backups = client.get("/api/admin/db/backups")
    assert res_backups.status_code == 200
    assert len(res_backups.json()["backups"]) > 0

def test_extract_donation_from_packet():
    from main import extract_donation_from_packet

    # Case 1: cmd 93102 with stringified extras
    chat_93102 = {
        "uid": "donor_hash_93102",
        "msg": "나베 파이팅!",
        "msgTime": 1726567890000,
        "profile": '{"nickname":"열혈팬93102","userIdHash":"donor_hash_93102"}',
        "extras": '{"payAmount": 5000, "donationType": "CHAT"}'
    }
    extracted = extract_donation_from_packet(chat_93102, cmd=93102)
    assert extracted is not None
    assert extracted["payAmount"] == 5000
    assert extracted["donatorNickname"] == "열혈팬93102"
    assert extracted["donatorChannelId"] == "donor_hash_93102"
    assert extracted["donationText"] == "나베 파이팅!"

    # Case 2: cmd 93101 with msgTypeCode 10 and dict extras
    chat_10 = {
        "msgTypeCode": 10,
        "uid": "donor_hash_10",
        "msg": "치즈 후원!",
        "profile": {"nickname": "치즈러버", "userIdHash": "donor_hash_10"},
        "extras": {"payAmount": "3000", "donationType": "CHAT"}
    }
    extracted_10 = extract_donation_from_packet(chat_10, cmd=93101)
    assert extracted_10 is not None
    assert extracted_10["payAmount"] == "3000"
    assert extracted_10["donatorNickname"] == "치즈러버"

    # Case 3: Normal chat message in cmd 93101 (must return None)
    chat_normal = {
        "msgTypeCode": 1,
        "uid": "user_normal",
        "msg": "!매수 1X 5",
        "profile": '{"nickname":"일반시청자","userIdHash":"user_normal"}'
    }
    extracted_normal = extract_donation_from_packet(chat_normal, cmd=93101)
    assert extracted_normal is None

@pytest.mark.anyio
async def test_chzzk_session_worker_donation_event():
    from chzzk_session import ChzzkSessionWorker
    import json

    received_donations = []
    async def mock_donation_callback(data):
        received_donations.append(data)

    worker = ChzzkSessionWorker(
        channel_id="4495f96624a2c60bd1ed5a6139014d20",
        on_donation=mock_donation_callback
    )
    status = worker.get_status()
    assert status["channel_id"] == "4495f96624a2c60bd1ed5a6139014d20"
    assert status["is_connected"] is False

    # Simulate SYSTEM connected event
    await worker.handle_socket_event(
        '42["SYSTEM", "{\\"type\\":\\"connected\\",\\"data\\":{\\"sessionKey\\":\\"mock_session_123\\"}}"]'
    )
    assert worker.session_key == "mock_session_123"
    assert worker.is_connected is True

    # Simulate SYSTEM subscribed event
    await worker.handle_socket_event('42["SYSTEM", "{\\"type\\":\\"subscribed\\",\\"data\\":{}}"]')
    assert worker.subscribed_donation is True

    # Simulate real-time DONATION event
    mock_don_payload = {
        "donationType": "CHAT",
        "channelId": "4495f96624a2c60bd1ed5a6139014d20",
        "donatorChannelId": "worker_donor_hash",
        "donatorNickname": "세션후원자",
        "payAmount": 2000,
        "donationText": "공식 세션 소켓으로 들어온 후원!",
        "messageTime": "88887777"
    }
    await worker.handle_socket_event(
        f'42["DONATION", {json.dumps(mock_don_payload)}]'
    )
    assert len(received_donations) == 1
    assert received_donations[0]["payAmount"] == 2000
    assert received_donations[0]["donatorNickname"] == "세션후원자"

def test_admin_users_and_grant_by_nickname(client):
    # 1. Ensure user exists with a hash ID
    res_cmd = client.post("/api/chat/command", json={
        "user_id": "real_hash_elf",
        "username": "화끈한 엘프 9999",
        "message": "!내정보"
    })
    assert res_cmd.status_code == 200

    # 2. Call GET /api/admin/users
    res_users = client.get("/api/admin/users")
    assert res_users.status_code == 200
    users_data = res_users.json()
    assert users_data["success"] is True
    found = [u for u in users_data["users"] if u["username"] == "화끈한 엘프 9999"]
    assert len(found) == 1
    assert found[0]["id"] == "real_hash_elf"
    start_points = found[0]["points"]

    # 3. Grant points using NICKNAME as user_id
    res_grant = client.post("/api/admin/grant-points", json={
        "user_id": "화끈한 엘프 9999",
        "username": "화끈한 엘프 9999",
        "points": 100000,
        "mode": "add"
    })
    assert res_grant.status_code == 200
    assert res_grant.json()["success"] is True
    # Must resolve to real_hash_elf and NOT create a new duplicate user
    assert res_grant.json()["user_id"] == "real_hash_elf"
    assert res_grant.json()["points"] == start_points + 100000

    # 4. Check user count - still exactly 1 user with that nickname!
    res_users_after = client.get("/api/admin/users")
    matching = [u for u in res_users_after.json()["users"] if u["username"] == "화끈한 엘프 9999"]
    assert len(matching) == 1
    assert matching[0]["id"] == "real_hash_elf"
    assert matching[0]["points"] == start_points + 100000

    # 5. Test donation processing resolving by nickname
    res_don = client.post("/api/chzzk/donation", json={
        "donationType": "CHAT",
        "channelId": "test_ch",
        "donatorNickname": "화끈한 엘프 9999",
        "payAmount": 1000,
        "donationText": "닉네임 식별 테스트"
    })
    assert res_don.status_code == 200
    don_data = res_don.json()
    assert don_data["success"] is True
    assert don_data["details"]["user_id"] == "real_hash_elf"
    assert don_data["details"]["points_credited"] == 1000000

def test_allin_chat_commands_api(client):
    # Ensure market unlocked
    client.post("/api/admin/lock-market", json={"locked": False})

    commands = [
        "!올인 1X",
        "!올인",
        "!올인 10X",
        "!매수 올인 1X",
        "!구매 올인 1X",
        "!매수 1X 올인",
        "!구매 1X 올인",
        "!매수올인 1X",
        "!구매올인 1X",
        "!풀매수 1X",
        "!allin 1X",
        "!전액매수 1X",
    ]

    for i, cmd in enumerate(commands):
        uid = f"api_allin_uid_{i}"
        uname = f"API올인러_{i}"
        res = client.post("/api/chat/command", json={
            "user_id": uid,
            "username": uname,
            "message": cmd
        })
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        reply = data["reply"]
        assert reply is not None
        assert "매수 체결" in reply or "구매 완료" in reply
        assert data["event"] is not None
        assert data["event"]["type"] == "trade_buy"

def test_buyers_overlay_and_api(client):
    """Test new buyers overlay routes and /api/buyers endpoint."""
    # Test HTML routes
    for path in ["/overlay/buyers", "/buyers-overlay", "/buyers", "/overlay/holders"]:
        res = client.get(path)
        assert res.status_code == 200
        assert "실시간 매수자 현황" in res.text
        assert "overlay-card" in res.text

    # Make a buy trade via chat command
    client.post("/api/chat/command", json={
        "user_id": "buyer_overlay_tester_1",
        "username": "실시간주주",
        "message": "!매수 10X 5"
    })

    # Test /api/buyers
    res_api = client.get("/api/buyers")
    assert res_api.status_code == 200
    data = res_api.json()
    assert data["success"] is True
    assert "buyers" in data
    assert "summary" in data
    assert "recent_trades" in data
    assert data["summary"]["total_buyers"] >= 1
    found = any(b["username"] == "실시간주주" for b in data["buyers"])
    assert found is True

def test_transfer_api_endpoint(client):
    """Test POST /api/transfer endpoint."""
    # Seed sender and receiver via chat command
    client.post("/api/chat/command", json={
        "user_id": "api_sender",
        "username": "API송금인",
        "message": "!내정보"
    })
    client.post("/api/chat/command", json={
        "user_id": "api_receiver",
        "username": "API수신인",
        "message": "!내정보"
    })

    # Test transfer via POST /api/transfer
    res = client.post("/api/transfer", json={
        "sender_id": "api_sender",
        "sender_username": "API송금인",
        "target_name": "API수신인",
        "amount": "20000"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["details"]["amount"] == 20000
    assert data["details"]["tax"] == 20 # 0.1% tax
    assert data["details"]["recipient_net"] == 19980

    # Test transfer failure with self
    res_err = client.post("/api/transfer", json={
        "sender_id": "api_sender",
        "sender_username": "API송금인",
        "target_name": "API송금인",
        "amount": "1000"
    })
    assert res_err.status_code == 400
    assert "본인 계좌" in res_err.json()["detail"]

def test_tracker_push_and_status(client):
    # 1. Check status endpoint
    res_status = client.get("/api/tracker/status")
    assert res_status.status_code == 200
    st_data = res_status.json()
    assert "connected" in st_data
    assert "tracker_data" in st_data

    # 2. Initial push establishes baseline
    res_init = client.post("/api/tracker/push", json={
        "nickname": "ちぃず鍋",
        "score": "2,137pt (2,137pt)",
        "record": "12123",
        "rank": "작걸3"
    })
    assert res_init.status_code == 200
    init_json = res_init.json()
    assert init_json["success"] is True

    # 3. Match finished: score increases from 2137 to 2350 (+213), new 1st place record '1' prepended
    res_match = client.post("/api/tracker/push", json={
        "nickname": "ちぃず鍋",
        "score": "2,350pt (2,137pt)",
        "record": "112123",
        "rank": "작걸3"
    })
    assert res_match.status_code == 200
    match_json = res_match.json()
    assert match_json["success"] is True
    assert match_json["settled"] is True
    assert match_json["rank"] == 1
    assert match_json["delta"] == 213
    assert match_json["current_price"] == 2350
    assert match_json["day_open_price"] == 2137

    # 4. Status reflects updated tracker and market state
    res_status2 = client.get("/api/tracker/status")
    assert res_status2.status_code == 200
    st2 = res_status2.json()
    assert st2["connected"] is True
    assert st2["last_synced_pts"] == 2350
    assert st2["last_synced_record"] == "112123"

    # 5. Chat command !트래커 reports current points and day open
    res_chat = client.post("/api/chat/command", json={
        "user_id": "test_user_tr",
        "username": "시청자",
        "message": "!트래커"
    })
    assert res_chat.status_code == 200
    reply = res_chat.json()["reply"]
    assert "2,350pt" in reply
    assert "2,137pt" in reply

def test_admin_delist_api(client):
    """Test POST /api/admin/delist triggers delisting and resets stock to 작성2 at 3,500P."""
    # First place a buy
    client.post("/api/chat/command", json={
        "user_id": "api_delist_user",
        "username": "상폐테스터",
        "message": "!매수 1X 1"
    })

    # Trigger admin delist
    res = client.post("/api/admin/delist", json={
        "old_rank": "작성3",
        "new_rank": "작성2",
        "starting_points": 3000
    })
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["delisting_info"]["new_rank"] == "작성2"
    assert data["delisting_info"]["new_price"] == 3000
    assert data["market_state"]["current_rank_name"] == "작성2"
    assert data["market_state"]["current_price"] == 3000

    # User should now have 0 shares
    res_info = client.post("/api/chat/command", json={
        "user_id": "api_delist_user",
        "username": "상폐테스터",
        "message": "!내정보"
    })
    assert "보유 포지션이 없습니다" in res_info.json()["reply"]

def test_tracker_push_demotion_to_master2_triggers_delisting(client):
    """Test that tracker pushing '작성2' while system was '작성3' triggers delisting and resets to 3,000P."""
    # First reset market to 작성3
    client.post("/api/admin/reset-market")

    # User buys shares
    client.post("/api/chat/command", json={
        "user_id": "victim_tracker_user",
        "username": "트래커피해자",
        "message": "!매수 1X 5"
    })

    # Tracker pushes update indicating demotion to 작성2 (기준점 3000/6000)
    res_push = client.post("/api/tracker/push", json={
        "nickname": "ちぃず鍋",
        "rank": "작성2",
        "score": "3000/6000 (3000)",
        "score_diff": "0",
        "record": "123"
    })
    assert res_push.status_code == 200
    push_data = res_push.json()
    assert push_data["success"] is True
    assert push_data["delisted"] is True
    assert push_data["current_price"] == 3000

    # User's shares wiped out (휴짓조각)
    res_info = client.post("/api/chat/command", json={
        "user_id": "victim_tracker_user",
        "username": "트래커피해자",
        "message": "!내정보"
    })
    assert "보유 포지션이 없습니다" in res_info.json()["reply"]


def test_lottery_api_endpoints(client):
    # 1. Check initial lottery status
    res_st = client.get("/api/lottery/status")
    assert res_st.status_code == 200
    st_data = res_st.json()
    assert st_data["success"] is True
    assert "lottery" in st_data
    assert "treasury" in st_data

    # 2. Open lottery via POST /api/admin/lottery/open
    res_open = client.post("/api/admin/lottery/open", json={
        "duration_minutes": 20,
        "title": "특별 복지 복권"
    })
    assert res_open.status_code == 200
    open_data = res_open.json()
    assert open_data["success"] is True
    assert open_data["data"]["is_active"] is True
    assert open_data["data"]["duration_minutes"] == 20
    assert open_data["data"]["title"] == "특별 복지 복권"
    assert open_data["market_state"]["lottery_is_open"] is True

    # 3. Verify status endpoint shows active
    res_st2 = client.get("/api/lottery/status")
    assert res_st2.status_code == 200
    assert res_st2.json()["lottery"]["is_active"] is True

    # 4. User scratches lottery via chat command API
    res_scratch = client.post("/api/chat/command", json={
        "user_id": "api_lotto_user",
        "username": "API복권러",
        "message": "!복권 3"
    })
    assert res_scratch.status_code == 200
    scratch_data = res_scratch.json()
    assert "3장 일괄 긁기" in scratch_data["reply"]
    assert scratch_data["event"] is not None

    # 5. Close lottery via POST /api/admin/lottery/close
    res_close = client.post("/api/admin/lottery/close")
    assert res_close.status_code == 200
    close_data = res_close.json()
    assert close_data["success"] is True
    assert close_data["data"]["is_active"] is False
    assert close_data["market_state"]["lottery_is_open"] is False

    # 6. Verify status shows closed
    res_st3 = client.get("/api/lottery/status")
    assert res_st3.status_code == 200
    assert res_st3.json()["lottery"]["is_active"] is False


def test_merchant_api_endpoints_and_admin_users(client):
    # 1. Check initial merchant status
    res_st = client.get("/api/merchant/status")
    assert res_st.status_code == 200
    st_data = res_st.json()
    assert st_data["success"] is True
    assert "merchant" in st_data
    assert "treasury" in st_data

    # 2. Open merchant via POST /api/admin/merchant/open
    res_open = client.post("/api/admin/merchant/open", json={
        "duration_minutes": 25,
        "merchant_name": "방랑신비상인"
    })
    assert res_open.status_code == 200
    open_data = res_open.json()
    assert open_data["success"] is True
    assert open_data["data"]["is_active"] is True
    assert open_data["market_state"]["merchant_is_open"] is True
    assert "shield" in open_data["market_state"]["merchant_items"]

    # 3. Verify status endpoint shows active
    res_st2 = client.get("/api/merchant/status")
    assert res_st2.status_code == 200
    assert res_st2.json()["merchant"]["is_active"] is True

    # 4. User buys items via chat command API
    # First grant points
    client.post("/api/admin/grant-points", json={
        "user_id": "api_merchant_viewer",
        "username": "치즈러버",
        "points": 2000000
    })

    res_buy = client.post("/api/chat/command", json={
        "user_id": "api_merchant_viewer",
        "username": "치즈러버",
        "message": "!상인구매 1 1"
    })
    assert res_buy.status_code == 200
    buy_data = res_buy.json()
    assert "구매 완료" in buy_data["reply"]
    assert buy_data["event"]["type"] == "merchant_bought"

    # 5. Close merchant via POST /api/admin/merchant/close
    res_close = client.post("/api/admin/merchant/close")
    assert res_close.status_code == 200
    close_data = res_close.json()
    assert close_data["success"] is True
    assert close_data["data"]["is_active"] is False
    assert close_data["market_state"]["merchant_is_open"] is False

    # 6. Buy a stock to have positions
    client.post("/api/chat/command", json={
        "user_id": "api_merchant_viewer",
        "username": "치즈러버",
        "message": "!매수 1X 10"
    })

    # 7. Test enriched GET /api/admin/users
    res_users = client.get("/api/admin/users")
    assert res_users.status_code == 200
    users_data = res_users.json()
    assert users_data["success"] is True
    assert "users" in users_data

    found = [u for u in users_data["users"] if u["id"] == "api_merchant_viewer"]
    assert len(found) == 1
    target_user = found[0]

    # Verify complete asset & item breakdown
    assert "net_worth" in target_user
    assert "cash" in target_user
    assert "stock_value" in target_user
    assert "positions" in target_user
    assert len(target_user["positions"]) >= 1
    assert "equipments" in target_user
    assert "equipped_item" in target_user
    assert "items" in target_user
    assert target_user["items"]["shield_scroll_count"] >= 1
    assert "auto_mining_active" in target_user["items"]

    # 8. Check Admin page HTML loads and contains Merchant & Inspector sections
    res_admin = client.get("/admin")
    assert res_admin.status_code == 200
    assert "방랑 신비상인" in res_admin.text
    assert "시청자 통합 자산 / 장비 / 아이템 실시간 모니터링" in res_admin.text
    assert "user-detail-modal" in res_admin.text


def test_second_place_settle_with_negative_delta_api(client):
    """Ensure 2nd place dividend is paid properly even when match point delta is negative."""
    # Buy 1X stock
    client.post("/api/chat/command", json={
        "user_id": "div_neg_user",
        "username": "마이너스2등",
        "message": "!매수 1X 10"
    })

    # Settle match for 2nd place with negative delta (-10pt)
    res_settle = client.post("/api/admin/settle-match", json={
        "rank": 2,
        "point_delta": -10
    })
    assert res_settle.status_code == 200
    data = res_settle.json()
    assert data["rank"] == 2
    assert "dividends" in data
    assert len(data["dividends"]) >= 1
    d = next(item for item in data["dividends"] if item["user_id"] == "div_neg_user")
    assert d["rate_pct"] in [1.0, 3.0]
    assert d["payout"] > 0
    assert d["amount"] == d["payout"]


def test_public_users_and_single_user_endpoints(client):
    """Test public GET /api/users and GET /api/user/{user_id_or_username}."""
    # 1. Create a user with points and a pickaxe
    client.post("/api/chat/command", json={
        "user_id": "pub_viewer_777",
        "username": "럭키세븐",
        "message": "!내정보"
    })
    client.post("/api/chat/command", json={
        "user_id": "pub_viewer_777",
        "username": "럭키세븐",
        "message": "!매수 1X 5"
    })

    # 2. Query public list /api/users
    res_users = client.get("/api/users")
    assert res_users.status_code == 200
    data = res_users.json()
    assert data["success"] is True
    assert "users" in data
    assert len(data["users"]) >= 1

    matched = [u for u in data["users"] if u["username"] == "럭키세븐"]
    assert len(matched) == 1
    u_info = matched[0]
    assert "net_worth" in u_info
    assert "cash" in u_info
    assert "stock_value" in u_info
    assert "positions" in u_info
    assert "equipments" in u_info
    assert "items" in u_info

    # 3. Query single user /api/user/{username}
    res_single = client.get("/api/user/럭키세븐")
    assert res_single.status_code == 200
    single_data = res_single.json()
    assert single_data["success"] is True
    assert single_data["user"]["username"] == "럭키세븐"
    assert len(single_data["user"]["positions"]) >= 1

    # 4. Query non-existent user
    res_404 = client.get("/api/user/존재하지않는유저12345")
    assert res_404.status_code == 404


def test_tunnel_endpoints(client):
    """Test GET and POST /api/tunnel."""
    # Initially or default
    res_get = client.get("/api/tunnel")
    assert res_get.status_code == 200

    # Set tunnel URL
    res_post = client.post("/api/admin/tunnel", json={"url": "https://test-mahjong.trycloudflare.com/"})
    assert res_post.status_code == 200
    assert res_post.json()["tunnel_url"] == "https://test-mahjong.trycloudflare.com"

    # Verify updated
    res_get2 = client.get("/api/tunnel")
    assert res_get2.json()["tunnel_url"] == "https://test-mahjong.trycloudflare.com"


def test_guide_page_includes_inspector(client):
    """Test GET /guide includes the viewer inspector tab and modal."""
    res_guide = client.get("/guide")
    assert res_guide.status_code == 200
    assert "tab-inspector" in res_guide.text
    assert "public-user-modal" in res_guide.text
    assert "시청자 랭킹" in res_guide.text and "스펙" in res_guide.text
    assert "user-search-input" in res_guide.text


def test_root_url_serves_guide_page(client):
    """Test GET / serves the viewer guide page directly (matching cloudflare tunnel root)."""
    res_root = client.get("/")
    assert res_root.status_code == 200
    assert "tab-inspector" in res_root.text
    assert "public-user-modal" in res_root.text
    assert "시청자 랭킹" in res_root.text


def test_static_json_snapshots(client):
    """Test /market_state.json and /users_state.json are served statically."""
    res_market = client.get("/market_state.json")
    assert res_market.status_code == 200
    assert "current_price" in res_market.json()

    res_users = client.get("/users_state.json")
    assert res_users.status_code == 200
    assert "users" in res_users.json()


def test_admin_lockdown_blocks_external_access(client):
    """Test that external requests via Cloudflare tunnel or external proxies are 403 Forbidden on admin routes."""
    # 1. External request with cf-connecting-ip hitting /admin
    cf_headers = {
        "cf-connecting-ip": "203.0.113.195",
        "cf-ray": "8c591234abcd-ICN",
        "host": "lan-six-prison-jerusalem.trycloudflare.com"
    }
    res_admin = client.get("/admin", headers=cf_headers)
    assert res_admin.status_code == 403
    assert "SECURITY SHIELD" in res_admin.text
    assert "관리자 페이지 접근 차단" in res_admin.text

    # 2. External request hitting /api/admin/*
    res_api = client.post("/api/admin/grant-points", headers=cf_headers, json={"user_id": "u", "points": 100})
    assert res_api.status_code == 403
    assert res_api.json()["success"] is False
    assert "원천 차단" in res_api.json()["detail"]

    # 3. External request hitting admin-only sensitive endpoints
    res_casino = client.post("/api/casino/open", headers=cf_headers, json={})
    assert res_casino.status_code == 403

    res_chat = client.post("/api/chat/command", headers=cf_headers, json={"user_id": "hack", "username": "hack", "message": "!매수"})
    assert res_chat.status_code == 403

    # 4. BUT external request to public viewer routes MUST SUCCEED (200 OK)
    res_pub_root = client.get("/", headers=cf_headers)
    assert res_pub_root.status_code == 200
    assert "tab-inspector" in res_pub_root.text

    res_pub_guide = client.get("/guide", headers=cf_headers)
    assert res_pub_guide.status_code == 200

    res_pub_market = client.get("/api/market/state", headers=cf_headers)
    assert res_pub_market.status_code == 200

    res_pub_users = client.get("/api/users", headers=cf_headers)
    assert res_pub_users.status_code == 200


def test_local_admin_access_allowed(client):
    """Test that local access (streamer PC) can still access /admin and admin APIs."""
    res_admin = client.get("/admin")
    assert res_admin.status_code == 200
    assert "관리자 제어판" in res_admin.text or "admin" in res_admin.text.lower()

    res_admin_users = client.get("/api/admin/users")
    assert res_admin_users.status_code == 200
    assert res_admin_users.json()["success"] is True


def test_credit_rating_in_user_inspector_api(client):
    """Test that /api/users and /api/user/{id} include credit rating payload."""
    client.post("/api/chat/command", json={
        "user_id": "api_credit_viewer_1",
        "username": "신용테스터",
        "message": "!내정보"
    })

    # Test single user endpoint
    res_single = client.get("/api/user/신용테스터")
    assert res_single.status_code == 200
    data = res_single.json()
    assert "credit" in data["user"]
    credit = data["user"]["credit"]
    assert "tier" in credit
    assert "grade" in credit
    assert "loan_limit" in credit
    assert "score" in credit
    assert credit["loan_limit"] > 0

    # Test users list endpoint
    res_list = client.get("/api/users")
    assert res_list.status_code == 200
    users = res_list.json()["users"]
    matched = [u for u in users if u["username"] == "신용테스터"]
    assert len(matched) == 1
    assert "credit" in matched[0]
    assert matched[0]["credit"]["grade"] == "BB"


def test_web_desk_endpoints(client):
    """Full end-to-end test for Web Viewer Lounge APIs (Auth, Transfer, Exchange, Arena, Stock)."""
    import re

    # 1. Create two users via chat command
    client.post("/api/chat/command", json={
        "user_id": "web_user_alice",
        "username": "웹앨리스",
        "message": "!내정보"
    })
    client.post("/api/chat/command", json={
        "user_id": "web_user_bob",
        "username": "웹밥",
        "message": "!내정보"
    })

    # 2. Test !웹로그인 command (One-time code)
    res_code = client.post("/api/chat/command", json={
        "user_id": "web_user_alice",
        "username": "웹앨리스",
        "message": "!웹로그인"
    })
    assert res_code.status_code == 200
    reply = res_code.json()["reply"]
    match = re.search(r"\[([0-9]{4})\]", reply)
    assert match is not None
    alice_code = match.group(1)

    # 3. Test POST /api/web/login with one-time code
    res_login = client.post("/api/web/login", json={
        "username": "웹앨리스",
        "code": alice_code
    })
    assert res_login.status_code == 200
    alice_token = res_login.json()["token"]
    assert alice_token.startswith("tk_")

    # 4. Test GET /api/web/me
    res_me = client.get("/api/web/me", headers={"x-web-token": alice_token})
    assert res_me.status_code == 200
    assert res_me.json()["user"]["username"] == "웹앨리스"
    assert res_me.json()["user"]["max_leverage_multiplier"] == 10
    assert res_me.json()["user"]["beast_heart_count"] == 0

    # 5. Test !비번 command (Permanent PIN)
    res_pin = client.post("/api/chat/command", json={
        "user_id": "web_user_bob",
        "username": "웹밥",
        "message": "!비번 7788"
    })
    assert res_pin.status_code == 200
    assert "7788" in res_pin.json()["reply"]

    # 6. Test POST /api/web/login with permanent PIN
    res_bob_login = client.post("/api/web/login", json={
        "username": "웹밥",
        "code": "7788"
    })
    assert res_bob_login.status_code == 200
    bob_token = res_bob_login.json()["token"]

    # 7. Test POST /api/web/transfer
    res_transfer = client.post("/api/web/transfer", json={
        "token": alice_token,
        "target_name": "웹밥",
        "amount": "5000"
    })
    assert res_transfer.status_code == 200
    assert res_transfer.json()["success"] is True

    # 8. Test POST /api/web/trade/stock (Buy & Sell)
    res_buy_stock = client.post("/api/web/trade/stock", json={
        "token": alice_token,
        "action": "BUY",
        "product_type": "1X",
        "quantity": 1
    })
    assert res_buy_stock.status_code == 200
    assert res_buy_stock.json()["success"] is True

    # Give Alice some scrolls to sell
    client.post("/api/chat/command", json={
        "user_id": "web_user_alice",
        "username": "웹앨리스",
        "message": "!상인구매 1 2"  # May fail if merchant closed, so grant directly via admin grant or test exchange
    })

    # Test Exchange: Bob gives Bob some points and tests listing item
    db = TestingSessionLocal()
    alice = db.query(User).filter_by(id="web_user_alice").first()
    alice.shield_scroll_count = 5
    bob = db.query(User).filter_by(id="web_user_bob").first()
    bob.points = 100000
    db.commit()
    db.close()

    # 9. Test POST /api/web/exchange/sell-item
    res_sell_item = client.post("/api/web/exchange/sell-item", json={
        "token": alice_token,
        "item_type": "shield",
        "quantity": 2,
        "price": 20000
    })
    assert res_sell_item.status_code == 200
    assert res_sell_item.json()["success"] is True
    listing_id = res_sell_item.json()["details"]["listing_id"]

    # 10. Test GET /api/web/exchange/listings
    res_listings = client.get("/api/web/exchange/listings", headers={"x-web-token": bob_token})
    assert res_listings.status_code == 200
    assert len(res_listings.json()["items"]) >= 1

    # 11. Test POST /api/web/exchange/buy
    res_buy_item = client.post("/api/web/exchange/buy", json={
        "token": bob_token,
        "listing_token": f"I{listing_id}"
    })
    assert res_buy_item.status_code == 200
    assert res_buy_item.json()["success"] is True

    # 12. Test POST /api/web/arena/open & GET /api/web/arena/status & POST /api/web/arena/join
    res_open_arena = client.post("/api/web/arena/open", json={
        "token": alice_token,
        "bet": "10000"
    })
    assert res_open_arena.status_code == 200

    res_arena_status = client.get("/api/web/arena/status")
    assert res_arena_status.status_code == 200
    assert len(res_arena_status.json()["open_matches"]) >= 1

    res_join_arena = client.post("/api/web/arena/join", json={
        "token": bob_token,
        "host_id": "web_user_alice"
    })
    assert res_join_arena.status_code == 200
    assert res_join_arena.json()["success"] is True
    assert "승자" in res_join_arena.json()["reply"]

    # 13. Test POST /api/web/logout
    res_logout = client.post("/api/web/logout", json={"token": alice_token})
    assert res_logout.status_code == 200
    # Next call to /api/web/me should be 401
    res_unauth = client.get("/api/web/me", headers={"x-web-token": alice_token})
    assert res_unauth.status_code == 401


def test_web_mining_starforce_cube_endpoints(client):
    """Test web lounge endpoints for mining, starforce enhancement, and cube rerolls."""
    # 1. Login user
    client.post("/api/chat/command", json={
        "user_id": "web_craftsman",
        "username": "장인유저",
        "message": "!내정보"
    })
    client.post("/api/chat/command", json={
        "user_id": "web_craftsman",
        "username": "장인유저",
        "message": "!비번 7777"
    })
    res_login = client.post("/api/web/login", json={"username": "장인유저", "code": "7777"})
    assert res_login.status_code == 200
    token = res_login.json()["token"]
    user_data = res_login.json()["user"]
    assert "mining" in user_data
    eq_id = user_data["equipments"][0]["id"]

    # 2. Test mining: POST /api/web/mining/mine
    res_mine = client.post("/api/web/mining/mine", json={"token": token})
    assert res_mine.status_code == 200
    mine_data = res_mine.json()
    assert mine_data["success"] is True
    assert "shares_awarded" in mine_data["details"]

    # 3. Test Starforce upgrade: POST /api/web/enhancement/upgrade
    res_sf = client.post("/api/web/enhancement/upgrade", json={
        "token": token,
        "equipment_id": eq_id
    })
    assert res_sf.status_code == 200
    sf_data = res_sf.json()
    assert sf_data["success"] is True
    assert sf_data["details"]["outcome"] in ["success", "maintain", "drop", "downgrade_prevented", "destroyed"]

    # 4. Test Buy Cubes: POST /api/web/cube/buy
    res_cbuy = client.post("/api/web/cube/buy", json={"token": token, "count": 2})
    assert res_cbuy.status_code == 200
    assert res_cbuy.json()["success"] is True
    assert res_cbuy.json()["user"]["items"]["cube_count"] >= 2

    # 5. Test Cube Use: POST /api/web/cube/use
    res_cuse = client.post("/api/web/cube/use", json={
        "token": token,
        "equipment_id": eq_id
    })
    assert res_cuse.status_code == 200
    cuse_data = res_cuse.json()
    assert cuse_data["success"] is True
    assert len(cuse_data["details"]["lines"]) == 3

    # 6. Test Line Lock: POST /api/web/cube/line-lock
    res_llock = client.post("/api/web/cube/line-lock", json={
        "token": token,
        "equipment_id": eq_id,
        "line_arg": "1",
        "state": "on"
    })
    assert res_llock.status_code == 200
    assert res_llock.json()["success"] is True

    # 6-1. Test Single Line Lock Enforcement (Locking line 2 auto-unsets line 1)
    res_llock2 = client.post("/api/web/cube/line-lock", json={
        "token": token,
        "equipment_id": eq_id,
        "line_arg": "2",
        "state": "on"
    })
    assert res_llock2.status_code == 200
    llock2_data = res_llock2.json()
    assert llock2_data["success"] is True
    eq_item = next(e for e in llock2_data["user"]["equipments"] if e["id"] == eq_id)
    assert eq_item["is_line1_locked"] is False
    assert eq_item["is_line2_locked"] is True
    assert eq_item["is_line3_locked"] is False

    # 7. Test Cube Lock Toggle: POST /api/web/cube/lock-toggle
    res_clock = client.post("/api/web/cube/lock-toggle", json={
        "token": token,
        "equipment_id": eq_id
    })
    assert res_clock.status_code == 200
    assert res_clock.json()["success"] is True

    # Unlock for subsequent actions
    res_cunlock = client.post("/api/web/cube/lock-toggle", json={
        "token": token,
        "equipment_id": eq_id
    })
    assert res_cunlock.status_code == 200

    # 8. Test Equip: POST /api/web/equipment/equip
    res_equip = client.post("/api/web/equipment/equip", json={
        "token": token,
        "equipment_id": eq_id
    })
    assert res_equip.status_code == 200
    assert res_equip.json()["success"] is True


def test_web_cube_snipe_options_and_commands(client):
    """Tests GET /api/web/cube/snipe-options and chat guide commands."""
    from command_handler import handle_chat_command

    # 1. Test Endpoint
    res = client.get("/api/web/cube/snipe-options")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "options" in data
    assert len(data["options"]) >= 23
    assert any(opt["keyword"] == "고블린" for opt in data["options"])
    assert any(opt["keyword"] == "과충전" for opt in data["options"])
    assert any(opt["keyword"] == "쿨초" for opt in data["options"])
    assert any(opt["keyword"] == "크리" for opt in data["options"])
    assert any(opt["keyword"] == "성공률" for opt in data["options"])
    assert any(opt["keyword"] == "배당" for opt in data["options"])
    assert any(opt["keyword"] == "야수" for opt in data["options"])
    assert "guide_text" in data
    assert "잠재저격주문서" in data["guide_text"]

    # 2. Test Chat Commands
    with TestingSessionLocal() as db:
        # Direct guide commands
        rep1, _ = handle_chat_command(db, "test_snipe_user", "유저1", "!저격목록")
        assert "잠재저격주문서 옵션 키워드 전체 목록" in rep1
        assert "고블린" in rep1
        assert "과충전" in rep1

        rep2, _ = handle_chat_command(db, "test_snipe_user", "유저1", "!저격옵션")
        assert "잠재저격주문서 옵션 키워드 전체 목록" in rep2

        rep3, _ = handle_chat_command(db, "test_snipe_user", "유저1", "!잠재목록")
        assert "잠재저격주문서 옵션 키워드 전체 목록" in rep3

        # Scroll command with guide keyword
        rep4, _ = handle_chat_command(db, "test_snipe_user", "유저1", "!주문서 저격목록")
        assert "잠재저격주문서 옵션 키워드 전체 목록" in rep4

        rep5, _ = handle_chat_command(db, "test_snipe_user", "유저1", "!주문서 저격 옵션")
        assert "잠재저격주문서 옵션 키워드 전체 목록" in rep5

        # Cube command with guide keyword
        rep6, _ = handle_chat_command(db, "test_snipe_user", "유저1", "!큐브 저격목록")
        assert "잠재저격주문서 옵션 키워드 전체 목록" in rep6

        rep7, _ = handle_chat_command(db, "test_snipe_user", "유저1", "!큐브 옵션")
        assert "잠재저격주문서 옵션 키워드 전체 목록" in rep7


def test_secure_reverse_auth_and_anti_bruteforce(client):
    """Tests reverse chat challenge auth (anti-hijacking) and anti-bruteforce lockout."""
    from command_handler import handle_chat_command

    # 1. Create Web Auth Challenge
    res_ch = client.post("/api/web/auth/challenge")
    assert res_ch.status_code == 200
    ch_data = res_ch.json()
    assert ch_data["success"] is True
    ch_id = ch_data["challenge_id"]
    code = ch_data["code"]
    assert ch_data["command"] == f"!인증 {code}"

    # 2. Poll before user types in chat -> PENDING
    res_p1 = client.get(f"/api/web/auth/poll?challenge_id={ch_id}")
    assert res_p1.status_code == 200
    assert res_p1.json()["status"] == "PENDING"

    # 3. User types !인증 [code] in chat
    with TestingSessionLocal() as db:
        rep_chat, _ = handle_chat_command(db, "chzzk_sec_user_99", "보안유저", f"!인증 {code}")
        assert "웹 라운지 인증이 완료되었습니다" in rep_chat

        # Check !웹로그인 in chat (contains security notice)
        rep_login_guide, _ = handle_chat_command(db, "chzzk_sec_user_99", "보안유저", "!웹로그인")
        assert "치즈나베 웹 로그인" in rep_login_guide
        assert "보안 추천" in rep_login_guide

    # 4. Poll after authorization -> AUTHORIZED with session token
    res_p2 = client.get(f"/api/web/auth/poll?challenge_id={ch_id}")
    assert res_p2.status_code == 200
    p2_data = res_p2.json()
    assert p2_data["status"] == "AUTHORIZED"
    assert "token" in p2_data
    assert p2_data["token"].startswith("tk_")
    assert p2_data["user"]["username"] == "보안유저"
    user_token = p2_data["token"]

    # 5. Challenge consumed -> subsequent poll is INVALID (replay attack prevented)
    res_p3 = client.get(f"/api/web/auth/poll?challenge_id={ch_id}")
    assert res_p3.status_code == 200
    assert res_p3.json()["status"] == "INVALID"

    # 6. Test setting PIN privately on Web without chat leaking
    res_set_pin = client.post("/api/web/user/set-pin", json={
        "token": user_token,
        "pin": "9876"
    })
    assert res_set_pin.status_code == 200
    assert res_set_pin.json()["success"] is True

    # 7. Test PIN Login on Web
    res_pin_login = client.post("/api/web/login", json={
        "username": "보안유저",
        "code": "9876"
    })
    assert res_pin_login.status_code == 200
    assert res_pin_login.json()["success"] is True

    # 8. Test Anti-Bruteforce Lockout (5 failed attempts locks out for 15 minutes)
    for i in range(4):
        res_fail = client.post("/api/web/login", json={
            "username": "보안유저",
            "code": f"000{i}"
        })
        assert res_fail.status_code == 400
        assert "올바르지 않습니다" in res_fail.json()["detail"]

    # 5th failure triggers lockout
    res_fail_5 = client.post("/api/web/login", json={
        "username": "보안유저",
        "code": "0009"
    })
    assert res_fail_5.status_code == 400
    assert "잠겼습니다" in res_fail_5.json()["detail"] or "차단" in res_fail_5.json()["detail"]

    # 6th attempt is immediately rejected by lockout
    res_fail_6 = client.post("/api/web/login", json={
        "username": "보안유저",
        "code": "9876"  # even correct pin is locked out
    })
    assert res_fail_6.status_code == 400
    assert "차단" in res_fail_6.json()["detail"] or "잠겼습니다" in res_fail_6.json()["detail"]


def test_web_merchant_and_casino_features(client):
    """Test wandering merchant price masking and casino race/mahjong API endpoints."""
    with TestingSessionLocal() as db:
        # 1. Mystery merchant wandering: price should be masked with "???"
        te.close_merchant(db)
    
    res_m_closed = client.get("/api/web/merchant/status")
    assert res_m_closed.status_code == 200
    m_data = res_m_closed.json()["merchant"]
    assert m_data["is_active"] is False
    assert len(m_data["items"]) > 0
    for item in m_data["items"].values():
        assert item["price"] == "???"
        assert item["stock"] == "???"

    # Re-open merchant and verify prices are revealed as numeric
    with TestingSessionLocal() as db:
        te.open_merchant(db, duration_minutes=10)
    
    res_m_open = client.get("/api/web/merchant/status")
    assert res_m_open.status_code == 200
    m_open_data = res_m_open.json()["merchant"]
    assert m_open_data["is_active"] is True
    for item in m_open_data["items"].values():
        assert isinstance(item["price"], (int, float))
        assert item["price"] > 0
        assert isinstance(item["stock"], int)
        assert item["stock"] > 0

    # 2. Test user for casino
    with TestingSessionLocal() as db:
        u = db.query(User).filter_by(id="casino_gamer_1").first()
        if not u:
            u = User(id="casino_gamer_1", username="겜블러", points=5000000.0)
            db.add(u)
        else:
            u.points = 5000000.0
        db.commit()
        te.open_casino(db, duration_minutes=15)

    # Set PIN and login on Web to get token
    client.post("/api/chat/command", json={
        "user_id": "casino_gamer_1",
        "username": "겜블러",
        "message": "!비번 1234"
    })
    res_login = client.post("/api/web/login", json={"username": "겜블러", "code": "1234"})
    assert res_login.status_code == 200
    token = res_login.json()["token"]

    # 3. Test POST /api/web/casino/race
    res_race = client.post("/api/web/casino/race", json={
        "token": token,
        "runner": "1",
        "bet": 10000
    })
    assert res_race.status_code == 200
    race_json = res_race.json()
    assert race_json["success"] is True
    assert "details" in race_json
    assert "ranking" in race_json["details"]
    assert "p1" in race_json["details"]
    assert "ranking_names" in race_json["details"]

    # 4. Test POST /api/web/casino/mahjong (Suit bet: "만")
    res_mj_suit = client.post("/api/web/casino/mahjong", json={
        "token": token,
        "choice": "만",
        "bet": 10000
    })
    assert res_mj_suit.status_code == 200
    mj_suit_json = res_mj_suit.json()
    assert mj_suit_json["success"] is True
    assert "details" in mj_suit_json
    assert "drawn_suit" in mj_suit_json["details"]
    assert "drawn_tile" in mj_suit_json["details"]

    # 5. Test POST /api/web/casino/mahjong (Exact tile bet: "1만")
    res_mj_exact = client.post("/api/web/casino/mahjong", json={
        "token": token,
        "choice": "1만",
        "bet": 10000
    })
    assert res_mj_exact.status_code == 200
    mj_exact_json = res_mj_exact.json()
    assert mj_exact_json["success"] is True
    assert "details" in mj_exact_json


def test_web_lottery_endpoints_and_admin_security(client):
    """Test web lottery purchase with tickets list in details and verify admin IP access."""
    # 1. Open Lottery
    with TestingSessionLocal() as db:
        te.open_lottery_event(db, duration_minutes=15)

    res_l_status = client.get("/api/web/lottery/status")
    assert res_l_status.status_code == 200
    assert res_l_status.json()["success"] is True
    assert res_l_status.json()["lottery"]["is_active"] is True

    # 2. Get user token for purchase
    with TestingSessionLocal() as db:
        u = db.query(User).filter_by(id="lottery_user_1").first()
        if not u:
            u = User(id="lottery_user_1", username="복권유저", points=1000000.0)
            db.add(u)
        else:
            u.points = 1000000.0
        db.commit()

    client.post("/api/chat/command", json={
        "user_id": "lottery_user_1",
        "username": "복권유저",
        "message": "!비번 5555"
    })
    res_login = client.post("/api/web/login", json={"username": "복권유저", "code": "5555"})
    assert res_login.status_code == 200
    token = res_login.json()["token"]

    # 3. Buy 3 basic tickets via Web
    res_buy = client.post("/api/web/lottery/buy", json={
        "token": token,
        "lottery_type": "basic",
        "count": 3
    })
    assert res_buy.status_code == 200
    buy_json = res_buy.json()
    assert buy_json["success"] is True
    assert "details" in buy_json
    details = buy_json["details"]
    assert "tickets" in details
    assert len(details["tickets"]) == 3
    for t in details["tickets"]:
        assert "tier" in t
        assert "name" in t
        assert "prize" in t
        assert "badge" in t

    # 4. Test admin route is allowed for local/testclient
    res_admin = client.get("/admin")
    assert res_admin.status_code == 200

    # 5. Test external access blocked when Cloudflare Tunnel header is present
    res_cf_blocked = client.get("/admin", headers={"cf-connecting-ip": "1.2.3.4"})
    assert res_cf_blocked.status_code == 403


def test_web_activities_and_scroll_enhancement_api(client):
    import main
    # 1. Test /api/web/activities endpoint
    res_act = client.get("/api/web/activities")
    assert res_act.status_code == 200
    act_data = res_act.json()
    assert act_data["success"] is True
    assert "activities" in act_data
    assert isinstance(act_data["activities"], list)

    # 2. Test manual recording and retrieval
    main.recent_activities.clear()
    main.record_activity("casino", "잭팟맨", "🎰 슬롯 잭팟", "777 잭팟 +5,000,000P 획득!", badge="🎰", outcome="jackpot")
    res_act2 = client.get("/api/web/activities")
    assert res_act2.status_code == 200
    acts2 = res_act2.json()["activities"]
    assert len(acts2) == 1
    assert acts2[0]["username"] == "잭팟맨"
    assert acts2[0]["outcome"] == "jackpot"
    assert acts2[0]["badge"] == "🎰"

    # 3. Test market state includes recent_activities and 100% absolute scrolls in merchant_items
    res_m = client.get("/api/market/state")
    assert res_m.status_code == 200
    m_data = res_m.json()
    assert "recent_activities" in m_data
    assert "merchant_items" in m_data
    assert "shield_100" in m_data["merchant_items"]
    assert "downgrade_100" in m_data["merchant_items"]








