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
    # 1. Test POST /api/chzzk/donation (1:100 ratio)
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
    # 10,000 KRW * 100 = 1,000,000 Points
    assert data["details"]["points_credited"] == 1000000
    assert "1,000,000P 충전 완료" in data["message"]

    # 2. Check user points
    res_user = client.get("/api/user/donor_api_1")
    assert res_user.status_code == 200
    assert res_user.json()["points"] >= 1000000

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
    assert don_data["details"]["points_credited"] == 100000

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

