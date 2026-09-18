import os
import re
import time
from datetime import datetime, timezone
from typing import Tuple, Optional, Dict, Any
from sqlalchemy.orm import Session
from models import Position
import trading_engine as te
from trading_engine import (
    STARTING_POINTS,
    get_market_state,
    get_or_create_user,
    calculate_position_valuation,
    execute_buy,
    execute_sell,
    execute_liquidate,
    register_limit_order,
    parse_product_type,
    execute_mining,
    execute_borrow,
    execute_repay,
    execute_treasury_donate,
    calculate_user_bank_assets,
    get_user_credit_info,
    format_user_credit_report,
    execute_bankruptcy,
    submit_bankruptcy_application,
    get_treasury_info,
    execute_margin_buy,
    is_market_locked,
    get_casino_state,
    open_casino,
    close_casino,
    DEFAULT_CASINO_MAX_BET,
    MIN_CASINO_BET,
    execute_slot_gamble,
    execute_dice_gamble,
    execute_mahjong_tile_gamble,
    execute_yakuman_race_gamble,
    settle_match,
    execute_delisting_and_relist,
    format_quantity,
    execute_transfer,
    parse_korean_amount,
    execute_pickaxe_upgrade,
    get_user_pickaxe_status,
    get_pickaxe_table_guide,
    get_pickaxe_info,
    execute_buy_equipment,
    execute_equip_item,
    execute_list_equipment,
    execute_buy_equipment_listing,
    execute_cancel_equipment_listing,
    get_equipment_market_listings,
    get_user_inventory_status,
    get_starforce_event_state,
    open_starforce_event,
    close_starforce_event,
    get_starforce_event_guide,
    set_auto_mining,
    renew_auto_mining,
    get_auto_mining_status,
    get_user_equipped_item,
    get_equipment_potential_effects,
    get_user_cooldown_status,
    execute_buy_cubes,
    execute_cube_use,
    execute_cube_fragment_exchange,
    execute_equipment_cube_lock,
    execute_potential_line_lock,
    set_day_open_price,
    get_lottery_event_state,
    open_lottery_event,
    close_lottery_event,
    execute_buy_lottery,
    get_lottery_guide,
    get_merchant_state,
    open_merchant,
    close_merchant,
    execute_buy_merchant_item,
    get_merchant_guide,
    get_user_item_inventory,
    get_user_special_snipe_scrolls,
    MERCHANT_ITEMS,
    toggle_user_scroll_arm,
    execute_list_item,
    execute_buy_item_listing,
    execute_cancel_item_listing,
    execute_buy_exchange,
    execute_cancel_exchange,
    get_unified_market_listings,
    match_potential_target,
    create_pvp_challenge,
    accept_pvp_challenge,
    decline_pvp_challenge,
    open_public_arena_match,
    join_public_arena_match,
    get_arena_status
)

CHANNEL_ID = os.getenv("CHANNEL_ID", "4495f96624a2c60bd1ed5a6139014d20")
GUIDE_WEB_URL = os.getenv("GUIDE_WEB_URL", "https://hot6mania.github.io/stoke-mahjong/")

SUPPORTED_LEVERAGE_PREFIXES = ["1", "2", "3", "5", "10", "20", "40", "60"]

NEWBIE_GUIDE_MESSAGE = f"""🔰 [마작 주식 & 금융 시스템 처음 오신 분 입문 안내]
스트리머의 마작 경기 점수에 따라 주가가 실시간 변동하는 시청자 참여형 모의 투자 게임입니다!

1️⃣ ⛏️ 무료 채굴: !채굴 (쿨타임마다 무료 포인트 및 1X 주식 수확)
2️⃣ 📈 주식 투자: 스트리머 승리 예상 시 !매수 1X [수량/올인], 패배 예상 시 !매수 INV [수량] (고수용: !10롱 올인, !10숏 올인)
3️⃣ 🔨 장비 & 큐브: !강화 로 곡괭이 스펙업(채굴량 폭증 & 쿨 단축), !큐브 로 잠재능력 3줄 뽑기
4️⃣ 🎰 미니게임: !슬롯 [금액], !복권 [동/은/금] [수량], !경마 [말이름] [금액]
5️⃣ ℹ️ 내 정보: !내정보 (포인트, 보유주식, 장비 스펙 한눈에 확인)

🌐 웹 실시간 차트 & 원클릭 플레이: {GUIDE_WEB_URL} (채팅창에 !웹)
📖 50+ 전체 명령어 사전: !명령어"""

HELP_MESSAGE = f"""📈 [마작 주식 명령어 안내] (💡 처음 오신 분 입문: !도움말 또는 !설명)
• 거래: !매수 [종목] [수량/올인], !매도 [종목] [수량/전량], !청산
• 금융: !내정보, !신용등급, !송금 [닉네임] [금액], !대출 [금액/최대], !상환, !기부 [금액], !채굴, !자동채굴 [on/off/갱신], !인증 [코드], !웹로그인, !비번 [4자리], !국고, !남은시간, !쿨타임
• 복권: !동복권 [수량], !은복권 [수량], !금복권 [수량], !복권 [동/은/금] [수량], !복권확률 (동 1천P / 은 5천P / 금 2만P 초대박!)
• 상인: !신비상인, !상인구매 [1~7] [수량], !아이템 (파방/상승/하강/잠재저격/절대파방/절대하강 한정 판매)
• 거래소: !거래소, !아이템판매 [파방/하강/상승/저격/큐브] [수량] [가격], !장비등록 [번호] [가격], !거래소구매 [번호], !거래소취소 [번호]
• 장비: !상태창, !내장비, !장착 [번호], !강화 [파방/하강/상승/풀/절대풀], !주문서 [파방/하강/상승/절대파방/절대하강] [on/off], !큐브구매 [수량], !큐브 [번호] [저격옵션], !저격목록, !큐브잠금 [번호], !옵션잠금 [1~3], !큐브조각, !피버, !곡괭이구매 [0/5/10]
• 도박: !슬롯 [금액], !주사위 [홀/짝/대/소] [금액], !마작 [만/삭/통 or 1만~9통] [금액], !경마 [대삼원/스안커/국사무쌍/구련보등] [금액], !카지노, !슬롯확률
• 투기장: !대결 @유저 [금액], !수락, !거절, !투기장 오픈 [금액], !투기장 참가 (⚔️ 1:1 맞짱 주사위 데스매치)
• 종목: 1X, 2X, 3X, 5X, 10X (레버리지) / INV, 2X_INV~10X_INV (인버스) [야수의 심장: 20X, 40X, 60X] (약어: !약어)
📖 상세 웹 가이드: {GUIDE_WEB_URL}"""
GUIDE_STOCK = HELP_MESSAGE

GUIDE_BUY = "💡 매수 사용법: !매수 [종목] [수량/올인/빚올인] (!올인, !구매도 가능. 예: !올인 1X, !매수 1X 올인, !구매 10X 1, !빚올인 10X)"
GUIDE_SELL = "💡 매도 사용법: !매도 [종목] [수량/전량] (!판매, !전량매도 가능. 예: !매도 10X 전량, !전량매도 10X)"
GUIDE_LIMIT = "💡 지정가 사용법: !지정가 [매수/매도] [종목] [목표가] [수량] (예: !지정가 매수 1X 300 10)"
GUIDE_LIQUIDATE = "💡 청산 사용법: !청산 [종목/전량] (예: !청산 10X, !청산 전량)"
GUIDE_BORROW = "💡 대출 사용법: !대출 [금액/최대] (경기 중에도 24시간 상시 가능, 예: !대출 최대, !대출 30000 | 개장 중엔 !빚올인 10X | 신용평가: !신용등급)"
GUIDE_REPAY = "💡 상환 사용법: !상환 [금액/전액] (예: !상환 20000, !상환 전액)"
GUIDE_TRANSFER = "💡 계좌이체 사용법: !송금 [받는분닉네임] [금액/올인] (예: !송금 치즈나베 10000, !이체 @CYTFT 5만, !송금 닉네임 올인)\n• 1만P 미만 면세, 1만P 이상 0.1%(1만P당 10P), 10만P 이상 0.2%의 미미한 수수료만 국고로 적립됩니다."
GUIDE_MINING = (
    "⛏️✨ [랜덤 채굴 & 크리티컬 확률 안내] (기본 15분마다 무료 채굴)\n"
    "• 🀄🌟 천화(天和) 신화 잭팟 (0.2%): 1X 20배 + 국고 10%(최대 30만P) + 10X 5주 + 쿨타임 즉시 초기화!\n"
    "• 🀄 구련보등 더블역만 (0.8%): 1X 10배 + 국고 5%(최대 10만P) + 10X 2주 + 쿨타임 3분 단축!\n"
    "• 🀄 국사무쌍 13면 역만급 초대박 (2.0%): 1X 5배 + 현금 15,000P + 10X 1주 + 쿨타임 1분 단축!\n"
    "• 💎 다이아몬드 슈퍼 크리티컬 (5.0%): 1X 3배 + 현금 7,000P + 쿨타임 1분 단축!\n"
    "• ⚡ 황금 광맥 더블 크리티컬 (14%): 1X 2배 + 현금 2,000P\n"
    "• ✨ 은 광맥 (23%): 1X 1.3배 ~ 1.5배 | ⛏️ 구리 (37%): 1X 1.0배 | 🪨 석탄/자갈 (18%): 0.6~0.8배\n"
    "🔥 곡괭이 강화(!강화): 고강 곡괭이 장착 시 채굴량 최대 80배 폭등 + 매 채굴 확정 최대 120만P 현금 + 쿨 3분 단축 + 크리 150% 보장!! (확인: !곡괭이, 강화표: !강화표)\n"
    "* 빚(대출) 보유 시 채굴 가치만큼 국고 빚이 즉시 탕감됩니다!"
)
GUIDE_CASINO = (
    "🎰 [국고 카지노 4종 사용법]\n"
    "• 🎰 슬롯머신: !슬롯 [금액/올인] (777 국고 15% MEGA JACKPOT)\n"
    "• 🎲 주사위 배틀: !주사위 [홀/짝/대/소] [금액/올인] (1.8배 / 7 무승부 환급 / 더블 2.2배)\n"
    "• 🀄 마작패 맞추기: !마작 [만/삭/통 or 1만~9통] [금액/올인] (수패 2.7배 / 1종 단기 24.3배 대박)\n"
    "• 🏇 역만 레이스: !경마 [1~4 or 마명] [금액/올인] (1위 3.6배 / 잠재 2등 세이프티 환급)\n"
    "• 상태 & 확률: !카지노, !슬롯확률\n"
    "* 스트리머 전용: !카지노오픈 [분] [최대한도], !카지노마감"
)
GUIDE_ARENA = (
    "⚔️ [지하 투기장 1:1 맞짱 데스매치 가이드]\n"
    "• 1:1 맞짱 신청: !대결 @상대닉네임 [금액/올인] (예: !대결 @메루1 50000)\n"
    "• 대결 수락: !수락 (90초 제한시간 내 수락 시 즉시 주사위 대결)\n"
    "• 대결 거절: !거절 (도망치기)\n"
    "• 공개 투기장 개설: !투기장 오픈 [금액] (아무나 와라!)\n"
    "• 공개 투기장 참가: !투기장 참가\n"
    "• 투기장 현황: !투기장\n"
    "• 룰: 1d100 주사위 맞짱! 더 높은 숫자 승리! 승자 98% 독식 대박, 2% 국고 수수료 적립!"
)

def handle_chat_command(
    db: Session,
    user_id: str,
    username: str,
    raw_message: str
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Dispatcher for incoming streaming chat commands.
    Returns: (reply_text, broadcast_event_dict)
    """
    import unicodedata
    raw_message = unicodedata.normalize('NFKC', str(raw_message or ""))
    msg = raw_message.strip()
    idx = msg.find("!")
    if idx == -1:
        return None, None
    msg = msg[idx:]

    # Handle accidental space after '!' (e.g. "! 10배 올인" -> "!10배 올인")
    if msg.startswith("! "):
        msg = "!" + msg[1:].lstrip()

    # Split command tokens
    tokens = msg.split()
    if len(tokens) > 1 and tokens[0] == "!":
        tokens = [f"!{tokens[1]}"] + tokens[2:]

    # Normalize separated leverage & direction tokens (e.g. ['!40', '롱', '올인'] -> ['!40롱', '올인'], ['!매수', '40', '롱', '올인'] -> ['!매수', '40롱', '올인'])
    merged_tokens = []
    skip_next = 0
    for i, t in enumerate(tokens):
        if skip_next > 0:
            skip_next -= 1
            continue
        has_bang = t.startswith("!")
        raw_num = t[1:] if has_bang else t
        is_lev_num = raw_num in SUPPORTED_LEVERAGE_PREFIXES
        is_lev_bae = raw_num.endswith("배") and raw_num[:-1] in SUPPORTED_LEVERAGE_PREFIXES
        if (is_lev_num or is_lev_bae) and i + 1 < len(tokens):
            next_t = tokens[i+1].strip().lower()
            next2_t = tokens[i+2].strip().lower() if i + 2 < len(tokens) else ""
            if is_lev_num and next_t == "배" and next2_t in ["롱", "숏", "인버스", "곱버스"]:
                combo = f"!{raw_num}배{next2_t}" if has_bang else f"{raw_num}배{next2_t}"
                merged_tokens.append(combo)
                skip_next = 2
                continue
            elif next_t in ["롱", "숏", "배", "배롱", "배숏", "인", "곱", "인버스", "곱버스", "레버", "레버리지"]:
                combo = f"!{raw_num}{next_t}" if has_bang else f"{raw_num}{next_t}"
                merged_tokens.append(combo)
                skip_next = 1
                continue
        merged_tokens.append(t)
    tokens = merged_tokens
    cmd = tokens[0].lower()

    # 1. Help & Newbie Beginner Guide Commands (!도움말, !설명, !초보, !튜토리얼, !입문, !help, !guide)
    if cmd in ["!도움말", "!설명", "!초보", "!튜토리얼", "!입문", "!help", "!guide"]:
        if len(tokens) > 1:
            sub = tokens[1].lower()
            if sub in ["매수", "buy", "구매"]:
                return GUIDE_BUY, None
            elif sub in ["매도", "sell", "판매"]:
                return GUIDE_SELL, None
            elif sub in ["채굴", "광부", "mine", "마이닝"]:
                return GUIDE_MINING, None
            elif sub in ["카지노", "도박", "casino", "슬롯", "경마"]:
                return GUIDE_CASINO, None
            elif sub in ["투기장", "대결", "arena", "pvp"]:
                return GUIDE_ARENA, None
            elif sub in ["대출", "빚", "loan", "대여"]:
                return GUIDE_BORROW, None
            elif sub in ["상환", "갚기", "repay"]:
                return GUIDE_REPAY, None
            elif sub in ["송금", "이체", "transfer"]:
                return GUIDE_TRANSFER, None
            elif sub in ["지정가", "limit"]:
                return GUIDE_LIMIT, None
            elif sub in ["청산", "liquidate"]:
                return GUIDE_LIQUIDATE, None
            elif sub in ["강화", "스타포스", "주문서", "upgrade", "sf"]:
                return (
                    "🔨 [스타포스 곡괭이 강화 & 주문서 가이드]\n"
                    "• 강화 시도: !강화 [장비번호/옵션] (예: !강화, !강화 1, !강화 파방, !강화 하강, !강화 풀)\n"
                    "• 🛡️ 일반 파괴방어권: 15성+ 실패 시 60% 확률 방어 (40% 뚫림 위험!)\n"
                    "• 📉 일반 하강방지권: 실패 시 70% 확률로 등급 하락 방어 (30% 하락 위험!)\n"
                    "• 🛡️✨ 절대 파괴방어권: 15성+ 폭발 파괴 100% 무적 결계 방어 (신비상인)\n"
                    "• 📉✨ 절대 하강방지권: 등급 하락 100% 무적 결계 방어 (신비상인)\n"
                    "• ⚡ 강화확률상승권: 성공률 +25% 곱연산 증폭\n"
                    "• 주문서 상시 설정: !주문서 (파방/하강/상승/절대파방/절대하강 on/off)"
                ), None
            elif sub in ["약어", "단축어", "alias"]:
                return (
                    "🏷️ [종목 약어 & 단축어 가이드]\n"
                    "• 📈 레버리지(상승/롱): 10배, 10레, 10버, 10롱 (2~5배도 동일: 5레, 5롱 등)\n"
                    "• 📉 인버스(하락/숏): 숏(1X), 곱버스(2X), 10숏, 10인, 10곱 (5숏, 3인 등)\n"
                    "⚡ 간편 주문 팁: 종목명만 입력해도 즉시 주문! (예: !10롱 올인, !10숏 5, !곱버스 전량)"
                ), None
            elif sub in ["명령어", "commands", "cmd", "사전", "전체"]:
                return HELP_MESSAGE, None
        return NEWBIE_GUIDE_MESSAGE, None

    # 1-0. Comprehensive Command List (!명령어, !주식명령어, !전체명령어, !주식도움말, !commands, !cmd)
    if cmd in ["!주식명령어", "!주식도움말", "!명령어", "!전체명령어", "!commands", "!cmd"]:
        return HELP_MESSAGE, None

    # 1-1. Web Guide & Site URL Command (!사이트, !주소, !웹, !웹사이트, !홈페이지, !설명서, !가이드, !웹가이드, !링크, !site, !link, !url, !web)
    if cmd in ["!사이트", "!주소", "!웹", "!웹사이트", "!홈페이지", "!설명서", "!가이드", "!웹가이드", "!링크", "!site", "!link", "!url", "!web"]:
        reply = (
            f"🌐 [마작 주식 웹 설명서 & 실시간 시세]\n"
            f"🔗 {GUIDE_WEB_URL}\n"
            f"• 실시간 주가 차트, 주주 랭킹, 상세 가이드 및 룰북을 웹에서 바로 확인하실 수 있습니다!\n"
            f"💡 처음 오신 분 입문 안내는 채팅창에 '!도움말' 또는 '!설명'을 입력해주세요."
        )
        return reply, None

    # 1-1-1. Secure Web Reverse Challenge Authentication (!인증, !인증번호, !인증코드, !로그인 [코드])
    if cmd in ["!인증", "!인증번호", "!인증코드", "!로그인인증", "!authcode"]:
        if len(tokens) < 2:
            return "💡 [웹 간편인증] 사용법: !인증 [4자리코드] (웹 라운지 [🔑 로그인] 창에 표시된 4자리 번호를 입력하세요! 예: !인증 8421)", None
        ok, reply, _ = te.verify_chat_auth_challenge(db, user_id, username, tokens[1])
        return reply, None

    # 1-1-2. Web Desk Login Code & Guide (!웹로그인, !접속, !웹인증, !weblogin, !auth, !login)
    if cmd in ["!웹로그인", "!접속", "!웹인증", "!weblogin", "!auth", "!login"]:
        if len(tokens) >= 2 and tokens[1].isdigit():
            # User provided challenge code directly with !웹로그인 or !login (e.g. !로그인 8421)
            ok, reply, _ = te.verify_chat_auth_challenge(db, user_id, username, tokens[1])
            return reply, None

        code = te.generate_web_login_code(user_id, username)
        reply = (
            f"🔑 [치즈나베 웹 로그인] {username} 님의 1회용 접속 코드: [{code}]\n"
            f"• 유효시간: 5분 | 웹페이지 상단 [🔑 로그인] 창에 닉네임과 위 4자리 코드를 입력해주세요!\n"
            f"🔒 [보안 추천] 타인의 코드 가로채기를 방지하려면 웹 로그인 창의 [⚡ 간편 채팅 인증(!인증)]을 이용하세요!"
        )
        return reply, None

    # 1-1-3. Permanent Web Login PIN (!비번, !비밀번호, !pin, !password)
    if cmd in ["!비번", "!비밀번호", "!pin", "!password"]:
        if len(tokens) < 2:
            return "💡 웹 비밀번호 설정법: !비번 [4자리숫자] (예: !비번 1234 | 웹 라운지에서 언제든 마이페이지로 안전하게 변경 가능)", None
        pin_arg = tokens[1]
        ok, msg = te.set_user_web_pin(db, user_id, pin_arg)
        return msg, None

    # 1-2. Abbreviation & Shorthand Guide (!약어, !단축어, !종목약어, etc.)
    if cmd in ["!약어", "!단축어", "!종목약어", "!줄임말", "!은어", "!별칭", "!alias"]:
        reply = (
            "🏷️ [종목 약어 & 단축어 가이드]\n"
            "• 📈 레버리지(상승/롱): 10배, 10레, 10버, 10롱 (2~5배도 동일: 5레, 5롱 등)\n"
            "• 📉 인버스(하락/숏): 숏(1X), 곱버스(2X), 10숏, 10인, 10곱 (5숏, 3인 등)\n"
            "⚡ 간편 주문 팁: 종목명만 입력해도 즉시 주문! (예: !10롱 올인, !10숏 5, !곱버스 전량)"
        )
        return reply, None

    # 2. Market State Query
    if cmd in ["!주식", "!시세", "!호가", "!가격", "!주가"]:
        state = get_market_state(db)
        day_open = getattr(state, "day_open_price", None) or state.previous_price
        diff = state.current_price - day_open
        diff_pct = (diff / day_open * 100.0) if day_open > 0 else 0.0

        if diff > 0:
            change_str = f"▲+{diff:,}P (+{diff_pct:.2f}%)"
        elif diff < 0:
            change_str = f"▼{diff:,}P ({diff_pct:.2f}%)"
        else:
            change_str = "0P (0.00%)"

        end_t = float(getattr(state, "free_trading_end_time", 0.0) or 0.0)
        rem_trade = max(0, int(end_t - time.time())) if (not state.is_trading_locked and end_t > 0) else 0
        if state.is_trading_locked:
            status_badge = "[경기 중 - 거래 마감]"
        elif rem_trade > 0:
            m_t, s_t = divmod(rem_trade, 60)
            status_badge = f"[장 열림 ({m_t}분 {s_t}초 남음)]"
        else:
            status_badge = "[장 열림]"

        delta_str = f"{state.last_settlement_delta:+d}pt" if state.last_settlement_delta != 0 else "0pt"
        rank_name = getattr(state, "current_rank_name", "작성3") or "작성3"

        reply = (
            f"📊 [나베주가 ({rank_name}) 시세] 현재가: {state.current_price:,}P (작혼 {state.current_rank_point:,}pt | {change_str}) | "
            f"당일시가: {day_open:,}P (직전: {delta_str}) | 상태: {status_badge} | "
            f"국고: {int(round(getattr(state, 'treasury_pool', 500000.0))):,}P"
        )
        return reply, None

    # 2-1. Remaining Time Query (!남은시간, !시간, !장시간, !남은장시간, !마감시간, !time, !타이머)
    if cmd in ["!남은시간", "!시간", "!장시간", "!남은장시간", "!마감시간", "!장마감", "!time", "!타이머"]:
        state = get_market_state(db)
        c_state = get_casino_state(db)
        user = get_or_create_user(db, user_id, username)

        now = time.time()

        # 1. Free Trading Remaining
        end_t = float(getattr(state, "free_trading_end_time", 0.0) or 0.0)
        is_locked = bool(getattr(state, "is_trading_locked", True))
        rem_trade = max(0, int(end_t - now)) if (not is_locked and end_t > 0) else 0

        if not is_locked and rem_trade > 0:
            m_t, s_t = divmod(rem_trade, 60)
            trade_str = f"🟢 장 열림 ({m_t}분 {s_t}초 후 마감)"
        elif not is_locked:
            trade_str = "🟢 장 열림 (자유 거래 중)"
        else:
            trade_str = "🔒 경기 진행 중 (거래 마감)"

        # 2. Casino Remaining
        if c_state["is_open"]:
            rem_c = c_state["remaining_sec"]
            if 0 < rem_c < 99999:
                m_c, s_c = divmod(rem_c, 60)
                casino_str = f"🎰 카지노 오픈 ({m_c}분 {s_c}초 남음)"
            else:
                casino_str = "🎰 카지노 오픈 (무제한)"
        else:
            casino_str = "💤 카지노 마감"

        # 3. Starforce Fever Remaining
        sf_state = get_starforce_event_state(db)
        if sf_state.get("is_active"):
            rem_sf = sf_state["remaining_sec"]
            m_sf, s_sf = divmod(rem_sf, 60)
            sf_str = f"🔥 {sf_state['event_type_name']} ({m_sf}분 {s_sf}초 남음)"
        else:
            sf_str = "💤 피버 대기중 (돌발 발동)"

        # 4. User Mining Cooldown
        equipped_item = get_user_equipped_item(db, user)
        pick_lvl = equipped_item.starforce if equipped_item else getattr(user, "pickaxe_level", 0) or 0
        pick_lvl = max(0, min(30, int(pick_lvl)))
        user.pickaxe_level = pick_lvl
        pick_info = get_pickaxe_info(pick_lvl)
        cd_min = pick_info["cooldown_minutes"]
        pot_eff = get_equipment_potential_effects(equipped_item) if equipped_item else {}
        pot_cd_red = pot_eff.get("mining_cd_reduction", 0)
        heavy_cd_add = pot_eff.get("heavy_mining_cd_add", 0)
        effective_cd_min = max(2, cd_min - pot_cd_red + heavy_cd_add)
        pickaxe_cd = effective_cd_min * 60
        mine_str = "⛏️ 즉시 가능"
        if user.last_mined_at:
            now_utc = datetime.now(timezone.utc)
            last_t = user.last_mined_at
            if last_t.tzinfo is None:
                last_t = last_t.replace(tzinfo=timezone.utc)
            elapsed = (now_utc - last_t).total_seconds()
            if elapsed < pickaxe_cd:
                rem_m = int(pickaxe_cd - elapsed)
                mm, ss = divmod(rem_m, 60)
                mine_str = f"⛏️ 쿨타임 {mm}분 {ss}초"

        # 5. Auto Mining Remaining
        end_am = float(getattr(user, "auto_mining_end_time", 0.0) or 0.0)
        if bool(getattr(user, "auto_mining_enabled", False)) and end_am > now:
            rem_am = int(end_am - now)
            h_am, mod_am = divmod(rem_am, 3600)
            m_am, s_am = divmod(mod_am, 60)
            auto_str = f"🟢 가동중 ({h_am}시간 {m_am}분 남음)" if h_am > 0 else f"🟢 가동중 ({m_am}분 {s_am}초 남음)"
        else:
            auto_str = "💤 OFF"

        reply = f"⏱️ [현재 남은 시간] 거래: {trade_str} | 도박: {casino_str} | 스타포스: {sf_str} | 내 채굴: {mine_str} | 자동채굴: {auto_str}"
        return reply, None

    # 2-2. Dedicated Cooldown Query (!쿨타임, !쿨, !cooldown, !cd, !채굴쿨)
    if cmd in ["!쿨타임", "!쿨", "!cooldown", "!cd", "!채굴쿨"]:
        return get_user_cooldown_status(db, user_id, username), None

    # 3. Account / Wallet Query (보유와 채굴을 '보유'로 완전 통합)
    if cmd in ["!내정보", "!지갑", "!내주식", "!계좌", "!잔고"]:
        user = get_or_create_user(db, user_id, username)
        state = get_market_state(db)
        positions = db.query(Position).filter(Position.user_id == user.id, Position.quantity > 0).all()

        portfolio_val = 0
        pos_summaries = []

        for p in positions:
            val = calculate_position_valuation(p, state.current_price)
            curr_val = int(round(val["current_value"]))
            portfolio_val += curr_val
            pnl_pct = val["pnl_pct"]
            sign = "+" if pnl_pct >= 0 else ""
            qty_str = format_quantity(p.quantity)
            pos_summaries.append(f"{p.product_type.value}: {qty_str}주 (평단 {int(round(p.entry_price)):,}P, {sign}{pnl_pct:.1f}%)")

        debt = getattr(user, "debt", 0) or 0
        bank_assets_info = calculate_user_bank_assets(user, market_state=state)
        bank_bal = bank_assets_info["bank_balance"]
        sav_bal = bank_assets_info["savings_balance"]
        fund_val = bank_assets_info["fund_valuation"]
        total_bank = bank_assets_info["total_bank_assets"]

        gross_assets = user.points + total_bank + portfolio_val
        net_assets = gross_assets - debt
        total_pnl = net_assets - STARTING_POINTS
        sign = "+" if total_pnl >= 0 else ""
        total_pnl_pct = (total_pnl / float(STARTING_POINTS)) * 100.0

        bank_parts = []
        if bank_bal > 0:
            bank_parts.append(f"예금 {bank_bal:,}P")
        if sav_bal > 0:
            bank_parts.append(f"적금 {sav_bal:,}P")
        if fund_val > 0:
            bank_parts.append(f"펀드 {fund_val:,}P")
        bank_str = f" | 금융: {total_bank:,}P({', '.join(bank_parts)})" if bank_parts else ""

        div_str = f" | 누적배당: +{user.total_dividends:,}P" if getattr(user, "total_dividends", 0) > 0 else ""
        debt_str = f" | 빚(대출): {debt:,}P" if debt > 0 else ""
        user_pick_lvl = getattr(user, "pickaxe_level", 0)
        if user_pick_lvl is None:
            user_pick_lvl = 0
        pickaxe = get_pickaxe_info(user_pick_lvl)
        pickaxe_str = f" | 장비: {pickaxe['name']}"

        am_enabled = bool(getattr(user, "auto_mining_enabled", False))
        am_end = float(getattr(user, "auto_mining_end_time", 0.0) or 0.0)
        now_ts = time.time()
        if am_enabled and am_end > now_ts:
            rem_sec = int(am_end - now_ts)
            h = rem_sec // 3600
            m = (rem_sec % 3600) // 60
            am_str = f" | 자동채굴: 🟢ON ({h}시간 {m}분)" if h > 0 else f" | 자동채굴: 🟢ON ({m}분)"
        else:
            am_str = " | 자동채굴: 💤OFF"

        cube_cnt = getattr(user, "cube_count", 0) or 0
        frag_cnt = getattr(user, "cube_fragments", 0) or 0
        cube_str = ""
        if cube_cnt > 0 or frag_cnt > 0:
            cube_str = f" | 큐브: {cube_cnt}개(조각: {frag_cnt})"

        credit_info = get_user_credit_info(user, db=db, market_state=state)
        credit_str = f" | 신용: {credit_info['tier']}등급({credit_info['grade']})"

        if pos_summaries:
            pos_str = " | ".join(pos_summaries)
            reply = (
                f"👤 [{user.username}] 현금: {user.points:,}P{debt_str}{bank_str} | 순자산: {net_assets:,}P ({sign}{total_pnl_pct:.1f}%){div_str}{credit_str}{pickaxe_str}{am_str}{cube_str} | "
                f"보유: [{pos_str}]"
            )
        else:
            reply = f"👤 [{user.username}] 현금: {user.points:,}P{debt_str}{bank_str} | 순자산: {net_assets:,}P ({sign}{total_pnl_pct:.1f}%){div_str}{credit_str}{pickaxe_str}{am_str}{cube_str} | 보유 포지션이 없습니다."

        return reply, None

    # Central Trading Lock Enforcement Gate (주식 거래만 잠금, 채굴 및 대출은 경기 중에도 24시간 상시 가능)
    TRADING_COMMANDS = {
        "!올인", "!allin", "!풀매수", "!전액매수", "!매수올인", "!구매올인",
        "!매수", "!사기", "!buy", "!구매", "!구매하기", "!매수하기",
        "!빚올인", "!빚으로올인", "!빚투", "!신용매수", "!대출매수", "!마진매수", "!빚매수", "!신용구매",
        "!빚으로", "!빚내서",
        "!매도", "!팔기", "!sell", "!판매", "!판매하기", "!매도하기", "!전량매도", "!풀매도", "!완판",
        "!지정가", "!예약", "!limit",
        "!청산", "!정리", "!손절", "!익절"
    }

    if cmd in TRADING_COMMANDS:
        state = get_market_state(db)
        if is_market_locked(db, state):
            db.rollback()
            if cmd in ["!매도", "!팔기", "!sell", "!판매", "!판매하기", "!매도하기", "!전량매도", "!풀매도", "!완판"]:
                return "⚠️ [거래 마감] 경기가 진행 중이므로 매도할 수 없습니다. (조회, 채굴, 대출 명령만 가능)", None
            elif cmd in ["!청산", "!정리", "!손절", "!익절"]:
                return "⚠️ [거래 마감] 경기가 진행 중이므로 청산할 수 없습니다.", None
            elif cmd in ["!지정가", "!예약", "!limit"]:
                return "⚠️ [거래 마감] 경기가 진행 중이므로 지정가 주문을 접수할 수 없습니다.", None
            else: # buy, all-in, margin buy
                return "⚠️ [거래 마감] 경기가 진행 중이므로 매수할 수 없습니다. (조회, 채굴, 대출 명령만 가능)", None

    # 4. Direct All-in Buy Order (!올인, !allin, !풀매수, !전액매수, !매수올인, !구매올인, !올인10배, !풀매수10X 등)
    allin_cmds = ["!올인", "!allin", "!풀매수", "!전액매수", "!매수올인", "!구매올인"]
    matched_allin_cmd = None
    allin_rem_product = None
    for ac in allin_cmds:
        if cmd == ac:
            matched_allin_cmd = ac
            break
        elif cmd.startswith(ac):
            rem = cmd[len(ac):].strip()
            p_cand = parse_product_type(f"{rem}X" if rem in SUPPORTED_LEVERAGE_PREFIXES else rem)
            if p_cand:
                matched_allin_cmd = ac
                allin_rem_product = p_cand.value
                break

    if matched_allin_cmd:
        state = get_market_state(db)
        if is_market_locked(db, state):
            db.rollback()
            return "⚠️ [거래 마감] 경기가 진행 중이므로 매수할 수 없습니다. (조회, 채굴, 대출 명령만 가능)", None

        is_margin = False
        product_str = allin_rem_product
        for t in tokens[1:]:
            clean_t = t.strip().strip("'\"`’‘“”,;[]()").strip()
            parsed_prod = parse_product_type(clean_t)
            if clean_t in ["빚", "신용", "대출", "빚으로", "빚올인", "빚투", "신용올인"]:
                is_margin = True
            elif parsed_prod:
                if product_str and product_str != "1X" and clean_t in ["롱", "기본", "현물", "주", "배"]:
                    continue
                product_str = parsed_prod.value
            elif clean_t in SUPPORTED_LEVERAGE_PREFIXES:
                product_str = f"{clean_t}X"

        if not product_str:
            product_str = "1X"

        if is_margin:
            success, reply, details = execute_margin_buy(db, user_id, username, product_str, "올인")
        else:
            success, reply, details = execute_buy(db, user_id, username, product_str, "올인")
        event = {"type": "trade_buy", "data": details} if success and details else None
        return reply, event

    # 4-0. Direct Product Command (e.g. !10X 올인, !10배 올인, !10배올인, !10배 전량, !10배 매도, !10롱 올인, !곱버스 전량)
    direct_prod = None
    direct_qty = None

    if cmd.startswith("!"):
        cmd_sub = cmd[1:]
        cand_sub = f"{cmd_sub}X" if cmd_sub in SUPPORTED_LEVERAGE_PREFIXES else cmd_sub
        direct_prod = parse_product_type(cand_sub)

        if direct_prod:
            rem_tokens = tokens[1:]
            if rem_tokens and rem_tokens[0].strip().strip("'\"`’‘“”,;[]()").lower() in ["롱", "숏", "배", "배롱", "배숏", "인", "곱", "인버스", "곱버스", "레버", "레버리지"]:
                rem_tokens = rem_tokens[1:]
            direct_qty = rem_tokens[0] if rem_tokens else "1"
        else:
            # Check attached forms without space (e.g. !10배올인, !10롱올인, !10배풀매수, !10배전량, !10배매도, !10배10)
            from trading_engine import PRODUCT_SYNONYMS
            for pfx in sorted(PRODUCT_SYNONYMS.keys(), key=len, reverse=True):
                if cmd_sub.startswith(pfx.lower()):
                    rem = cmd_sub[len(pfx):].strip()
                    cand = parse_product_type(pfx)
                    if cand:
                        direct_prod = cand
                        direct_qty = rem if rem else (tokens[1] if len(tokens) >= 2 else "1")
                        break

    if direct_prod:
        state = get_market_state(db)
        if is_market_locked(db, state):
            db.rollback()
            return "⚠️ [거래 마감] 경기가 진행 중이므로 거래할 수 없습니다. (조회, 채굴, 대출 명령만 가능)", None

        allin_words = ["올인", "all", "전액", "풀매수", "다", "전부", "최대", "올인매수", "전액매수"]
        margin_words = ["빚올인", "빚으로올인", "대출올인", "신용올인", "빚투", "신용구매", "빚", "대출", "신용"]
        sell_words = ["전량", "매도", "팔기", "판매", "전량매도", "풀매도", "완판", "정리", "청산", "익절", "손절"]
        buy_words = ["매수", "사기", "구매", "매수하기"]

        qty_token = (direct_qty or "1").strip().strip("'\"`’‘“”,;[]()").strip()

        # Check if action is SELL (e.g. !10배 전량, !10배 매도, !10배 매도 5, !10배전량, !10배팔기)
        if any(qty_token.startswith(sw) for sw in sell_words) or qty_token in sell_words:
            sell_qty = "전량"
            if len(tokens) >= 3:
                sell_qty = tokens[2].strip()
            elif qty_token not in sell_words:
                for sw in sell_words:
                    if qty_token.startswith(sw):
                        rem_q = qty_token[len(sw):].strip()
                        if rem_q:
                            sell_qty = rem_q
                        break
            success, reply, details = execute_sell(db, user_id, username, direct_prod.value, sell_qty)
            event = {"type": "trade_sell", "data": details} if success and details else None
            return reply, event

        # Check if action is BUY keyword (e.g. !10배 매수 5, !10배 매수 올인, !10배 매수)
        if qty_token in buy_words or any(qty_token.startswith(bw) for bw in buy_words):
            buy_qty = "1"
            if len(tokens) >= 3:
                buy_qty = tokens[2].strip()
            elif qty_token not in buy_words:
                for bw in buy_words:
                    if qty_token.startswith(bw):
                        rem_q = qty_token[len(bw):].strip()
                        if rem_q:
                            buy_qty = rem_q
                        break
            qty_token = buy_qty

        # Execute Buy / Margin Buy
        if qty_token in margin_words:
            success, reply, details = execute_margin_buy(db, user_id, username, direct_prod.value, "올인")
        elif qty_token in allin_words:
            success, reply, details = execute_buy(db, user_id, username, direct_prod.value, "올인")
        else:
            success, reply, details = execute_buy(db, user_id, username, direct_prod.value, qty_token)
        event = {"type": "trade_buy", "data": details} if success and details else None
        return reply, event

    # 4-1. Mysterious Merchant Direct Buy Commands (!상인구매, !신비구매, !상점구매 등)
    merchant_buy_cmds = ["!상인구매", "!신비구매", "!상점구매", "!주문서구매", "!비밀구매", "!스크롤구매"]
    if cmd in merchant_buy_cmds:
        if len(tokens) < 2:
            return get_merchant_guide(db), None
        item_target = tokens[1].strip().strip("'\"`’‘“”,;[]()")
        qty_token = tokens[2].strip().strip("'\"`’‘“”,;[]()") if len(tokens) >= 3 else "1"
        success, reply, details = execute_buy_merchant_item(db, user_id, username, item_target, qty_token)
        event = {"type": "merchant_bought", "data": details} if success and details else None
        return reply, event

    # 4-2. Market Buy Order (!매수, !사기, !구매 etc. - strictly stocks)
    if cmd in ["!매수", "!사기", "!buy", "!구매", "!구매하기", "!매수하기"]:
        # Flexible syntax: !매수 [종목] [수량/올인/빚올인] or !매수 [올인/수량] [종목] or !매수 올인
        if len(tokens) < 2:
            return GUIDE_BUY, None

        t1 = tokens[1].strip().strip("'\"`’‘“”,;[]()").strip()
        t2 = tokens[2].strip().strip("'\"`’‘“”,;[]()").strip() if len(tokens) >= 3 else ""

        # Check if t1 has attached all-in suffix (e.g. 10배올인, 10X올인, 10배풀매수, 10롱올인)
        for aiw in ["올인", "풀매수", "전액", "전액매수", "올인매수", "빚올인", "빚투", "전부", "다", "최대"]:
            if t1.endswith(aiw) and len(t1) > len(aiw):
                prod_part = t1[:-len(aiw)].strip()
                p_cand = parse_product_type(f"{prod_part}X" if prod_part in SUPPORTED_LEVERAGE_PREFIXES else prod_part)
                if p_cand:
                    t1 = p_cand.value
                    if not t2:
                        t2 = aiw
                    break

        p1 = parse_product_type(t1)
        p2 = parse_product_type(t2) if (t2 and not t2.isdigit()) else None

        allin_words = ["올인", "all", "전액", "풀매수", "다", "전부", "최대", "올인매수", "전액매수"]
        margin_words = ["빚올인", "빚으로올인", "대출올인", "신용올인", "빚투", "신용구매", "빚", "대출", "신용"]

        if p1:
            product_str = p1.value
            qty_str = t2 if t2 else "1"
        elif p2:
            product_str = p2.value
            qty_str = t1
        elif t1 in allin_words:
            product_str = "1X"
            qty_str = "올인"
        elif t1 in margin_words:
            product_str = "1X"
            qty_str = "빚올인"
        elif t1 in SUPPORTED_LEVERAGE_PREFIXES:
            product_str = f"{t1}X"
            qty_str = t2 if t2 else "1"
        else:
            product_str = t1
            qty_str = t2 if t2 else "1"

        if qty_str in margin_words:
            success, reply, details = execute_margin_buy(db, user_id, username, product_str, "올인")
        elif qty_str in allin_words:
            success, reply, details = execute_buy(db, user_id, username, product_str, "올인")
        else:
            success, reply, details = execute_buy(db, user_id, username, product_str, qty_str)

        event = {"type": "trade_buy", "data": details} if success and details else None
        return reply, event

    # 4-2. Direct Margin Buy / 빚투 / 빚올인
    if cmd in ["!빚올인", "!빚으로올인", "!빚투", "!신용매수", "!대출매수", "!마진매수", "!빚매수", "!신용구매"]:
        product_str = None
        qty_str = "올인"
        for t in tokens[1:]:
            clean_t = t.strip().strip("'\"`’‘“”,;[]()").strip()
            parsed_prod = parse_product_type(clean_t)
            if parsed_prod:
                product_str = parsed_prod.value
            elif clean_t in SUPPORTED_LEVERAGE_PREFIXES:
                product_str = f"{clean_t}X"
            elif clean_t not in ["올인", "all", "전액", "빚올인", "신용"]:
                qty_str = clean_t
        if not product_str:
            product_str = "1X"
        success, reply, details = execute_margin_buy(db, user_id, username, product_str, qty_str)
        event = {"type": "trade_buy", "data": details} if success and details else None
        return reply, event

    # 4-3. 빚으로 / 빚내서
    if cmd in ["!빚으로", "!빚내서"]:
        product_str = None
        for t in tokens[1:]:
            clean_t = t.strip().strip("'\"`’‘“”,;[]()").strip()
            p = parse_product_type(clean_t)
            if p:
                product_str = p.value
                break
            elif clean_t in SUPPORTED_LEVERAGE_PREFIXES:
                product_str = f"{clean_t}X"
                break
        if not product_str:
            product_str = "1X"
        success, reply, details = execute_margin_buy(db, user_id, username, product_str, "올인")
        event = {"type": "trade_buy", "data": details} if success and details else None
        return reply, event

    # 5. Market Sell Order
    if cmd in ["!매도", "!팔기", "!sell", "!판매", "!판매하기", "!매도하기", "!전량매도", "!풀매도", "!완판"]:
        all_sell_words = ["전량", "all", "모두", "올인", "전부", "다", "최대", "풀매도", "전액"]
        if cmd in ["!전량매도", "!풀매도", "!완판"]:
            raw_p = tokens[1].strip().strip("'\"`’‘“”,;[]()").strip() if len(tokens) >= 2 else "1X"
            parsed_p = parse_product_type(raw_p)
            if parsed_p:
                product_str = parsed_p.value
            elif raw_p in SUPPORTED_LEVERAGE_PREFIXES:
                product_str = f"{raw_p}X"
            else:
                product_str = raw_p
            qty_str = "전량"
        elif len(tokens) < 2:
            return GUIDE_SELL, None
        else:
            t1 = tokens[1].strip().strip("'\"`’‘“”,;[]()").strip()
            t2 = tokens[2].strip().strip("'\"`’‘“”,;[]()").strip() if len(tokens) >= 3 else ""
            p1 = parse_product_type(t1)
            p2 = parse_product_type(t2) if (t2 and not t2.isdigit()) else None
            if p1:
                product_str = p1.value
                qty_str = t2 if t2 else "전량"
            elif p2:
                product_str = p2.value
                qty_str = t1
            elif t1 in all_sell_words:
                product_str = "1X"
                qty_str = "전량"
            elif t1 in SUPPORTED_LEVERAGE_PREFIXES:
                product_str = f"{t1}X"
                qty_str = t2 if t2 else "전량"
            else:
                product_str = t1
                qty_str = t2 if t2 else "전량"

        if qty_str in all_sell_words:
            qty_str = "전량"

        success, reply, details = execute_sell(db, user_id, username, product_str, qty_str)
        event = {"type": "trade_sell", "data": details} if success and details else None
        return reply, event

    # 6. Limit Order
    if cmd in ["!지정가", "!예약", "!limit"]:
        # Expected syntax: !지정가 [매수/매도] [종목] [목표가] [수량]
        if len(tokens) < 5:
            return GUIDE_LIMIT, None
        order_type_str, product_str, target_price_str, qty_str = tokens[1], tokens[2], tokens[3], tokens[4]
        success, reply, details = register_limit_order(
            db, user_id, username, order_type_str, product_str, target_price_str, qty_str
        )
        event = {"type": "limit_order", "data": details} if success and details else None
        return reply, event

    # 7. Instant Liquidation / Closeout
    if cmd in ["!청산", "!정리", "!손절", "!익절"]:
        # Expected syntax: !청산 [종목/전량]
        if len(tokens) < 2:
            return GUIDE_LIQUIDATE, None
        target_str = tokens[1]
        success, reply, details = execute_liquidate(db, user_id, username, target_str)
        event = {"type": "liquidate_manual", "data": details} if success and details else None
        return reply, event

    # 8. Mining (Proof of Watch 채굴)
    if cmd in ["!채굴", "!출석", "!에어드랍", "!mine"]:
        success, reply, details = execute_mining(db, user_id, username)
        event = {"type": "mining", "data": details} if success and details else None
        return reply, event

    # 8-1. Mining Probability & Critical Guide
    if cmd in ["!채굴확률", "!채굴안내", "!채굴정보", "!광맥", "!채굴배율"]:
        return GUIDE_MINING, None

    # 8-1-1. Auto-Mining Controls (!자동채굴, !오토채굴, !오토, !automine)
    if cmd in ["!자동채굴", "!오토채굴", "!오토", "!automine", "!autonmine", "!오토마이닝"]:
        sub_arg = tokens[1].strip().lower() if len(tokens) >= 2 else ""
        if sub_arg in ["on", "켜기", "시작", "start", "enable", "가동"]:
            success, reply, details = set_auto_mining(db, user_id, username, enable=True)
            event = {"type": "auto_mining_toggle", "data": details} if success and details else None
            return reply, event
        elif sub_arg in ["off", "끄기", "중지", "종료", "stop", "disable", "정지"]:
            success, reply, details = set_auto_mining(db, user_id, username, enable=False)
            event = {"type": "auto_mining_toggle", "data": details} if success and details else None
            return reply, event
        elif sub_arg in ["갱신", "연장", "리셋", "renew", "reset", "재시작"]:
            success, reply, details = renew_auto_mining(db, user_id, username)
            event = {"type": "auto_mining_renew", "data": details} if success and details else None
            return reply, event
        else:
            return get_auto_mining_status(db, user_id, username), None

    # 8-2. Pickaxe / Equipment Status / Inventory / Spec (!상태창, !스테이터스, !곡괭이, !내장비, !인벤토리)
    if cmd in [
        "!상태창", "!스테이터스", "!스펙", "!status", "!spec", "!내스펙", "!상태",
        "!곡괭이", "!채굴기", "!장비", "!내곡괭이", "!내장비", "!인벤토리", "!인벤", "!pickaxe", "!inventory"
    ]:
        target_token = tokens[1] if len(tokens) >= 2 else None
        is_status_cmd = cmd in ["!상태창", "!스테이터스", "!스펙", "!status", "!spec", "!내스펙", "!상태"]
        is_inven_cmd = cmd in ["!내장비", "!인벤토리", "!인벤", "!inventory"]
        if is_inven_cmd and not target_token:
            return get_user_inventory_status(db, user_id, username), None
        return get_user_pickaxe_status(db, user_id, username, target_token, force_detail=is_status_cmd), None

    # 8-2b. Consumable Items Inventory (!아이템, !내아이템, !소비템, !가방, !소비, !items)
    if cmd in ["!아이템", "!내아이템", "!소비템", "!가방", "!소비", "!items"]:
        user = get_or_create_user(db, user_id, username)
        s_cnt = getattr(user, "shield_scroll_count", 0) or 0
        b_cnt = getattr(user, "boost_scroll_count", 0) or 0
        d_cnt = getattr(user, "downgrade_scroll_count", 0) or 0
        s100_cnt = getattr(user, "shield_100_scroll_count", 0) or 0
        d100_cnt = getattr(user, "downgrade_100_scroll_count", 0) or 0
        snipe_cnt = getattr(user, "snipe_scroll_count", 0) or 0
        c_cnt = getattr(user, "cube_count", 0) or 0
        f_cnt = getattr(user, "cube_fragments", 0) or 0
        m_state = get_merchant_state(db)
        m_status = "🛒 [신비상인 마을 체류중!]" if m_state.get("is_active") else "🔒 [신비상인 부재중]"

        abs_lines = []
        if s100_cnt > 0:
            abs_lines.append(f"• 🛡️✨ [100% 확정] 절대 파괴방어권: {s100_cnt:,}장 (15성+ 폭발 파괴 100% 완벽 방어)")
        if d100_cnt > 0:
            abs_lines.append(f"• 📉✨ [100% 확정] 절대 하강방지권: {d100_cnt:,}장 (강화 실패 시 등급 하락 100% 완벽 방어)")
        abs_block = ("\n" + "\n".join(abs_lines)) if abs_lines else ""

        special_scrolls = get_user_special_snipe_scrolls(user)
        special_lines = []
        special_names = {
            "DIVIDEND_BOOST_PCT": "📈 배당금 증폭 전용 저격주문서",
            "MINING_CD_RESET": "⚡ 쿨타임 초기화 전용 저격주문서",
            "STARFORCE_SUCCESS_BOOST": "⭐ 성공률 증가 전용 저격주문서",
            "GOBLIN_JACKPOT_CHANCE": "👹 황금 고블린 전용 저격주문서",
            "MINING_YIELD_BOOST": "⛏️ 채굴량 증폭 전용 저격주문서",
            "MINING_BONUS_CASH": "🪙 확정 현금 전용 저격주문서",
            "MAHJONG_TILE_BOOST": "🀄 마작 화료 전용 저격주문서",
            "HEAVY_MINING": "🌋 과충전 채굴 전용 저격주문서",
            "STARFORCE_DISCOUNT": "🔨 강화비 할인 전용 저격주문서",
        }
        for scode, scnt in special_scrolls.items():
            sname = special_names.get(scode, f"🎯 {scode} 전용 저격주문서")
            special_lines.append(f"• 🌟 {sname}: {scnt:,}장 (1줄 88% 확정급! 사용: !주문서 저격 {scode} / !주문서 전용 {scode})")
        sp_block = ("\n" + "\n".join(special_lines)) if special_lines else ""

        msg = (
            f"🎒 [{user.username}님의 소비 아이템 보따리]\n"
            f"• 🛡️ 파괴방어권: {s_cnt:,}장 (15성+ 실패 시 60% 확률로 파괴 방어 | 40% 뚫림 주의)\n"
            f"• ⚡ 강화확률상승권: {b_cnt:,}장 (스타포스 성공률 +10%p 보너스)\n"
            f"• 📉 하강방지권: {d_cnt:,}장 (강화 실패 시 70% 확률로 등급 하락 방어 | 30% 하강 주의){abs_block}\n"
            f"• 🎯 잠재저격주문서: {snipe_cnt:,}장 (!큐브 저격 [옵션] 사용 시 원하는 옵션 35% 저격 + 가중치 3.5배)\n"
            f"• 🔮 미라클 큐브: {c_cnt:,}개 (!큐브 [번호] 사용)\n"
            f"• 🧩 큐브 조각: {f_cnt:,}개 (10개당 15,000P 환급){sp_block}\n"
            f"💡 방어 안내: 일반 파방(60%) 및 하강방지권(70%)은 '확률'로 적용됩니다! (100% 무적 방어는 신비상인의 절대 주문서 필요)\n"
            f"💡 주문서 사용법: 강화 시 직접 지정하여 사용합니다. (예: !강화 파방, !강화 하강, !강화 절대파방, !강화 풀 | 상시 설정: !주문서)\n"
            f"💡 신비상인 구매: !상인구매 [1~7] [수량] ({m_status}) | 유저 거래소: !거래소, !아이템판매"
        )
        return msg, None

    # 8-3. Pickaxe Upgrade (!강화, !업그레이드 [장비번호/옵션])
    if cmd in ["!강화", "!업그레이드", "!곡괭이강화", "!곡괭이업그레이드", "!upgrade"]:
        target_token = None
        use_shield = None
        use_boost = None
        use_downgrade = None
        use_shield_100 = None
        use_downgrade_100 = None

        for tok in tokens[1:]:
            clean_tok = tok.strip().strip("'\"`’‘“”,;[]()").lower()
            if clean_tok in ["절대풀", "100풀", "절대풀장착", "절대올"]:
                use_shield_100 = True
                use_downgrade_100 = True
                use_boost = True
            elif clean_tok in ["풀", "풀주문서", "풀장착", "올", "all", "전부", "다"]:
                use_shield = True
                use_boost = True
                use_downgrade = True
            elif clean_tok in ["절대파방", "100파방", "절대파방권", "절대방어권", "shield100", "shield_100", "100파괴방어"]:
                use_shield_100 = True
            elif clean_tok in ["노절대파방", "노100파방", "절대파방off", "100파방off"]:
                use_shield_100 = False
            elif clean_tok in ["절대하강", "100하강", "절대하방", "100하방", "downgrade100", "downgrade_100", "100하방권"]:
                use_downgrade_100 = True
            elif clean_tok in ["노절대하강", "노100하강", "절대하강off", "100하강off"]:
                use_downgrade_100 = False
            elif clean_tok in ["파방", "파방권", "파괴방어", "파괴방어권", "방어권", "shield"]:
                use_shield = True
            elif clean_tok in ["노파방", "노실드", "noshield", "파방off"]:
                use_shield = False
            elif clean_tok in ["상승", "상승권", "확률상승", "확률상승권", "boost"]:
                use_boost = True
            elif clean_tok in ["노상승", "noboost", "상승off"]:
                use_boost = False
            elif clean_tok in ["하강", "하강방지", "하강권", "하강방지권", "방지권", "downgrade"]:
                use_downgrade = True
            elif clean_tok in ["노하강", "nodowngrade", "하강off"]:
                use_downgrade = False
            elif clean_tok.startswith("#") or clean_tok.isdigit() or clean_tok in ["현재", "기본", "장착", "equipped"]:
                target_token = clean_tok
            elif target_token is None:
                target_token = clean_tok

        success, reply, details = execute_pickaxe_upgrade(
            db, user_id, username, target_token,
            use_shield=use_shield, use_boost=use_boost, use_downgrade=use_downgrade,
            use_shield_100=use_shield_100, use_downgrade_100=use_downgrade_100
        )
        event = {"type": "pickaxe_upgrade", "data": details} if success and details else None
        return reply, event

    # 8-3-1. Designated Scroll Arming Setting & Snipe Scroll Rolling (!주문서, !주문서설정, !주문서장착, !주문서관리, !주문서사용)
    if cmd in ["!주문서", "!주문서설정", "!주문서장착", "!주문서관리", "!주문서사용"]:
        sub_tokens = tokens[1:]
        clean_args = [t.strip().strip("'\"`’‘“”,;[]()").lower() for t in sub_tokens if t.strip().lower() not in ["사용", "적용", "돌리기"]]

        if not clean_args:
            success, reply, details = toggle_user_scroll_arm(db, user_id, username, None, None)
            return reply, None

        # Check if user is asking for snipe options list/guide e.g. !주문서 저격목록, !주문서 저격 옵션, !주문서 목록, !주문서 옵션, !주문서 도감
        if any(a in ["저격목록", "저격옵션", "저격리스트", "옵션목록", "잠재목록", "잠재옵션", "저격도감", "잠재도감"] for a in clean_args) or (
            any(a in ["저격", "잠재저격", "snipe", "잠재"] for a in clean_args) and any(a in ["목록", "리스트", "옵션", "가이드", "도감", "설명", "list", "options", "help", "도움말"] for a in clean_args)
        ):
            return te.get_snipe_options_guide_text(), None

        # Check for ON / OFF toggle tokens
        on_off_tokens = [a for a in clean_args if a in ["on", "off", "켜기", "끄기", "활성", "비활성", "true", "false", "start", "stop"]]
        non_on_off = [a for a in clean_args if a not in ["on", "off", "켜기", "끄기", "활성", "비활성", "true", "false", "start", "stop"]]

        # 1. Any command containing ON/OFF is 100% a TOGGLE setting - NEVER CUBE USE!
        if on_off_tokens:
            on_off_val = on_off_tokens[0]
            scroll_type_val = non_on_off[0] if non_on_off else "전체"
            success, reply, details = toggle_user_scroll_arm(db, user_id, username, scroll_type_val, on_off_val)
            return reply, None

        # 2. Direct Snipe Scroll Cube Use: ONLY when user explicitly asks for snipe cube rolling (!주문서사용 or contains 저격)
        is_snipe_use = (cmd == "!주문서사용") or any(a in ["저격", "잠재저격", "snipe", "저격주문서"] for a in clean_args)
        if is_snipe_use:
            target_item_token = None
            keyword_tokens = []
            for a in clean_args:
                if a in ["저격", "잠재저격", "snipe", "저격주문서", "4"]:
                    continue
                elif a.startswith("#") or (a.isdigit() and int(a) > 4):
                    target_item_token = a
                else:
                    keyword_tokens.append(a)

            keyword_str = " ".join(keyword_tokens) if keyword_tokens else None
            if keyword_str and keyword_str.strip().lower() in ["목록", "리스트", "옵션", "가이드", "도감", "설명", "list", "options", "help", "도움말"]:
                return te.get_snipe_options_guide_text(), None

            if not keyword_str:
                # No target keyword specified, show snipe scroll guide
                success, reply, details = toggle_user_scroll_arm(db, user_id, username, "저격", None)
                return reply, None

            success, reply, details = execute_cube_use(
                db, user_id, username,
                item_id_or_index=target_item_token,
                target_keyword=keyword_str,
                use_snipe=True
            )
            event = {"type": "cube_use", "data": details} if success and details else None
            return reply, event

        # 3. Simple toggle by scroll type name alone (e.g. !주문서 상승, !주문서 강화, !주문서 2, !주문서 파방, !주문서 전체)
        scroll_arg = clean_args[0] if len(clean_args) >= 1 else None
        state_arg = clean_args[1] if len(clean_args) >= 2 else None
        success, reply, details = toggle_user_scroll_arm(db, user_id, username, scroll_arg, state_arg)
        return reply, None

    # 8-3-2. Potential Snipe Scroll Options Guide (!저격목록, !저격옵션, !저격리스트, !옵션목록, !잠재목록, !잠재옵션, !저격가이드, !저격도감, !잠재도감)
    if cmd in ["!저격목록", "!저격옵션", "!저격리스트", "!옵션목록", "!잠재목록", "!잠재옵션", "!저격가이드", "!저격도감", "!잠재도감"]:
        return te.get_snipe_options_guide_text(), None

    # 8-4. Pickaxe Tier Guide (!강화표, !곡괭이목록)
    if cmd in ["!곡괭이목록", "!곡괭이표", "!강화표", "!강화목록"]:
        return get_pickaxe_table_guide(), None

    # 8-5. Store Buy Equipment (!곡괭이구매, !새장비, !장비상점)
    if cmd in ["!곡괭이구매", "!새장비", "!장비상점", "!장비상점구매"]:
        tier_str = tokens[1] if len(tokens) >= 2 else "0"
        success, reply, details = execute_buy_equipment(db, user_id, username, tier_str)
        event = {"type": "equipment_buy", "data": details} if success and details else None
        return reply, event

    # 8-6. Equip Item (!장착, !장비장착, !장비교체)
    if cmd in ["!장착", "!장비장착", "!장비교체", "!equip"]:
        if len(tokens) < 2:
            return "⛏️ [장비 장착] 사용법: !장착 [장비번호] (예: !장착 2, !장비장착 3 | 내 장비 번호 확인: !내장비)", None
        success, reply, details = execute_equip_item(db, user_id, username, tokens[1])
        event = {"type": "equipment_equip", "data": details} if success and details else None
        return reply, event

    # 8-7. Unified Marketplace & Consumable Item Trade (!거래소, !아이템판매, !거래소구매, !거래소취소)
    if cmd in ["!거래소", "!통합거래소", "!마켓", "!시장"]:
        return get_unified_market_listings(db), None

    if cmd in ["!아이템판매", "!아이템등록", "!아이템제안", "!주문서판매"]:
        if len(tokens) < 4:
            return (
                "🏪 [거래소 아이템 판매 등록]\n"
                "• 사용법: !아이템판매 [파방/하강/상승/큐브] [수량] [가격] [구매자(선택)]\n"
                "(예: !아이템판매 파방 1 350000 | 직거래: !아이템판매 파방 1 300000 치즈나베)\n"
                "• 거래 성사 시 5% 수수료가 국고로 환원됩니다."
            ), None
        item_tok = tokens[1]
        qty_tok = tokens[2]
        price_tok = tokens[3]
        buyer_tok = tokens[4] if len(tokens) >= 5 else None
        success, reply, details = execute_list_item(db, user_id, username, item_tok, qty_tok, price_tok, buyer_tok)
        event = {"type": "item_list", "data": details} if success and details else None
        return reply, event

    if cmd in ["!거래소구매", "!마켓구매"]:
        if len(tokens) < 2:
            return "🏪 [거래소 구매] 사용법: !거래소구매 [거래번호] (예: !거래소구매 I1 또는 !거래소구매 E1 | 거래소 목록: !거래소)", None
        success, reply, details = execute_buy_exchange(db, user_id, username, tokens[1])
        event = {"type": "exchange_trade", "data": details} if success and details else None
        return reply, event

    if cmd in ["!거래소취소", "!거래소회수", "!마켓취소"]:
        if len(tokens) < 2:
            return "📦 [거래소 등록 취소] 사용법: !거래소취소 [거래번호] (예: !거래소취소 I1 또는 !거래소취소 E1)", None
        success, reply, details = execute_cancel_exchange(db, user_id, username, tokens[1])
        return reply, None

    # 8-8. Equipment P2P Trade / Market Listing (!장비판매, !장비제안, !직거래, !장비등록)
    if cmd in ["!장비판매", "!장비제안", "!직거래", "!장비등록"]:
        if cmd == "!장비등록":
            if len(tokens) < 3:
                return "🏪 [장비 거래소 등록] 사용법: !장비등록 [내장비번호] [가격] (예: !장비등록 2 50000 | 5% 수수료 국고 환원)", None
            success, reply, details = execute_list_equipment(db, user_id, username, tokens[1], tokens[2], None)
        else:
            if len(tokens) >= 4:
                # Direct trade to buyer: !장비판매 [구매자] [장비번호] [가격]
                success, reply, details = execute_list_equipment(db, user_id, username, tokens[2], tokens[3], tokens[1])
            elif len(tokens) == 3:
                # Public listing: !장비판매 [장비번호] [가격]
                success, reply, details = execute_list_equipment(db, user_id, username, tokens[1], tokens[2], None)
            else:
                return "🤝 [장비 판매] 사용법: !장비판매 [구매자닉네임] [내장비번호] [가격] 또는 !장비등록 [내장비번호] [가격] (수수료 5% 국고 환원)", None
        event = {"type": "equipment_list", "data": details} if success and details else None
        return reply, event

    # 8-9. Equipment Marketplace View (!장비장터, !장비거래소, !장비마켓, !장터)
    if cmd in ["!장비장터", "!장비거래소", "!장비마켓", "!장터"]:
        return get_equipment_market_listings(db), None

    # 8-10. Equipment Buy / Accept Trade (!장비구매, !장비수락, !장터구매)
    if cmd in ["!장비구매", "!장비수락", "!장터구매"]:
        if len(tokens) < 2:
            return "🏪 [장비 구매] 사용법: !장비구매 [거래번호] (장터 매물 확인: !장비장터 | 상점 새 곡괭이는 !곡괭이구매 [종류])", None
        arg = tokens[1]
        if arg in ["나무", "돌", "철", "wood", "stone", "iron", "기본", "상점"]:
            success, reply, details = execute_buy_equipment(db, user_id, username, arg)
            event = {"type": "equipment_buy", "data": details} if success and details else None
            return reply, event
        success, reply, details = execute_buy_equipment_listing(db, user_id, username, arg)
        event = {"type": "equipment_trade", "data": details} if success and details else None
        return reply, event

    # 8-11. Cancel Market Listing (!장비회수, !장비등록취소, !장비취소)
    if cmd in ["!장비회수", "!장비등록취소", "!장비취소"]:
        if len(tokens) < 2:
            return "📦 [장비 등록 취소] 사용법: !장비회수 [거래번호] (예: !장비회수 1)", None
        success, reply, details = execute_cancel_equipment_listing(db, user_id, username, tokens[1])
        return reply, None

    # 8-11. Star Force Fever Event Query & Streamer Controls (!피버, !스타포스이벤트, !샤이닝, !피버오픈, !피버마감)
    if cmd in ["!피버", "!스타포스이벤트", "!샤이닝", "!피버이벤트", "!피버타임", "!피버오픈", "!피버열기", "!피버시작", "!피버마감", "!피버종료", "!피버닫기"]:
        is_streamer = (user_id == CHANNEL_ID or username in ["치즈나베", "스트리머"] or user_id in ["streamer", "admin"])

        # Streamer Close Event
        if cmd in ["!피버마감", "!피버종료", "!피버닫기"]:
            if not is_streamer:
                return "🚫 피버 이벤트 마감은 스트리머(치즈나베)만 진행할 수 있습니다!", None
            success, reply, details = close_starforce_event(db)
            event = {"type": "starforce_fever_close", "data": details} if success and details else None
            return reply, event

        # Check if this is an open command or !피버 with arguments
        is_open_cmd = cmd in ["!피버오픈", "!피버열기", "!피버시작"] or (cmd in ["!피버", "!샤이닝"] and len(tokens) >= 2)

        if is_open_cmd:
            if not is_streamer:
                return "🚫 피버 이벤트 강제 개장은 스트리머(치즈나베)만 진행할 수 있습니다! (피버는 정해진 주기마다 자동으로도 발동됩니다)", None

            dur = 10.0
            ev_type_arg = "SHINING"
            for tok in tokens[1:]:
                clean_tok = tok.replace("분", "").strip()
                if clean_tok.replace(".", "", 1).isdigit():
                    dur = float(clean_tok)
                elif any(k in tok for k in ["할인", "30", "discount", "세일"]):
                    ev_type_arg = "DISCOUNT_30"
                elif any(k in tok for k in ["100", "확정", "fever", "성공"]):
                    ev_type_arg = "FEVER_100"
                elif any(k in tok for k in ["샤이닝", "shining", "슈퍼", "all"]):
                    ev_type_arg = "SHINING"

            success, reply, details = open_starforce_event(db, duration_minutes=dur, event_type_str=ev_type_arg)
            event = {"type": "starforce_fever_open", "data": details} if success and details else None
            return reply, event

        # General viewer query
        return get_starforce_event_guide(db), None

    # 8-11. Maple Cube Purchase (!큐브구매, !큐브사기, !buycube, !cube구매)
    if cmd in ["!큐브구매", "!큐브사기", "!buycube", "!cube구매", "!큐브구입", "!미라클큐브구매"]:
        qty_token = tokens[1] if len(tokens) >= 2 else "1"
        success, reply, details = execute_buy_cubes(db, user_id, username, qty_token)
        event = {"type": "cube_buy", "data": details} if success and details else None
        return reply, event

    # 8-12. Maple Cube Potential Reset (!큐브, !cube, !미라클큐브, !블랙큐브, !잠재, !잠재능력)
    if cmd in ["!큐브", "!cube", "!미라클큐브", "!블랙큐브", "!잠재", "!잠재능력", "!큐브사용"]:
        # Check if user is asking for snipe options list e.g. !큐브 옵션, !큐브 저격목록, !큐브 저격 옵션, !큐브 도감
        for tok in tokens[1:]:
            clean = tok.strip().strip("'\"`’‘“”,;[]()").lower()
            if clean in ["저격목록", "저격옵션", "저격리스트", "옵션목록", "잠재목록", "잠재옵션", "옵션도감", "저격도감"]:
                return te.get_snipe_options_guide_text(), None

        target_token = None
        target_keyword = None
        use_snipe = False
        lock_lines = []

        skip_indices = set()
        for idx_t, tok in enumerate(tokens[1:], start=1):
            if idx_t in skip_indices:
                continue
            clean = tok.strip().strip("'\"`’‘“”,;[]()").lower()
            if clean in ["저격", "저격권", "snipe", "target"]:
                use_snipe = True
            elif "잠금" in clean or "lock" in clean:
                for c in ["1", "2", "3"]:
                    if c in clean:
                        lock_lines.append(int(c))
                # Check next tokens for numbers
                for next_idx in range(idx_t + 1, len(tokens)):
                    nxt = tokens[next_idx].strip().strip("'\"`’‘“”,;[]()").lower()
                    if nxt in ["1", "2", "3", "1줄", "2줄", "3줄"]:
                        lock_lines.append(int(nxt[0]))
                        skip_indices.add(next_idx)
                    else:
                        break
            elif clean.startswith("#") or clean.isdigit() or clean in ["현재", "기본", "장착", "equipped"]:
                target_token = clean
            else:
                target_keyword = clean

        if target_keyword:
            if target_keyword in ["목록", "리스트", "옵션", "가이드", "도감", "설명", "list", "options", "help", "도움말"]:
                return te.get_snipe_options_guide_text(), None
            use_snipe = True

        lock_lines = sorted(list(set(lock_lines))) if lock_lines else None

        success, reply, details = execute_cube_use(
            db, user_id, username, target_token,
            target_keyword=target_keyword, use_snipe=use_snipe,
            lock_lines=lock_lines
        )
        event = {"type": "cube_use", "data": details} if success and details else None
        return reply, event

    # 8-13. Cube Fragment Exchange (!큐브조각, !큐브조각교환, !조각교환, !조각)
    if cmd in ["!큐브조각", "!큐브조각교환", "!조각교환", "!조각"]:
        success, reply, details = execute_cube_fragment_exchange(db, user_id, username)
        event = {"type": "cube_fragment_exchange", "data": details} if success and details else None
        return reply, event

    # 8-14. Equipment Cube Lock (!큐브잠금, !장비잠금, !큐브락, !cubelock, !큐브보호, !장비보호, !큐브해제, !큐브잠금해제)
    if cmd in ["!큐브잠금", "!장비잠금", "!큐브락", "!cubelock", "!큐브보호", "!장비보호", "!큐브해제", "!큐브잠금해제"]:
        state_str = None
        target_eq = None
        if cmd in ["!큐브해제", "!큐브잠금해제"]:
            state_str = "off"
            if len(tokens) > 1:
                target_eq = tokens[1]
        else:
            if len(tokens) == 2:
                if tokens[1].lower() in ["on", "off", "켜기", "끄기", "해제", "잠금", "설정"]:
                    state_str = tokens[1]
                else:
                    target_eq = tokens[1]
            elif len(tokens) >= 3:
                target_eq = tokens[1]
                state_str = tokens[2]

        success, reply, details = execute_equipment_cube_lock(db, user_id, username, target_eq, state_str)
        event = {"type": "cube_lock", "data": details} if success and details else None
        return reply, event

    # 8-15. Potential Line Lock (!옵션잠금, !잠재잠금, !라인잠금, !줄잠금, !옵션락, !잠재락)
    if cmd in ["!옵션잠금", "!잠재잠금", "!라인잠금", "!줄잠금", "!옵션락", "!잠재락"]:
        line_arg = None
        state_str = None
        target_eq = None
        if len(tokens) >= 2:
            line_arg = tokens[1]
        if len(tokens) >= 3:
            state_str = tokens[2]
        if len(tokens) >= 4:
            target_eq = tokens[3]

        success, reply, details = execute_potential_line_lock(db, user_id, username, line_arg, state_str, target_eq)
        event = {"type": "potential_line_lock", "data": details} if success and details else None
        return reply, event

    # 9. Treasury Info Query
    if cmd in ["!국고", "!풀", "!채굴풀"]:
        info = get_treasury_info(db)
        pool = int(info["treasury_pool"])
        reply = (
            f"🏛️ [마작 국고 현황] 채굴 풀: {pool:,}P | "
            f"거래 수수료: 1% 국고 자동 적립 | 국고 기부: !기부 [금액] (신용점수/칭호 부여) | 채굴: !채굴 (15분 쿨)"
        )
        return reply, None

    # 9-1. Voluntary Treasury Donation (!기부, !국고기부, !후원)
    if cmd in ["!기부", "!국고기부", "!후원", "!기부하기", "!국고후원"]:
        amount_str = tokens[1] if len(tokens) >= 2 else ""
        success, reply, details = execute_treasury_donate(db, user_id, username, amount_str)
        event = {"type": "treasury_donation", "data": details} if success and details else None
        return reply, event

    # 10. Dividend Policy Query
    if cmd in ["!배당", "!배당금"]:
        reply = (
            "🎁 [승리 배당 안내] 1X(기본주) 보유 시 스트리머가 1위를 달성할 때마다 "
            "보유 평가액의 5%가 현금 배당으로 즉시 지급됩니다! (2위: 1%, 3위: 무배당)"
        )
        return reply, None

    # 10-1. Credit Rating & Loan Limit Query (신용등급 / 신용점수 / 대출한도 조회)
    if cmd in ["!신용등급", "!신용", "!신용도", "!신용점수", "!대출한도", "!한도", "!credit"]:
        user = get_or_create_user(db, user_id, username)
        report = format_user_credit_report(user, db)
        return report, None

    # 11. Margin Loan (Borrow from Treasury)
    if cmd in ["!대출", "!빚", "!사채", "!borrow", "!loan", "!빌리기", "!차용"]:
        user = get_or_create_user(db, user_id, username)
        if len(tokens) < 2:
            credit_info = get_user_credit_info(user, db=db)
            current_debt = getattr(user, "debt", 0) or 0
            limit = credit_info["loan_limit"]
            avail = max(0, limit - current_debt)
            return f"{GUIDE_BORROW} (신용: {credit_info['tier_name']} | 현재 빚: {current_debt:,}P | 추가 가능 한도: {avail:,}P | 금리: {credit_info['interest_rate_pct']:.1f}%)", None

        # Check if user typed '!대출 10X 올인' or '!대출 올인 10X' or '!빚 10X 올인' -> route to margin buy
        if len(tokens) >= 3:
            p1 = parse_product_type(tokens[1])
            p2 = parse_product_type(tokens[2])
            if p1 and tokens[2] in ["올인", "all", "전액", "최대", "빚올인"]:
                success, reply, details = execute_margin_buy(db, user_id, username, tokens[1], "올인")
                event = {"type": "trade_buy", "data": details} if success and details else None
                return reply, event
            elif p2 and tokens[1] in ["올인", "all", "전액", "최대", "빚올인"]:
                success, reply, details = execute_margin_buy(db, user_id, username, tokens[2], "올인")
                event = {"type": "trade_buy", "data": details} if success and details else None
                return reply, event

        amt_str = tokens[1]
        success, reply, details = execute_borrow(db, user_id, username, amt_str)
        event = {"type": "loan_borrow", "data": details} if success and details else None
        return reply, event

    # 12. Loan Repay
    if cmd in ["!상환", "!빚갚기", "!갚기", "!repay"]:
        amt_str = tokens[1] if len(tokens) >= 2 else "전액"
        success, reply, details = execute_repay(db, user_id, username, amt_str)
        event = {"type": "loan_repay", "data": details} if success and details else None
        return reply, event

    # 12-1. Account Transfer / Wire Transfer (계좌이체 / 송금)
    if cmd in ["!송금", "!이체", "!보내기", "!전송", "!transfer", "!send"]:
        if len(tokens) < 3:
            return GUIDE_TRANSFER, None

        allin_words = ["올인", "all", "전액", "전부", "다", "최대"]

        def is_amount(s: str) -> bool:
            clean = s.strip().lower().replace(",", "").replace("p", "").replace("원", "")
            if clean in allin_words:
                return True
            return parse_korean_amount(s) is not None

        t1 = tokens[1].strip()
        t_last = tokens[-1].strip()

        # Check if first argument is amount (e.g. !송금 10000 치즈나베, !송금 5만 @CYTFT, !송금 올인 철수)
        if is_amount(t1) and not is_amount(t_last):
            amt_str = t1
            target_str = " ".join(tokens[2:])
        else:
            # Standard order: !송금 [닉네임] [금액] (e.g. !송금 치즈나베 10000, !이체 @치즈나베 5만)
            amt_str = t_last
            target_str = " ".join(tokens[1:-1])

        success, reply, details = execute_transfer(db, user_id, username, target_str, amt_str)
        event = {"type": "account_transfer", "data": details} if success and details else None
        return reply, event

    # 12-2. Central Bank (치즈나베 중앙은행)
    if cmd in ["!은행", "!중앙은행", "!bank"]:
        user = get_or_create_user(db, user_id, username)
        info = te.get_user_bank_info(db, user)
        sav = info.get("savings")
        sav_str = f"{sav['per_round']:,}P ({sav['current_rounds']}/{sav['target_rounds']}회 | 누적: {sav['total_deposited']:,}P | 만기예상: {sav['estimated_payout']:,}P)" if sav else "미가입 (!적금 [회당금액])"
        fund = info.get("fund", {})
        fund_str = f"{fund.get('units', 0):,.4f}좌 (평가: {fund.get('valuation', 0):,}P | 수익률: {fund.get('pnl_pct', 0.0):+.2f}%)" if fund.get("units", 0) > 0 else "미보유 (!펀드매수 [금액])"
        ins = info.get("insurance")
        sav_str = f"{sav.get('plan_name', '정기적금')} ({sav.get('current_rounds', 0)}/{sav.get('target_rounds', 5)}회 | {sav.get('total_deposited', 0):,}P 적립)" if sav else "미가입 (!적금 [금액] [판수])"
        ins_str = f"{ins.get('plan_name', '파괴보험')} ({ins.get('matches_left', 0)}경기 남음 | 보장: {ins.get('coverage_amount', 1000000):,}P)" if ins and ins.get("active") else "미가입 (!보험 가입 [플랜])"
        fund_tot = info.get("total_fund_valuation", 0)
        fund_str = f"{fund_tot:,}P 보유 (4대 펀드 포트폴리오 | !펀드)" if fund_tot > 0 else "미보유 (!펀드, !펀드매수)"

        report = (
            f"🏛️ [치즈나베 중앙은행] {user.username}님의 종합 금융 계좌\n"
            f"• 보통예금 잔액: {info['bank_balance']:,}P (경기당 +0.5% 복리 이자 지급 | !입금, !출금)\n"
            f"• 정기적금: {sav_str}\n"
            f"• 마작 지수 펀드: {fund_str}\n"
            f"• 스타포스 파괴보험: {ins_str}\n"
            f"• 신용 등급: {info['credit']['tier_name']} (대출 한도: {info['credit']['loan_limit']:,}P | 현재 빚: {info['debt']:,}P | !대출, !상환)\n"
            f"• 보유 현금: {user.points:,}P"
        )
        return report, None

    if cmd in ["!입금", "!예금", "!deposit"]:
        if len(tokens) < 2:
            return "💡 [보통예금 입금 사용법] !입금 [금액/올인] (예: !입금 50000, !입금 올인 | 경기 종료마다 +0.5% 복리 이자)", None
        success, reply, details = te.execute_bank_deposit(db, user_id, username, tokens[1])
        event = {"type": "bank_deposit", "data": details} if success and details else None
        return reply, event

    if cmd in ["!출금", "!인출", "!withdraw"]:
        if len(tokens) < 2:
            return "💡 [보통예금 출금 사용법] !출금 [금액/전액] (예: !출금 50000, !출금 전액)", None
        success, reply, details = te.execute_bank_withdraw(db, user_id, username, tokens[1])
        event = {"type": "bank_withdraw", "data": details} if success and details else None
        return reply, event

    if cmd in ["!적금", "!정기적금", "!적금가입", "!적금해지"]:
        if cmd == "!적금해지" or (len(tokens) > 1 and tokens[1] in ["해지", "취소", "중도해지"]):
            success, reply, details = te.execute_cancel_savings(db, user_id, username)
            event = {"type": "bank_savings_cancel", "data": details} if success and details else None
            return reply, event
        if len(tokens) < 2:
            return (
                "💡 [치즈나베 정기적금 4종 상품 안내]\n"
                "1️⃣ ⚡ 스피드 단기 적금 (3경기 | 만기 +10% 보너스 | 회당 5,000P~100만P)\n"
                "2️⃣ 🪙 나베 정기 적금 (5경기 | 만기 +20% 보너스 | 회당 5,000P~200만P)\n"
                "3️⃣ 🐋 고래 장기 적금 (10경기 | 만기 +35% 보너스 | 회당 1만P~500만P)\n"
                "4️⃣ 👑 슈퍼 연금 적금 (20경기 | 만기 +60% 보너스 | 회당 2만P~1,000만P)\n"
                "• 가입 문법: !적금 [회당금액] [판수/상품명] (예: !적금 10000 3, !적금 50000 5, !적금 100000 고래, !적금 해지)"
            ), None
        per_amt = tokens[1]
        rounds_val = tokens[2] if len(tokens) > 2 else "5"
        success, reply, details = te.execute_open_savings(db, user_id, username, per_amt, rounds_val)
        event = {"type": "bank_savings_open", "data": details} if success and details else None
        return reply, event

    if cmd in ["!펀드", "!마작펀드", "!펀드매수", "!펀드환매"]:
        if cmd == "!펀드매수" or (len(tokens) > 1 and tokens[1] in ["매수", "구매", "투자"]):
            amt_str = "올인"
            f_key = "index"
            if cmd == "!펀드매수":
                amt_str = tokens[1] if len(tokens) > 1 else "올인"
                f_key = tokens[2] if len(tokens) > 2 else "index"
            else:
                amt_str = tokens[2] if len(tokens) > 2 else "올인"
                f_key = tokens[3] if len(tokens) > 3 else "index"
            success, reply, details = te.execute_buy_fund(db, user_id, username, amt_str, f_key)
            event = {"type": "bank_fund_buy", "data": details} if success and details else None
            return reply, event
        if cmd == "!펀드환매" or (len(tokens) > 1 and tokens[1] in ["환매", "매도", "판매"]):
            u_str = "전부"
            f_key = "index"
            if cmd == "!펀드환매":
                u_str = tokens[1] if len(tokens) > 1 else "전부"
                f_key = tokens[2] if len(tokens) > 2 else "index"
            else:
                u_str = tokens[2] if len(tokens) > 2 else "전부"
                f_key = tokens[3] if len(tokens) > 3 else "index"
            success, reply, details = te.execute_sell_fund(db, user_id, username, u_str, f_key)
            event = {"type": "bank_fund_sell", "data": details} if success and details else None
            return reply, event
        user = get_or_create_user(db, user_id, username)
        info = te.get_user_bank_info(db, user)
        funds_p = info.get("funds", {})

        lines = ["🏛️📊 [치즈나베 중앙은행 4대 다각화 펀드 현황]"]
        lines.append("💡 초보 가이드: 주식 직접 매매가 두렵다면 금융 바구니에 맡기세요!")
        for fid, fdef in te.DIVERSIFIED_FUNDS.items():
            f_data = funds_p.get(fid, {})
            u_units = f_data.get("units", 0.0)
            u_val = f_data.get("valuation", 0)
            u_pnl_pct = f_data.get("pnl_pct", 0.0)
            hold_str = f"보유: {u_units:,.4f}좌 ({u_val:,}P | {u_pnl_pct:+.2f}%)" if u_units > 0 else "미보유"
            lines.append(f"• [{fdef['name']}] NAV: {f_data.get('nav', 1000.0):,.2f}P ({fdef['risk_stars']}) | {hold_str}")
        lines.append("💬 투자 문법: !펀드매수 [금액] [지수/배당/야수/인프라], !펀드환매 [좌수/전부] [펀드명]")
        return "\n".join(lines), None

    if cmd in ["!보험", "!파괴보험", "!보험가입", "!안심보험"]:
        if len(tokens) > 1 and tokens[1] in ["가입", "신청", "구매"]:
            plan_arg = tokens[2] if len(tokens) > 2 else "standard"
            success, reply, details = te.execute_buy_insurance(db, user_id, username, plan_arg)
            event = {"type": "bank_insurance_buy", "data": details} if success and details else None
            return reply, event
        user = get_or_create_user(db, user_id, username)
        b_data = te.get_user_bank_data(user)
        ins = b_data.get("insurance")
        if ins and ins.get("active"):
            return (
                f"🏥🛡️ [{ins.get('plan_name', '스타포스 안심 파괴 보험')} 가입 중]\n"
                f"• 보장 상태: 유효 (잔여 {ins.get('matches_left', 0)}경기 동안 보장)\n"
                f"• 보장 혜택: 15성 이상 스타포스 실패로 파괴 시 보통예금으로 {ins.get('coverage_amount', 1000000):,}P 즉시 지급!\n"
                f"• 남은 보상 청구 가능 횟수: {ins.get('claims_left', 1)}회"
            ), None
        lines = [
            "🏥🛡️ [스타포스 안심 파괴 보험 등급별 상품 안내] (5경기 유효)",
            "1️⃣ 🛡️ 실속형: 보험료 30,000P ➔ 파괴 시 위로금 500,000P 지급",
            "2️⃣ 🛡️ 표준형: 보험료 50,000P ➔ 파괴 시 위로금 1,000,000P 지급",
            "3️⃣ 🛡️ 프리미엄: 보험료 120,000P ➔ 파괴 시 위로금 3,000,000P 지급",
            "4️⃣ 🛡️ VVIP 종결형: 보험료 350,000P ➔ 파괴 시 위로금 10,000,000P 지급",
            "💬 가입 문법: !보험 가입 [실속/표준/프리미엄/VVIP] (예: !보험 가입 표준, !보험 가입 vvip)"
        ]
        return "\n".join(lines), None

    # 13. Bankruptcy / Rehabilitation (Na-bae Judge's Court)
    if cmd in ["!파산신청", "!개인회생", "!파산", "!회생", "!회생신청", "!개인파산", "!회생신청서", "!파산신청서", "!워크아웃", "!구제", "!구제신청"]:
        reason = " ".join(tokens[1:]) if len(tokens) > 1 else ""
        success, reply, details = submit_bankruptcy_application(db, user_id, username, reason)
        event = {"type": "bankruptcy_requested", "data": details} if success and details else None
        return reply, event

    # 14. Streamer Casino Open / Close Controls
    if cmd in ["!카지노오픈", "!도박오픈", "!카지노열기", "!도박열기"]:
        is_streamer = (user_id == CHANNEL_ID or username in ["치즈나베", "스트리머"] or user_id in ["streamer", "admin"])
        if not is_streamer:
            return "🚫 카지노 개장은 스트리머(치즈나베)만 진행할 수 있습니다!", None
        duration = 3.0
        max_bet = DEFAULT_CASINO_MAX_BET
        for token in tokens[1:]:
            clean_tok = token.replace(",", "").strip()
            if clean_tok.endswith("만"):
                try:
                    val = float(clean_tok[:-1])
                    max_bet = int(val * 10000)
                    continue
                except ValueError:
                    pass
            if clean_tok.endswith("분"):
                try:
                    duration = float(clean_tok[:-1])
                    continue
                except ValueError:
                    pass
            if clean_tok.replace(".", "", 1).isdigit():
                num = float(clean_tok)
                if num >= 1000:
                    max_bet = int(num)
                else:
                    duration = num
        max_bet = max(MIN_CASINO_BET, max_bet)
        success, reply, details = open_casino(db, duration_minutes=duration, max_bet=max_bet)
        event = {"type": "casino_open", "data": details} if success and details else None
        return reply, event

    if cmd in ["!카지노마감", "!도박마감", "!카지노닫기", "!도박닫기", "!카지노종료", "!도박종료"]:
        is_streamer = (user_id == CHANNEL_ID or username in ["치즈나베", "스트리머"] or user_id in ["streamer", "admin"])
        if not is_streamer:
            return "🚫 카지노 마감은 스트리머(치즈나베)만 진행할 수 있습니다!", None
        success, reply, details = close_casino(db)
        event = {"type": "casino_close", "data": details} if success and details else None
        return reply, event

    # 15. Casino Status Query
    if cmd in ["!카지노", "!도박장"]:
        c_state = get_casino_state(db)
        t_info = get_treasury_info(db)
        pool = int(t_info["treasury_pool"])
        if not c_state["is_open"]:
            return f"🎰 [나베 국고 카지노: 마감] 현재 도박장이 닫혀 있습니다. (국고 상금풀: {pool:,}P) | 스트리머가 개장할 때까지 대기해주세요!", None
        rem = c_state["remaining_sec"]
        time_str = f"{rem//60}분 {rem%60}초 남음" if rem > 0 else "무제한"
        return f"🎰 [나베 국고 카지노: 영업중 🔥] 남은 시간: {time_str} | 최대 배팅: {c_state['max_bet']:,}P | 잭팟 국고: {pool:,}P | 명령어: !경마 [1~4/마명] [금액] (1위 3.6배), !슬롯 [금액/올인], !주사위 [홀/짝/대/소] [금액], !마작 [패] [금액] (확률: !슬롯확률)", None

    # 15-1. Casino & Slot Odds Query
    if cmd in ["!슬롯확률", "!도박확률", "!확률", "!배당표", "!카지노확률", "!배당율"]:
        reply = (
            "🎰 [국고 슬롯 공식 확률 & 배당표]\n"
            "• 총 당첨률 50.5% (반반 승률 & 당첨금 캡 완전 해제! 🔥)\n"
            "• 👑777: 국고 15% MEGA JACKPOT 즉시 독식! (최소 12배 보장, 무제한)\n"
            "• 🀄역만: 8배 | 💎: 5배 | 🔔: 3.5배 | 🍇: 2.5배 | 🍒: 1.8배 (캡 없음)\n"
            "• 🥈2개 일치: 일반(🍒🍇🔔) 1.6배 적중(42.6%) | 고급(💎🀄7️⃣) 2.0배 적중(2.8%)\n"
            "• 💣/불일치: 꽝 (49.5% 국고 적립 | 잠재능력 장착 시 당첨금 최대 +35% 증폭 보너스)"
        )
        return reply, None

    # 16. Slot Machine Gamble
    if cmd in ["!슬롯", "!슬롯머신", "!slot", "!도박", "!룰렛"]:
        if len(tokens) < 2:
            return "🎰 [슬롯머신] 사용법: !슬롯 [금액/올인] (예: !슬롯 1000, !슬롯 올인) | 777 대박 시 국고 15% MEGA JACKPOT 즉시 독식 (당첨금 캡 없음!)", None
        bet_str = tokens[1]
        success, reply, details = execute_slot_gamble(db, user_id, username, bet_str)
        event = None
        if success and details:
            is_jackpot = details.get("is_jackpot", False)
            if is_jackpot:
                event = {"type": "casino_jackpot", "data": {**details, "gamble_type": "slot_jackpot", "payout": details["net_payout"], "win": True}}
            else:
                event = {"type": "casino_spin", "data": {**details, "win": details["won"], "payout": details["net_payout"], "bet_amount": details["bet"]}}
        return reply, event

    # 17. Dice Roll Gamble
    if cmd in ["!주사위", "!다이스", "!dice"]:
        if len(tokens) < 3:
            return "🎲 [주사위 배틀] 사용법: !주사위 [홀/짝/대/소] [금액/올인] (예: !주사위 홀 2000, !주사위 대 올인) | 홀/짝/대/소 1.8배(50% 반반 승률, 합 7은 대/소 무승부 전액 환급), 더블(1-1/6-6) 시 2.2배 크리티컬 대박 (캡 없음!)", None
        if tokens[1] in ["홀", "짝", "대", "소", "even", "odd", "high", "low"]:
            choice_str = tokens[1]
            bet_str = tokens[2]
        elif tokens[2] in ["홀", "짝", "대", "소", "even", "odd", "high", "low"]:
            choice_str = tokens[2]
            bet_str = tokens[1]
        else:
            choice_str = tokens[1]
            bet_str = tokens[2]
        success, reply, details = execute_dice_gamble(db, user_id, username, choice_str, bet_str)
        event = None
        if success and details:
            dice_sum = details.get("total", 0)
            d1, d2 = details.get("dice", [0, 0])
            is_crit = details.get("is_critical", False)
            if is_crit:
                event = {"type": "casino_jackpot", "data": {**details, "gamble_type": "dice_critical", "dice1": d1, "dice2": d2, "dice_sum": dice_sum, "payout": details["net_payout"], "win": True}}
            else:
                event = {"type": "casino_dice", "data": {**details, "dice1": d1, "dice2": d2, "dice_sum": dice_sum, "user_choice": choice_str, "win": details["won"], "is_push": details.get("is_push", False), "payout": details["net_payout"], "bet_amount": details["bet"]}}
        return reply, event

    # 17-1. Mahjong Tile Guess Gamble (!마작 [만/삭/통 or 1만~9통 or 1만,4만,7만] [베팅금])
    if cmd in ["!마작", "!마작패", "!패맞추기", "!mahjong", "!화료", "!화료패", "!대기", "!대기패"]:
        if len(tokens) < 3:
            return (
                "🀄 [마작패 / 화료패 맞추기] 사용법: !마작 [선택패들] [베팅금] 또는 !화료 [패목록] [베팅금]\n"
                "• 수패 맞추기 (만/삭/통): 1/3 확률, 배당 2.7배 (RTP 90%)\n"
                "• 1종 정확히 맞추기 (1만~9통 27종): 1/27 확률, 배당 24.3배 대박! (RTP 90%)\n"
                "• 화료패(다면 대기) 맞추기: 원하는 만큼 여러 개 패 선택 가능! (개수 늘어날수록 배율 자동 조정)\n"
                "  - 2종 대기: 12.15배 | 3종 대기: 8.10배 | 4종: 6.08배 | 9종: 2.70배\n"
                "💡 예시: !마작 만 10000 | !마작 7통 5000 | !화료 1만,4만,7만 10000 | !화료 147만 5000 | !마작 1만 4만 7만 올인"
            ), None

        def is_bet_token(tok: str) -> bool:
            clean = tok.strip().lower().replace(",", "")
            if clean in ["올인", "all", "전액", "풀베팅", "최대", "max"]:
                return True
            if clean.isdigit():
                return True
            if (clean.endswith("만") or clean.endswith("천") or clean.endswith("k")):
                sub = clean[:-1]
                if sub.isdigit() or sub.replace(".", "", 1).isdigit():
                    return True
            return False

        if is_bet_token(tokens[-1]):
            bet_str = tokens[-1]
            choice_str = " ".join(tokens[1:-1])
        elif is_bet_token(tokens[1]):
            bet_str = tokens[1]
            choice_str = " ".join(tokens[2:])
        else:
            choice_str = tokens[1]
            bet_str = tokens[2]

        success, reply, details = execute_mahjong_tile_gamble(db, user_id, username, choice_str, bet_str)
        event = None
        if success and details:
            is_jackpot = (details.get("bet_type") == "exact") or (details.get("multiplier", 0) >= 10.0)
            if details.get("won"):
                event = {"type": "casino_jackpot" if is_jackpot else "casino_spin", "data": {**details, "gamble_type": "mahjong", "payout": details["net_payout"], "win": True}}
            else:
                event = {"type": "casino_spin", "data": {**details, "gamble_type": "mahjong", "payout": details["net_payout"], "win": False}}
        return reply, event

    # 17-2. Yakuman 4-Greats Race Gamble (!경마, !레이스, !역만레이스, !말, !horse, !race)
    if cmd in ["!경마", "!레이스", "!역만레이스", "!말", "!horse", "!race"]:
        if len(tokens) < 3:
            return (
                "🏇 [역만 4대 천왕 경마 레이스] 사용법: !경마 [말이름/번호] [베팅금/올인] (또는 !레이스)\n"
                "• 1번마 🐉 대삼원 (배당 3.6배, 우승 확률 25%)\n"
                "• 2번마 🀄 스안커 (배당 3.6배, 우승 확률 25%)\n"
                "• 3번마 🌸 국사무쌍 (배당 3.6배, 우승 확률 25%)\n"
                "• 4번마 ⚡ 구련보등 (배당 3.6배, 우승 확률 25%)\n"
                "💡 곡괭이 잠재능력(역만 레이스 2등 세이프티) 장착 시 2등 준우승 시 최대 40% 베팅금 환급!\n"
                "(예: !경마 대삼원 10000, !레이스 2 5000, !경마 스안커 올인)"
            ), None
        choice_str = tokens[1]
        bet_str = tokens[2]
        if choice_str.isdigit() and len(tokens[1]) > 1:
            choice_str, bet_str = tokens[2], tokens[1]

        success, reply, details = execute_yakuman_race_gamble(db, user_id, username, choice_str, bet_str)
        event = None
        if success and details:
            if details.get("won"):
                event = {"type": "casino_jackpot", "data": {**details, "gamble_type": "yakuman_race", "payout": details["net_payout"], "win": True}}
            else:
                event = {"type": "casino_spin", "data": {**details, "gamble_type": "yakuman_race", "payout": details["net_payout"], "win": False}}
        return reply, event

    # 17-3. State Welfare Lottery Event Commands (!복권오픈 [분], !복권마감)
    if cmd in ["!복권오픈", "!복권열기", "!복권시작", "!오픈복권"]:
        is_streamer = (user_id == CHANNEL_ID or username in ["치즈나베", "스트리머"] or user_id in ["streamer", "admin"])
        if not is_streamer:
            return "🚫 복권 이벤트 강제 오픈은 스트리머(치즈나베)만 진행할 수 있습니다! (복권은 20~40분 주기마다 국가 복지로 자동 오픈됩니다)", None

        dur = 10
        if len(tokens) >= 2:
            try:
                dur = int(tokens[1].replace("분", "").strip())
            except ValueError:
                dur = 10
        success, reply, details = open_lottery_event(db, duration_minutes=dur)
        event = {"type": "lottery_event_started", "data": details} if success and details else None
        return reply, event

    if cmd in ["!복권마감", "!복권종료", "!복권닫기"]:
        is_streamer = (user_id == CHANNEL_ID or username in ["치즈나베", "스트리머"] or user_id in ["streamer", "admin"])
        if not is_streamer:
            return "🚫 복권 이벤트 마감은 스트리머(치즈나베)만 진행할 수 있습니다!", None

        success, reply, details = close_lottery_event(db)
        event = {"type": "lottery_event_ended", "data": details} if success and details else None
        return reply, event

    # 17-4. State Welfare Lottery Odds & Status (!복권확률, !복권정보, !복권상태, !복권안내)
    if cmd in ["!복권확률", "!복권정보", "!복권상태", "!복권안내"]:
        ev_state = get_lottery_event_state(db)
        guide = get_lottery_guide()
        if ev_state["is_active"]:
            rem = ev_state["remaining_sec"]
            m = rem // 60
            s = rem % 60
            prefix = f"🎉 [국가 복지 복권: 판매중! 🔥] 남은 시간: {m}분 {s:02d}초 (동 1,000P / 은 5,000P / 금 20,000P)\n"
        else:
            next_m = max(1, ev_state["next_event_in_sec"] // 60)
            prefix = f"🔒 [국가 복지 복권: 준비중] 약 {next_m}분 후 자동으로 오픈됩니다! (명령어: !복권 [종류] [수량])\n"
        return prefix + guide, None

    # 17-5. State Welfare Lottery Purchase & Scratch (!복권, !동복권, !은복권, !금복권, !lotto, !lottery)
    lottery_direct_cmds = {
        "!동복권": "basic", "!동복권구매": "basic", "!동복": "basic",
        "!은복권": "silver", "!은복권구매": "silver", "!은복": "silver",
        "!금복권": "gold", "!금복권구매": "gold", "!금복": "gold"
    }
    if cmd in ["!복권", "!복권구매", "!복권긁기", "!lotto", "!lottery"] or cmd in lottery_direct_cmds:
        if len(tokens) >= 2 and tokens[1] in ["확률", "정보", "상태", "안내", "도움말", "help"]:
            ev_state = get_lottery_event_state(db)
            guide = get_lottery_guide()
            if ev_state["is_active"]:
                rem = ev_state["remaining_sec"]
                m = rem // 60
                s = rem % 60
                prefix = f"🎉 [국가 복지 복권: 판매중! 🔥] 남은 시간: {m}분 {s:02d}초 (동 1,000P / 은 5,000P / 금 20,000P)\n"
            else:
                next_m = max(1, ev_state["next_event_in_sec"] // 60)
                prefix = f"🔒 [국가 복지 복권: 준비중] 약 {next_m}분 후 자동으로 오픈됩니다! (명령어: !동복권 [수량] / !은복권 [수량] / !금복권 [수량])\n"
            return prefix + guide, None

        if cmd in lottery_direct_cmds:
            l_type = lottery_direct_cmds[cmd]
            qty = 1
            if len(tokens) >= 2:
                arg0 = tokens[1].replace("장", "").replace("개", "").strip().lower()
                if arg0 in ["최대", "max", "올인", "다", "전부"]:
                    qty = 10
                elif arg0.isdigit():
                    qty = max(1, min(10, int(arg0)))
        else:
            l_type = "basic"
            qty = 1
            known_types = {
                "동": "basic", "일반": "basic", "동복권": "basic", "일반복권": "basic", "싼거": "basic", "1": "basic", "basic": "basic", "bronze": "basic",
                "은": "silver", "고급": "silver", "은복권": "silver", "고급복권": "silver", "중간": "silver", "중간거": "silver", "2": "silver", "silver": "silver",
                "금": "gold", "대박": "gold", "금복권": "gold", "대박복권": "gold", "비싼거": "gold", "초대박": "gold", "3": "gold", "gold": "gold", "vip": "gold"
            }
            raw_args = tokens[1:]
            if len(raw_args) == 1:
                arg0 = raw_args[0].replace("장", "").replace("개", "").strip().lower()
                if arg0 in ["최대", "max", "올인", "다", "전부"]:
                    qty = 10
                elif arg0.isdigit():
                    qty = int(arg0)
                elif arg0 in known_types:
                    l_type = known_types[arg0]
                    qty = 1
            elif len(raw_args) >= 2:
                arg0 = raw_args[0].replace("장", "").replace("개", "").strip().lower()
                arg1 = raw_args[1].replace("장", "").replace("개", "").strip().lower()
                if arg0 in known_types:
                    l_type = known_types[arg0]
                    if arg1.isdigit():
                        qty = int(arg1)
                    elif arg1 in ["최대", "max", "올인", "다", "전부"]:
                        qty = 10
                elif arg1 in known_types:
                    l_type = known_types[arg1]
                    if arg0.isdigit():
                        qty = int(arg0)
                    elif arg0 in ["최대", "max", "올인", "다", "전부"]:
                        qty = 10
                else:
                    if arg0.isdigit():
                        qty = int(arg0)

        success, reply, details = execute_buy_lottery(db, user_id, username, count=qty, lottery_type=l_type)
        event = None
        if success and details:
            if details.get("has_jackpot"):
                event = {"type": "lottery_jackpot", "data": {**details, "user_id": user_id, "username": username}}
            else:
                event = {"type": "lottery_scratch", "data": {**details, "user_id": user_id, "username": username}}
        return reply, event

    # 17-5. Mysterious Merchant Status & Shop Guide (!신비상인, !상인, !신비상점, !비밀상인, !상점)
    if cmd in ["!신비상인", "!상인", "!신비상점", "!비밀상인", "!상점", "!merchant"]:
        return get_merchant_guide(db), None

    # 17-6. Mysterious Merchant Streamer Commands (!신비상인오픈 [분], !신비상인마감)
    if cmd in ["!신비상인오픈", "!상인오픈", "!신비상점오픈", "!상점오픈"]:
        is_streamer = (user_id == CHANNEL_ID or username in ["치즈나베", "스트리머"] or user_id in ["streamer", "admin"])
        if not is_streamer:
            return "🚫 신비상인 강제 소환은 스트리머(치즈나베)만 진행할 수 있습니다! (신비상인은 25~50분마다 무작위로 자동 등장합니다)", None

        dur = 10
        if len(tokens) >= 2:
            try:
                dur = int(tokens[1].replace("분", "").strip())
            except ValueError:
                dur = 10
        success, reply, details = open_merchant(db, duration_minutes=dur)
        event = {"type": "merchant_appeared", "data": details} if success and details else None
        return reply, event

    if cmd in ["!신비상인마감", "!상인마감", "!신비상점마감", "!상인퇴장", "!신비상인종료"]:
        is_streamer = (user_id == CHANNEL_ID or username in ["치즈나베", "스트리머"] or user_id in ["streamer", "admin"])
        if not is_streamer:
            return "🚫 신비상인 마감은 스트리머(치즈나베)만 진행할 수 있습니다!", None

        success, reply, details = close_merchant(db)
        event = {"type": "merchant_left", "data": details} if success and details else None
        return reply, event

    # 17-7. Underground Arena 1:1 PvP Deathmatch (!대결, !결투, !맞짱, !pvp, !피빕, !수락, !거절, !투기장)
    if cmd in ["!대결방법", "!투기장방법", "!대결가이드", "!투기장가이드"]:
        return GUIDE_ARENA, None

    if cmd in ["!대결", "!결투", "!맞짱", "!pvp", "!피빕", "!배틀", "!다이다이", "!1대1", "!1:1"]:
        if len(tokens) < 3:
            return (
                "⚔️ [지하 투기장 1:1 맞짱 데스매치]\n"
                "💡 사용법: !대결 @상대닉네임 [금액/올인] (예: !대결 @메루1 50000, !대결 @CYTFT 올인)\n"
                "• 1d100 주사위 승부! 더 높은 숫자가 승리!\n"
                "• 승자 98% 독식 대박, 2% 국고 수수료 적립 (90초 제한시간 내 !수락 / !거절)"
            ), None

        target_token = tokens[1]
        bet_token = tokens[2]
        if target_token.isdigit() or target_token in ["올인", "all", "전액", "최대"] or target_token.endswith("만") or target_token.endswith("천"):
            target_token, bet_token = tokens[2], tokens[1]

        success, reply, details = create_pvp_challenge(db, user_id, username, target_token, bet_token)
        event = {"type": "pvp_challenge", "data": details} if success and details else None
        return reply, event

    if cmd in ["!수락", "!승낙", "!받기", "!accept", "!yes"]:
        success, reply, details = accept_pvp_challenge(db, user_id, username)
        event = {"type": "pvp_duel", "data": details, "reply": reply} if success and details else None
        return reply, event

    if cmd in ["!거절", "!런", "!도망", "!decline", "!no"]:
        success, reply, details = decline_pvp_challenge(db, user_id, username)
        event = {"type": "pvp_declined", "data": details, "reply": reply} if success and details else None
        return reply, event

    if cmd in ["!투기장", "!아레나", "!arena", "!투기장오픈", "!투기장참가"]:
        if cmd == "!투기장오픈":
            if len(tokens) < 2:
                return "⚔️ [투기장 공개 개설] 사용법: !투기장 오픈 [금액/올인] (예: !투기장 오픈 30000)", None
            success, reply, details = open_public_arena_match(db, user_id, username, tokens[1])
            event = {"type": "pvp_open", "data": details, "reply": reply} if success and details else None
            return reply, event

        if cmd == "!투기장참가":
            target_host = tokens[1] if len(tokens) > 1 else None
            success, reply, details = join_public_arena_match(db, user_id, username, target_host)
            event = {"type": "pvp_duel", "data": details, "reply": reply} if success and details else None
            return reply, event

        if len(tokens) == 1:
            return get_arena_status(db), None

        sub = tokens[1].lower()
        if sub in ["오픈", "개설", "열기", "open"]:
            if len(tokens) < 3:
                return "⚔️ [투기장 공개 개설] 사용법: !투기장 오픈 [금액/올인] (예: !투기장 오픈 30000)", None
            success, reply, details = open_public_arena_match(db, user_id, username, tokens[2])
            event = {"type": "pvp_open", "data": details} if success and details else None
            return reply, event

        if sub in ["참가", "참여", "도전", "join"]:
            target_host = tokens[2] if len(tokens) > 2 else None
            success, reply, details = join_public_arena_match(db, user_id, username, target_host)
            event = {"type": "pvp_duel", "data": details} if success and details else None
            return reply, event

        if sub.isdigit() or sub in ["올인", "all", "전액", "최대"] or sub.endswith("만") or sub.endswith("천"):
            success, reply, details = open_public_arena_match(db, user_id, username, tokens[1])
            event = {"type": "pvp_open", "data": details} if success and details else None
            return reply, event

        return get_arena_status(db), None

    # 18. Streamer Match Settlement Command (!정산 [등수] [변동점수])
    if cmd in ["!정산", "!경기정산", "!결과", "!settle"]:
        is_streamer = (user_id == CHANNEL_ID or username in ["치즈나베", "스트리머"] or user_id in ["streamer", "admin"])
        if not is_streamer:
            return "🚫 경기 정산은 스트리머(치즈나베) 전용 명령어입니다!", None

        if len(tokens) < 2:
            return "🎯 [경기 정산 사용법] !정산 [순위(1~4)] [변동점수(선택)] (예: !정산 2 0, !정산 1 270, !정산 2, !정산 3 -330)", None

        try:
            rank_val = int(tokens[1])
            if rank_val not in (1, 2, 3, 4):
                return "⚠️ 순위는 1, 2, 3, 4 중 하나를 입력해주세요. (예: !정산 2 0, !정산 1 270)", None
        except ValueError:
            return f"⚠️ 올바른 순위를 입력해주세요: '{tokens[1]}'", None

        delta_val = 0
        if len(tokens) >= 3:
            try:
                delta_str = tokens[2].replace("+", "").strip()
                delta_val = int(delta_str)
            except ValueError:
                delta_val = 0
        else:
            default_deltas = {1: 270, 2: 0, 3: -330, 4: -600}
            delta_val = default_deltas.get(rank_val, 0)

        settle_res = settle_match(db, rank=rank_val, point_delta=delta_val)
        if settle_res.get("delisted"):
            delist_info = settle_res["delisting_info"]
            reply = (
                f"🚨🚨 [경기 정산 & 상장폐지] {rank_val}위 ({delta_sign}pt) 정산 결과 점수 0pt 이하로 [작성2] 강등 발생!\n"
                f"💥 작성3 종목이 전격 [상장폐지]되었으며, 기존 주주 총 {delist_info['wiped_positions_count']}명의 모든 주식이 [휴짓조각(0주)] 처리되었습니다!\n"
                f"✨ 신규 종목 [작성2] (시작가 {settle_res['new_price']:,}P) 신규 상장 완료! (5분간 자유 거래 오픈)"
            )
            event = {
                "type": "delisting",
                "data": {
                    **settle_res,
                    "rank": rank_val,
                    "point_delta": delta_val,
                    "free_trading_remaining": 300
                }
            }
            return reply, event

        new_price = settle_res["new_price"]
        divs = settle_res.get("dividends", [])
        div_count = len(divs)
        div_total = sum(d.get("payout", 0) or d.get("amount", 0) for d in divs)
        pct_label = "1위 우승 5% 1X" if rank_val == 1 else ("2위 준우승 1% 1X" if rank_val == 2 else "")
        div_label = f" | 🎁 {pct_label} 배당: {div_count}명(+{div_total:,}P)" if div_count > 0 else ""
        liq_count = len(settle_res.get("liquidations", []))
        liq_label = f" | 🚨청산 {liq_count}건" if liq_count > 0 else ""

        delta_sign = f"+{delta_val}" if delta_val > 0 else f"{delta_val}"
        reply = (
            f"📢 [경기 정산 완료] {rank_val}위 ({delta_sign}pt) 정산 완료! "
            f"새 주가: {new_price:,}P{div_label}{liq_label} | 5분간 자유 거래 오픈!"
        )
        event = {
            "type": "settlement",
            "data": {
                **settle_res,
                "rank": rank_val,
                "point_delta": delta_val,
                "free_trading_remaining": 300
            }
        }
        return reply, event

    # 18-1. Streamer Demotion & Delisting Command (!강등, !상장폐지)
    if cmd in ["!강등", "!상장폐지", "!강등처리", "!delist"]:
        is_streamer = (user_id == CHANNEL_ID or username in ["치즈나베", "스트리머"] or user_id in ["streamer", "admin"])
        if not is_streamer:
            return "🚫 강등/상장폐지 처리는 스트리머(치즈나베) 전용 명령어입니다!", None

        state = get_market_state(db)
        curr_rank = getattr(state, "current_rank_name", "작성3") or "작성3"
        target_rank = "작성2"
        target_pts = 3000

        if len(tokens) >= 2:
            target_rank = tokens[1].strip()
        if len(tokens) >= 3:
            try:
                target_pts = int(re.sub(r"[^\d]", "", tokens[2]))
            except Exception:
                target_pts = 3000

        delist_res = execute_delisting_and_relist(
            db,
            old_rank=curr_rank,
            new_rank=target_rank,
            starting_points=target_pts
        )

        reply = (
            f"🚨🚨 [긴급 속보: 상장폐지 & 신규 상장] 치즈나베의 '{curr_rank}' 강등으로 인해 {curr_rank} 종목이 전격 [상장폐지]되었습니다!\n"
            f"💥 기존 주주 총 {delist_res['wiped_positions_count']}명의 보유 주식(총 {format_quantity(delist_res['total_wiped_shares'])}주)이 전량 [휴짓조각(0주)] 처리되었습니다.\n"
            f"✨ 신규 종목 [{target_rank}] (시작가 {delist_res['new_price']:,}P)가 새로 상장되어 거래가 시작됩니다! (5분간 자유 거래 오픈)"
        )
        event = {
            "type": "delisting",
            "data": {
                **delist_res,
                "free_trading_remaining": 300
            }
        }
        return reply, event

    # 19. Streamer Day Open Price Setting Command (!시가설정, !시작지점, !시가재설정, !시작점재설정, !기준가설정, !시작점설정)
    if cmd in ["!시가설정", "!시작지점", "!시가재설정", "!시작점재설정", "!기준가설정", "!시작점설정"]:
        is_streamer = (user_id == CHANNEL_ID or username in ["치즈나베", "스트리머"] or user_id in ["streamer", "admin"])
        if not is_streamer:
            return "🚫 당일 시작가 설정은 스트리머(치즈나베) 전용 명령어입니다!", None

        state = get_market_state(db)
        if cmd in ["!시가재설정", "!시작점재설정"] or len(tokens) < 2:
            target_price = state.current_price
        else:
            try:
                cleaned = re.sub(r"[^\d]", "", tokens[1])
                if not cleaned:
                    return f"⚠️ 올바른 숫자를 입력해주세요: '{tokens[1]}'", None
                target_price = int(cleaned)
                if target_price <= 0:
                    return "⚠️ 설정할 시작가는 0보다 커야 합니다.", None
            except Exception:
                return f"⚠️ 올바른 숫자를 입력해주세요: '{tokens[1]}'", None

        set_day_open_price(db, target_price)

        diff = state.current_price - target_price
        pct = (diff / target_price * 100.0) if target_price > 0 else 0.0
        sign = "+" if diff >= 0 else ""

        reply = (
            f"📢 [시가 설정 완료] 당일 시작가가 {target_price:,}P로 설정되었습니다! "
            f"(현재가: {state.current_price:,}P | 오늘 누적 등락: {sign}{diff:,}P / {sign}{pct:.2f}%)"
        )
        event = {
            "type": "market_update",
            "data": {
                "day_open_price": target_price,
                "current_price": state.current_price,
                "diff": diff,
                "diff_pct": pct
            }
        }
        return reply, event

    # 20. Real-time Mahjong Tracker Query Command (!트래커, !전적, !작혼, !tracker, !스코어, !점수)
    if cmd in ["!트래커", "!전적", "!작혼", "!tracker", "!스코어", "!점수"]:
        state = get_market_state(db)
        day_open = getattr(state, "day_open_price", 2137)
        diff = state.current_rank_point - day_open
        pct = (diff / day_open * 100.0) if day_open > 0 else 0.0
        sign = "+" if diff >= 0 else ""

        now = time.time()
        rem = max(0, int(state.free_trading_end_time - now)) if getattr(state, "free_trading_end_time", None) else 0

        if state.is_trading_locked:
            status_str = "🔒 거래 마감 (경기 중)"
        elif rem > 0:
            m = rem // 60
            s = rem % 60
            status_str = f"⏳ 자유 거래 진행 중 ({m:02d}:{s:02d})"
        else:
            status_str = "🟢 장 열림 (거래 가능)"

        rank_name = getattr(state, "current_rank_name", "작성3") or "작성3"
        reply = (
            f"🀄 [작혼 나베주가 ({rank_name}) 현황] 현재 점수: {state.current_rank_point:,}pt (주가: {state.current_price:,}P) | "
            f"당일 시작점: {day_open:,}pt | "
            f"오늘 누적 등락: {sign}{diff:,}pt ({sign}{pct:.2f}%) | 상태: {status_str}"
        )
        return reply, None

    return None, None

