import time
import math
import json
import hashlib
import random
import re
import uuid
import secrets
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Tuple, List, Optional
from sqlalchemy import func
from sqlalchemy.orm import Session
from models import (
    User, Position, MarketState, LimitOrder, ProductType,
    OrderType, OrderStatus, BankruptcyApplication, BankruptcyStatus,
    DonationRecord, UserEquipment, EquipmentListing, ItemListing,
    UserAssetHistory, ArenaMatchLog
)

PRODUCT_MULTIPLIERS: Dict[ProductType, float] = {
    ProductType.ONE_X: 1.0,
    ProductType.TWO_X: 2.0,
    ProductType.THREE_X: 3.0,
    ProductType.FIVE_X: 5.0,
    ProductType.TEN_X: 10.0,
    ProductType.TWENTY_X: 20.0,
    ProductType.FORTY_X: 40.0,
    ProductType.SIXTY_X: 60.0,
    ProductType.INV: -1.0,
    ProductType.TWO_X_INV: -2.0,
    ProductType.THREE_X_INV: -3.0,
    ProductType.FIVE_X_INV: -5.0,
    ProductType.TEN_X_INV: -10.0,
    ProductType.TWENTY_X_INV: -20.0,
    ProductType.FORTY_X_INV: -40.0,
    ProductType.SIXTY_X_INV: -60.0,
}

SUPPORTED_PRODUCTS_GUIDE: str = "1X, 2X, 3X, 5X, 10X (레버리지) / INV, 2X_INV, 3X_INV, 5X_INV, 10X_INV (인버스) [야수의 심장 해금: 20X(1줄), 40X(2줄), 60X(3줄)]"

PRODUCT_SYNONYMS = {
    "1X": ProductType.ONE_X,
    "1x": ProductType.ONE_X,
    "1배": ProductType.ONE_X,
    "1레": ProductType.ONE_X,
    "1버": ProductType.ONE_X,
    "1레버": ProductType.ONE_X,
    "1롱": ProductType.ONE_X,
    "롱": ProductType.ONE_X,
    "기본": ProductType.ONE_X,
    "기본주": ProductType.ONE_X,
    "현물": ProductType.ONE_X,

    "2X": ProductType.TWO_X,
    "2x": ProductType.TWO_X,
    "2배": ProductType.TWO_X,
    "2레": ProductType.TWO_X,
    "2버": ProductType.TWO_X,
    "2레버": ProductType.TWO_X,
    "2롱": ProductType.TWO_X,
    "2배롱": ProductType.TWO_X,
    "2배레버": ProductType.TWO_X,
    "2배레버리지": ProductType.TWO_X,
    "2X레버": ProductType.TWO_X,
    "레버리지": ProductType.TWO_X,
    "레버": ProductType.TWO_X,

    "3X": ProductType.THREE_X,
    "3x": ProductType.THREE_X,
    "3배": ProductType.THREE_X,
    "3레": ProductType.THREE_X,
    "3버": ProductType.THREE_X,
    "3레버": ProductType.THREE_X,
    "3롱": ProductType.THREE_X,
    "3배롱": ProductType.THREE_X,
    "3배레버": ProductType.THREE_X,
    "3배레버리지": ProductType.THREE_X,
    "3X레버": ProductType.THREE_X,

    "5X": ProductType.FIVE_X,
    "5x": ProductType.FIVE_X,
    "5배": ProductType.FIVE_X,
    "5레": ProductType.FIVE_X,
    "5버": ProductType.FIVE_X,
    "5레버": ProductType.FIVE_X,
    "5롱": ProductType.FIVE_X,
    "5배롱": ProductType.FIVE_X,
    "5배레버": ProductType.FIVE_X,
    "5배레버리지": ProductType.FIVE_X,
    "5X레버": ProductType.FIVE_X,

    "10X": ProductType.TEN_X,
    "10x": ProductType.TEN_X,
    "10배": ProductType.TEN_X,
    "10배주": ProductType.TEN_X,
    "10배주식": ProductType.TEN_X,
    "10레": ProductType.TEN_X,
    "10버": ProductType.TEN_X,
    "10롱": ProductType.TEN_X,
    "10배롱": ProductType.TEN_X,
    "10X롱": ProductType.TEN_X,
    "10레버": ProductType.TEN_X,
    "10배레버": ProductType.TEN_X,
    "10배레버리지": ProductType.TEN_X,
    "10X레버": ProductType.TEN_X,

    "20X": ProductType.TWENTY_X,
    "20x": ProductType.TWENTY_X,
    "20배": ProductType.TWENTY_X,
    "20배주": ProductType.TWENTY_X,
    "20배주식": ProductType.TWENTY_X,
    "20레": ProductType.TWENTY_X,
    "20버": ProductType.TWENTY_X,
    "20롱": ProductType.TWENTY_X,
    "20배롱": ProductType.TWENTY_X,
    "20X롱": ProductType.TWENTY_X,
    "20레버": ProductType.TWENTY_X,
    "20배레버": ProductType.TWENTY_X,
    "20배레버리지": ProductType.TWENTY_X,
    "20X레버": ProductType.TWENTY_X,

    "40X": ProductType.FORTY_X,
    "40x": ProductType.FORTY_X,
    "40배": ProductType.FORTY_X,
    "40배주": ProductType.FORTY_X,
    "40배주식": ProductType.FORTY_X,
    "40레": ProductType.FORTY_X,
    "40버": ProductType.FORTY_X,
    "40롱": ProductType.FORTY_X,
    "40배롱": ProductType.FORTY_X,
    "40X롱": ProductType.FORTY_X,
    "40레버": ProductType.FORTY_X,
    "40배레버": ProductType.FORTY_X,
    "40배레버리지": ProductType.FORTY_X,
    "40X레버": ProductType.FORTY_X,

    "60X": ProductType.SIXTY_X,
    "60x": ProductType.SIXTY_X,
    "60배": ProductType.SIXTY_X,
    "60배주": ProductType.SIXTY_X,
    "60배주식": ProductType.SIXTY_X,
    "60레": ProductType.SIXTY_X,
    "60버": ProductType.SIXTY_X,
    "60롱": ProductType.SIXTY_X,
    "60배롱": ProductType.SIXTY_X,
    "60X롱": ProductType.SIXTY_X,
    "60레버": ProductType.SIXTY_X,
    "60배레버": ProductType.SIXTY_X,
    "60배레버리지": ProductType.SIXTY_X,
    "60X레버": ProductType.SIXTY_X,

    "INV": ProductType.INV,
    "inv": ProductType.INV,
    "1X_INV": ProductType.INV,
    "1XINV": ProductType.INV,
    "1배인버스": ProductType.INV,
    "1인": ProductType.INV,
    "1곱": ProductType.INV,
    "1숏": ProductType.INV,
    "인버스": ProductType.INV,
    "인버스1X": ProductType.INV,
    "숏": ProductType.INV,

    "2X_INV": ProductType.TWO_X_INV,
    "2x_inv": ProductType.TWO_X_INV,
    "2XINV": ProductType.TWO_X_INV,
    "2xinv": ProductType.TWO_X_INV,
    "곱버스": ProductType.TWO_X_INV,
    "2X인버스": ProductType.TWO_X_INV,
    "2x인버스": ProductType.TWO_X_INV,
    "2배인버스": ProductType.TWO_X_INV,
    "2배곱버스": ProductType.TWO_X_INV,
    "2인": ProductType.TWO_X_INV,
    "2곱": ProductType.TWO_X_INV,
    "2X숏": ProductType.TWO_X_INV,
    "2배숏": ProductType.TWO_X_INV,
    "2숏": ProductType.TWO_X_INV,
    "인버스2X": ProductType.TWO_X_INV,
    "인버스2배": ProductType.TWO_X_INV,

    "3X_INV": ProductType.THREE_X_INV,
    "3x_inv": ProductType.THREE_X_INV,
    "3XINV": ProductType.THREE_X_INV,
    "3xinv": ProductType.THREE_X_INV,
    "3배인버스": ProductType.THREE_X_INV,
    "3배곱버스": ProductType.THREE_X_INV,
    "3인": ProductType.THREE_X_INV,
    "3곱": ProductType.THREE_X_INV,
    "3X인버스": ProductType.THREE_X_INV,
    "3X숏": ProductType.THREE_X_INV,
    "3배숏": ProductType.THREE_X_INV,
    "3숏": ProductType.THREE_X_INV,
    "인버스3X": ProductType.THREE_X_INV,
    "인버스3배": ProductType.THREE_X_INV,

    "5X_INV": ProductType.FIVE_X_INV,
    "5x_inv": ProductType.FIVE_X_INV,
    "5XINV": ProductType.FIVE_X_INV,
    "5xinv": ProductType.FIVE_X_INV,
    "5배인버스": ProductType.FIVE_X_INV,
    "5배곱버스": ProductType.FIVE_X_INV,
    "5인": ProductType.FIVE_X_INV,
    "5곱": ProductType.FIVE_X_INV,
    "5X인버스": ProductType.FIVE_X_INV,
    "5X숏": ProductType.FIVE_X_INV,
    "5배숏": ProductType.FIVE_X_INV,
    "5숏": ProductType.FIVE_X_INV,
    "인버스5X": ProductType.FIVE_X_INV,
    "인버스5배": ProductType.FIVE_X_INV,

    "10X_INV": ProductType.TEN_X_INV,
    "10x_inv": ProductType.TEN_X_INV,
    "10XINV": ProductType.TEN_X_INV,
    "10xinv": ProductType.TEN_X_INV,
    "10배인버스": ProductType.TEN_X_INV,
    "10배곱버스": ProductType.TEN_X_INV,
    "10인": ProductType.TEN_X_INV,
    "10곱": ProductType.TEN_X_INV,
    "10X인버스": ProductType.TEN_X_INV,
    "10X숏": ProductType.TEN_X_INV,
    "10배숏": ProductType.TEN_X_INV,
    "10숏": ProductType.TEN_X_INV,
    "인버스10X": ProductType.TEN_X_INV,
    "인버스10배": ProductType.TEN_X_INV,

    "20X_INV": ProductType.TWENTY_X_INV,
    "20x_inv": ProductType.TWENTY_X_INV,
    "20XINV": ProductType.TWENTY_X_INV,
    "20xinv": ProductType.TWENTY_X_INV,
    "20배인버스": ProductType.TWENTY_X_INV,
    "20배곱버스": ProductType.TWENTY_X_INV,
    "20인": ProductType.TWENTY_X_INV,
    "20곱": ProductType.TWENTY_X_INV,
    "20X인버스": ProductType.TWENTY_X_INV,
    "20X숏": ProductType.TWENTY_X_INV,
    "20배숏": ProductType.TWENTY_X_INV,
    "20숏": ProductType.TWENTY_X_INV,
    "인버스20X": ProductType.TWENTY_X_INV,
    "인버스20배": ProductType.TWENTY_X_INV,

    "40X_INV": ProductType.FORTY_X_INV,
    "40x_inv": ProductType.FORTY_X_INV,
    "40XINV": ProductType.FORTY_X_INV,
    "40xinv": ProductType.FORTY_X_INV,
    "40배인버스": ProductType.FORTY_X_INV,
    "40배곱버스": ProductType.FORTY_X_INV,
    "40인": ProductType.FORTY_X_INV,
    "40곱": ProductType.FORTY_X_INV,
    "40X인버스": ProductType.FORTY_X_INV,
    "40X숏": ProductType.FORTY_X_INV,
    "40배숏": ProductType.FORTY_X_INV,
    "40숏": ProductType.FORTY_X_INV,
    "인버스40X": ProductType.FORTY_X_INV,
    "인버스40배": ProductType.FORTY_X_INV,

    "60X_INV": ProductType.SIXTY_X_INV,
    "60x_inv": ProductType.SIXTY_X_INV,
    "60XINV": ProductType.SIXTY_X_INV,
    "60xinv": ProductType.SIXTY_X_INV,
    "60배인버스": ProductType.SIXTY_X_INV,
    "60배곱버스": ProductType.SIXTY_X_INV,
    "60인": ProductType.SIXTY_X_INV,
    "60곱": ProductType.SIXTY_X_INV,
    "60X인버스": ProductType.SIXTY_X_INV,
    "60X숏": ProductType.SIXTY_X_INV,
    "60배숏": ProductType.SIXTY_X_INV,
    "60숏": ProductType.SIXTY_X_INV,
    "인버스60X": ProductType.SIXTY_X_INV,
    "인버스60배": ProductType.SIXTY_X_INV,
}

def parse_product_type(text: str) -> Optional[ProductType]:
    """Parse product string or Korean synonym into ProductType enum, stripping quotes and symbols."""
    if not text:
        return None
    cleaned = str(text).strip().strip("'\"`’‘“”,;[]()").strip()
    if not cleaned:
        return None

    # Exact or uppercase lookup
    if cleaned.upper() in PRODUCT_SYNONYMS:
        return PRODUCT_SYNONYMS[cleaned.upper()]
    if cleaned in PRODUCT_SYNONYMS:
        return PRODUCT_SYNONYMS[cleaned]

    # Handle forms like "10x", "5x", "10배", "5배", "10레", "10버", "10롱", "40배", "60배"
    upper_c = cleaned.upper()
    for suffix in ["X", "배", "레", "버", "레버", "배레버", "롱", "배롱", "X롱", "배주", "배주식"]:
        if upper_c.endswith(suffix):
            prefix = upper_c[:-len(suffix)].strip()
            if prefix in ["1", "2", "3", "5", "10", "20", "40", "60"]:
                return PRODUCT_SYNONYMS.get(f"{prefix}X")

    # Handle inverse forms like "10숏", "10인", "10곱", "10인버스", "10곱버스", "40숏", "60숏"
    for suffix in ["인", "곱", "숏", "배인", "배곱", "배숏", "인버스", "곱버스", "X인버스", "X숏", "X_INV", "XINV"]:
        if upper_c.endswith(suffix):
            prefix = upper_c[:-len(suffix)].strip()
            if prefix in ["1", "2", "3", "5", "10", "20", "40", "60"]:
                inv_key = "INV" if prefix == "1" else f"{prefix}X_INV"
                return PRODUCT_SYNONYMS.get(inv_key)

    return None

STARTING_POINTS: int = 50000
DEFAULT_TREASURY_POOL: float = 500000.0
TRADING_FEE_RATE: float = 0.01  # 1% 거래 수수료 -> 국고 채굴풀 자동 적립
MAX_LOAN_LIMIT: int = 50000000    # 최대 50,000,000P 신용 대출 상한선 (1등급 한도)
LOAN_INTEREST_RATE: float = 0.02 # 경기당 2% 대출 기준 이자 (5등급 기준)

# ==========================================
# Credit Rating & Personalized Loan Limit System (개인별 신용등급 및 차등 대출 한도제)
# ==========================================
# 1등급(AAA) ~ 10등급(D) 개인 신용평가 체계 (0~1000점)
CREDIT_TIERS: List[Tuple[int, int, str, str, int, float]] = [
    # (min_score, tier, grade, tier_name, loan_limit, interest_rate)
    (900, 1,  "AAA", "1등급 (AAA 최우수)", 50000000, 0.010),
    (800, 2,  "AA",  "2등급 (AA 우수)",    30000000, 0.012),
    (700, 3,  "A",   "3등급 (A 우량)",     15000000, 0.015),
    (600, 4,  "BBB", "4등급 (BBB 양호)",   7000000,  0.018),
    (500, 5,  "BB",  "5등급 (BB 보통)",    3000000,  0.020),
    (400, 6,  "B",   "6등급 (B 일반)",     1500000,  0.022),
    (300, 7,  "CCC", "7등급 (CCC 주의)",    700000,  0.025),
    (200, 8,  "CC",  "8등급 (CC 경고)",     300000,  0.030),
    (100, 9,  "C",   "9등급 (C 고위험)",    100000,  0.035),
    (0,   10, "D",   "10등급 (D 신용불량)",        0, 0.050),
]

# 계좌이체 수수료 정책: 1만P 미만 면세, 1만P 이상 0.1%(1만P당 10P), 10만P 이상 0.2%(10만P당 200P)의 미미한 수수료
TRANSFER_TAX_THRESHOLD: int = 10000       # 1만P 이상 이체 시 미미한 수수료 부과
TRANSFER_TAX_RATE: float = 0.001          # 1만P 이상 미미한 0.1% 이체 수수료
TRANSFER_HIGH_TAX_THRESHOLD: int = 100000 # 10만P 이상 이체 시
TRANSFER_HIGH_TAX_RATE: float = 0.002     # 10만P 이상 0.2% 이체 수수료

# ==========================================
# MapleStory Equipment Potential & Cube System (메이플 큐브 잠재능력)
# ==========================================

CUBE_COST: int = 15000
CUBE_FRAGMENT_EXCHANGE_COST: int = 10
CUBE_FRAGMENT_EXCHANGE_REWARD: int = 15000

CUBE_TIER_ORDER = ["NONE", "RARE", "EPIC", "UNIQUE", "LEGENDARY"]

CUBE_TIER_DISPLAY: Dict[str, str] = {
    "NONE": "잠재 없음",
    "RARE": "💙 레어 (RARE)",
    "EPIC": "💜 에픽 (EPIC)",
    "UNIQUE": "💛 유니크 (UNIQUE)",
    "LEGENDARY": "🌟 레전드리 (LEGENDARY)",
}

# Promotion rates based on official Black Cube rates from Namuwiki
CUBE_PROMOTION_RATES: Dict[str, float] = {
    "NONE": 100.0,   # 1st cube unlocks RARE with 100% chance
    "RARE": 15.0,    # RARE -> EPIC (15.0%)
    "EPIC": 3.5,     # EPIC -> UNIQUE (3.5%)
    "UNIQUE": 1.4,   # UNIQUE -> LEGENDARY (1.4%)
    "LEGENDARY": 0.0 # Max tier
}

# Pity guarantee ceilings based on official MapleStory data (3.2 등급 상승 보장)
CUBE_PITY_CEILINGS: Dict[str, int] = {
    "RARE": 10,     # 10회 천장
    "EPIC": 42,     # 42회 천장
    "UNIQUE": 107,  # 107회 천장
}

POTENTIAL_OPTIONS: Dict[str, Dict[str, Any]] = {
    "MINING_CD_RESET": {
        "name": "쿨타임 즉시 초기화",
        "unit": "%",
        "icon": "⚡",
        "tiers": {
            "EPIC": (4.0, "채굴 시 4% 확률로 쿨타임 즉시 초기화"),
            "UNIQUE": (8.0, "채굴 시 8% 확률로 쿨타임 즉시 초기화"),
            "LEGENDARY": (15.0, "채굴 시 15% 확률로 쿨타임 즉시 초기화"),
        }
    },
    "MINING_BONUS_CASH": {
        "name": "채굴 확정 현금",
        "unit": "P",
        "icon": "🪙",
        "tiers": {
            "RARE": (3000, "매 채굴 시 확정 현금 +3,000P"),
            "EPIC": (10000, "매 채굴 시 확정 현금 +10,000P"),
            "UNIQUE": (25000, "매 채굴 시 확정 현금 +25,000P"),
            "LEGENDARY": (60000, "매 채굴 시 확정 현금 +60,000P"),
        }
    },
    "MINING_CRIT_BOOST": {
        "name": "채굴 크리티컬 확률",
        "unit": "%",
        "icon": "💥",
        "tiers": {
            "RARE": (3.0, "채굴 크리티컬 확률 +3%"),
            "EPIC": (7.0, "채굴 크리티컬 확률 +7%"),
            "UNIQUE": (14.0, "채굴 크리티컬 확률 +14%"),
            "LEGENDARY": (25.0, "채굴 크리티컬 확률 +25%"),
        }
    },
    "MINING_YIELD_BOOST": {
        "name": "채굴량 배율",
        "unit": "x",
        "icon": "⛏️",
        "tiers": {
            "RARE": (0.2, "주식 채굴량 배율 +0.2x"),
            "EPIC": (0.5, "주식 채굴량 배율 +0.5x"),
            "UNIQUE": (1.0, "주식 채굴량 배율 +1.0x"),
            "LEGENDARY": (2.0, "주식 채굴량 배율 +2.0x"),
        }
    },
    "CASINO_SLOT_BOOST": {
        "name": "슬롯 당첨금 보너스",
        "unit": "%",
        "icon": "🎰",
        "tiers": {
            "EPIC": (5.0, "슬롯 당첨 시 당첨금 +5% 보너스"),
            "UNIQUE": (9.0, "슬롯 당첨 시 당첨금 +9% 보너스"),
            "LEGENDARY": (14.0, "슬롯 당첨 시 당첨금 +14% 보너스"),
        }
    },
    "CASINO_DICE_PAYBACK": {
        "name": "주사위 패배 페이백",
        "unit": "%",
        "icon": "🎲",
        "tiers": {
            "EPIC": (8.0, "주사위 패배 시 베팅금 8% 페이백"),
            "UNIQUE": (14.0, "주사위 패배 시 베팅금 14% 페이백"),
            "LEGENDARY": (20.0, "주사위 패배 시 베팅금 20% 페이백"),
        }
    },
    "MAHJONG_TILE_BOOST": {
        "name": "마작패 화료 배당 보너스",
        "unit": "%",
        "icon": "🀄",
        "tiers": {
            "EPIC": (4.0, "마작패 맞추기 적중 시 당첨금 +4.0% 보너스"),
            "UNIQUE": (7.5, "마작패 맞추기 적중 시 당첨금 +7.5% 보너스"),
            "LEGENDARY": (11.1, "마작패 맞추기 적중 시 당첨금 +11.1% 보너스"),
        }
    },
    "RACE_SAFETY_PAYBACK": {
        "name": "역만 레이스 2등 세이프티",
        "unit": "%",
        "icon": "🏇",
        "tiers": {
            "EPIC": (15.0, "역만 경마 2등(준우승) 시 베팅금 15% 세이프티 환급"),
            "UNIQUE": (25.0, "역만 경마 2등(준우승) 시 베팅금 25% 세이프티 환급"),
            "LEGENDARY": (40.0, "역만 경마 2등(준우승) 시 베팅금 40% 세이프티 환급"),
        }
    },
    "STARFORCE_DISCOUNT": {
        "name": "스타포스 강화비 할인",
        "unit": "%",
        "icon": "🔨",
        "tiers": {
            "EPIC": (5.0, "스타포스 강화 비용 5% 상시 할인"),
            "UNIQUE": (10.0, "스타포스 강화 비용 10% 상시 할인"),
            "LEGENDARY": (20.0, "스타포스 강화 비용 20% 상시 할인"),
        }
    },
    "STARFORCE_SAFEGUARD": {
        "name": "15성+ 파괴 방지",
        "unit": "%",
        "icon": "🛡️",
        "tiers": {
            "UNIQUE": (30.0, "15성 이상 강화 실패 시 30% 확률 파괴 방지"),
            "LEGENDARY": (65.0, "15성 이상 강화 실패 시 65% 확률 파괴 방지"),
        }
    },
    "AUTO_MINING_DURATION": {
        "name": "자동채굴 시간 연장",
        "unit": "%",
        "icon": "⏰",
        "tiers": {
            "RARE": (15.0, "자동 채굴 지속 시간 +15%"),
            "EPIC": (30.0, "자동 채굴 지속 시간 +30%"),
            "UNIQUE": (60.0, "자동 채굴 지속 시간 +60%"),
            "LEGENDARY": (100.0, "자동 채굴 지속 시간 +100%"),
        }
    },
    "FEE_DISCOUNT": {
        "name": "거래 수수료 감면",
        "unit": "%",
        "icon": "📉",
        "tiers": {
            "EPIC": (15.0, "주식 거래 및 송금 수수료 15% 감면"),
            "UNIQUE": (30.0, "주식 거래 및 송금 수수료 30% 감면"),
            "LEGENDARY": (60.0, "주식 거래 및 송금 수수료 60% 감면"),
        }
    },
    "STARFORCE_SUCCESS_BOOST": {
        "name": "강화 성공률 증가 & 실패율 감소",
        "unit": "%",
        "icon": "⭐",
        "tiers": {
            "EPIC": (2.0, "스타포스 성공률 +2.0% 증가 & 실패 확률 -2.0% 감소"),
            "UNIQUE": (4.0, "스타포스 성공률 +4.0% 증가 & 실패 확률 -4.0% 감소"),
            "LEGENDARY": (8.0, "스타포스 성공률 +8.0% 증가 & 실패 확률 -8.0% 감소"),
        }
    },
    "MINING_CD_REDUCTION": {
        "name": "채굴 쿨타임 단축",
        "unit": "분",
        "icon": "⌛",
        "tiers": {
            "EPIC": (1, "채굴 기본 쿨타임 -1분 영구 단축"),
            "UNIQUE": (2, "채굴 기본 쿨타임 -2분 영구 단축"),
            "LEGENDARY": (3, "채굴 기본 쿨타임 -3분 영구 단축"),
        }
    },
    "TREASURY_LOOT_PCT": {
        "name": "국고 풀 갈취",
        "unit": "%",
        "icon": "🏛️",
        "tiers": {
            "EPIC": (0.05, "채굴 시 국고 상금풀의 0.05% 추가 갈취"),
            "UNIQUE": (0.10, "채굴 시 국고 상금풀의 0.10% 추가 갈취"),
            "LEGENDARY": (0.25, "채굴 시 국고 상금풀의 0.25% 추가 갈취"),
        }
    },
    "DIVIDEND_BOOST_PCT": {
        "name": "배당금 수령 증폭",
        "unit": "%",
        "icon": "📈",
        "tiers": {
            "RARE": (20.0, "마작 경기 배당금 수령액 +20% 증폭"),
            "EPIC": (50.0, "마작 경기 배당금 수령액 +50% 증폭"),
            "UNIQUE": (120.0, "마작 경기 배당금 수령액 +120% 증폭"),
            "LEGENDARY": (250.0, "마작 경기 배당금 수령액 +250% (3.5배!) 초대박 증폭"),
        }
    },
    "HEAVY_MINING": {
        "name": "과충전 집중 채굴",
        "unit": "분",
        "icon": "🌋",
        "tiers": {
            "RARE": (1, "쿨타임 +1분 증가하는 대신 채굴 보상(주식/현금) +50% 증폭"),
            "EPIC": (2, "쿨타임 +2분 증가하는 대신 채굴 보상(주식/현금) +100% 증폭 (2.0배)"),
            "UNIQUE": (4, "쿨타임 +4분 증가하는 대신 채굴 보상(주식/현금) +200% 증폭 (3.0배)"),
            "LEGENDARY": (7, "쿨타임 +7분 증가하는 대신 채굴 보상(주식/현금) +400% 증폭 (5.0배 초대박 한방!)"),
        }
    },
    "GOBLIN_JACKPOT_CHANCE": {
        "name": "황금 고블린 잭팟",
        "unit": "%",
        "icon": "👹",
        "tiers": {
            "RARE": (1.5, "채굴 시 1.5% 확률로 황금 고블린 토벌 (+200,000P 잭팟)"),
            "EPIC": (4.0, "채굴 시 4.0% 확률로 황금 고블린 토벌 (+600,000P 잭팟)"),
            "UNIQUE": (8.0, "채굴 시 8.0% 확률로 황금 고블린 토벌 (+1,500,000P 잭팟)"),
            "LEGENDARY": (15.0, "채굴 시 15.0% 확률로 황금 고블린 토벌 (+3,500,000P 초대형 잭팟!!)"),
        }
    },
    "LEVERAGE_20X_UNLOCK": {
        "name": "야수의 심장",
        "unit": "배",
        "icon": "🦁",
        "tiers": {
            "LEGENDARY": (20.0, "20X/40X/60X 초고배율 레버리지 & 인버스 매매 개방! (1줄: 20배, 2줄: 40배, 3줄: 60배)"),
        }
    }
}

def match_potential_target(target_str: Optional[str]) -> Tuple[Optional[str], Optional[List[str]]]:
    """Matches user input keyword to target potential codes and a friendly label."""
    if not target_str:
        return None, None
    raw = target_str.strip().lower().replace(" ", "").replace("_", "")

    # Specific options
    if any(k in raw for k in ["고블린", "황금고블린", "goblin"]):
        return "👹 황금 고블린 잭팟", ["GOBLIN_JACKPOT_CHANCE"]
    if any(k in raw for k in ["과충전", "묵직", "heavy", "오버차지"]):
        return "🌋 과충전 집중 채굴", ["HEAVY_MINING"]
    if any(k in raw for k in ["쿨초", "초기화", "reset"]):
        return "⚡ 쿨타임 즉시 초기화", ["MINING_CD_RESET"]
    if any(k in raw for k in ["쿨감", "단축", "reduction"]):
        return "⌛ 채굴 쿨타임 단축", ["MINING_CD_REDUCTION"]
    if any(k in raw for k in ["크리", "치명", "crit"]):
        return "💥 채굴 크리티컬 확률", ["MINING_CRIT_BOOST"]
    if any(k in raw for k in ["채굴량", "배율", "yield"]):
        return "⛏️ 주식 채굴량 배율", ["MINING_YIELD_BOOST"]
    if any(k in raw for k in ["현금", "캐시", "cash"]):
        return "🪙 채굴 확정 현금", ["MINING_BONUS_CASH"]
    if any(k in raw for k in ["국고", "갈취", "loot"]):
        return "🏛️ 국고 풀 갈취", ["TREASURY_LOOT_PCT"]
    if any(k in raw for k in ["자동", "지속", "auto"]):
        return "⏰ 자동채굴 시간 연장", ["AUTO_MINING_DURATION"]
    if any(k in raw for k in ["슬롯", "slot"]):
        return "🎰 슬롯 당첨금 보너스", ["CASINO_SLOT_BOOST"]
    if any(k in raw for k in ["주사위", "dice"]):
        return "🎲 주사위 패배 페이백", ["CASINO_DICE_PAYBACK"]
    if any(k in raw for k in ["마작", "화료", "mahjong"]):
        return "🀄 마작패 화료 배당 보너스", ["MAHJONG_TILE_BOOST"]
    if any(k in raw for k in ["경마", "레이스", "race"]):
        return "🏇 역만 레이스 2등 세이프티", ["RACE_SAFETY_PAYBACK"]
    if any(k in raw for k in ["파괴방지", "세이프가드", "safeguard"]):
        return "🛡️ 15성+ 파괴 방지", ["STARFORCE_SAFEGUARD"]
    if any(k in raw for k in ["성공률", "성공확률"]):
        return "⭐ 강화 성공률 증가 & 실패율 감소", ["STARFORCE_SUCCESS_BOOST"]
    if any(k in raw for k in ["할인", "강화비"]):
        return "🔨 스타포스 강화비 할인", ["STARFORCE_DISCOUNT"]
    if any(k in raw for k in ["배당", "dividend"]):
        return "📈 배당금 수령 증폭", ["DIVIDEND_BOOST_PCT"]
    if any(k in raw for k in ["수수료", "fee"]):
        return "📉 거래 수수료 감면", ["FEE_DISCOUNT"]
    if any(k in raw for k in ["야수", "레버리지", "beast"]):
        return "🦁 야수의 심장", ["LEVERAGE_20X_UNLOCK"]

    # Broad Categories
    if any(k in raw for k in ["채굴", "광부", "mining"]):
        return "⛏️ 채굴 계열 전체", [
            "MINING_CD_RESET", "MINING_BONUS_CASH", "MINING_CRIT_BOOST",
            "MINING_YIELD_BOOST", "HEAVY_MINING", "MINING_CD_REDUCTION",
            "AUTO_MINING_DURATION", "TREASURY_LOOT_PCT", "GOBLIN_JACKPOT_CHANCE"
        ]
    if any(k in raw for k in ["카지노", "도박", "casino"]):
        return "🎰 카지노 계열 전체", [
            "CASINO_SLOT_BOOST", "CASINO_DICE_PAYBACK", "MAHJONG_TILE_BOOST", "RACE_SAFETY_PAYBACK"
        ]
    if any(k in raw for k in ["강화", "스타포스", "starforce"]):
        return "⭐ 스타포스 계열 전체", [
            "STARFORCE_DISCOUNT", "STARFORCE_SAFEGUARD", "STARFORCE_SUCCESS_BOOST"
        ]
    if any(k in raw for k in ["주식", "stock"]):
        return "📈 주식/배당 계열 전체", [
            "DIVIDEND_BOOST_PCT", "FEE_DISCOUNT", "LEVERAGE_20X_UNLOCK"
        ]

    return None, None


SNIPE_TARGET_DEFINITIONS: List[Dict[str, Any]] = [
    # 1. Mining
    {
        "keyword": "고블린",
        "aliases": ["황금고블린", "goblin"],
        "category": "채굴",
        "name": "황금 고블린 잭팟",
        "icon": "👹",
        "desc": "채굴 시 확률적으로 황금 고블린을 토벌하여 거액 잭팟 현금 획득",
        "max_val": "최대 15% / +3,500,000P"
    },
    {
        "keyword": "과충전",
        "aliases": ["묵직", "heavy", "오버차지"],
        "category": "채굴",
        "name": "과충전 집중 채굴",
        "icon": "🌋",
        "desc": "쿨타임이 소폭 증가하는 대신 채굴량(주식/현금) 초대박 한방 증폭",
        "max_val": "쿨+7분 대신 보상 +400% (5.0배)"
    },
    {
        "keyword": "쿨초",
        "aliases": ["초기화", "reset"],
        "category": "채굴",
        "name": "쿨타임 즉시 초기화",
        "icon": "⚡",
        "desc": "채굴 직후 즉시 쿨타임이 0초로 리셋되어 연속 채굴 가능",
        "max_val": "최대 15% 확률로 쿨타임 즉시 0초"
    },
    {
        "keyword": "쿨감",
        "aliases": ["단축", "reduction"],
        "category": "채굴",
        "name": "채굴 쿨타임 단축",
        "icon": "⌛",
        "desc": "곡괭이의 기본 채굴 쿨타임을 영구적으로 단축",
        "max_val": "쿨타임 -3분 영구 단축"
    },
    {
        "keyword": "크리",
        "aliases": ["치명", "crit"],
        "category": "채굴",
        "name": "채굴 크리티컬 확률",
        "icon": "💥",
        "desc": "채굴 시 1.5배~3.0배 대박 크리티컬 발생 확률 대폭 증가",
        "max_val": "크리티컬 확률 +25%"
    },
    {
        "keyword": "채굴량",
        "aliases": ["배율", "yield"],
        "category": "채굴",
        "name": "주식 채굴량 배율",
        "icon": "⛏️",
        "desc": "매 채굴 시 주어지는 1X 마작 주식 기본 배율 증가",
        "max_val": "주식 채굴 배율 +2.0x"
    },
    {
        "keyword": "현금",
        "aliases": ["캐시", "cash"],
        "category": "채굴",
        "name": "채굴 확정 현금",
        "icon": "🪙",
        "desc": "채굴 성공 시마다 무조건 확정 추가 현금(P) 지급",
        "max_val": "매 채굴마다 확정 +60,000P"
    },
    {
        "keyword": "국고",
        "aliases": ["갈취", "loot"],
        "category": "채굴",
        "name": "국고 풀 갈취",
        "icon": "🏛️",
        "desc": "채굴 시 국고 상금풀의 일정 퍼센트를 추가로 털어 현금 강탈",
        "max_val": "국고 잔고의 0.25% 약탈"
    },
    {
        "keyword": "자동",
        "aliases": ["지속", "auto"],
        "category": "채굴",
        "name": "자동채굴 시간 연장",
        "icon": "⏰",
        "desc": "자동 채굴 이용권 활성화 시 지속 시간을 대폭 연장",
        "max_val": "지속 시간 +100% (2배)"
    },

    # 2. Starforce
    {
        "keyword": "성공률",
        "aliases": ["성공확률"],
        "category": "스타포스",
        "name": "강화 성공률 증가",
        "icon": "⭐",
        "desc": "스타포스 강화 성공률을 올리고 실패 확률을 직접 감소",
        "max_val": "성공률 +8.0% & 실패율 -8.0%"
    },
    {
        "keyword": "할인",
        "aliases": ["강화비"],
        "category": "스타포스",
        "name": "스타포스 강화비 할인",
        "icon": "🔨",
        "desc": "스타포스 강화 시 지불하는 포인트 비용 상시 할인",
        "max_val": "강화 비용 20% 상시 할인"
    },
    {
        "keyword": "파괴방지",
        "aliases": ["세이프가드", "safeguard"],
        "category": "스타포스",
        "name": "15성+ 파괴 방지",
        "icon": "🛡️",
        "desc": "15성 이상 위험 구간에서 파괴 실패 시 파괴를 무효화",
        "max_val": "파괴 무효화 확률 65%"
    },

    # 3. Stock & Dividend
    {
        "keyword": "배당",
        "aliases": ["dividend"],
        "category": "주식",
        "name": "배당금 수령 증폭",
        "icon": "📈",
        "desc": "마작 경기 종료 시 주주들에게 정산되는 배당금 수령액 증폭",
        "max_val": "배당금 수령액 +100% (2배!)"
    },
    {
        "keyword": "수수료",
        "aliases": ["fee"],
        "category": "주식",
        "name": "거래 수수료 감면",
        "icon": "📉",
        "desc": "주식 매매 수수료 및 P2P 송금 수수료 감면 혜택",
        "max_val": "수수료 60% 상시 감면"
    },
    {
        "keyword": "야수",
        "aliases": ["레버리지", "beast"],
        "category": "주식",
        "name": "야수의 심장",
        "icon": "🦁",
        "desc": "20X / 40X / 60X 초고배율 야수주 매매 권한 영구 해금",
        "max_val": "최대 60배 레버리지 개방"
    },

    # 4. Casino
    {
        "keyword": "슬롯",
        "aliases": ["slot"],
        "category": "카지노",
        "name": "슬롯 당첨금 보너스",
        "icon": "🎰",
        "desc": "카지노 슬롯머신 당첨 시 당첨금 추가 보너스 증폭",
        "max_val": "당첨금 +14% 보너스"
    },
    {
        "keyword": "주사위",
        "aliases": ["dice"],
        "category": "카지노",
        "name": "주사위 패배 페이백",
        "icon": "🎲",
        "desc": "카지노 주사위 배틀 패배 시 베팅 포인트 일부 환급",
        "max_val": "패배 시 20% 즉시 페이백"
    },
    {
        "keyword": "마작",
        "aliases": ["화료", "mahjong"],
        "category": "카지노",
        "name": "마작패 화료 배당 보너스",
        "icon": "🀄",
        "desc": "마작패 뽑기 맞추기 적중 시 당첨금 추가 보너스",
        "max_val": "적중 배당금 +11.1% 보너스"
    },
    {
        "keyword": "경마",
        "aliases": ["레이스", "race"],
        "category": "카지노",
        "name": "역만 레이스 2등 세이프티",
        "icon": "🏇",
        "desc": "역만 경마에서 2등(준우승) 시 베팅금 세이프티 환급",
        "max_val": "2등 시 베팅금 40% 환급"
    },

    # 5. Broad Groups
    {
        "keyword": "채굴",
        "aliases": ["광부", "mining"],
        "category": "통합",
        "name": "⛏️ 채굴 계열 종합 (9종)",
        "icon": "⛏️",
        "desc": "채굴 관련 9개 옵션 전체에 3.5배 가중치 분산 적용",
        "max_val": "채굴 9종 종합 가중치"
    },
    {
        "keyword": "스타포스",
        "aliases": ["강화", "starforce"],
        "category": "통합",
        "name": "⭐ 스타포스 계열 종합 (3종)",
        "icon": "⭐",
        "desc": "강화 관련 3개 옵션 전체에 3.5배 가중치 분산 적용",
        "max_val": "강화 3종 종합 가중치"
    },
    {
        "keyword": "주식",
        "aliases": ["stock"],
        "category": "통합",
        "name": "📈 주식/배당 계열 종합 (3종)",
        "icon": "📈",
        "desc": "주식/배당/수수료 3개 옵션 전체에 3.5배 가중치 적용",
        "max_val": "주식 3종 종합 가중치"
    },
    {
        "keyword": "카지노",
        "aliases": ["도박", "casino"],
        "category": "통합",
        "name": "🎰 카지노 계열 종합 (4종)",
        "icon": "🎰",
        "desc": "카지노 미니게임 4개 옵션 전체에 3.5배 가중치 적용",
        "max_val": "도박 4종 종합 가중치"
    }
]


def get_snipe_options_data() -> List[Dict[str, Any]]:
    """Returns structured list of all snipe target definitions."""
    return SNIPE_TARGET_DEFINITIONS


def get_snipe_options_guide_text() -> str:
    """Returns formatted guide text for potential snipe scroll options."""
    return (
        "🎯 [잠재저격주문서 옵션 키워드 전체 목록]\n"
        "💡 사용법: !큐브 [장비번호] [옵션명] 또는 !주문서 저격 [옵션명] (예: !큐브 저격 고블린)\n"
        "• 저격 주문서 사용 시 Line 1 확정 저격 확률 35% + 전 라인 3.5배 가중치 부여!\n\n"
        "⛏️ [채굴 계열]\n"
        "• 고블린: 👹 황금 고블린 잭팟 (채굴 시 최대 +350만P 잭팟)\n"
        "• 과충전: 🌋 과충전 집중 채굴 (쿨+7분 대신 보상 +400% 5배)\n"
        "• 쿨초: ⚡ 쿨타임 즉시 초기화 (채굴 시 최대 15% 쿨타임 0초)\n"
        "• 쿨감: ⌛ 채굴 쿨타임 단축 (쿨타임 -3분 영구 단축)\n"
        "• 크리: 💥 채굴 크리티컬 확률 (치명타율 최대 +25%)\n"
        "• 채굴량: ⛏️ 주식 채굴량 배율 (채굴량 최대 +2.0x)\n"
        "• 현금: 🪙 채굴 확정 현금 (매 채굴 시 확정 +6만P)\n"
        "• 국고: 🏛️ 국고 풀 갈취 (국고 잔고의 0.25% 추가 약탈)\n"
        "• 자동: ⏰ 자동채굴 시간 연장 (지속 시간 최대 +100%)\n\n"
        "⭐ [스타포스 강화 계열]\n"
        "• 성공률: ⭐ 강화 성공률 증가 & 실패율 감소 (성공률 +8%)\n"
        "• 할인: 🔨 스타포스 강화비 할인 (강화 비용 20% 상시 할인)\n"
        "• 파괴방지: 🛡️ 15성+ 파괴 방지 (15성 이상 실패 시 65% 방어)\n\n"
        "📈 [주식 & 배당 계열]\n"
        "• 배당: 📈 배당금 수령 증폭 (경기 종료 배당금 최대 2배!)\n"
        "• 수수료: 📉 거래 수수료 감면 (주식/송금 수수료 최대 60% 감면)\n"
        "• 야수: 🦁 야수의 심장 (20X~60X 초고배율 레버리지 개방)\n\n"
        "🎰 [카지노 계열]\n"
        "• 슬롯: 🎰 당첨금 보너스 (+14%) | 주사위: 🎲 패배 페이백 (20%)\n"
        "• 마작: 🀄 화료 보너스 (+11.1%) | 경마: 🏇 2등 세이프티 (40%)\n\n"
        "🌐 [통합 계열] 채굴, 스타포스, 주식, 카지노 (해당 계열 전체 분산 가중치)"
    )


def get_lower_potential_tier(tier: str) -> str:
    """Returns the tier directly below the given tier (minimum RARE)."""
    order = ["RARE", "EPIC", "UNIQUE", "LEGENDARY"]
    if tier in order:
        idx = order.index(tier)
        if idx > 0:
            return order[idx - 1]
    return "RARE"

def roll_single_potential_line(
    tier: str,
    target_codes: Optional[List[str]] = None,
    target_chance_pct: float = 0.0,
    target_weight: float = 3.5
) -> Dict[str, Any]:
    """Rolls a single potential line option for the specified tier."""
    valid_keys = [
        code for code, data in POTENTIAL_OPTIONS.items()
        if tier in data["tiers"]
    ]
    if not valid_keys:
        valid_keys = ["MINING_BONUS_CASH"]
        tier = "RARE"

    target_match = [c for c in (target_codes or []) if c in valid_keys]
    # Targeted chance (e.g. 35% for normal snipe, 88% for specific named snipe scroll)
    if target_match and target_chance_pct > 0 and random.uniform(0, 100) < target_chance_pct:
        code = random.choice(target_match)
    elif target_match:
        # Weighted probability for targeted potential codes (3.5x for normal, 10x for special)
        w = max(1.0, float(target_weight))
        weights = [w if k in target_match else 1.0 for k in valid_keys]
        code = random.choices(valid_keys, weights=weights, k=1)[0]
    else:
        code = random.choice(valid_keys)

    opt = POTENTIAL_OPTIONS[code]
    val, desc = opt["tiers"][tier]
    return {
        "code": code,
        "name": opt["name"],
        "icon": opt["icon"],
        "tier": tier,
        "val": val,
        "unit": opt["unit"],
        "text": f"{opt['icon']} {opt['name']} {desc}"
    }

def roll_cube_potential(
    tier: str,
    target_codes: Optional[List[str]] = None,
    line1_snipe_chance: float = 35.0,
    is_special_snipe: bool = False
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """
    Rolls 3 lines of potential options based on MapleStory distribution rules:
    - Line 1: Current tier (100%), targeted snipe chance (35% standard or 88% special)
    - Line 2: Current tier (50%) / 1 tier lower (50%), 3.5x~10x weight for target
    - Line 3: Current tier (20%) / 1 tier lower (80%), 3.5x~10x weight for target
    """
    tier = (tier or "RARE").upper()
    lower_tier = get_lower_potential_tier(tier)

    eff_line1_chance = float(line1_snipe_chance) if target_codes else 0.0
    sec_weight = 10.0 if is_special_snipe else 3.5

    # Line 1: 100% Current tier
    line1 = roll_single_potential_line(tier, target_codes=target_codes, target_chance_pct=eff_line1_chance, target_weight=sec_weight)

    # Line 2: 50% Current / 50% Lower (RARE is always RARE | LEGENDARY boosted to 80%)
    if tier == "RARE":
        l2_tier = "RARE"
    elif tier == "LEGENDARY":
        l2_tier = "LEGENDARY" if random.random() < 0.80 else lower_tier
    else:
        l2_tier = tier if random.random() < 0.50 else lower_tier
    line2 = roll_single_potential_line(l2_tier, target_codes=target_codes, target_chance_pct=0.0, target_weight=sec_weight)

    # Line 3: 20% Current / 80% Lower (RARE is always RARE | LEGENDARY boosted to 60%)
    if tier == "RARE":
        l3_tier = "RARE"
    elif tier == "LEGENDARY":
        l3_tier = "LEGENDARY" if random.random() < 0.60 else lower_tier
    else:
        l3_tier = tier if random.random() < 0.20 else lower_tier
    line3 = roll_single_potential_line(l3_tier, target_codes=target_codes, target_chance_pct=0.0, target_weight=sec_weight)

    # Strict Guarantee: If tier is LEGENDARY, at least 1 line is 100% guaranteed to be a LEGENDARY option!
    if tier == "LEGENDARY":
        lines = [line1, line2, line3]
        if not any(l.get("tier") == "LEGENDARY" for l in lines):
            line1 = roll_single_potential_line("LEGENDARY", target_codes=target_codes, target_chance_pct=eff_line1_chance, target_weight=sec_weight)

    return line1, line2, line3

roll_equipment_potential = roll_cube_potential

def get_equipment_potential_effects(item: Optional[UserEquipment]) -> Dict[str, Any]:
    """Aggregates all 3 potential lines from an equipment into numeric bonuses."""
    effects = {
        "cd_reset_pct": 0.0,
        "bonus_cash": 0,
        "crit_boost": 0.0,
        "yield_boost": 0.0,
        "heavy_mining_cd_add": 0,
        "heavy_mining_reward_pct": 0.0,
        "slot_payback_pct": 0.0,
        "slot_boost_pct": 0.0,
        "dice_payback_pct": 0.0,
        "mahjong_boost_pct": 0.0,
        "race_safety_pct": 0.0,
        "starforce_discount_pct": 0.0,
        "safeguard_pct": 0.0,
        "auto_duration_pct": 0.0,
        "fee_discount_pct": 0.0,
        "starforce_success_boost": 0.0,
        "mining_cd_reduction": 0,
        "treasury_loot_pct": 0.0,
        "dividend_boost_pct": 0.0,
        "goblin_chance": 0.0,
        "goblin_reward": 0,
        "leverage_20x_unlocked": False,
        "leverage_unlock_count": 0,
        "max_leverage_multiplier": 10,
    }
    if not item:
        return effects

    lines = [item.potential_line_1, item.potential_line_2, item.potential_line_3]
    for raw in lines:
        if not raw:
            continue
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            code = data.get("code")
            val = float(data.get("val", 0))
            if code == "MINING_CD_RESET":
                effects["cd_reset_pct"] += val
            elif code == "MINING_BONUS_CASH":
                effects["bonus_cash"] += int(val)
            elif code == "MINING_CRIT_BOOST":
                effects["crit_boost"] += val
            elif code == "MINING_YIELD_BOOST":
                effects["yield_boost"] += val
            elif code == "HEAVY_MINING":
                effects["heavy_mining_cd_add"] += int(val)
                line_tier = data.get("tier", "RARE")
                pct_map = {"RARE": 50.0, "EPIC": 100.0, "UNIQUE": 200.0, "LEGENDARY": 400.0}
                effects["heavy_mining_reward_pct"] += pct_map.get(line_tier, 50.0)
            elif code in ["CASINO_SLOT_PAYBACK", "CASINO_SLOT_BOOST"]:
                effects["slot_payback_pct"] += val
                effects["slot_boost_pct"] += val
            elif code == "CASINO_DICE_PAYBACK":
                effects["dice_payback_pct"] += val
            elif code == "MAHJONG_TILE_BOOST":
                effects["mahjong_boost_pct"] += val
            elif code == "RACE_SAFETY_PAYBACK":
                effects["race_safety_pct"] += val
            elif code == "STARFORCE_DISCOUNT":
                effects["starforce_discount_pct"] += val
            elif code == "STARFORCE_SAFEGUARD":
                effects["safeguard_pct"] += val
            elif code == "AUTO_MINING_DURATION":
                effects["auto_duration_pct"] += val
            elif code == "FEE_DISCOUNT":
                effects["fee_discount_pct"] += val
            elif code == "STARFORCE_SUCCESS_BOOST":
                effects["starforce_success_boost"] += val
            elif code == "MINING_CD_REDUCTION":
                effects["mining_cd_reduction"] += int(val)
            elif code == "TREASURY_LOOT_PCT":
                effects["treasury_loot_pct"] += val
            elif code == "DIVIDEND_BOOST_PCT":
                effects["dividend_boost_pct"] += val
            elif code == "GOBLIN_JACKPOT_CHANCE":
                effects["goblin_chance"] += val
                line_tier = data.get("tier", "EPIC")
                if line_tier == "RARE":
                    reward = 200000
                elif line_tier == "EPIC":
                    reward = 600000
                elif line_tier == "UNIQUE":
                    reward = 1500000
                else:  # LEGENDARY
                    reward = 3500000
                effects["goblin_reward"] += reward
            elif code == "LEVERAGE_20X_UNLOCK":
                effects["leverage_20x_unlocked"] = True
                effects["leverage_unlock_count"] += 1
        except Exception:
            continue

    # Balance caps
    effects["cd_reset_pct"] = min(70.0, effects["cd_reset_pct"])
    effects["crit_boost"] = min(100.0, effects["crit_boost"])
    effects["heavy_mining_cd_add"] = min(20, effects["heavy_mining_cd_add"])
    effects["heavy_mining_reward_pct"] = min(1200.0, effects["heavy_mining_reward_pct"])
    effects["slot_payback_pct"] = min(30.0, effects["slot_payback_pct"])
    effects["slot_boost_pct"] = min(35.0, effects["slot_boost_pct"])
    effects["dice_payback_pct"] = min(30.0, effects["dice_payback_pct"])
    effects["mahjong_boost_pct"] = min(30.0, effects["mahjong_boost_pct"])
    effects["race_safety_pct"] = min(60.0, effects["race_safety_pct"])
    effects["starforce_discount_pct"] = min(50.0, effects["starforce_discount_pct"])
    effects["safeguard_pct"] = min(90.0, effects["safeguard_pct"])
    effects["auto_duration_pct"] = min(200.0, effects["auto_duration_pct"])
    effects["fee_discount_pct"] = min(90.0, effects["fee_discount_pct"])
    effects["starforce_success_boost"] = min(20.0, effects["starforce_success_boost"])
    effects["mining_cd_reduction"] = min(8, effects["mining_cd_reduction"])
    effects["treasury_loot_pct"] = min(1.0, effects["treasury_loot_pct"])
    effects["dividend_boost_pct"] = min(750.0, effects["dividend_boost_pct"])
    effects["goblin_chance"] = min(35.0, effects["goblin_chance"])

    # Calculate maximum leverage multiplier based on Beast Heart (야수의 심장) line count
    cnt = effects["leverage_unlock_count"]
    if cnt >= 3:
        effects["max_leverage_multiplier"] = 60
    elif cnt == 2:
        effects["max_leverage_multiplier"] = 40
    elif cnt == 1:
        effects["max_leverage_multiplier"] = 20
    else:
        effects["max_leverage_multiplier"] = 10

    return effects

def get_user_fee_discount_pct(db: Session, user: User) -> float:
    """Returns total fee discount percentage from user's equipped item potential lines."""
    try:
        item = db.query(UserEquipment).filter_by(user_id=user.id, is_equipped=True).first()
        if not item:
            item = db.query(UserEquipment).filter_by(user_id=user.id).first()
        effects = get_equipment_potential_effects(item)
        return min(90.0, float(effects.get("fee_discount_pct", 0.0)))
    except Exception:
        return 0.0

def get_user_max_leverage_multiplier(db: Session, user: User) -> int:
    """Returns the maximum allowed leverage multiplier (10, 20, 40, or 60) from user's equipped item."""
    try:
        item = db.query(UserEquipment).filter_by(user_id=user.id, is_equipped=True).first()
        if not item:
            item = db.query(UserEquipment).filter_by(user_id=user.id).first()
        effects = get_equipment_potential_effects(item)
        return int(effects.get("max_leverage_multiplier", 10))
    except Exception:
        return 10

def user_has_20x_unlock(db: Session, user: User) -> bool:
    """Checks if the user has at least 20X leverage unlocked (backward compatibility)."""
    return get_user_max_leverage_multiplier(db, user) >= 20

def check_user_leverage_permission(db: Session, user: User, product_type: ProductType) -> Tuple[bool, str]:
    """
    Checks if user is authorized to trade the given product_type.
    1X ~ 10X (and INV ~ 10X_INV): default allowed (up to 10X).
    20X / 20X_INV: requires at least 1 line of [야수의 심장] (20배).
    40X / 40X_INV: requires at least 2 lines of [야수의 심장] (40배).
    60X / 60X_INV: requires at least 3 lines of [야수의 심장] (60배).
    """
    multiplier = abs(PRODUCT_MULTIPLIERS.get(product_type, 1.0))
    if multiplier <= 10.0:
        return True, ""

    max_mult = get_user_max_leverage_multiplier(db, user)
    if multiplier <= max_mult:
        return True, ""

    if multiplier > 40.0:
        req_lines = 3
    elif multiplier > 20.0:
        req_lines = 2
    else:
        req_lines = 1

    return False, f"🦁 [야수의 심장 전용] {product_type.value} 종목은 잠재능력 레전더리 옵션 [야수의 심장]이 {req_lines}줄 이상 장착되어야 거래할 수 있습니다! (현재 해금: {max_mult}배)"

def format_potential_summary(item: Optional[UserEquipment]) -> str:
    """Returns concise potential tier badge and options summary."""
    if not item:
        return ""
    tier = (item.potential_tier or "NONE").upper()
    if tier == "NONE":
        return "🔮 [잠재: 없음]"
    disp = CUBE_TIER_DISPLAY.get(tier, tier)
    return f"🔮 [{disp}]"


def parse_korean_amount(val_str: Any) -> Optional[int]:
    """Parse amounts like 10000, 10,000, 5만, 10만, 1.5만, 5천, 1억 into integer points."""
    if val_str is None:
        return None
    s = str(val_str).strip().lower().replace(",", "").replace("p", "").replace("원", "")
    if not s:
        return None
    if s.isdigit():
        return int(s)

    # 억
    m_eok = re.match(r"^(\d+(?:\.\d+)?)\s*억$", s)
    if m_eok:
        try:
            return int(round(float(m_eok.group(1)) * 100000000))
        except ValueError:
            return None

    # 만 (e.g. 5만, 1.5만, 10만)
    m_man = re.match(r"^(\d+(?:\.\d+)?)\s*만$", s)
    if m_man:
        try:
            return int(round(float(m_man.group(1)) * 10000))
        except ValueError:
            return None

    # 천 (e.g. 5천, 1.5천)
    m_cheon = re.match(r"^(\d+(?:\.\d+)?)\s*천$", s)
    if m_cheon:
        try:
            return int(round(float(m_cheon.group(1)) * 1000))
        except ValueError:
            return None

    # Compound: e.g. 5만5천 or 1만2000
    m_comp = re.match(r"^(\d+)\s*만\s*(\d+)?$", s)
    if m_comp:
        try:
            man_part = int(m_comp.group(1)) * 10000
            rem_str = m_comp.group(2)
            rem_part = int(rem_str) if rem_str else 0
            return man_part + rem_part
        except ValueError:
            return None

    try:
        f = float(s)
        return int(round(f))
    except ValueError:
        return None

def calculate_transfer_tax(amount: int) -> Tuple[int, float, str]:
    """
    Calculate transfer tax based on amount:
    - < 10,000P: 0% (면세)
    - 10,000P ~ 99,999P: 0.1% (미미한 이체 수수료)
    - >= 100,000P: 0.2% (이체 수수료)
    Returns: (tax_amount, tax_rate, tax_label)
    """
    if amount >= TRANSFER_HIGH_TAX_THRESHOLD:
        tax = max(1, int(round(amount * TRANSFER_HIGH_TAX_RATE)))
        return tax, TRANSFER_HIGH_TAX_RATE, "이체 수수료"
    elif amount >= TRANSFER_TAX_THRESHOLD:
        tax = max(1, int(round(amount * TRANSFER_TAX_RATE)))
        return tax, TRANSFER_TAX_RATE, "이체 수수료"
    else:
        return 0, 0.0, "면세"

def format_quantity(quantity: Any) -> str:
    """Safely format stock quantity: integer if whole number (e.g. 5), else 2 decimals (e.g. 5.25)."""
    try:
        f = float(quantity)
        if f.is_integer():
            return str(int(f))
        return f"{f:.2f}"
    except (ValueError, TypeError):
        return str(quantity)

def calculate_stock_price(rank_points: int) -> int:
    """1:1 Rank Point Peg with a safety floor of 100P to prevent bankruptcy."""
    return max(100, int(rank_points))

def get_market_state(db: Session) -> MarketState:
    """Retrieve market state or create default."""
    state = db.query(MarketState).filter_by(id=1).first()
    if not state:
        initial_rank = 2340
        initial_price = calculate_stock_price(initial_rank)
        state = MarketState(
            id=1,
            current_rank_name="작성3",
            current_rank_point=initial_rank,
            current_price=initial_price,
            previous_price=initial_price,
            day_open_price=initial_price,
            is_trading_locked=False,
            last_settlement_delta=0,
            treasury_pool=DEFAULT_TREASURY_POOL
        )
        db.add(state)
        db.commit()
        db.refresh(state)
    else:
        updated = False
        if not getattr(state, "current_rank_name", None):
            state.current_rank_name = "작성3"
            updated = True
        if getattr(state, "treasury_pool", None) is None or state.treasury_pool < 50000.0:
            state.treasury_pool = DEFAULT_TREASURY_POOL
            updated = True
        if getattr(state, "day_open_price", None) is None or state.day_open_price <= 0:
            state.day_open_price = state.current_price or 2340
            updated = True
        end_time = getattr(state, "free_trading_end_time", 0.0) or 0.0
        if not state.is_trading_locked and end_time > 0 and time.time() >= end_time:
            state.is_trading_locked = True
            state.free_trading_end_time = 0.0
            updated = True
        if updated:
            try:
                db.commit()
                db.refresh(state)
            except Exception:
                pass
    return state

def set_day_open_price(db: Session, price: Optional[int] = None) -> int:
    """Set today's opening rank point / stock price baseline."""
    state = get_market_state(db)
    target_price = int(price) if price is not None and int(price) > 0 else state.current_price
    state.day_open_price = target_price
    db.commit()
    db.refresh(state)
    return target_price

def is_market_locked(db: Session, state: Optional[MarketState] = None) -> bool:
    """
    Checks if the trading market is currently locked.
    Enforces lock if:
    1. state.is_trading_locked == True
    2. free_trading_end_time was set and has expired (time.time() >= free_trading_end_time)
    If expired, automatically updates state.is_trading_locked = True in DB.
    """
    if not state:
        state = get_market_state(db)

    if getattr(state, "is_trading_locked", False):
        return True

    end_time = getattr(state, "free_trading_end_time", 0.0) or 0.0
    if end_time > 0 and time.time() >= end_time:
        state.is_trading_locked = True
        state.free_trading_end_time = 0.0
        try:
            db.commit()
            db.refresh(state)
        except Exception:
            pass
        return True

    return False

def get_user_by_identifier(db: Session, identifier: str) -> Optional[User]:
    """Find user by exact ID or exact/case-insensitive username."""
    if not identifier:
        return None
    clean = identifier.strip()
    # 1. By ID
    u = db.query(User).filter_by(id=clean).first()
    if u:
        return u
    # 2. By Username (exact)
    u = db.query(User).filter_by(username=clean).first()
    if u:
        return u
    # 3. By Username (case-insensitive)
    u = db.query(User).filter(User.username.ilike(clean)).first()
    return u

def get_or_create_user(db: Session, user_id: str, username: str) -> User:
    """Find or initialize user with starting points (50,000P). Resolves by ID or Username."""
    # 1. Search by user_id
    user = db.query(User).filter_by(id=user_id).first()

    # 2. Search by username if not found
    if not user and username:
        user = db.query(User).filter_by(username=username).first()
        if not user:
            user = db.query(User).filter(User.username.ilike(username.strip())).first()

    # 3. Check if user_id was passed as username
    if not user and user_id:
        user = db.query(User).filter_by(username=user_id).first()
        if not user:
            user = db.query(User).filter(User.username.ilike(user_id.strip())).first()

    if not user:
        user = User(id=user_id, username=username or user_id, points=STARTING_POINTS)
        db.add(user)
        db.commit()
        db.refresh(user)
    elif username and user.username != username and not user.username.startswith("chzzk_"):
        user.username = username
        db.commit()
    return user

def calculate_position_valuation(position: Position, current_base_price: int) -> Dict[str, Any]:
    """Calculate the real-time market value, unrealized PnL, and effective unit price of a position."""
    if not position or position.quantity <= 0 or position.invested_cash <= 0:
        return {
            "current_value": 0.0,
            "unit_price": float(current_base_price),
            "unrealized_pnl": 0.0,
            "pnl_pct": 0.0,
        }

    entry = position.entry_price if position.entry_price > 0 else float(current_base_price)
    base_return = (current_base_price - entry) / entry if entry > 0 else 0.0
    multiplier = PRODUCT_MULTIPLIERS.get(position.product_type, 1.0)
    product_return = base_return * multiplier

    # Total current valuation of this position
    current_value = max(0.0, position.invested_cash * (1.0 + product_return))
    unrealized_pnl = current_value - position.invested_cash
    pnl_pct = product_return * 100.0
    unit_price = current_value / position.quantity if position.quantity > 0 else float(current_base_price)

    return {
        "current_value": current_value,
        "unit_price": unit_price,
        "unrealized_pnl": unrealized_pnl,
        "pnl_pct": pnl_pct,
    }

def get_user_credit_info(
    user: User,
    db: Optional[Session] = None,
    market_state: Optional[MarketState] = None
) -> Dict[str, Any]:
    """
    Computes real-time dynamic credit rating (신용등급), credit score (0~1000),
    personalized margin loan limit, and interest rate.
    
    Scoring model:
    - Base: 500 pts (BB tier)
    - Net Worth / Assets: -150 ~ +200 pts
    - Collateral / Equipment: 0 ~ +180 pts
    - Income / Mining: 0 ~ +120 pts
    - Repayment History: 0 ~ +150 pts
    - Donation VIP: 0 ~ +80 pts
    - Debt Overleverage: 0 ~ -200 pts
    - Bankruptcy history: -350 pts
    """
    cash = int(getattr(user, "points", 0) or 0)
    debt = int(getattr(user, "debt", 0) or 0)
    total_mined = float(getattr(user, "total_mined", 0.0) or 0.0)
    repay_count = int(getattr(user, "repay_count", 0) or 0)
    total_repaid = int(getattr(user, "total_repaid", 0) or 0)

    # 1. Position stock valuation
    stock_value = 0.0
    current_price = 2340
    if market_state is not None:
        current_price = getattr(market_state, "current_price", 2340) or 2340
    elif db is not None:
        try:
            st = get_market_state(db)
            if st:
                current_price = getattr(st, "current_price", 2340) or 2340
        except Exception:
            pass

    positions = getattr(user, "positions", None)
    if positions:
        for p in positions:
            if getattr(p, "quantity", 0) > 0:
                try:
                    val = calculate_position_valuation(p, current_price)
                    stock_value += val.get("current_value", 0.0)
                except Exception:
                    pass

    net_worth = int(round(cash + stock_value - debt))

    # Factor 1: Net Worth score (-150 ~ +200)
    if net_worth >= 100000000:
        asset_score = 200
    elif net_worth >= 30000000:
        asset_score = 160
    elif net_worth >= 10000000:
        asset_score = 120
    elif net_worth >= 3000000:
        asset_score = 80
    elif net_worth >= 1000000:
        asset_score = 50
    elif net_worth >= 100000:
        asset_score = 25
    elif net_worth >= 0:
        asset_score = 0
    elif net_worth >= -500000:
        asset_score = -50
    elif net_worth >= -2000000:
        asset_score = -100
    else:
        asset_score = -150

    # Factor 2: Collateral Equipment score (0 ~ +180)
    collateral_score = 0
    equipped = None
    equipments = getattr(user, "equipments", None)
    if equipments:
        for eq in equipments:
            if getattr(eq, "is_equipped", False):
                equipped = eq
                break
        if not equipped and len(equipments) > 0:
            equipped = max(equipments, key=lambda e: getattr(e, "starforce", 0) or 0)

    if equipped:
        ename = getattr(equipped, "name", "")
        if "다이아" in ename:
            collateral_score += 60
        elif "백금" in ename:
            collateral_score += 45
        elif "황금" in ename:
            collateral_score += 30
        elif "은" in ename:
            collateral_score += 15
        else:
            collateral_score += 5

        sf = int(getattr(equipped, "starforce", 0) or 0)
        collateral_score += min(75, sf * 3)

        pot = (getattr(equipped, "potential_tier", "") or "").upper()
        if pot == "LEGENDARY":
            collateral_score += 45
        elif pot == "UNIQUE":
            collateral_score += 30
        elif pot == "EPIC":
            collateral_score += 20
        elif pot == "RARE":
            collateral_score += 10
    else:
        pick_lvl = getattr(user, "pickaxe_level", 1) or 1
        if pick_lvl >= 5:
            collateral_score += 60
        elif pick_lvl == 4:
            collateral_score += 45
        elif pick_lvl == 3:
            collateral_score += 30
        elif pick_lvl == 2:
            collateral_score += 15
        else:
            collateral_score += 5

    # Factor 3: Income / Mining score (0 ~ +120)
    if total_mined >= 5000000:
        mining_score = 120
    elif total_mined >= 1000000:
        mining_score = 90
    elif total_mined >= 200000:
        mining_score = 60
    elif total_mined >= 50000:
        mining_score = 30
    elif total_mined >= 10000:
        mining_score = 15
    else:
        mining_score = 0

    # Factor 4: Repayment History score (0 ~ +150)
    cnt_pts = min(60, repay_count * 10)
    if total_repaid >= 10000000:
        amt_pts = 90
    elif total_repaid >= 3000000:
        amt_pts = 60
    elif total_repaid >= 1000000:
        amt_pts = 40
    elif total_repaid >= 200000:
        amt_pts = 20
    elif total_repaid >= 1:
        amt_pts = 10
    else:
        amt_pts = 0
    repayment_score = cnt_pts + amt_pts

    # Factor 5: Donation VIP score (0 ~ +80)
    donation_score = 0
    donations = getattr(user, "donations", None)
    if donations:
        d_cnt = len(donations)
        if d_cnt >= 5:
            donation_score = 80
        elif d_cnt >= 2:
            donation_score = 50
        elif d_cnt >= 1:
            donation_score = 30

    # Factor 6: Debt Overleverage penalty (0 ~ -200)
    gross_assets = max(0.0, cash + stock_value)
    if debt <= 0:
        debt_penalty = 20  # clean credit bonus!
    else:
        if gross_assets <= 0:
            debt_penalty = -200
        else:
            ratio = debt / gross_assets
            if ratio > 2.0:
                debt_penalty = -200
            elif ratio > 1.2:
                debt_penalty = -120
            elif ratio > 0.7:
                debt_penalty = -60
            elif ratio > 0.3:
                debt_penalty = -20
            else:
                debt_penalty = 0

    # Factor 7: Bankruptcy Penalty (0 ~ -350)
    bankruptcy_penalty = 0
    if getattr(user, "last_bankrupt_at", None) is not None:
        bankruptcy_penalty = -350

    # Compute Total Score clamped [0, 1000]
    raw_score = (
        500
        + asset_score
        + collateral_score
        + mining_score
        + repayment_score
        + donation_score
        + debt_penalty
        + bankruptcy_penalty
    )
    final_score = max(0, min(1000, int(round(raw_score))))

    # Match tier
    tier_info = CREDIT_TIERS[-1]  # default to lowest
    for t in CREDIT_TIERS:
        if final_score >= t[0]:
            tier_info = t
            break

    _, tier_num, grade_str, tier_name_str, limit_val, interest_val = tier_info
    avail_val = max(0, limit_val - debt)

    return {
        "score": final_score,
        "tier": tier_num,
        "grade": grade_str,
        "tier_name": tier_name_str,
        "loan_limit": limit_val,
        "available_borrow": avail_val,
        "interest_rate": interest_val,
        "interest_rate_pct": round(interest_val * 100.0, 1),
        "limit": limit_val,
        "available": avail_val,
        "rate_pct": round(interest_val * 100.0, 1),
        "debt": debt,
        "net_worth": net_worth,
        "cash": cash,
        "stock_value": stock_value,
        "factors": {
            "asset_score": asset_score,
            "collateral_score": collateral_score,
            "mining_score": mining_score,
            "repayment_score": repayment_score,
            "donation_score": donation_score,
            "debt_penalty": debt_penalty,
            "bankruptcy_penalty": bankruptcy_penalty
        }
    }

def get_user_loan_limit(db: Session, user: User) -> int:
    """Returns the maximum loan limit for the user based on dynamic credit rating."""
    info = get_user_credit_info(user, db=db)
    return info["loan_limit"]

def format_user_credit_report(user: User, db: Session) -> str:
    """Formats a detailed credit rating report for chat display."""
    info = get_user_credit_info(user, db=db)
    f = info["factors"]
    plus_minus = lambda v: f"+{v}" if v > 0 else str(v)

    report = (
        f"💳 [나베신용평가원] {user.username}님의 신용평가 보고서\n"
        f"• 신용등급: {info['tier_name']} (신용점수: {info['score']}점 / 1,000점)\n"
        f"• 대출 한도: {info['loan_limit']:,}P (현재 빚: {info['debt']:,}P | 대출 가능: {info['available_borrow']:,}P)\n"
        f"• 적용 금리: 경기당 {info['interest_rate_pct']:.1f}% (기준금리 2.0%)\n"
        f"• 신용 평가 요인:\n"
        f"  - 순자산: {info['net_worth']:,}P ({plus_minus(f['asset_score'])}점)\n"
        f"  - 장비/담보: {plus_minus(f['collateral_score'])}점 | 채굴 실적: {plus_minus(f['mining_score'])}점\n"
        f"  - 상환 실적: {plus_minus(f['repayment_score'])}점 | 부채 위험도: {plus_minus(f['debt_penalty'])}점"
    )
    if f["bankruptcy_penalty"] < 0:
        report += f"\n  - ⚠️ 파산 이력 감점: {f['bankruptcy_penalty']}점"
    report += "\n💡 신용 올리기: 성실한 채굴, 곡괭이 강화, 대출금 정상 상환 시 신용점수가 대폭 상승합니다!"
    return report

def execute_buy(
    db: Session,
    user_id: str,
    username: str,
    product_str: str,
    quantity_str: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Execute market buy order."""
    state = get_market_state(db)
    if is_market_locked(db, state):
        db.rollback()
        return False, "⚠️ [거래 마감] 경기가 진행 중이므로 매수할 수 없습니다. (조회 명령만 가능)", None

    product_type = parse_product_type(product_str)
    if not product_type:
        return False, f"⚠️ 알 수 없는 종목입니다: '{product_str}' (지원: {SUPPORTED_PRODUCTS_GUIDE})", None
    product_str = product_type.value

    user = get_or_create_user(db, user_id, username)
    allowed, err_msg = check_user_leverage_permission(db, user, product_type)
    if not allowed:
        return False, err_msg, None
    current_price = state.current_price

    # Determine quantity
    clean_qty_str = quantity_str.strip()
    for unit in ["주", "개"]:
        if clean_qty_str.endswith(unit) and len(clean_qty_str) > len(unit):
            candidate = clean_qty_str[:-len(unit)].strip()
            try:
                float(candidate)
                clean_qty_str = candidate
                break
            except ValueError:
                pass

    if clean_qty_str in ["빚올인", "빚으로올인", "대출올인", "신용올인", "빚투"]:
        return execute_margin_buy(db, user_id, username, product_str, "올인")

    if clean_qty_str in ["올인", "all", "전액", "풀매수", "올인매수", "전액매수", "최대", "전부", "다"]:
        quantity = math.floor(user.points / (current_price * (1.0 + TRADING_FEE_RATE)))
        if quantity <= 0:
            current_debt = getattr(user, "debt", 0) or 0
            credit_info = get_user_credit_info(user, db=db, market_state=state)
            avail_loan = max(0, credit_info["loan_limit"] - current_debt)
            treasury_avail = int(getattr(state, "treasury_pool", DEFAULT_TREASURY_POOL) or 0)
            actual_avail = min(avail_loan, treasury_avail)
            if actual_avail > 0:
                return False, (
                    f"⚠️ 보유 포인트가 부족하여 올인 매수할 수 없습니다 (보유: {user.points:,}P, 1주 필요: {int(current_price * (1.0 + TRADING_FEE_RATE)):,}P). "
                    f"💡 빚(국고 대출)으로 올인하시려면 '!매수 {product_type.value} 빚올인' 또는 '!빚올인 {product_type.value}'을 입력하세요! (신용: {credit_info['tier_name']}, 대출 가능: {actual_avail:,}P)"
                ), None
            return False, f"⚠️ 포인트가 부족하여 올인 매수할 수 없습니다. (보유: {user.points:,}P, 현재가: {current_price:,}P, 수수료: 1%)", None
    else:
        try:
            quantity = float(clean_qty_str)
            if quantity <= 0:
                return False, "⚠️ 매수 수량은 0보다 커야 합니다.", None
        except ValueError:
            return False, f"⚠️ 유효하지 않은 수량입니다: '{quantity_str}' (수량 숫자 또는 '올인' 입력)", None

    fee_disc = get_user_fee_discount_pct(db, user)
    eff_fee_rate = TRADING_FEE_RATE * (1.0 - fee_disc / 100.0) if fee_disc > 0 else TRADING_FEE_RATE
    cost = int(round(quantity * current_price))
    fee = max(0 if fee_disc > 0 else 1, int(round(cost * eff_fee_rate))) if cost > 0 else 0
    total_deduct = cost + fee

    while total_deduct > user.points and quantity > 0:
        quantity -= 1
        cost = int(round(quantity * current_price))
        fee = max(0 if fee_disc > 0 else 1, int(round(cost * eff_fee_rate))) if cost > 0 else 0
        total_deduct = cost + fee

    if quantity <= 0 or user.points < total_deduct:
        return False, f"⚠️ 잔여 포인트 부족! 필요: {total_deduct:,}P (체결금 {cost:,}P + 수수료 {fee:,}P) | 보유: {user.points:,}P", None

    # Deduct cash & accumulate fee to Treasury Pool
    user.points -= total_deduct
    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL
    state.treasury_pool += fee

    # Update or create position
    pos = db.query(Position).filter_by(user_id=user.id, product_type=product_type).first()
    if pos and pos.quantity > 0:
        new_quantity = pos.quantity + quantity
        new_invested = pos.invested_cash + cost
        weighted_entry = new_invested / new_quantity
        pos.quantity = new_quantity
        pos.invested_cash = new_invested
        pos.entry_price = weighted_entry
    else:
        if not pos:
            pos = Position(
                user_id=user.id,
                product_type=product_type,
                quantity=quantity,
                entry_price=float(current_price),
                invested_cash=float(cost)
            )
            db.add(pos)
        else:
            pos.quantity = quantity
            pos.entry_price = float(current_price)
            pos.invested_cash = float(cost)

    db.commit()
    db.refresh(user)
    db.refresh(pos)

    qty_display = format_quantity(quantity)
    is_allin = clean_qty_str in ["올인", "all", "전액", "풀매수", "올인매수", "전액매수", "최대", "전부", "다"]
    allin_label = "전액 올인 " if is_allin else ""
    msg = (
        f"✅ [매수 체결] [구매 완료] {user.username}님이 {product_type.value} {qty_display}주(총 {cost:,}P)를 "
        f"{allin_label}구매했습니다! "
        f"(매수 완료 | 체결단가: {current_price:,}P, 수수료: {fee:,}P 국고 적립, 잔여: {user.points:,}P)"
    )
    return True, msg, {
        "user_id": user.id,
        "username": user.username,
        "product_type": product_type.value,
        "quantity": quantity,
        "price": current_price,
        "cost": cost,
        "fee": fee,
        "total_cost": total_deduct,
        "remaining_points": user.points,
        "treasury_pool": state.treasury_pool
    }

def execute_margin_buy(
    db: Session,
    user_id: str,
    username: str,
    product_str: str,
    quantity_str: str = "올인"
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Execute Margin Buy / 빚으로 올인:
    Borrow available credit from community treasury pool (up to MAX_LOAN_LIMIT)
    and immediately invest all available points into the target stock product.
    """
    state = get_market_state(db)
    if is_market_locked(db, state):
        db.rollback()
        return False, "⚠️ [거래 마감] 경기가 진행 중이므로 매수할 수 없습니다. (조회 명령만 가능)", None

    product_type = parse_product_type(product_str)
    if not product_type:
        return False, f"⚠️ 알 수 없는 종목입니다: '{product_str}' (지원: {SUPPORTED_PRODUCTS_GUIDE})", None
    product_str = product_type.value

    user = get_or_create_user(db, user_id, username)
    allowed, err_msg = check_user_leverage_permission(db, user, product_type)
    if not allowed:
        return False, err_msg, None
    current_price = state.current_price
    current_debt = getattr(user, "debt", 0) or 0

    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL

    credit_info = get_user_credit_info(user, db=db, market_state=state)
    user_loan_limit = credit_info["loan_limit"]

    # Calculate borrowable capacity
    max_borrow = max(0, user_loan_limit - current_debt)
    borrow_amount = min(max_borrow, int(state.treasury_pool))

    # If user has borrowable room and treasury has funds, borrow first
    if borrow_amount > 0:
        state.treasury_pool -= borrow_amount
        user.debt = current_debt + borrow_amount
        user.points += borrow_amount

    # Now calculate buy quantity with total cash
    clean_qty_str = (quantity_str or "올인").strip()
    if clean_qty_str in ["올인", "all", "전액", "풀매수", "올인매수", "전액매수", "최대", "전부", "다", "빚올인", "빚으로올인", "대출올인", "신용올인", "빚투"]:
        quantity = math.floor(user.points / (current_price * (1.0 + TRADING_FEE_RATE)))
        if quantity <= 0:
            db.commit()
            if borrow_amount > 0:
                return False, f"⚠️ 국고에서 {borrow_amount:,}P를 대출하였으나 현재 주가({current_price:,}P) 1주를 매수하기에 부족합니다. (보유 현금: {user.points:,}P, 총 빚: {user.debt:,}P)", None
            return False, f"⚠️ 이미 {user.username}님의 신용등급({credit_info['tier_name']}) 최대 대출 한도({user_loan_limit:,}P)에 도달하였고 잔여 포인트({user.points:,}P)도 부족하여 매수할 수 없습니다. (총 빚: {user.debt:,}P)", None
    else:
        try:
            quantity = float(clean_qty_str)
            if quantity <= 0:
                return False, "⚠️ 매수 수량은 0보다 커야 합니다.", None
        except ValueError:
            return False, f"⚠️ 유효하지 않은 수량입니다: '{quantity_str}' (수량 숫자 또는 '올인' 입력)", None

    cost = int(round(quantity * current_price))
    fee = max(1, int(round(cost * TRADING_FEE_RATE))) if cost > 0 else 0
    total_deduct = cost + fee

    while total_deduct > user.points and quantity > 0:
        quantity -= 1
        cost = int(round(quantity * current_price))
        fee = max(1, int(round(cost * TRADING_FEE_RATE))) if cost > 0 else 0
        total_deduct = cost + fee

    if quantity <= 0 or user.points < total_deduct:
        db.commit()
        return False, f"⚠️ 잔여 포인트 부족! 필요: {total_deduct:,}P (체결금 {cost:,}P + 수수료 {fee:,}P) | 보유 현금: {user.points:,}P (빚: {user.debt:,}P)", None

    # Deduct cash & accumulate fee to Treasury Pool
    user.points -= total_deduct
    state.treasury_pool += fee

    # Update or create position
    pos = db.query(Position).filter_by(user_id=user.id, product_type=product_type).first()
    if pos and pos.quantity > 0:
        new_quantity = pos.quantity + quantity
        new_invested = pos.invested_cash + cost
        weighted_entry = new_invested / new_quantity
        pos.quantity = new_quantity
        pos.invested_cash = new_invested
        pos.entry_price = weighted_entry
    else:
        if not pos:
            pos = Position(
                user_id=user.id,
                product_type=product_type,
                quantity=quantity,
                entry_price=float(current_price),
                invested_cash=float(cost)
            )
            db.add(pos)
        else:
            pos.quantity = quantity
            pos.entry_price = float(current_price)
            pos.invested_cash = float(cost)

    db.commit()
    db.refresh(user)
    db.refresh(pos)
    db.refresh(state)

    qty_display = format_quantity(quantity)
    if borrow_amount > 0:
        msg = (
            f"💳🔥 [빚투 / 신용 올인 체결] {user.username}님 국고 대출 {borrow_amount:,}P 실행 후 "
            f"{product_type.value} {qty_display}주(총 {cost:,}P)를 전액 올인 구매했습니다! (풀매수 완료 | "
            f"체결단가: {current_price:,}P | 총 채무: {user.debt:,}P | 잔여 현금: {user.points:,}P)"
        )
    else:
        msg = (
            f"✅ [매수 체결] [구매 완료] {user.username}님이 {product_type.value} {qty_display}주(총 {cost:,}P)를 전액 올인 구매했습니다! (매수 완료 | "
            f"체결단가: {current_price:,}P, 수수료: {fee:,}P 국고 적립, 잔여: {user.points:,}P)"
        )

    return True, msg, {
        "user_id": user.id,
        "username": user.username,
        "product_type": product_type.value,
        "quantity": quantity,
        "price": current_price,
        "cost": cost,
        "fee": fee,
        "total_cost": total_deduct,
        "borrowed_amount": borrow_amount,
        "total_debt": user.debt,
        "remaining_points": user.points,
        "treasury_pool": state.treasury_pool
    }

def execute_sell(
    db: Session,
    user_id: str,
    username: str,
    product_str: str,
    quantity_str: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Execute market sell order."""
    state = get_market_state(db)
    if is_market_locked(db, state):
        db.rollback()
        return False, "⚠️ [거래 마감] 경기가 진행 중이므로 매도할 수 없습니다. (조회 명령만 가능)", None

    product_type = parse_product_type(product_str)
    if not product_type:
        return False, f"⚠️ 알 수 없는 종목입니다: '{product_str}' (지원: {SUPPORTED_PRODUCTS_GUIDE})", None
    product_str = product_type.value

    user = get_or_create_user(db, user_id, username)
    pos = db.query(Position).filter_by(user_id=user.id, product_type=product_type).first()

    if not pos or pos.quantity <= 0:
        return False, f"⚠️ {user.username}님은 {product_type.value} 포지션을 보유하고 있지 않습니다.", None

    clean_qty = quantity_str.strip()
    for unit in ["주", "개"]:
        if clean_qty.endswith(unit) and len(clean_qty) > len(unit):
            candidate = clean_qty[:-len(unit)].strip()
            try:
                float(candidate)
                clean_qty = candidate
                break
            except ValueError:
                pass

    if clean_qty in ["전량", "all", "모두", "올인", "전부", "다", "최대", "풀매도", "전액"]:
        sell_qty = pos.quantity
    else:
        try:
            sell_qty = float(clean_qty)
            if sell_qty <= 0:
                return False, "⚠️ 매도 수량은 0보다 커야 합니다.", None
            if sell_qty > pos.quantity + 1e-9:
                qty_has = format_quantity(pos.quantity)
                return False, f"⚠️ 보유 수량을 초과했습니다! (현재 보유: {qty_has}주)", None
        except ValueError:
            return False, f"⚠️ 유효하지 않은 수량입니다: '{quantity_str}' (수량 숫자 또는 '전량' 입력)", None

    val = calculate_position_valuation(pos, state.current_price)
    ratio = min(1.0, sell_qty / pos.quantity)
    gross_payout = int(round(val["current_value"] * ratio))
    fee_disc = get_user_fee_discount_pct(db, user)
    eff_fee_rate = TRADING_FEE_RATE * (1.0 - fee_disc / 100.0) if fee_disc > 0 else TRADING_FEE_RATE
    fee = max(0 if fee_disc > 0 else 1, int(round(gross_payout * eff_fee_rate))) if gross_payout > 0 else 0
    net_payout = max(0, gross_payout - fee)
    invested_part = pos.invested_cash * ratio
    pnl = net_payout - invested_part
    pnl_pct = (pnl / invested_part * 100.0) if invested_part > 0 else 0.0

    # Credit net points & accumulate fee to Treasury Pool
    user.points += net_payout
    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL
    state.treasury_pool += fee

    # Adjust position
    pos.quantity = max(0.0, pos.quantity - sell_qty)
    pos.invested_cash = max(0.0, pos.invested_cash - invested_part)
    if pos.quantity <= 1e-6 or pos.invested_cash <= 0:
        pos.quantity = 0.0
        pos.invested_cash = 0.0
        pos.entry_price = 0.0

    db.commit()
    db.refresh(user)

    qty_display = format_quantity(sell_qty)
    sign = "+" if pnl >= 0 else ""
    msg = f"✅ [매도 체결 / 판매 완료] {user.username}님이 {product_type.value} {qty_display}주를 판매했습니다! (매도 완료 | +{net_payout:,}P 입금, 수수료: {fee:,}P 국고 적립, 손익: {sign}{int(round(pnl)):,}P / {sign}{pnl_pct:.1f}%)"

    return True, msg, {
        "user_id": user.id,
        "username": user.username,
        "product_type": product_type.value,
        "quantity": sell_qty,
        "payout": net_payout,
        "gross_payout": gross_payout,
        "fee": fee,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "remaining_points": user.points,
        "treasury_pool": state.treasury_pool
    }

def execute_liquidate(
    db: Session,
    user_id: str,
    username: str,
    target_str: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Execute user-requested instant market liquidation (!청산 [종목/전량]).
    Sells position(s) at current market value immediately.
    """
    state = get_market_state(db)
    if is_market_locked(db, state):
        db.rollback()
        return False, "⚠️ [거래 마감] 경기가 진행 중이므로 청산할 수 없습니다.", None

    user = get_or_create_user(db, user_id, username)
    clean_target = target_str.strip()

    if clean_target in ["전량", "all", "모두", "전체"]:
        positions = db.query(Position).filter(Position.user_id == user.id, Position.quantity > 0).all()
        if not positions:
            return False, f"⚠️ {user.username}님은 보유 중인 포지션이 없습니다.", None

        total_gross_payout = 0
        total_invested = 0.0
        closed_details = []

        for p in positions:
            val = calculate_position_valuation(p, state.current_price)
            payout = int(round(val["current_value"]))
            total_gross_payout += payout
            total_invested += p.invested_cash
            closed_details.append(f"{p.product_type.value}({int(payout):,}P)")
            p.quantity = 0.0
            p.invested_cash = 0.0
            p.entry_price = 0.0

        fee = max(1, int(round(total_gross_payout * TRADING_FEE_RATE))) if total_gross_payout > 0 else 0
        net_payout = max(0, total_gross_payout - fee)
        total_pnl = net_payout - total_invested

        user.points += net_payout
        if getattr(state, "treasury_pool", None) is None:
            state.treasury_pool = DEFAULT_TREASURY_POOL
        state.treasury_pool += fee
        db.commit()

        sign = "+" if total_pnl >= 0 else ""
        msg = f"⚡ [전량 청산 완료] {user.username}님의 모든 포지션 즉시 정리 완료! (회수: +{net_payout:,}P, 수수료: {fee:,}P 국고 적립, 손익: {sign}{int(round(total_pnl)):,}P | 종목: {', '.join(closed_details)})"
        return True, msg, {
            "user_id": user.id,
            "username": user.username,
            "total_payout": net_payout,
            "gross_payout": total_gross_payout,
            "fee": fee,
            "total_pnl": total_pnl,
            "remaining_points": user.points,
            "treasury_pool": state.treasury_pool
        }
    else:
        # Liquidate specific product
        product_type = parse_product_type(clean_target)
        if not product_type:
            return False, f"⚠️ 청산 대상이 올바르지 않습니다: '{target_str}' (예: !청산 전량, !청산 2X)", None
        return execute_sell(db, user_id, username, product_type.value, "전량")

def register_limit_order(
    db: Session,
    user_id: str,
    username: str,
    order_type_str: str,
    product_str: str,
    target_price_str: str,
    quantity_str: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Register limit order (!지정가 [매수/매도] [종목] [목표가] [수량])."""
    state = get_market_state(db)
    if is_market_locked(db, state):
        db.rollback()
        return False, "⚠️ [거래 마감] 경기가 진행 중이므로 지정가 주문을 접수할 수 없습니다.", None

    # Parse order type
    clean_ot = order_type_str.strip().upper()
    if clean_ot in ["매수", "BUY"]:
        order_type = OrderType.BUY
    elif clean_ot in ["매도", "SELL"]:
        order_type = OrderType.SELL
    else:
        return False, f"⚠️ 주문 유형은 '매수' 또는 '매도'여야 합니다: '{order_type_str}'", None

    product_type = parse_product_type(product_str)
    if not product_type:
        return False, f"⚠️ 알 수 없는 종목입니다: '{product_str}' (지원: {SUPPORTED_PRODUCTS_GUIDE})", None
    product_str = product_type.value

    try:
        target_price = float(target_price_str)
        if target_price <= 0:
            return False, "⚠️ 목표가는 0보다 커야 합니다.", None
    except ValueError:
        return False, f"⚠️ 목표가가 올바른 숫자가 아닙니다: '{target_price_str}'", None

    try:
        quantity = float(quantity_str)
        if quantity <= 0:
            return False, "⚠️ 주문 수량은 0보다 커야 합니다.", None
    except ValueError:
        return False, f"⚠️ 주문 수량이 올바른 숫자가 아닙니다: '{quantity_str}'", None

    user = get_or_create_user(db, user_id, username)
    if order_type == OrderType.BUY:
        allowed, err_msg = check_user_leverage_permission(db, user, product_type)
        if not allowed:
            return False, err_msg, None
    current_price = state.current_price

    if order_type == OrderType.BUY:
        # Check cash and reserve
        cost_reserved = int(round(target_price * quantity))
        fee_reserved = max(1, int(round(cost_reserved * TRADING_FEE_RATE))) if cost_reserved > 0 else 0
        total_reserved = cost_reserved + fee_reserved
        if user.points < total_reserved:
            return False, f"⚠️ 잔여 포인트 부족! 예약 필요금: {total_reserved:,}P (수수료 {fee_reserved:,}P 포함) | 보유: {user.points:,}P", None

        # Check if immediate fill
        if current_price <= target_price:
            actual_cost = int(round(current_price * quantity))
            fee = max(1, int(round(actual_cost * TRADING_FEE_RATE))) if actual_cost > 0 else 0
            total_deduct = actual_cost + fee
            user.points -= total_deduct
            if getattr(state, "treasury_pool", None) is None:
                state.treasury_pool = DEFAULT_TREASURY_POOL
            state.treasury_pool += fee

            pos = db.query(Position).filter_by(user_id=user.id, product_type=product_type).first()
            if pos and pos.quantity > 0:
                pos.quantity += quantity
                pos.invested_cash += actual_cost
                pos.entry_price = pos.invested_cash / pos.quantity
            else:
                if not pos:
                    pos = Position(
                        user_id=user.id,
                        product_type=product_type,
                        quantity=quantity,
                        entry_price=float(current_price),
                        invested_cash=float(actual_cost)
                    )
                    db.add(pos)
                else:
                    pos.quantity = quantity
                    pos.entry_price = float(current_price)
                    pos.invested_cash = float(actual_cost)

            order = LimitOrder(
                user_id=user.id,
                order_type=order_type,
                product_type=product_type,
                target_price=target_price,
                quantity=quantity,
                status=OrderStatus.FILLED
            )
            db.add(order)
            db.commit()
            qty_display = format_quantity(quantity)
            msg = f"✅ [지정가 매수 즉시 체결] 현재가({current_price:,}P)가 목표가({target_price:g}P) 이하이므로 즉시 체결되었습니다! ({product_type.value} {qty_display}주, 수수료: {fee:,}P 국고 적립, 잔여: {user.points:,}P)"
            return True, msg, {"order_id": order.id, "status": "FILLED"}
        else:
            # Reserve cash and place pending order
            user.points -= total_reserved
            order = LimitOrder(
                user_id=user.id,
                order_type=order_type,
                product_type=product_type,
                target_price=target_price,
                quantity=quantity,
                status=OrderStatus.PENDING
            )
            db.add(order)
            db.commit()
            qty_display = format_quantity(quantity)
            msg = f"📌 [지정가 매수 예약] #{order.id} {product_type.value} {qty_display}주 @ 목표가 {target_price:g}P 예약 완료 (예약금: {total_reserved:,}P 차감)"
            return True, msg, {"order_id": order.id, "status": "PENDING"}

    else: # SELL
        pos = db.query(Position).filter_by(user_id=user.id, product_type=product_type).first()
        if not pos or pos.quantity < quantity - 1e-9:
            has_q = pos.quantity if pos else 0
            qty_has = format_quantity(has_q)
            return False, f"⚠️ 매도 예약할 수량이 부족합니다. (보유: {qty_has}주)", None

        if current_price >= target_price:
            # Immediate fill
            val = calculate_position_valuation(pos, current_price)
            ratio = min(1.0, quantity / pos.quantity)
            gross_payout = int(round(val["current_value"] * ratio))
            fee = max(1, int(round(gross_payout * TRADING_FEE_RATE))) if gross_payout > 0 else 0
            net_payout = max(0, gross_payout - fee)
            invested_part = pos.invested_cash * ratio
            pnl = net_payout - invested_part

            user.points += net_payout
            if getattr(state, "treasury_pool", None) is None:
                state.treasury_pool = DEFAULT_TREASURY_POOL
            state.treasury_pool += fee

            pos.quantity = max(0.0, pos.quantity - quantity)
            pos.invested_cash = max(0.0, pos.invested_cash - invested_part)
            if pos.quantity <= 1e-6:
                pos.quantity = 0.0
                pos.invested_cash = 0.0
                pos.entry_price = 0.0

            order = LimitOrder(
                user_id=user.id,
                order_type=order_type,
                product_type=product_type,
                target_price=target_price,
                quantity=quantity,
                status=OrderStatus.FILLED
            )
            db.add(order)
            db.commit()
            qty_display = format_quantity(quantity)
            sign = "+" if pnl >= 0 else ""
            msg = f"✅ [지정가 매도 즉시 체결] 현재가({current_price:,}P)가 목표가({target_price:g}P) 이상이므로 즉시 체결되었습니다! ({product_type.value} {qty_display}주, +{net_payout:,}P 입금, 수수료: {fee:,}P 국고 적립)"
            return True, msg, {"order_id": order.id, "status": "FILLED"}
        else:
            # Reserve shares from position
            ratio = min(1.0, quantity / pos.quantity)
            invested_part = pos.invested_cash * ratio
            pos.quantity = max(0.0, pos.quantity - quantity)
            pos.invested_cash = max(0.0, pos.invested_cash - invested_part)
            if pos.quantity <= 1e-6:
                pos.quantity = 0.0
                pos.invested_cash = 0.0
                pos.entry_price = 0.0

            order = LimitOrder(
                user_id=user.id,
                order_type=order_type,
                product_type=product_type,
                target_price=target_price,
                quantity=quantity,
                status=OrderStatus.PENDING
            )
            db.add(order)
            db.commit()
            qty_display = format_quantity(quantity)
            msg = f"📌 [지정가 매도 예약] #{order.id} {product_type.value} {qty_display}주 @ 목표가 {target_price:g}P 예약 완료"
            return True, msg, {"order_id": order.id, "status": "PENDING"}

def execute_delisting_and_relist(
    db: Session,
    old_rank: str = "작성3",
    new_rank: str = "작성2",
    starting_points: int = 3000
) -> Dict[str, Any]:
    """
    Execute delisting (상장폐지) of the old rank stock and launch a new rank stock:
    1. All existing stock positions are wiped out (휴짓조각: quantity=0, invested_cash=0, entry_price=0).
    2. Pending BUY limit orders are refunded to users (reserved cash + fee) and cancelled.
    3. Pending SELL limit orders are cancelled.
    4. MarketState is updated to new rank, starting points (3,000P for 작성2 3000/6000), and new price.
    """
    state = get_market_state(db)

    # 1. Wipe all existing positions to 0 (휴짓조각)
    positions = db.query(Position).filter(
        (Position.quantity > 0) | (Position.invested_cash > 0)
    ).all()
    wiped_positions_count = 0
    total_wiped_shares = 0.0
    total_wiped_cash = 0.0
    affected_users = set()

    for pos in positions:
        if pos.quantity > 0 or pos.invested_cash > 0:
            wiped_positions_count += 1
            total_wiped_shares += pos.quantity
            total_wiped_cash += pos.invested_cash
            affected_users.add(pos.user_id)
            pos.quantity = 0.0
            pos.invested_cash = 0.0
            pos.entry_price = 0.0

    # 2. Cancel and refund pending limit orders
    pending_orders = db.query(LimitOrder).filter_by(status=OrderStatus.PENDING).all()
    cancelled_orders_count = 0
    refunded_buy_points = 0

    for order in pending_orders:
        if order.order_type == OrderType.BUY:
            cost_reserved = int(round(order.target_price * order.quantity))
            fee_reserved = max(1, int(round(cost_reserved * TRADING_FEE_RATE))) if cost_reserved > 0 else 0
            total_reserved = cost_reserved + fee_reserved
            if order.user:
                order.user.points += total_reserved
            refunded_buy_points += total_reserved
        order.status = OrderStatus.CANCELLED
        cancelled_orders_count += 1

    # 3. Update market state to new stock
    state.current_rank_name = new_rank
    state.current_rank_point = starting_points
    new_p = calculate_stock_price(starting_points)
    state.current_price = new_p
    state.previous_price = new_p
    state.day_open_price = new_p
    state.last_settlement_delta = 0
    state.is_trading_locked = False

    db.commit()
    db.refresh(state)

    return {
        "old_rank": old_rank,
        "new_rank": new_rank,
        "starting_points": starting_points,
        "new_price": new_p,
        "wiped_positions_count": wiped_positions_count,
        "total_wiped_shares": total_wiped_shares,
        "total_wiped_cash": total_wiped_cash,
        "affected_users_count": len(affected_users),
        "cancelled_orders_count": cancelled_orders_count,
        "refunded_buy_points": refunded_buy_points,
    }

# Central Bank Financial Products & Fund Definitions
INSURANCE_PLANS: Dict[str, Dict[str, Any]] = {
    "basic": {
        "id": "basic",
        "name": "실속형 플랜",
        "cost": 30000,
        "coverage": 500000,
        "matches": 5,
        "claims": 1,
        "aliases": ["1", "실속", "실속형", "basic", "소형", "3만", "30000", "50만"],
        "desc": "보험료 30,000P | 15성+ 파괴 시 500,000P 위로금 (5경기)"
    },
    "standard": {
        "id": "standard",
        "name": "표준형 플랜",
        "cost": 50000,
        "coverage": 1000000,
        "matches": 5,
        "claims": 1,
        "aliases": ["2", "표준", "표준형", "standard", "기본", "5만", "50000", "100만"],
        "desc": "보험료 50,000P | 15성+ 파괴 시 1,000,000P 위로금 (5경기)"
    },
    "premium": {
        "id": "premium",
        "name": "프리미엄 플랜",
        "cost": 120000,
        "coverage": 3000000,
        "matches": 5,
        "claims": 1,
        "aliases": ["3", "프리미엄", "고급", "premium", "12만", "120000", "300만"],
        "desc": "보험료 120,000P | 15성+ 파괴 시 3,000,000P 위로금 (5경기)"
    },
    "vvip": {
        "id": "vvip",
        "name": "VVIP 종결 플랜",
        "cost": 350000,
        "coverage": 10000000,
        "matches": 5,
        "claims": 1,
        "aliases": ["4", "vvip", "vip", "종결", "최고급", "35만", "350000", "1000만", "천만"],
        "desc": "보험료 350,000P | 15성+ 파괴 시 10,000,000P 위로금 (5경기)"
    }
}

SAVINGS_PLANS: Dict[int, Dict[str, Any]] = {
    3: {
        "rounds": 3,
        "name": "스피드 단기 적금",
        "bonus_pct": 0.10,
        "min_per_round": 5000,
        "max_per_round": 1000000,
        "aliases": ["3", "3판", "3회", "3경기", "단기", "스피드", "초단기", "speed"],
        "desc": "3경기 완납 시 +10% 만기 보너스 이자 지급 (단기 회수형)"
    },
    5: {
        "rounds": 5,
        "name": "나베 정기 적금",
        "bonus_pct": 0.20,
        "min_per_round": 5000,
        "max_per_round": 2000000,
        "aliases": ["5", "5판", "5회", "5경기", "표준", "정기", "일반", "standard"],
        "desc": "5경기 완납 시 +20% 만기 보너스 이자 지급 (표준 밸런스형)"
    },
    10: {
        "rounds": 10,
        "name": "고래 장기 적금",
        "bonus_pct": 0.35,
        "min_per_round": 10000,
        "max_per_round": 5000000,
        "aliases": ["10", "10판", "10회", "10경기", "장기", "고래", "대박", "whale"],
        "desc": "10경기 완납 시 +35% 만기 보너스 이자 지급 (고수익 잭팟형)"
    },
    20: {
        "rounds": 20,
        "name": "슈퍼 연금 적금",
        "bonus_pct": 0.60,
        "min_per_round": 20000,
        "max_per_round": 10000000,
        "aliases": ["20", "20판", "20회", "20경기", "연금", "슈퍼연금", "초장기", "mega", "pension"],
        "desc": "20경기 완납 시 +60% 초대박 만기 보너스 이자 지급 (장기 연금형)"
    }
}

DIVERSIFIED_FUNDS: Dict[str, Dict[str, Any]] = {
    "index": {
        "id": "index",
        "name": "마작 종합 지수 펀드 (ETF)",
        "risk_tier": "중위험·시장추종",
        "risk_stars": "⭐️⭐️⭐️",
        "aliases": ["지수", "인덱스", "index", "종합", "마작지수", "etf", "1", "기본"],
        "min_invest": 10000,
        "initial_nav": 1000.0,
        "desc": "KOSPI200/S&P500 유사. 나베 1X 주가 지수 변동과 경기 종합 점수에 정비례하는 대표 지수 연동 펀드",
        "beginner_guide": "💡 [주가지수 ETF] 치즈나베 마작 시장 전체를 따라가는 정석 펀드! 주가가 오를 것 같을 때 투자하세요."
    },
    "dividend": {
        "id": "dividend",
        "name": "나베 우량 배당국채 펀드",
        "risk_tier": "초저위험·원금안정",
        "risk_stars": "⭐️",
        "aliases": ["배당", "국채", "안정", "dividend", "채권", "2"],
        "min_invest": 10000,
        "initial_nav": 1000.0,
        "desc": "원금 보전 최우선! 주가 하락에도 손실을 극소화하며, 경기 승리 배당금과 국고 이자가 매 경기 꾸준히 가산",
        "beginner_guide": "💡 [배당형 예금 유사] 주가가 떨어져도 안심! 스트리머 배당금과 국고 이자를 꾸준히 모아 안정적으로 이자를 받는 펀드입니다."
    },
    "beast": {
        "id": "beast",
        "name": "야수 10X 레버리지 펀드",
        "risk_tier": "초고위험·초고수익",
        "risk_stars": "⭐️⭐️⭐️⭐️⭐️",
        "aliases": ["야수", "레버리지", "beast", "10x", "10배", "헤지", "3"],
        "min_invest": 10000,
        "initial_nav": 1000.0,
        "desc": "TQQQ 3배 레버리지 유사. 10X 롱/숏 공격적 모멘텀에 베팅하여 대승 시 폭등하지만 역풍 시 손실도 큰 야수 펀드",
        "beginner_guide": "💡 [고수익 공격형] 인생역전 도파민 추구! 스트리머가 연승 가도를 달릴 때 하루아침에 큰 수익을 낼 수 있는 초고수익 펀드입니다."
    },
    "infra": {
        "id": "infra",
        "name": "탄광·스타포스 인프라 펀드 (REITs)",
        "risk_tier": "중저위험·실물인프라",
        "risk_stars": "⭐️⭐️",
        "aliases": ["인프라", "탄광", "채굴", "스타포스", "infra", "reits", "리츠", "4"],
        "min_invest": 10000,
        "initial_nav": 1000.0,
        "desc": "맥쿼리인프라 유사. 주가와 무관하게 전 서버 유저들의 채굴량, 곡괭이 강화 수수료, 큐브 소비액의 5%를 분배받아 우상향",
        "beginner_guide": "💡 [인프라 실물 리츠] 다른 시청자들이 채굴하고 강화하고 큐브를 돌릴 때마다 통행세처럼 펀드로 돈이 차곡차곡 들어옵니다!"
    }
}

def get_all_fund_navs(state: MarketState) -> Dict[str, float]:
    """Retrieve current NAVs for all diversified funds."""
    base_nav = float(getattr(state, "fund_nav", 1000.0) or 1000.0)
    navs = {"index": base_nav}
    navs_json = getattr(state, "fund_navs_json", None)
    if navs_json:
        try:
            parsed = json.loads(navs_json)
            if isinstance(parsed, dict):
                for k, v in parsed.items():
                    try:
                        navs[k] = float(v)
                    except (ValueError, TypeError):
                        pass
        except Exception:
            pass
    for fid, fdef in DIVERSIFIED_FUNDS.items():
        if fid not in navs:
            navs[fid] = float(fdef.get("initial_nav", 1000.0))
    navs["index"] = base_nav
    return navs

def save_all_fund_navs(state: MarketState, navs: Dict[str, float]):
    """Persist fund NAVs to market state."""
    state.fund_nav = navs.get("index", 1000.0)
    state.fund_navs_json = json.dumps(navs, ensure_ascii=False)

def resolve_insurance_plan(plan_str: Optional[str]) -> Dict[str, Any]:
    """Resolves insurance plan from user input alias."""
    if not plan_str:
        return INSURANCE_PLANS["standard"]
    clean = str(plan_str).strip().lower()
    for plan_key, plan in INSURANCE_PLANS.items():
        if clean == plan_key or clean == plan["name"].lower() or clean in plan["aliases"]:
            return plan
    return INSURANCE_PLANS["standard"]

def resolve_savings_plan(rounds_or_name: Any) -> Dict[str, Any]:
    """Resolves savings plan from user input (number of rounds or plan alias)."""
    if not rounds_or_name:
        return SAVINGS_PLANS[5]
    clean = str(rounds_or_name).strip().lower().replace("판", "").replace("회", "").replace("경기", "")
    try:
        r_num = int(clean)
        if r_num in SAVINGS_PLANS:
            return SAVINGS_PLANS[r_num]
        if r_num <= 4:
            return SAVINGS_PLANS[3]
        elif r_num <= 7:
            return SAVINGS_PLANS[5]
        elif r_num <= 15:
            return SAVINGS_PLANS[10]
        else:
            return SAVINGS_PLANS[20]
    except (ValueError, TypeError):
        pass
    for r_num, plan in SAVINGS_PLANS.items():
        if clean in plan["aliases"] or clean == plan["name"].lower():
            return plan
    return SAVINGS_PLANS[5]

def resolve_fund_plan(fund_str: Optional[str]) -> Dict[str, Any]:
    """Resolves fund definition from user input alias."""
    if not fund_str:
        return DIVERSIFIED_FUNDS["index"]
    clean = str(fund_str).strip().lower()
    for fid, fdef in DIVERSIFIED_FUNDS.items():
        if clean == fid or clean in fdef["aliases"] or clean in fdef["name"].lower():
            return fdef
    return DIVERSIFIED_FUNDS["index"]


def settle_match(db: Session, rank: int, point_delta: int) -> Dict[str, Any]:
    """
    Admin match settlement:
    1. Checks demotion condition (points drop <= 0):
       If demoting from 작성3 to 작성2, triggers delisting (상장폐지)!
    2. Updates rank points and recalculates base stock price
    3. Rebalances positions and runs liquidation (margin call) checks
    4. Triggers pending limit orders matching new price
    5. Unlocks trading market
    """
    state = get_market_state(db)
    old_price = state.current_price
    curr_rank_name = getattr(state, "current_rank_name", "작성3") or "작성3"

    # Demotion & Delisting trigger check:
    # If rank points drop to 0 or below, demotion to 작성2 triggers delisting!
    if state.current_rank_point + point_delta <= 0:
        delist_info = execute_delisting_and_relist(
            db,
            old_rank=curr_rank_name,
            new_rank="작성2",
            starting_points=3000
        )

        # Collect loan interest on debtors
        total_interest_collected = 0
        debtors = db.query(User).filter(User.debt > 0).all()
        for debtor in debtors:
            debtor_credit = get_user_credit_info(debtor, db=db, market_state=state)
            interest = int(math.ceil(debtor.debt * debtor_credit["interest_rate"]))
            if interest > 0:
                if debtor.points >= interest:
                    debtor.points -= interest
                    total_interest_collected += interest
                else:
                    paid = debtor.points
                    unpaid = interest - paid
                    debtor.points = 0
                    debtor.debt += unpaid
                    total_interest_collected += paid

        if getattr(state, "treasury_pool", None) is None:
            state.treasury_pool = DEFAULT_TREASURY_POOL
        state.treasury_pool += total_interest_collected

        state.is_trading_locked = False
        db.commit()
        db.refresh(state)

        return {
            "rank": rank,
            "point_delta": point_delta,
            "delisted": True,
            "delisting_info": delist_info,
            "current_rank_name": state.current_rank_name,
            "new_rank_points": state.current_rank_point,
            "old_price": old_price,
            "new_price": state.current_price,
            "return_pct": -1.0,
            "is_trading_locked": state.is_trading_locked,
            "treasury_pool": state.treasury_pool,
            "liquidations": [],
            "dividends": [],
            "filled_orders": [],
            "interest_collected": total_interest_collected
        }

    state.current_rank_point += point_delta
    new_price = calculate_stock_price(state.current_rank_point)
    return_pct = (new_price - old_price) / old_price if old_price > 0 else 0.0

    state.previous_price = old_price
    state.current_price = new_price
    state.last_settlement_delta = point_delta

    # Settle active positions & check liquidations
    positions = db.query(Position).filter(Position.quantity > 0, Position.invested_cash > 0).all()
    liquidations: List[Dict[str, Any]] = []

    for pos in positions:
        mult = PRODUCT_MULTIPLIERS.get(pos.product_type, 1.0)
        entry = pos.entry_price if pos.entry_price > 0 else float(old_price)
        base_ret = (new_price - entry) / entry if entry > 0 else 0.0
        product_ret = base_ret * mult

        # Margin Call / Liquidation Check:
        # If leveraged/inverse position loss >= 100% (or account value <= 0), forcefully liquidate
        is_derivative = pos.product_type != ProductType.ONE_X
        if is_derivative and product_ret <= -1.0:
            user = pos.user
            uname = user.username if user else pos.user_id
            liquidations.append({
                "user_id": pos.user_id,
                "username": uname,
                "product_type": pos.product_type.value,
                "lost_cash": int(round(pos.invested_cash)),
                "lost_quantity": pos.quantity,
                "entry_price": pos.entry_price,
            })
            pos.quantity = 0.0
            pos.invested_cash = 0.0
            pos.entry_price = 0.0
        else:
            # Do NOT alter pos.entry_price, pos.invested_cash, or pos.quantity!
            # The user's purchase price (평단가) must strictly reflect what they bought it for.
            pass

    # Accumulate liquidated collateral into Treasury Pool (No money lost, redistributed to community)
    total_liquidated_cash = sum(liq["lost_cash"] for liq in liquidations)
    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL
    state.treasury_pool += total_liquidated_cash

    # PoS Victory Dividend: 1st place pays 5%, 2nd place pays 1% to all 1X holders
    dividends_distributed: List[Dict[str, Any]] = []
    try:
        r = int(rank)
    except (ValueError, TypeError):
        r = 0
    # Buffed Dividend Rates: 1st place 8%, 2nd place 3%, 3rd place 1%
    div_rate = 0.08 if r == 1 else (0.03 if r == 2 else (0.01 if r == 3 else 0.0))

    if div_rate > 0:
        all_positions = db.query(Position).filter(Position.quantity > 0).all()
        for p in all_positions:
            is_one_x = (
                p.product_type == ProductType.ONE_X or
                p.product_type == "1X" or
                getattr(p.product_type, "value", None) == "1X"
            )
            if is_one_x and p.user:
                u = p.user
                payout = max(1, int(round(p.quantity * new_price * div_rate))) if (p.quantity > 0 and new_price > 0) else 0
                if payout > 0:
                    eq = get_user_equipped_item(db, u)
                    pot_eff = get_equipment_potential_effects(eq) if eq else {}
                    div_boost_pct = min(750.0, float(pot_eff.get("dividend_boost_pct", 0.0)))
                    if div_boost_pct > 0:
                        payout = int(round(payout * (1.0 + div_boost_pct / 100.0)))
                    u.points += payout
                    u.total_dividends = (u.total_dividends or 0) + payout
                    dividends_distributed.append({
                        "user_id": u.id,
                        "username": u.username,
                        "payout": payout,
                        "amount": payout,
                        "shares": p.quantity,
                        "rate_pct": div_rate * 100.0,
                        "dividend_boost_pct": div_boost_pct
                    })

    # Central Bank Periodic Settlement Processing:
    # 1. Demand Deposit (보통예금) Interest: +0.5% paid to all users with bank_balance > 0
    bank_users = db.query(User).filter(User.bank_balance > 0).all()
    for bu in bank_users:
        b_interest = max(1, int(round(bu.bank_balance * 0.005)))
        bu.bank_balance += b_interest

    # 2. Installment Savings (정기적금) deduction & maturity check + Insurance matches decrement
    bank_data_users = db.query(User).filter(User.bank_data.isnot(None)).all()
    for bdu in bank_data_users:
        b_data = get_user_bank_data(bdu)
        dirty_bank = False

        # Installment Savings
        sav = b_data.get("savings")
        if sav and isinstance(sav, dict):
            per_round = int(sav.get("per_round", 0))
            if per_round > 0:
                paid = False
                if bdu.points >= per_round:
                    bdu.points -= per_round
                    paid = True
                elif (getattr(bdu, "bank_balance", 0) or 0) >= per_round:
                    bdu.bank_balance -= per_round
                    paid = True

                if paid:
                    sav["current_rounds"] = int(sav.get("current_rounds", 0)) + 1
                    sav["total_deposited"] = int(sav.get("total_deposited", 0)) + per_round
                    target_rounds = int(sav.get("target_rounds", 5))
                    if sav["current_rounds"] >= target_rounds:
                        # Maturity!
                        bonus_pct = float(sav.get("bonus_pct", 0.20))
                        bonus = int(round(sav["total_deposited"] * bonus_pct))
                        total_payout = sav["total_deposited"] + bonus
                        bdu.bank_balance = (getattr(bdu, "bank_balance", 0) or 0) + total_payout
                        pct_label = f"+{int(bonus_pct * 100)}%"
                        plan_title = sav.get("plan_name", "정기적금")
                        b_data["last_maturity_notice"] = (
                            f"🎉 [{plan_title} 만기 축하!] {target_rounds}회차 완납 달성! "
                            f"원금 {sav['total_deposited']:,}P + 보너스 이자({pct_label}) {bonus:,}P = 총 {total_payout:,}P 보통예금 입금 완료!"
                        )
                        del b_data["savings"]
                else:
                    sav["missed_rounds"] = int(sav.get("missed_rounds", 0)) + 1
                    if sav["missed_rounds"] >= 2:
                        # Auto-cancel due to consecutive misses, refund principal
                        refund = int(sav.get("total_deposited", 0))
                        bdu.bank_balance = (getattr(bdu, "bank_balance", 0) or 0) + refund
                        b_data["last_maturity_notice"] = (
                            f"⚠️ [정기적금 납입 실패로 인한 자동 해지] 2회 연속 잔액 부족으로 적금이 해지되었으며, "
                            f"지금까지 납입된 원금 {refund:,}P가 보통예금으로 환급되었습니다."
                        )
                        del b_data["savings"]
                dirty_bank = True

        # Insurance policy match decrement
        ins = b_data.get("insurance")
        if ins and isinstance(ins, dict) and ins.get("active"):
            left_m = int(ins.get("matches_left", 1)) - 1
            if left_m <= 0:
                ins["active"] = False
                ins["matches_left"] = 0
            else:
                ins["matches_left"] = left_m
            dirty_bank = True

        if dirty_bank:
            save_user_bank_data(bdu, b_data)

    # 3. Diversified Funds NAV update based on stock movement and economic yields
    price_change_ratio = (new_price - old_price) / max(1, old_price)
    navs = get_all_fund_navs(state)
    # Index: 60% beta + 0.5% base yield
    navs["index"] = max(100.0, round(navs.get("index", 1000.0) * (1.0 + (price_change_ratio * 0.6) + 0.005), 2))
    # Dividend: 10% beta + 1.2% guaranteed dividend yield
    navs["dividend"] = max(100.0, round(navs.get("dividend", 1000.0) * (1.0 + (price_change_ratio * 0.1) + 0.012), 2))
    # Beast: 2.5x high beta momentum
    navs["beast"] = max(50.0, round(navs.get("beast", 1000.0) * (1.0 + (price_change_ratio * 2.5)), 2))
    # Infra REITs: 0.9% steady infrastructure dividend
    navs["infra"] = max(100.0, round(navs.get("infra", 1000.0) * (1.0 + 0.009), 2))
    save_all_fund_navs(state, navs)

    # Process pending limit orders
    pending_orders = db.query(LimitOrder).filter_by(status=OrderStatus.PENDING).all()
    filled_orders: List[Dict[str, Any]] = []

    for order in pending_orders:
        user = order.user
        if not user:
            continue

        if order.order_type == OrderType.BUY and new_price <= order.target_price:
            # BUY order filled
            cost_reserved = int(round(order.target_price * order.quantity))
            fee_reserved = max(1, int(round(cost_reserved * TRADING_FEE_RATE))) if cost_reserved > 0 else 0
            total_reserved = cost_reserved + fee_reserved

            actual_cost = int(round(new_price * order.quantity))
            actual_fee = max(1, int(round(actual_cost * TRADING_FEE_RATE))) if actual_cost > 0 else 0
            actual_total = actual_cost + actual_fee

            refund = max(0, total_reserved - actual_total)
            user.points += refund
            if getattr(state, "treasury_pool", None) is None:
                state.treasury_pool = DEFAULT_TREASURY_POOL
            state.treasury_pool += actual_fee

            pos = db.query(Position).filter_by(user_id=user.id, product_type=order.product_type).first()
            if pos and pos.quantity > 0:
                pos.quantity += order.quantity
                pos.invested_cash += actual_cost
                pos.entry_price = float(new_price)
            else:
                if not pos:
                    pos = Position(
                        user_id=user.id,
                        product_type=order.product_type,
                        quantity=order.quantity,
                        entry_price=float(new_price),
                        invested_cash=float(actual_cost)
                    )
                    db.add(pos)
                else:
                    pos.quantity = order.quantity
                    pos.entry_price = float(new_price)
                    pos.invested_cash = float(actual_cost)

            order.status = OrderStatus.FILLED
            filled_orders.append({
                "order_id": order.id,
                "user_id": user.id,
                "username": user.username,
                "order_type": "BUY",
                "product_type": order.product_type.value,
                "quantity": order.quantity,
                "target_price": order.target_price,
                "fill_price": new_price,
                "fee": actual_fee
            })

        elif order.order_type == OrderType.SELL and new_price >= order.target_price:
            # SELL order filled
            gross_payout = int(round(new_price * order.quantity))
            fee = max(1, int(round(gross_payout * TRADING_FEE_RATE))) if gross_payout > 0 else 0
            net_payout = max(0, gross_payout - fee)
            user.points += net_payout
            if getattr(state, "treasury_pool", None) is None:
                state.treasury_pool = DEFAULT_TREASURY_POOL
            state.treasury_pool += fee

            order.status = OrderStatus.FILLED
            filled_orders.append({
                "order_id": order.id,
                "user_id": user.id,
                "username": user.username,
                "order_type": "SELL",
                "product_type": order.product_type.value,
                "quantity": order.quantity,
                "target_price": order.target_price,
                "fill_price": new_price,
                "fee": fee
            })

    # Loan interest: 2% charged on all outstanding debts at settlement
    total_interest_collected = 0
    debtors = db.query(User).filter(User.debt > 0).all()
    for debtor in debtors:
        debtor_credit = get_user_credit_info(debtor, db=db, market_state=state)
        interest = int(math.ceil(debtor.debt * debtor_credit["interest_rate"]))
        if interest > 0:
            if debtor.points >= interest:
                debtor.points -= interest
                total_interest_collected += interest
            else:
                paid = debtor.points
                unpaid = interest - paid
                debtor.points = 0
                debtor.debt += unpaid  # unpaid interest compounded into debt principal
                total_interest_collected += paid

    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL
    state.treasury_pool += total_interest_collected

    # Unlock market after settlement
    state.is_trading_locked = False

    # Record asset snapshots for all users after match settlement
    try:
        all_users = db.query(User).all()
        for u in all_users:
            record_user_asset_snapshot(
                db, u,
                event_type="SETTLEMENT",
                note=f"마작 경기 정산: {rank}등 ({point_delta:+d}pt)",
                force=True
            )
    except Exception:
        pass

    db.commit()
    db.refresh(state)

    return {
        "rank": rank,
        "point_delta": point_delta,
        "delisted": False,
        "current_rank_name": getattr(state, "current_rank_name", "작성3") or "작성3",
        "new_rank_points": state.current_rank_point,
        "old_price": old_price,
        "new_price": new_price,
        "return_pct": return_pct,
        "is_trading_locked": state.is_trading_locked,
        "treasury_pool": state.treasury_pool,
        "liquidations": liquidations,
        "dividends": dividends_distributed,
        "filled_orders": filled_orders,
        "interest_collected": total_interest_collected
    }

# 메이플 스타일 곡괭이 스타포스 강화표 (0성 ~ 30성 종결 MAX)
# 2025/2026 메이플스토리 룰 반영: 실패 시 단계 하락 전면 삭제 (등급 유지) | 15성~: 파괴 확률 존재 (파괴 시 12성 장비의 흔적 복원)
STARFORCE_TIERS: Dict[int, Dict[str, Any]] = {
    0: {"cost": 2000, "success": 99.75, "maintain": 0.25, "drop": 0.0, "destroy": 0.0},
    1: {"cost": 4000, "success": 94.50, "maintain": 5.50, "drop": 0.0, "destroy": 0.0},
    2: {"cost": 6000, "success": 89.25, "maintain": 10.75, "drop": 0.0, "destroy": 0.0},
    3: {"cost": 8000, "success": 89.25, "maintain": 10.75, "drop": 0.0, "destroy": 0.0},
    4: {"cost": 12000, "success": 84.00, "maintain": 16.00, "drop": 0.0, "destroy": 0.0},
    5: {"cost": 16000, "success": 78.75, "maintain": 21.25, "drop": 0.0, "destroy": 0.0},
    6: {"cost": 20000, "success": 73.50, "maintain": 26.50, "drop": 0.0, "destroy": 0.0},
    7: {"cost": 25000, "success": 68.25, "maintain": 31.75, "drop": 0.0, "destroy": 0.0},
    8: {"cost": 30000, "success": 63.00, "maintain": 37.00, "drop": 0.0, "destroy": 0.0},
    9: {"cost": 40000, "success": 57.75, "maintain": 42.25, "drop": 0.0, "destroy": 0.0},
    10: {"cost": 50000, "success": 52.50, "maintain": 47.50, "drop": 0.0, "destroy": 0.0},
    11: {"cost": 70000, "success": 47.25, "maintain": 52.75, "drop": 0.0, "destroy": 0.0},
    12: {"cost": 100000, "success": 42.00, "maintain": 58.00, "drop": 0.0, "destroy": 0.0},
    13: {"cost": 140000, "success": 36.75, "maintain": 63.25, "drop": 0.0, "destroy": 0.0},
    14: {"cost": 200000, "success": 31.50, "maintain": 68.50, "drop": 0.0, "destroy": 0.0},
    15: {"cost": 300000, "success": 31.50, "maintain": 66.445, "drop": 0.0, "destroy": 2.055},
    16: {"cost": 450000, "success": 31.50, "maintain": 66.445, "drop": 0.0, "destroy": 2.055},
    17: {"cost": 650000, "success": 15.75, "maintain": 77.510, "drop": 0.0, "destroy": 6.740},
    18: {"cost": 900000, "success": 15.75, "maintain": 77.510, "drop": 0.0, "destroy": 6.740},
    19: {"cost": 1250000, "success": 15.75, "maintain": 75.825, "drop": 0.0, "destroy": 8.425},
    20: {"cost": 1700000, "success": 31.50, "maintain": 58.225, "drop": 0.0, "destroy": 10.275},
    21: {"cost": 2300000, "success": 15.75, "maintain": 71.6125, "drop": 0.0, "destroy": 12.6375},
    22: {"cost": 3000000, "success": 15.75, "maintain": 67.40, "drop": 0.0, "destroy": 16.85},
    23: {"cost": 4200000, "success": 10.50, "maintain": 71.60, "drop": 0.0, "destroy": 17.90},
    24: {"cost": 5800000, "success": 10.50, "maintain": 71.60, "drop": 0.0, "destroy": 17.90},
    25: {"cost": 8000000, "success": 10.50, "maintain": 71.60, "drop": 0.0, "destroy": 17.90},
    26: {"cost": 11000000, "success": 7.35, "maintain": 74.16, "drop": 0.0, "destroy": 18.53},
    27: {"cost": 15000000, "success": 5.25, "maintain": 75.80, "drop": 0.0, "destroy": 18.95},
    28: {"cost": 20000000, "success": 3.15, "maintain": 77.48, "drop": 0.0, "destroy": 19.37},
    29: {"cost": 26000000, "success": 1.05, "maintain": 79.16, "drop": 0.0, "destroy": 19.79},
    30: {"cost": 0, "success": 0.0, "maintain": 0.0, "drop": 0.0, "destroy": 0.0}
}

STARFORCE_EVENT_TYPES: Dict[str, Dict[str, Any]] = {
    "DISCOUNT_30": {
        "code": "DISCOUNT_30",
        "name": "비용 30% 할인",
        "title": "💸 [피버] 스타포스 강화 비용 30% 파격 할인!",
        "has_discount": True,
        "has_100_percent": False,
        "desc": "모든 강화 단계의 비용이 30% 파격 할인됩니다!"
    },
    "FEVER_100": {
        "code": "FEVER_100",
        "name": "5·10·15성 100% 성공",
        "title": "⭐ [피버] 5성 / 10성 / 15성 100% 확정 성공!",
        "has_discount": False,
        "has_100_percent": True,
        "desc": "★5성➔6성, ★10성➔11성, ★15성➔16성 도전 시 실패/파괴 없이 무조건 100% 성공합니다!"
    },
    "SHINING": {
        "code": "SHINING",
        "name": "샤이닝 스타포스",
        "title": "✨🌟 [슈퍼 피버] 샤이닝 스타포스 (비용 30% 할인 + 5/10/15성 100% 성공)!",
        "has_discount": True,
        "has_100_percent": True,
        "desc": "강화 비용 30% 할인 + 5성, 10성, 15성 100% 확정 성공 혜택이 동시 적용됩니다!"
    }
}

# Star Force Fever Event Interval & Duration Settings (15~30 min intervals)
STARFORCE_EVENT_MIN_INTERVAL_MINUTES = 15.0   # 15 minutes
STARFORCE_EVENT_MAX_INTERVAL_MINUTES = 30.0   # 30 minutes
STARFORCE_EVENT_DURATIONS = [5.0, 7.0, 10.0]  # 5~10 minutes

def get_starforce_event_state(
    db: Session,
    force_trigger: bool = False,
    manual_type: Optional[str] = None,
    manual_duration: Optional[float] = None
) -> Dict[str, Any]:
    """
    Retrieve current Star Force Fever Event state.
    Handles spontaneous trigger at random intervals (15~30 minutes), random duration (5~10 min), and automatic expiration.
    """
    state = get_market_state(db)
    now = time.time()

    ev_type = getattr(state, "sf_event_type", None)
    end_time = float(getattr(state, "sf_event_end_time", 0.0) or 0.0)
    title = getattr(state, "sf_event_title", None)
    next_time = float(getattr(state, "sf_next_event_time", 0.0) or 0.0)

    # 1. Automatic expiration check
    if ev_type and end_time > 0 and now >= end_time:
        ev_type = None
        title = None
        end_time = 0.0
        # Schedule next spontaneous event in 15 ~ 30 minutes
        next_time = now + random.uniform(STARFORCE_EVENT_MIN_INTERVAL_MINUTES, STARFORCE_EVENT_MAX_INTERVAL_MINUTES) * 60.0
        state.sf_event_type = None
        state.sf_event_title = None
        state.sf_event_end_time = 0.0
        state.sf_next_event_time = next_time
        try:
            db.commit()
            db.refresh(state)
        except Exception:
            pass

    # 2. Initialization or Spontaneous Random Trigger
    if not ev_type:
        max_allowed_next = now + (STARFORCE_EVENT_MAX_INTERVAL_MINUTES * 60.0) + 60.0
        if not next_time or next_time <= 0 or next_time > max_allowed_next:
            next_time = now + random.uniform(STARFORCE_EVENT_MIN_INTERVAL_MINUTES, STARFORCE_EVENT_MAX_INTERVAL_MINUTES) * 60.0
            state.sf_next_event_time = next_time
            try:
                db.commit()
                db.refresh(state)
            except Exception:
                pass

        if (next_time > 0 and now >= next_time) or force_trigger:
            if manual_type and manual_type in STARFORCE_EVENT_TYPES:
                chosen_type = manual_type
            else:
                r = random.random()
                if r < 0.45:
                    chosen_type = "DISCOUNT_30"
                elif r < 0.85:
                    chosen_type = "FEVER_100"
                else:
                    chosen_type = "SHINING"

            if manual_duration and manual_duration > 0:
                dur_minutes = float(manual_duration)
            else:
                dur_minutes = random.choice(STARFORCE_EVENT_DURATIONS)

            conf = STARFORCE_EVENT_TYPES[chosen_type]
            ev_type = chosen_type
            title = conf["title"]
            end_time = now + dur_minutes * 60.0
            next_time = end_time + random.uniform(STARFORCE_EVENT_MIN_INTERVAL_MINUTES, STARFORCE_EVENT_MAX_INTERVAL_MINUTES) * 60.0

            state.sf_event_type = ev_type
            state.sf_event_title = title
            state.sf_event_end_time = end_time
            state.sf_next_event_time = next_time
            try:
                db.commit()
                db.refresh(state)
            except Exception:
                pass

    is_active = bool(ev_type and end_time > now)
    rem_sec = max(0, int(end_time - now)) if is_active else 0
    next_rem_sec = max(0, int(next_time - now)) if (not is_active and next_time > now) else 0

    conf = STARFORCE_EVENT_TYPES.get(ev_type, {}) if is_active else {}
    has_discount = conf.get("has_discount", False)
    has_100_percent = conf.get("has_100_percent", False)
    event_type_name = conf.get("name", "")

    return {
        "is_active": is_active,
        "event_type": ev_type,
        "event_type_name": event_type_name,
        "title": title or "",
        "end_time": end_time,
        "remaining_sec": rem_sec,
        "remaining_seconds": rem_sec,
        "next_event_time": next_time,
        "next_remaining_sec": next_rem_sec,
        "has_discount": has_discount,
        "has_100_percent": has_100_percent,
        "desc": conf.get("desc", "")
    }

def open_starforce_event(
    db: Session,
    duration_minutes: float = 10.0,
    event_type_str: str = "SHINING"
) -> Tuple[bool, str, Dict[str, Any]]:
    """Open a Star Force Fever Event manually (Streamer Command)."""
    state = get_market_state(db)
    now = time.time()

    t_clean = (event_type_str or "").strip().lower()
    if any(k in t_clean for k in ["할인", "30", "discount", "세일"]):
        ev_type = "DISCOUNT_30"
    elif any(k in t_clean for k in ["100", "확정", "fever", "성공"]):
        ev_type = "FEVER_100"
    else:
        ev_type = "SHINING"

    conf = STARFORCE_EVENT_TYPES[ev_type]
    dur_min = max(1.0, float(duration_minutes or 10.0))
    end_time = now + dur_min * 60.0
    next_time = end_time + random.uniform(STARFORCE_EVENT_MIN_INTERVAL_MINUTES, STARFORCE_EVENT_MAX_INTERVAL_MINUTES) * 60.0

    state.sf_event_type = ev_type
    state.sf_event_title = conf["title"]
    state.sf_event_end_time = end_time
    state.sf_next_event_time = next_time
    db.commit()
    db.refresh(state)

    dur_str = f"{int(dur_min)}분 동안" if dur_min % 1 == 0 else f"{dur_min}분 동안"
    reply = (
        f"🔥 [스타포스 피버 OPEN] {conf['title']} ({dur_str})! "
        f"지금 채팅창에 '!강화 [장비번호]'로 곡괭이를 강화해보세요! ({conf['desc']})"
    )
    details = {
        "is_active": True,
        "event_type": ev_type,
        "title": conf["title"],
        "duration_minutes": dur_min,
        "end_time": end_time
    }
    return True, reply, details

def close_starforce_event(db: Session) -> Tuple[bool, str, Dict[str, Any]]:
    """Close active Star Force Fever Event immediately."""
    state = get_market_state(db)
    now = time.time()
    old_title = getattr(state, "sf_event_title", "") or "스타포스 피버"
    state.sf_event_type = None
    state.sf_event_title = None
    state.sf_event_end_time = 0.0
    state.sf_next_event_time = now + random.uniform(STARFORCE_EVENT_MIN_INTERVAL_MINUTES, STARFORCE_EVENT_MAX_INTERVAL_MINUTES) * 60.0
    db.commit()
    db.refresh(state)

    reply = "🔒 [스타포스 피버 종료] 진행 중이던 피버 이벤트가 마감되었습니다. 다음 돌발 피버를 기대해주세요!"
    details = {
        "is_active": False,
        "previous_title": old_title
    }
    return True, reply, details

def get_starforce_event_guide(db: Session) -> str:
    """Returns status guide for Star Force Fever events."""
    sf = get_starforce_event_state(db)
    if sf["is_active"]:
        rem_m, rem_s = divmod(sf["remaining_sec"], 60)
        return (
            f"🔥 [스타포스 피버 진행 중!]\n"
            f"• 현재 이벤트: {sf['title']}\n"
            f"• 남은 시간: {rem_m}분 {rem_s}초\n"
            f"• 혜택: {sf['desc']}\n"
            f"👉 지금 !내장비, !강화 명령어로 강화에 도전해보세요!"
        )
    else:
        next_m = sf["next_remaining_sec"] // 60
        next_h, next_mod_m = divmod(next_m, 60)
        if next_h > 0:
            next_str = f"약 {next_h}시간 {next_mod_m}분 후 예정"
        elif next_m > 0:
            next_str = f"약 {next_m}분 후 예정"
        else:
            next_str = "곧 발생 예정"
        return (
            f"⭐ [스타포스 돌발 피버 이벤트 안내]\n"
            f"• 현재 상태: 대기 중 (다음 돌발 피버: {next_str})\n"
            f"• 이벤트 종류:\n"
            f"  1. 💸 비용 30% 할인: 전 구간 강화 비용 30% 파격 세일\n"
            f"  2. ⭐ 5·10·15성 100% 성공: ★5성, ★10성, ★15성(파괴위험구간) 100% 무조건 확정 성공!\n"
            f"  3. ✨🌟 샤이닝 스타포스: 30% 할인 + 5/10/15성 100% 성공 동시 발동!\n"
            f"💡 피버는 약 15~30분 주기로 5~10분간 랜덤 돌발 발생합니다! (스트리머 명령어: !피버 [분] [종류])"
        )

# ==========================================
# State Welfare Lottery Event (국가 복지 복권 이벤트)
# ==========================================
LOTTERY_TICKET_PRICE: int = 1000          # 기본 동 복권 1장당 1,000P
MAX_LOTTERY_PURCHASE: int = 10            # 1회 최대 10장 구매
LOTTERY_DEFAULT_DURATION_MIN: int = 10    # 1회 10분 오픈
LOTTERY_MIN_INTERVAL_MINUTES: float = 20.0 # 최소 20분 간격
LOTTERY_MAX_INTERVAL_MINUTES: float = 40.0 # 최대 40분 간격

LOTTERY_SPECS: Dict[str, Dict[str, Any]] = {
    "basic": {
        "id": "basic",
        "name": "동 복권(일반)",
        "icon": "🥉",
        "price": 1000,
        "aliases": ["동", "일반", "동복권", "일반복권", "싼거", "1", "basic", "bronze", "1000"],
        "tiers": [
            {
                "tier": 1,
                "name": "🥇 1등 (국고 잭팟 50배!)",
                "icon": "👑",
                "prize": 50000,
                "prob": 0.003,  # 0.3% (50배 잭팟)
                "badge": "1등(5만)",
                "is_jackpot": True
            },
            {
                "tier": 2,
                "name": "🥈 2등 (특별 지원금 15배!)",
                "icon": "✨",
                "prize": 15000,
                "prob": 0.012,  # 1.2% (15배 대박)
                "badge": "2등(1.5만)",
                "is_jackpot": True
            },
            {
                "tier": 3,
                "name": "🥉 3등 (행운 복지금 5배!)",
                "icon": "💎",
                "prize": 5000,
                "prob": 0.040,  # 4.0% (5배)
                "badge": "3등(5천)",
                "is_jackpot": False
            },
            {
                "tier": 4,
                "name": "🌟 4등 (복지 장려금 2배!)",
                "icon": "🍀",
                "prize": 2000,
                "prob": 0.090,  # 9.0% (2배)
                "badge": "4등(2천)",
                "is_jackpot": False
            },
            {
                "tier": 5,
                "name": "🎁 5등 (구매금액 100% 환급)",
                "icon": "🎁",
                "prize": 1000,
                "prob": 0.160,  # 16.0% (1배 본전)
                "badge": "5등(1천)",
                "is_jackpot": False
            },
            {
                "tier": 6,
                "name": "🍀 6등 (행운의 페이백 50%)",
                "icon": "🍀",
                "prize": 500,
                "prob": 0.200,  # 20.0% (0.5배 페이백)
                "badge": "6등(5백)",
                "is_jackpot": False
            },
            {
                "tier": 7,
                "name": "💀 꽝 (다음 기회에!)",
                "icon": "💀",
                "prize": 0,
                "prob": 0.495,  # 49.5% (손실 꽝)
                "badge": "꽝",
                "is_jackpot": False
            }
        ]
    },
    "silver": {
        "id": "silver",
        "name": "은 복권(고급)",
        "icon": "🥈",
        "price": 5000,
        "aliases": ["은", "고급", "은복권", "고급복권", "중간", "중간거", "2", "silver", "5000"],
        "tiers": [
            {
                "tier": 1,
                "name": "🥇 1등 (50만 대박 잭팟 100배!)",
                "icon": "👑",
                "prize": 500000,
                "prob": 0.0015,  # 0.15% (100배 대박)
                "badge": "1등(50만)",
                "is_jackpot": True
            },
            {
                "tier": 2,
                "name": "🥈 2등 (10만 특별금 20배!)",
                "icon": "✨",
                "prize": 100000,
                "prob": 0.0085,  # 0.85% (20배)
                "badge": "2등(10만)",
                "is_jackpot": True
            },
            {
                "tier": 3,
                "name": "🥉 3등 (행운 복지금 6배!)",
                "icon": "💎",
                "prize": 30000,
                "prob": 0.035,  # 3.5% (6배)
                "badge": "3등(3만)",
                "is_jackpot": False
            },
            {
                "tier": 4,
                "name": "🌟 4등 (복지 장려금 2배!)",
                "icon": "🍀",
                "prize": 10000,
                "prob": 0.080,  # 8.0% (2배)
                "badge": "4등(1만)",
                "is_jackpot": False
            },
            {
                "tier": 5,
                "name": "🎁 5등 (구매금액 100% 환급)",
                "icon": "🎁",
                "prize": 5000,
                "prob": 0.160,  # 16.0% (1배 본전)
                "badge": "5등(5천)",
                "is_jackpot": False
            },
            {
                "tier": 6,
                "name": "🍀 6등 (행운의 페이백 50%)",
                "icon": "🍀",
                "prize": 2500,
                "prob": 0.240,  # 24.0% (0.5배 페이백)
                "badge": "6등(2.5천)",
                "is_jackpot": False
            },
            {
                "tier": 7,
                "name": "💀 꽝 (다음 기회에!)",
                "icon": "💀",
                "prize": 0,
                "prob": 0.475,  # 47.5% (손실 꽝)
                "badge": "꽝",
                "is_jackpot": False
            }
        ]
    },
    "gold": {
        "id": "gold",
        "name": "금 복권(초대박 VIP)",
        "icon": "🥇",
        "price": 20000,
        "aliases": ["금", "대박", "금복권", "대박복권", "비싼거", "초대박", "3", "gold", "20000", "vip"],
        "tiers": [
            {
                "tier": 1,
                "name": "👑 1등 (500만 초대박 잭팟 250배!!)",
                "icon": "👑",
                "prize": 5000000,
                "prob": 0.0004,  # 0.04% (250배 초대박)
                "badge": "1등(500만)",
                "is_jackpot": True
            },
            {
                "tier": 2,
                "name": "🥈 2등 (80만 대박금 40배!)",
                "icon": "✨",
                "prize": 800000,
                "prob": 0.0035,  # 0.35% (40배)
                "badge": "2등(80만)",
                "is_jackpot": True
            },
            {
                "tier": 3,
                "name": "🥉 3등 (15만 특별금 7.5배!)",
                "icon": "💎",
                "prize": 150000,
                "prob": 0.025,  # 2.5% (7.5배)
                "badge": "3등(15만)",
                "is_jackpot": False
            },
            {
                "tier": 4,
                "name": "🌟 4등 (5만 장려금 2.5배!)",
                "icon": "🍀",
                "prize": 50000,
                "prob": 0.075,  # 7.5% (2.5배)
                "badge": "4등(5만)",
                "is_jackpot": False
            },
            {
                "tier": 5,
                "name": "🎁 5등 (구매금액 100% 환급)",
                "icon": "🎁",
                "prize": 20000,
                "prob": 0.170,  # 17.0% (1배 본전)
                "badge": "5등(2만)",
                "is_jackpot": False
            },
            {
                "tier": 6,
                "name": "🍀 6등 (행운의 페이백 50%)",
                "icon": "🍀",
                "prize": 10000,
                "prob": 0.250,  # 25.0% (0.5배 페이백)
                "badge": "6등(1만)",
                "is_jackpot": False
            },
            {
                "tier": 7,
                "name": "💀 꽝 (다음 기회에!)",
                "icon": "💀",
                "prize": 0,
                "prob": 0.4761,  # 47.61% (손실 꽝)
                "badge": "꽝",
                "is_jackpot": False
            }
        ]
    }
}

LOTTERY_TIERS = LOTTERY_SPECS["basic"]["tiers"]

def resolve_lottery_spec(type_token: Optional[str] = None) -> Dict[str, Any]:
    """Resolves lottery spec by id or alias. Defaults to 'basic'."""
    if not type_token:
        return LOTTERY_SPECS["basic"]
    token = str(type_token).strip().lower()
    for spec_key, spec in LOTTERY_SPECS.items():
        if token == spec_key or token in spec.get("aliases", []):
            return spec
    return LOTTERY_SPECS["basic"]

def get_lottery_event_state(
    db: Session,
    force_trigger: bool = False,
    manual_duration: Optional[int] = None
) -> Dict[str, Any]:
    """
    Check and maintain the State Welfare Lottery Event status:
    - Checks expiration when now >= end_time.
    - Spontaneously opens lottery event every 20 ~ 40 minutes for 10 minutes.
    """
    state = get_market_state(db)
    now = time.time()

    is_open = bool(getattr(state, "lottery_is_open", False))
    end_time = float(getattr(state, "lottery_end_time", 0.0) or 0.0)
    title = getattr(state, "lottery_title", None) or "국가 복지 복권"
    next_time = float(getattr(state, "lottery_next_event_time", 0.0) or 0.0)

    # 1. Expiration check
    if is_open and end_time > 0 and now >= end_time:
        is_open = False
        end_time = 0.0
        next_time = now + random.uniform(LOTTERY_MIN_INTERVAL_MINUTES, LOTTERY_MAX_INTERVAL_MINUTES) * 60.0
        state.lottery_is_open = False
        state.lottery_end_time = 0.0
        state.lottery_next_event_time = next_time
        try:
            db.commit()
            db.refresh(state)
        except Exception:
            pass

    # 2. Spontaneous Random Trigger or Force Trigger
    if not is_open:
        max_allowed_next = now + (LOTTERY_MAX_INTERVAL_MINUTES * 60.0) + 60.0
        if not next_time or next_time <= 0 or next_time > max_allowed_next:
            next_time = now + random.uniform(LOTTERY_MIN_INTERVAL_MINUTES, LOTTERY_MAX_INTERVAL_MINUTES) * 60.0
            state.lottery_next_event_time = next_time
            try:
                db.commit()
                db.refresh(state)
            except Exception:
                pass

        if (next_time > 0 and now >= next_time) or force_trigger:
            dur_m = float(manual_duration) if manual_duration and manual_duration > 0 else float(LOTTERY_DEFAULT_DURATION_MIN)
            is_open = True
            end_time = now + dur_m * 60.0
            next_time = end_time + random.uniform(LOTTERY_MIN_INTERVAL_MINUTES, LOTTERY_MAX_INTERVAL_MINUTES) * 60.0

            state.lottery_is_open = True
            state.lottery_end_time = end_time
            state.lottery_title = title
            state.lottery_next_event_time = next_time
            try:
                db.commit()
                db.refresh(state)
            except Exception:
                pass

    active = bool(is_open and end_time > now)
    rem_sec = max(0, int(end_time - now)) if active else 0
    next_in_sec = max(0, int(next_time - now)) if (next_time and next_time > now) else 0

    return {
        "is_active": active,
        "remaining_sec": rem_sec,
        "end_time": end_time,
        "title": title,
        "next_event_in_sec": next_in_sec,
        "ticket_price": LOTTERY_TICKET_PRICE
    }

def open_lottery_event(
    db: Session,
    duration_minutes: int = 10,
    title: str = "국가 복지 복권"
) -> Tuple[bool, str, Dict[str, Any]]:
    """Open State Welfare Lottery Event manually (streamer/admin)."""
    state = get_market_state(db)
    now = time.time()
    dur_m = max(1, min(120, int(duration_minutes)))
    end_time = now + (dur_m * 60.0)
    next_time = end_time + random.uniform(LOTTERY_MIN_INTERVAL_MINUTES, LOTTERY_MAX_INTERVAL_MINUTES) * 60.0

    state.lottery_is_open = True
    state.lottery_end_time = end_time
    state.lottery_title = title
    state.lottery_next_event_time = next_time

    db.commit()
    db.refresh(state)

    msg = f"🎉🏛️ [국가 복지 복권 오픈] '{title}' 이벤트가 {dur_m}분간 시작되었습니다! (당첨률 85%! 1등 50,000P 국고 대박 | 명령어: !복권)"
    details = {
        "is_active": True,
        "duration_minutes": dur_m,
        "remaining_sec": dur_m * 60,
        "end_time": end_time,
        "title": title
    }
    return True, msg, details

def close_lottery_event(db: Session) -> Tuple[bool, str, Dict[str, Any]]:
    """Close active State Welfare Lottery Event manually."""
    state = get_market_state(db)
    now = time.time()
    title = getattr(state, "lottery_title", "국가 복지 복권") or "국가 복지 복권"

    state.lottery_is_open = False
    state.lottery_end_time = 0.0
    state.lottery_next_event_time = now + random.uniform(LOTTERY_MIN_INTERVAL_MINUTES, LOTTERY_MAX_INTERVAL_MINUTES) * 60.0

    db.commit()
    db.refresh(state)

    msg = f"🔒 [복권 이벤트 마감] '{title}' 복권 판매가 마감되었습니다. 잠시 후 다음 복지 시간에 다시 열립니다!"
    details = {
        "is_active": False,
        "remaining_sec": 0,
        "title": title
    }
    return True, msg, details

def execute_buy_lottery(
    db: Session,
    user_id: str,
    username: str,
    count: int = 1,
    lottery_type: Optional[str] = "basic"
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Buy and scratch State Welfare Lottery tickets (!복권 / !복권 [종류] [수량]):
    - Available only during active lottery event
    - 3 Tiers:
      * basic (동 복권): 1,000P / 1등 50,000P (50배) / RTP 98.0%
      * silver (은 복권): 5,000P / 1등 500,000P (100배 대박) / RTP 98.0%
      * gold (금 복권): 20,000P / 1등 5,000,000P (250배 초대박 잭팟) / RTP 97.5%
    """
    ev_state = get_lottery_event_state(db)
    if not ev_state["is_active"]:
        next_m = max(1, ev_state["next_event_in_sec"] // 60)
        return False, f"🔒 지금은 복권 이벤트 기간이 아닙니다! (약 {next_m}분 후 다음 국가 복지 복권이 자동으로 열립니다. 스트리머 전용: !복권오픈 [분])", None

    spec = resolve_lottery_spec(lottery_type)
    ticket_price = spec.get("price", LOTTERY_TICKET_PRICE)
    spec_tiers = spec.get("tiers", LOTTERY_TIERS)
    spec_name = spec.get("name", "동 복권(일반)")
    spec_icon = spec.get("icon", "🎫")

    try:
        qty = int(count)
    except (ValueError, TypeError):
        qty = 1
    if qty <= 0:
        qty = 1
    if qty > MAX_LOTTERY_PURCHASE:
        return False, f"⚠️ 복권은 1회 최대 {MAX_LOTTERY_PURCHASE}장까지만 구매할 수 있습니다.", None

    total_cost = qty * ticket_price
    user = get_or_create_user(db, user_id, username)
    if user.points < total_cost:
        return False, f"⚠️ 보유 현금이 부족합니다! (필요: {total_cost:,}P | 보유: {user.points:,}P | [{spec_name}] 장당 {ticket_price:,}P)", None

    state = get_market_state(db)

    tickets_results = []
    total_prize = 0
    jackpot_hits = []

    for _ in range(qty):
        roll = random.random()
        cum = 0.0
        chosen_tier = spec_tiers[-1]
        for t in spec_tiers:
            cum += t["prob"]
            if roll < cum:
                chosen_tier = t
                break

        prize = chosen_tier["prize"]
        total_prize += prize
        tickets_results.append({
            "tier": chosen_tier["tier"],
            "name": chosen_tier["name"],
            "icon": chosen_tier["icon"],
            "prize": prize,
            "badge": chosen_tier["badge"],
            "is_jackpot": chosen_tier["is_jackpot"]
        })
        if chosen_tier["is_jackpot"]:
            jackpot_hits.append(chosen_tier)

    net_profit = total_prize - total_cost

    user.points -= total_cost
    user.points += total_prize

    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL
    if net_profit > 0:
        state.treasury_pool = max(100000.0, state.treasury_pool - net_profit)
    else:
        state.treasury_pool += abs(net_profit)

    db.commit()
    db.refresh(user)
    db.refresh(state)

    sign = "+" if net_profit >= 0 else ""
    if qty == 1:
        res = tickets_results[0]
        profit_str = f"{sign}{net_profit:,}P" if net_profit != 0 else "0P"
        if res["prize"] == 0:
            reply = (
                f"🎫 [{spec_icon} {spec_name}] {user.username}님 긁기 결과: {res['icon']} {res['name']}! "
                f"아쉽게도 꽝입니다... (손실: {profit_str} | 보유 현금: {user.points:,}P)"
            )
        else:
            reply = (
                f"🎫 [{spec_icon} {spec_name}] {user.username}님 긁기 결과: {res['icon']} {res['name']}! "
                f"당첨금 +{res['prize']:,}P 지급! (수익: {profit_str} | 보유 현금: {user.points:,}P)"
            )
    else:
        from collections import Counter
        tier_counts = Counter(r["badge"] for r in tickets_results)
        summary_items = [f"{badge} {cnt}장" for badge, cnt in tier_counts.items()]
        summary_str = ", ".join(summary_items)
        reply = (
            f"🎫 [{spec_icon} {spec_name} {qty}장 일괄 긁기] {user.username}님 결과: [{summary_str}]! "
            f"총 당첨금: +{total_prize:,}P (총 비용: {total_cost:,}P | 순수익: {sign}{net_profit:,}P | 잔액: {user.points:,}P)"
        )

    details = {
        "user_id": user.id,
        "username": user.username,
        "lottery_type": spec.get("id", "basic"),
        "lottery_name": spec_name,
        "ticket_price": ticket_price,
        "ticket_count": qty,
        "total_cost": total_cost,
        "total_prize": total_prize,
        "net_profit": net_profit,
        "has_jackpot": len(jackpot_hits) > 0,
        "jackpots": jackpot_hits,
        "tickets": tickets_results,
        "user_points": user.points,
        "treasury_pool": state.treasury_pool
    }
    return True, reply, details

def get_lottery_guide() -> str:
    """Returns guide & prize probabilities for State Welfare Lottery (3 tiers)."""
    return (
        "🎫✨ [국가 복지 복권 3종 안내] (상식적인 플마제로 ~98% 밸런스 복권!)\n"
        "1️⃣ 🥉 동 복권(일반) [1,000P] (명령어: !복권 동 [수량])\n"
        "  • 🥇 1등 (0.4%): 50,000P (50배 국고 잭팟)\n"
        "  • 🥈 2등 (2.0%): 10,000P | 🥉 3등 (5.0%): 4,000P | 4등 2,000P | 5등 1,000P | 💀 꽝 0P (64.6%)\n"
        "2️⃣ 🥈 은 복권(고급) [5,000P] (명령어: !복권 은 [수량])\n"
        "  • 🥇 1등 (0.2%): 500,000P (100배 대박 잭팟!)\n"
        "  • 🥈 2등 (1.5%): 100,000P | 🥉 3등 (4.0%): 30,000P | 4등 10,000P | 5등 5,000P | 💀 꽝 0P (76.3%)\n"
        "3️⃣ 🥇 금 복권(초대박) [20,000P] (명령어: !복권 금 [수량])\n"
        "  • 👑 1등 (0.05%): 5,000,000P (250배 초대형 잭팟!!)\n"
        "  • 🥈 2등 (0.4%): 1,000,000P (50배 대박) | 🥉 3등 (2.5%): 200,000P | 4등 60,000P | 5등 20,000P | 💀 꽝 0P (73.05%)\n"
        "💡 1회 최대 10장 구매 가능 | 이벤트 시간 동안만 판매 (!복권오픈 [분], !복권마감)"
    )

MERCHANT_DEFAULT_DURATION_MIN = 10
MERCHANT_MIN_INTERVAL_MINUTES = 25
MERCHANT_MAX_INTERVAL_MINUTES = 50

MERCHANT_ITEMS = {
    "shield": {
        "id": 1,
        "name": "🛡️ 파괴방어권",
        "aliases": ["1", "파괴방어권", "파괴방지권", "파괴방어", "파방", "파방권", "shield", "protect"],
        "field": "shield_scroll_count",
        "desc": "15성+ 스타포스 강화 실패 시 폭발 파괴 100% 방어",
        "min_price": 350000,
        "max_price": 700000,
        "min_stock": 2,
        "max_stock": 6
    },
    "boost": {
        "id": 2,
        "name": "⚡ 강화확률상승권",
        "aliases": ["2", "강화확률상승권", "확률상승권", "상승권", "확률상승", "boost"],
        "field": "boost_scroll_count",
        "desc": "스타포스 강화 성공률 +25% 곱연산 증폭 (실패/하락률 차감)",
        "min_price": 250000,
        "max_price": 450000,
        "min_stock": 5,
        "max_stock": 12
    },
    "downgrade": {
        "id": 3,
        "name": "📉 하강방지권",
        "aliases": ["3", "하강방지권", "하강방어권", "하강권", "하강방지", "downgrade", "safe"],
        "field": "downgrade_scroll_count",
        "desc": "스타포스 강화 실패 시 등급(성수) 하락 100% 방어",
        "min_price": 300000,
        "max_price": 550000,
        "min_stock": 3,
        "max_stock": 8
    },
    "snipe": {
        "id": 4,
        "name": "🎯 잠재저격주문서",
        "aliases": ["4", "잠재저격주문서", "저격주문서", "저격권", "저격", "snipe", "target", "큐브주문서"],
        "field": "snipe_scroll_count",
        "desc": "큐브 사용 시 원하는 잠재 옵션 확률 대폭 증가 (1줄 35% 저격 + 전체 3.5배 가중치)",
        "min_price": 350000,
        "max_price": 650000,
        "min_stock": 2,
        "max_stock": 5
    },
    "shield_100": {
        "id": 6,
        "name": "🛡️✨ [100% 확정] 절대 파괴방어권",
        "aliases": ["6", "절대파방", "100파방", "100%파방", "절대파괴방어권", "100%파괴방어권", "완전파방", "shield100", "perfect_shield"],
        "field": "shield_100_scroll_count",
        "desc": "★15 이상 스타포스 강화 실패 시 폭발 파괴를 100% 완벽 방어! (0% 파괴, 절대 무적 결계)",
        "min_price": 5000000,
        "max_price": 10000000,
        "min_stock": 1,
        "max_stock": 1
    },
    "downgrade_100": {
        "id": 7,
        "name": "📉✨ [100% 확정] 절대 하강방지권",
        "aliases": ["7", "절대하강", "100하강", "100%하강", "절대하강방지권", "100%하강방지권", "완전하강", "downgrade100", "perfect_downgrade"],
        "field": "downgrade_100_scroll_count",
        "desc": "스타포스 강화 실패 시 등급(성수) 하락을 100% 완벽 방어! (0% 하락, 성수 절대 보존)",
        "min_price": 3500000,
        "max_price": 7000000,
        "min_stock": 1,
        "max_stock": 1
    }
}


def get_user_special_snipe_scrolls(user: User) -> Dict[str, int]:
    """Returns dict of code -> count for specific option sniper scrolls."""
    raw = getattr(user, "special_snipe_scrolls", "{}") or "{}"
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(data, dict):
            return {str(k): int(v) for k, v in data.items() if int(v) > 0}
        return {}
    except Exception:
        return {}

def add_user_special_snipe_scroll(user: User, code: str, count: int = 1, db: Optional[Session] = None) -> None:
    """Adds specific option sniper scrolls to user."""
    curr = get_user_special_snipe_scrolls(user)
    curr[code] = curr.get(code, 0) + max(1, int(count))
    user.special_snipe_scrolls = json.dumps(curr, ensure_ascii=False)
    if db is not None:
        try:
            db.commit()
        except Exception:
            pass

def consume_user_special_snipe_scroll(user: User, code: str, db: Optional[Session] = None) -> bool:
    """Consumes 1 specific option sniper scroll if available."""
    curr = get_user_special_snipe_scrolls(user)
    if curr.get(code, 0) <= 0:
        return False
    curr[code] -= 1
    if curr[code] <= 0:
        del curr[code]
    user.special_snipe_scrolls = json.dumps(curr, ensure_ascii=False)
    if db is not None:
        try:
            db.commit()
        except Exception:
            pass
    return True

def get_user_bank_data(user: User) -> Dict[str, Any]:
    """Returns bank data dict from JSON."""
    raw = getattr(user, "bank_data", "{}") or "{}"
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        return {}

def save_user_bank_data(user: User, data: Dict[str, Any]) -> None:
    """Saves bank data dict to JSON."""
    user.bank_data = json.dumps(data, ensure_ascii=False)

def calculate_merchant_inflation_multiplier(db: Session, state: MarketState) -> float:
    """Calculates inflation multiplier (1.0x ~ 6.0x) based on average user wealth and treasury pool."""
    try:
        from sqlalchemy import func
        total_points = db.query(func.sum(User.points)).scalar() or 0
        total_bank = db.query(func.sum(User.bank_balance)).scalar() or 0
        total_wealth = total_points + total_bank
        user_count = db.query(User).count() or 1
        avg_wealth = total_wealth / max(1, user_count)

        wealth_mult = max(1.0, min(6.0, (avg_wealth / 70000.0) ** 0.8)) if avg_wealth > 70000 else 1.0
        treasury = getattr(state, "treasury_pool", 0.0) or getattr(state, "treasury_balance", 0.0) or 0.0
        treasury_mult = max(1.0, min(3.0, (float(treasury) / 15000000.0) ** 0.45)) if treasury > 15000000 else 1.0

        return round(wealth_mult * 0.75 + treasury_mult * 0.25, 2)
    except Exception:
        return 1.0


def roll_merchant_special_snipe(inflation_mult: float = 1.0) -> Tuple[Optional[str], Optional[str], Optional[str], int, int]:
    """75% chance to stock a specific named potential sniper scroll with 1~3 stock (scaled by inflation)."""
    if random.uniform(0, 100) > 75.0:
        return None, None, None, 0, 0

    candidates = [
        ("DIVIDEND_BOOST_PCT", "📈 배당금 증폭 전용 저격주문서", "큐브 사용 시 1줄 [배당금 증폭] 88% 확정급 저격!", 2400000),
        ("MINING_CD_RESET", "⚡ 쿨타임 초기화 전용 저격주문서", "큐브 사용 시 1줄 [쿨타임 즉시 초기화] 88% 확정급 저격!", 2800000),
        ("STARFORCE_SUCCESS_BOOST", "⭐ 성공률 증가 전용 저격주문서", "큐브 사용 시 1줄 [강화 성공률 증가] 88% 확정급 저격!", 2700000),
        ("GOBLIN_JACKPOT_CHANCE", "👹 황금 고블린 전용 저격주문서", "큐브 사용 시 1줄 [황금 고블린 잭팟] 88% 확정급 저격!", 2500000),
        ("MINING_YIELD_BOOST", "⛏️ 채굴량 증폭 전용 저격주문서", "큐브 사용 시 1줄 [주식 채굴량 배율] 88% 확정급 저격!", 2100000),
        ("MINING_BONUS_CASH", "🪙 확정 현금 전용 저격주문서", "큐브 사용 시 1줄 [채굴 확정 현금] 88% 확정급 저격!", 1800000),
        ("MAHJONG_TILE_BOOST", "🀄 마작 화료 전용 저격주문서", "큐브 사용 시 1줄 [마작패 화료 보너스] 88% 확정급 저격!", 1900000),
        ("HEAVY_MINING", "🌋 과충전 채굴 전용 저격주문서", "큐브 사용 시 1줄 [과충전 집중 채굴] 88% 확정급 저격!", 2200000),
        ("STARFORCE_DISCOUNT", "🔨 강화비 할인 전용 저격주문서", "큐브 사용 시 1줄 [스타포스 강화비 할인] 88% 확정급 저격!", 1800000),
    ]
    code, name, desc, base_price = random.choice(candidates)
    stock = random.randint(1, 3)
    scaled_base = int(round(base_price * max(1.0, inflation_mult)))
    price = int(round(scaled_base * random.uniform(0.85, 1.35) / 10000)) * 10000
    return code, name, desc, price, stock


def get_merchant_state(
    db: Session,
    force_trigger: bool = False,
    manual_duration: Optional[int] = None
) -> Dict[str, Any]:
    """Check and maintain Mysterious Merchant (신비상인) status."""
    state = get_market_state(db)
    now = time.time()

    is_open = bool(getattr(state, "merchant_is_open", False))
    end_time = float(getattr(state, "merchant_end_time", 0.0) or 0.0)
    name = getattr(state, "merchant_name", None) or "신비상인"
    next_time = float(getattr(state, "merchant_next_time", 0.0) or 0.0)

    # 1. Expiration check
    if is_open and end_time > 0 and now >= end_time:
        is_open = False
        end_time = 0.0
        next_time = now + random.uniform(MERCHANT_MIN_INTERVAL_MINUTES, MERCHANT_MAX_INTERVAL_MINUTES) * 60.0
        state.merchant_is_open = False
        state.merchant_end_time = 0.0
        state.merchant_next_time = next_time
        try:
            db.commit()
            db.refresh(state)
        except Exception:
            pass

    # 2. Spontaneous Random Trigger or Force Trigger
    if not is_open:
        max_allowed_next = now + (MERCHANT_MAX_INTERVAL_MINUTES * 60.0) + 60.0
        if not next_time or next_time <= 0 or next_time > max_allowed_next:
            next_time = now + random.uniform(MERCHANT_MIN_INTERVAL_MINUTES, MERCHANT_MAX_INTERVAL_MINUTES) * 60.0
            state.merchant_next_time = next_time
            try:
                db.commit()
                db.refresh(state)
            except Exception:
                pass

        if (next_time > 0 and now >= next_time) or force_trigger:
            dur_m = float(manual_duration) if manual_duration and manual_duration > 0 else float(MERCHANT_DEFAULT_DURATION_MIN)
            is_open = True
            end_time = now + dur_m * 60.0
            next_time = end_time + random.uniform(MERCHANT_MIN_INTERVAL_MINUTES, MERCHANT_MAX_INTERVAL_MINUTES) * 60.0

            # Dynamic Inflation Multiplier based on server assets
            infl_mult = calculate_merchant_inflation_multiplier(db, state)

            # Randomize standard items stock & price scaled by inflation
            state.merchant_shield_price = int(round(random.randint(25, 98) * 10000 * infl_mult / 10000)) * 10000
            state.merchant_shield_stock = random.randint(1, 8)
            state.merchant_boost_price = int(round(random.randint(15, 65) * 10000 * infl_mult / 10000)) * 10000
            state.merchant_boost_stock = random.randint(3, 16)
            state.merchant_downgrade_price = int(round(random.randint(20, 80) * 10000 * infl_mult / 10000)) * 10000
            state.merchant_downgrade_stock = random.randint(2, 10)
            state.merchant_snipe_price = int(round(random.randint(30, 120) * 10000 * infl_mult / 10000)) * 10000
            state.merchant_snipe_stock = random.randint(1, 6)

            # Probabilistically bring special named option sniper scroll (1~3 stock)
            sp_code, sp_name, sp_desc, sp_price, sp_stock = roll_merchant_special_snipe(inflation_mult=infl_mult)
            state.merchant_special_snipe_code = sp_code
            state.merchant_special_snipe_name = sp_name
            state.merchant_special_snipe_desc = sp_desc
            state.merchant_special_snipe_price = sp_price
            state.merchant_special_snipe_stock = sp_stock

            # Ultra-luxury 100% Absolute Defense & Drop Prevention Scrolls (35% chance, 1 stock, dynamic pricing)
            if random.uniform(0, 100) < 35.0:
                base_s100 = random.randint(50, 95) * 100000
                state.merchant_shield_100_price = int(round(base_s100 * infl_mult / 100000)) * 100000
                state.merchant_shield_100_stock = 1
            else:
                state.merchant_shield_100_stock = 0

            if random.uniform(0, 100) < 35.0:
                base_d100 = random.randint(35, 75) * 100000
                state.merchant_downgrade_100_price = int(round(base_d100 * infl_mult / 100000)) * 100000
                state.merchant_downgrade_100_stock = 1
            else:
                state.merchant_downgrade_100_stock = 0

            state.merchant_is_open = True
            state.merchant_end_time = end_time
            state.merchant_name = name
            state.merchant_next_time = next_time
            try:
                db.commit()
                db.refresh(state)
            except Exception:
                pass

    active = bool(is_open and end_time > now)
    rem_sec = max(0, int(end_time - now)) if active else 0
    next_in_sec = max(0, int(next_time - now)) if (next_time and next_time > now) else 0

    # Auto-initialize legacy zero prices if found in database
    cur_shield_price = getattr(state, "merchant_shield_price", 0) or 0
    cur_boost_price = getattr(state, "merchant_boost_price", 0) or 0
    cur_downgrade_price = getattr(state, "merchant_downgrade_price", 0) or 0
    cur_snipe_price = getattr(state, "merchant_snipe_price", 0) or 0

    updated_m_price = False
    if cur_shield_price <= 0:
        state.merchant_shield_price = random.randint(20, 98) * 10000
        updated_m_price = True
    if cur_boost_price <= 0:
        state.merchant_boost_price = random.randint(12, 65) * 10000
        updated_m_price = True
    if cur_downgrade_price <= 0:
        state.merchant_downgrade_price = random.randint(15, 80) * 10000
        updated_m_price = True
    if cur_snipe_price <= 0:
        state.merchant_snipe_price = random.randint(25, 120) * 10000
        updated_m_price = True

    if updated_m_price:
        try:
            db.commit()
            db.refresh(state)
        except Exception:
            pass

    items_dict: Dict[str, Any] = {
        "shield": {
            "id": 1,
            "name": "🛡️ 파괴방어권",
            "price": getattr(state, "merchant_shield_price", 500000) or 500000,
            "stock": getattr(state, "merchant_shield_stock", 5) or 0,
            "desc": "15성+ 강화 실패 시 폭발 파괴 75% 방어 (25% 확률로 폭발할 수 있음!)"
        },
        "boost": {
            "id": 2,
            "name": "⚡ 강화확률상승권",
            "price": getattr(state, "merchant_boost_price", 350000) or 350000,
            "stock": getattr(state, "merchant_boost_stock", 10) or 0,
            "desc": "스타포스 강화 성공률 +25% 곱연산 증폭"
        },
        "downgrade": {
            "id": 3,
            "name": "📉 하강방지권",
            "price": getattr(state, "merchant_downgrade_price", 400000) or 400000,
            "stock": getattr(state, "merchant_downgrade_stock", 8) or 0,
            "desc": "강화 실패 시 등급(성수) 하락 80% 방어 (20% 확률로 하락할 수 있음)"
        },
        "snipe": {
            "id": 4,
            "name": "🎯 잠재저격주문서",
            "price": getattr(state, "merchant_snipe_price", 500000) or 500000,
            "stock": getattr(state, "merchant_snipe_stock", 4) or 0,
            "desc": "큐브 사용 시 원하는 잠재 옵션 확률 대폭 증가 (1줄 35% 저격 + 전체 3.5배 가중치)"
        }
    }

    if getattr(state, "merchant_special_snipe_stock", 0) > 0 and getattr(state, "merchant_special_snipe_code", None):
        items_dict["special"] = {
            "id": 5,
            "name": state.merchant_special_snipe_name,
            "price": getattr(state, "merchant_special_snipe_price", 750000) or 750000,
            "stock": getattr(state, "merchant_special_snipe_stock", 0) or 0,
            "code": state.merchant_special_snipe_code,
            "desc": state.merchant_special_snipe_desc or "큐브 사용 시 1줄 88% 확정급 저격!"
        }

    if getattr(state, "merchant_shield_100_stock", 0) > 0:
        items_dict["shield_100"] = {
            "id": 6,
            "name": "🛡️✨ [100% 확정] 절대 파괴방어권",
            "price": getattr(state, "merchant_shield_100_price", 15000000) or 15000000,
            "stock": getattr(state, "merchant_shield_100_stock", 0) or 0,
            "desc": "★15 이상 스타포스 폭발 파괴를 100% 완벽 방어! (0% 파괴, 절대 무적 방패)"
        }

    if getattr(state, "merchant_downgrade_100_stock", 0) > 0:
        items_dict["downgrade_100"] = {
            "id": 7,
            "name": "📉✨ [100% 확정] 절대 하강방지권",
            "price": getattr(state, "merchant_downgrade_100_price", 10000000) or 10000000,
            "stock": getattr(state, "merchant_downgrade_100_stock", 0) or 0,
            "desc": "스타포스 강화 실패 시 등급(성수) 하락을 100% 완벽 방어! (0% 하락, 성수 절대 보존)"
        }

    return {
        "is_active": active,
        "remaining_sec": rem_sec,
        "end_time": end_time,
        "merchant_name": name,
        "next_event_in_sec": next_in_sec,
        "items": items_dict
    }


def calculate_merchant_inflation_multiplier(db: Session, state: MarketState) -> float:
    """Dynamically scales merchant prices based on users' wealth (top holders) and central treasury pool."""
    try:
        top_users = db.query(User).order_by(User.points.desc()).limit(5).all()
        if not top_users:
            return 1.0
        avg_top_cash = sum(u.points for u in top_users) / len(top_users)
        treasury = float(getattr(state, "treasury_pool", 500000.0) or 500000.0)

        cash_factor = max(1.0, (avg_top_cash / 1000000.0) ** 0.5)
        treasury_factor = max(1.0, (treasury / 2000000.0) ** 0.35)
        mult = max(1.0, min(10.0, (cash_factor * 0.65 + treasury_factor * 0.35)))
        return round(mult, 2)
    except Exception:
        return 1.0


def open_merchant(
    db: Session,
    duration_minutes: int = 10,
    name: str = "신비상인"
) -> Tuple[bool, str, Dict[str, Any]]:
    """Streamer/Admin manual spawn for Mysterious Merchant with dynamic economy pricing."""
    state = get_market_state(db)
    now = time.time()
    dur_m = max(1, min(120, int(duration_minutes)))
    end_time = now + (dur_m * 60.0)
    next_time = end_time + random.uniform(MERCHANT_MIN_INTERVAL_MINUTES, MERCHANT_MAX_INTERVAL_MINUTES) * 60.0

    state.merchant_is_open = True
    state.merchant_end_time = end_time
    state.merchant_name = name
    state.merchant_next_time = next_time

    # Compute dynamic economy inflation multiplier (scales with user cash & treasury pool)
    mult = calculate_merchant_inflation_multiplier(db, state)

    # Generate random wide-range prices scaled by inflation (rounded to nearest 10,000P)
    state.merchant_shield_price = int(round((random.randint(18, 95) * 10000) * mult / 10000)) * 10000
    state.merchant_shield_stock = random.randint(1, 8)
    state.merchant_boost_price = int(round((random.randint(10, 55) * 10000) * mult / 10000)) * 10000
    state.merchant_boost_stock = random.randint(3, 16)
    state.merchant_downgrade_price = int(round((random.randint(14, 75) * 10000) * mult / 10000)) * 10000
    state.merchant_downgrade_stock = random.randint(2, 10)
    state.merchant_snipe_price = int(round((random.randint(22, 110) * 10000) * mult / 10000)) * 10000
    state.merchant_snipe_stock = random.randint(1, 6)

    # Roll special named sniper scroll with scaled price
    sp_code, sp_name, sp_desc, sp_price, sp_stock = roll_merchant_special_snipe()
    if sp_price:
        sp_price = int(round(sp_price * mult / 10000)) * 10000
    state.merchant_special_snipe_code = sp_code
    state.merchant_special_snipe_name = sp_name
    state.merchant_special_snipe_desc = sp_desc
    state.merchant_special_snipe_price = sp_price
    state.merchant_special_snipe_stock = sp_stock

    # Ultra-luxury 100% Absolute Defense & Drop Prevention Scrolls (35% chance, 1 stock, dynamic pricing)
    if random.uniform(0, 100) < 35.0:
        base_s100 = random.randint(50, 95) * 100000
        state.merchant_shield_100_price = int(round(base_s100 * mult / 100000)) * 100000
        state.merchant_shield_100_stock = 1
    else:
        state.merchant_shield_100_stock = 0

    if random.uniform(0, 100) < 35.0:
        base_d100 = random.randint(35, 75) * 100000
        state.merchant_downgrade_100_price = int(round(base_d100 * mult / 100000)) * 100000
        state.merchant_downgrade_100_stock = 1
    else:
        state.merchant_downgrade_100_stock = 0

    db.commit()
    db.refresh(state)

    ev_state = get_merchant_state(db)
    sp_msg = f" | ⭐ 한정 특매: [{state.merchant_special_snipe_name}]" if state.merchant_special_snipe_stock > 0 else ""
    if state.merchant_shield_100_stock > 0:
        sp_msg += " | 🛡️ [100% 절대파방 한정 입고!]"
    if state.merchant_downgrade_100_stock > 0:
        sp_msg += " | 📉 [100% 절대하강 한정 입고!]"
    msg = f"🧞‍♂️🛒 [신비상인 등장] 방랑 {name}이(가) 마을에 나타났습니다! ({dur_m}분간 영업{sp_msg} | 명령어: !신비상인, !상인구매)"
    return True, msg, ev_state

def close_merchant(db: Session) -> Tuple[bool, str, Dict[str, Any]]:
    """Close Mysterious Merchant."""
    state = get_market_state(db)
    now = time.time()
    name = getattr(state, "merchant_name", "신비상인") or "신비상인"

    state.merchant_is_open = False
    state.merchant_end_time = 0.0
    state.merchant_next_time = now + random.uniform(MERCHANT_MIN_INTERVAL_MINUTES, MERCHANT_MAX_INTERVAL_MINUTES) * 60.0

    db.commit()
    db.refresh(state)

    msg = f"🔒 [신비상인 퇴장] {name}이(가) 보따리를 싸고 마을을 떠났습니다. 다음 방문을 기다려주세요!"
    details = {
        "is_active": False,
        "remaining_sec": 0,
        "merchant_name": name
    }
    return True, msg, details

def execute_buy_merchant_item(
    db: Session,
    user_id: str,
    username: str,
    item_key_str: str,
    quantity_str: str = "1"
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Buy item from Mysterious Merchant (!상인구매 [1/2/3/4/5] [수량])."""
    m_state = get_merchant_state(db)
    if not m_state["is_active"]:
        next_m = max(1, m_state["next_event_in_sec"] // 60)
        return False, f"🔒 지금은 신비상인이 마을에 없습니다! (약 {next_m}분 후 다음 방문 예정. 스트리머 전용: !신비상인오픈 [분])", None

    state = get_market_state(db)
    clean_key = (item_key_str or "").strip().lower()
    matched_item_type = None
    for k, info in MERCHANT_ITEMS.items():
        if clean_key in [str(info["id"])] + [a.lower() for a in info["aliases"]]:
            matched_item_type = k
            break

    is_special = False
    if clean_key in ["5", "special", "특수", "전용", "전용저격", "전용주문서", "특정"]:
        is_special = True
    elif state.merchant_special_snipe_code and (
        clean_key == state.merchant_special_snipe_code.lower() or
        (state.merchant_special_snipe_name and clean_key in state.merchant_special_snipe_name.lower())
    ):
        is_special = True

    if not matched_item_type and not is_special:
        sp_guide = f", 5({state.merchant_special_snipe_name})" if (getattr(state, "merchant_special_snipe_stock", 0) > 0 and state.merchant_special_snipe_name) else ""
        return False, f"⚠️ 구매할 아이템을 지정해주세요: 1(파괴방어권), 2(강화확률상승권), 3(하강방지권), 4(잠재저격주문서){sp_guide} (예: !상인구매 4 1, !상인구매 저격 1)", None

    user = get_or_create_user(db, user_id, username)

    if is_special:
        unit_price = getattr(state, "merchant_special_snipe_price", 750000) or 750000
        avail_stock = getattr(state, "merchant_special_snipe_stock", 0) or 0
        item_def = {
            "id": 5,
            "name": getattr(state, "merchant_special_snipe_name", "특수 전용 저격주문서") or "특수 전용 저격주문서",
            "desc": getattr(state, "merchant_special_snipe_desc", "1줄 88% 확정급 전용 저격") or "1줄 88% 확정급 전용 저격"
        }
        if avail_stock <= 0 or not state.merchant_special_snipe_code:
            return False, "⚠️ 특수 전용 저격주문서는 오늘 입고되지 않았거나 매진되었습니다!", None
    else:
        item_def = MERCHANT_ITEMS[matched_item_type]
        if matched_item_type == "shield":
            unit_price = getattr(state, "merchant_shield_price", 500000) or 500000
            avail_stock = getattr(state, "merchant_shield_stock", 0) or 0
        elif matched_item_type == "boost":
            unit_price = getattr(state, "merchant_boost_price", 350000) or 350000
            avail_stock = getattr(state, "merchant_boost_stock", 0) or 0
        elif matched_item_type == "downgrade":
            unit_price = getattr(state, "merchant_downgrade_price", 400000) or 400000
            avail_stock = getattr(state, "merchant_downgrade_stock", 0) or 0
        elif matched_item_type == "shield_100":
            unit_price = getattr(state, "merchant_shield_100_price", 15000000) or 15000000
            avail_stock = getattr(state, "merchant_shield_100_stock", 0) or 0
        elif matched_item_type == "downgrade_100":
            unit_price = getattr(state, "merchant_downgrade_100_price", 10000000) or 10000000
            avail_stock = getattr(state, "merchant_downgrade_100_stock", 0) or 0
        else:  # snipe
            unit_price = getattr(state, "merchant_snipe_price", 500000) or 500000
            avail_stock = getattr(state, "merchant_snipe_stock", 0) or 0

    if avail_stock <= 0:
        return False, f"⚠️ [{item_def['name']}]은(는) 오늘 준비된 수량이 모두 매진되었습니다!", None

    try:
        clean_q = str(quantity_str).strip().lower()
        if clean_q in ["올인", "최대", "max", "다", "전부"]:
            qty = min(avail_stock, max(1, user.points // unit_price if unit_price > 0 else 1))
        else:
            qty = int(clean_q.replace("개", "").replace("장", "").strip())
    except (ValueError, TypeError):
        qty = 1

    if qty <= 0:
        qty = 1

    requested_qty = qty
    # Clamp quantity to available stock ("더 많은 개수 입력하면 있는만큼 사게해줘")
    if qty > avail_stock:
        qty = avail_stock

    total_cost = qty * unit_price
    if user.points < total_cost:
        affordable_qty = (user.points // unit_price) if unit_price > 0 else 0
        if affordable_qty > 0:
            qty = min(qty, affordable_qty)
            total_cost = qty * unit_price
        else:
            return False, f"⚠️ 보유 현금이 부족합니다! (필요: {unit_price:,}P | 보유: {user.points:,}P | 단가: {unit_price:,}P)", None

    # Deduct funds and grant consumable item
    user.points -= total_cost
    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL
    state.treasury_pool += total_cost

    # Update stock in state
    if is_special:
        state.merchant_special_snipe_stock = max(0, avail_stock - qty)
        add_user_special_snipe_scroll(user, state.merchant_special_snipe_code, qty)
        user_stock = get_user_special_snipe_scrolls(user).get(state.merchant_special_snipe_code, 0)
    elif matched_item_type == "shield":
        state.merchant_shield_stock = max(0, avail_stock - qty)
        user.shield_scroll_count = (getattr(user, "shield_scroll_count", 0) or 0) + qty
        user_stock = user.shield_scroll_count
    elif matched_item_type == "boost":
        state.merchant_boost_stock = max(0, avail_stock - qty)
        user.boost_scroll_count = (getattr(user, "boost_scroll_count", 0) or 0) + qty
        user_stock = user.boost_scroll_count
    elif matched_item_type == "downgrade":
        state.merchant_downgrade_stock = max(0, avail_stock - qty)
        user.downgrade_scroll_count = (getattr(user, "downgrade_scroll_count", 0) or 0) + qty
        user_stock = user.downgrade_scroll_count
    elif matched_item_type == "shield_100":
        state.merchant_shield_100_stock = max(0, avail_stock - qty)
        user.shield_100_scroll_count = (getattr(user, "shield_100_scroll_count", 0) or 0) + qty
        user_stock = user.shield_100_scroll_count
    elif matched_item_type == "downgrade_100":
        state.merchant_downgrade_100_stock = max(0, avail_stock - qty)
        user.downgrade_100_scroll_count = (getattr(user, "downgrade_100_scroll_count", 0) or 0) + qty
        user_stock = user.downgrade_100_scroll_count
    else:  # snipe
        state.merchant_snipe_stock = max(0, avail_stock - qty)
        user.snipe_scroll_count = (getattr(user, "snipe_scroll_count", 0) or 0) + qty
        user_stock = user.snipe_scroll_count

    total_remaining_stock = (
        (getattr(state, "merchant_shield_stock", 0) or 0) +
        (getattr(state, "merchant_boost_stock", 0) or 0) +
        (getattr(state, "merchant_downgrade_stock", 0) or 0) +
        (getattr(state, "merchant_snipe_stock", 0) or 0) +
        (getattr(state, "merchant_special_snipe_stock", 0) or 0) +
        (getattr(state, "merchant_shield_100_stock", 0) or 0) +
        (getattr(state, "merchant_downgrade_100_stock", 0) or 0)
    )

    all_sold_out = (total_remaining_stock <= 0)
    sold_out_msg = ""
    if all_sold_out:
        close_merchant(db)
        sold_out_msg = f"\n🚪💨 [완판 마감] 신비상인의 모든 물품이 완판(매진)되어 보따리를 싸고 마을을 떠났습니다! 다음 방문을 기다려주세요."
    else:
        db.commit()
        db.refresh(user)
        db.refresh(state)

    clamp_msg = f" (요청 {requested_qty}개 중 가능 수량 {qty}개 구매)" if requested_qty > qty else ""
    reply = (
        f"🛒✨ [신비상인 구매 완료] {user.username}님이 [{item_def['name']}] {qty}장을 {total_cost:,}P에 구매했습니다!{clamp_msg} "
        f"(보유 수량: {user_stock}장 | 잔여 현금: {user.points:,}P | 상인 남은 재고: {max(0, avail_stock - qty)}개){sold_out_msg}"
    )
    details = {
        "item_type": "special" if is_special else matched_item_type,
        "item_name": item_def["name"],
        "quantity": qty,
        "unit_price": unit_price,
        "total_cost": total_cost,
        "user_stock": user_stock,
        "remaining_merchant_stock": max(0, avail_stock - qty),
        "user_points": user.points,
        "all_sold_out": all_sold_out
    }
    return True, reply, details

def get_merchant_guide(db: Session) -> str:
    m_state = get_merchant_state(db)
    if not m_state["is_active"]:
        next_m = max(1, m_state["next_event_in_sec"] // 60)
        return f"🔒 [신비상인: 부재중] 신비상인이 여행 중입니다. 약 {next_m}분 후에 다시 마을에 나타납니다! (명령어: !신비상인)"

    items = m_state["items"]
    rem = m_state["remaining_sec"]
    m = rem // 60
    s = rem % 60

    extra_lines = []
    buy_guide = "!상인구매 [1/2/3/4] [수량] (예: !상인구매 4 1, !상인구매 저격 1)"
    if "special" in items and items["special"].get("stock", 0) > 0:
        sp = items["special"]
        extra_lines.append(f"5. 🌟 {sp['name']} : {sp['price']:,}P (재고 {sp['stock']}개) - {sp['desc']}")
        buy_guide = "!상인구매 [1~5] [수량]"

    if "shield_100" in items and items["shield_100"].get("stock", 0) > 0:
        s100 = items["shield_100"]
        extra_lines.append(f"6. 🛡️✨ {s100['name']} : {s100['price']:,}P (한정 1개) - ★15+ 파괴 확률 100% 완전 방어!")
        buy_guide = "!상인구매 [1~7] [수량] (예: !상인구매 6 1, !상인구매 절대파방)"

    if "downgrade_100" in items and items["downgrade_100"].get("stock", 0) > 0:
        d100 = items["downgrade_100"]
        extra_lines.append(f"7. 📉✨ {d100['name']} : {d100['price']:,}P (한정 1개) - 실패 시 성수 하락 100% 완전 방어!")
        buy_guide = "!상인구매 [1~7] [수량] (예: !상인구매 7 1, !상인구매 절대하강)"

    extra_txt = ("\n".join(extra_lines) + "\n") if extra_lines else ""

    return (
        f"🧞‍♂️✨ [신비상인의 비밀 보따리 상점] (남은 시간: {m}분 {s:02d}초)\n"
        f"1. 🛡️ 파괴방어권 : {items['shield']['price']:,}P (재고 {items['shield']['stock']}개) - 15성+ 폭발 파괴 60% 방어\n"
        f"2. ⚡ 강화확률상승권 : {items['boost']['price']:,}P (재고 {items['boost']['stock']}개) - 강화 성공률 +25% 곱연산 증폭\n"
        f"3. 📉 하강방지권 : {items['downgrade']['price']:,}P (재고 {items['downgrade']['stock']}개) - 실패 시 성수 하락 70% 방어\n"
        f"4. 🎯 잠재저격주문서 : {items['snipe']['price']:,}P (재고 {items['snipe']['stock']}개) - 큐브 사용 시 원하는 옵션 확률 대폭 증가 (1줄 35% 저격 + 전체 3.5배 가중치)\n"
        f"{extra_txt}"
        f"💡 구매 명령어: {buy_guide}"
    )

def get_user_item_inventory(db: Session, user: User) -> Dict[str, Any]:
    return {
        "cube_count": getattr(user, "cube_count", 0) or 0,
        "cube_fragments": getattr(user, "cube_fragments", 0) or 0,
        "shield_scroll_count": getattr(user, "shield_scroll_count", 0) or 0,
        "boost_scroll_count": getattr(user, "boost_scroll_count", 0) or 0,
        "downgrade_scroll_count": getattr(user, "downgrade_scroll_count", 0) or 0,
        "snipe_scroll_count": getattr(user, "snipe_scroll_count", 0) or 0,
    }

def get_pickaxe_info(level: int, event_state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    lvl = max(0, min(30, int(level or 0)))

    if lvl >= 30:
        base_name = "👑 오리하르콘 곡괭이"
    elif lvl >= 28:
        base_name = "🛡️ 아다만티움 곡괭이"
    elif lvl >= 25:
        base_name = "🔮 미스릴 곡괭이"
    elif lvl >= 22:
        base_name = "🌌 옵시디언 곡괭이"
    elif lvl >= 20:
        base_name = "💎 다이아 곡괭이"
    elif lvl >= 15:
        base_name = "🪙 황금 곡괭이"
    elif lvl >= 10:
        base_name = "⛓️ 철 곡괭이"
    elif lvl >= 5:
        base_name = "🪨 돌 곡괭이"
    else:
        base_name = "🪵 나무 곡괭이"

    name = f"{base_name} (★{lvl}성)"
    if lvl == 30:
        name = f"{base_name} (★30성 종결 MAX)"

    t = dict(STARFORCE_TIERS[lvl])

    # Star Force Fever Event adjustments
    has_discount = False
    has_100_percent = False
    if event_state and event_state.get("is_active"):
        has_discount = bool(event_state.get("has_discount"))
        has_100_percent = bool(event_state.get("has_100_percent"))

    base_cost = t["cost"]
    cost = base_cost
    if has_discount and base_cost > 0:
        cost = max(100, int(round(base_cost * 0.70)))

    s_rate = t["success"]
    m_rate = t["maintain"]
    d_rate = t["drop"]
    dest_rate = t["destroy"]

    is_guaranteed_100 = False
    if has_100_percent and lvl in (5, 10, 15):
        s_rate = 100.0
        m_rate = 0.0
        d_rate = 0.0
        dest_rate = 0.0
        is_guaranteed_100 = True

    # Mining yield multiplier calculation (BUFFED)
    # 0성 1.0x -> 10성 3.0x -> 15성 6.5x -> 20성 22.0x -> 22성 36.0x -> 25성 80.0x -> 30성 300.0x
    yield_table = {
        0: 1.00, 1: 1.15, 2: 1.30, 3: 1.45, 4: 1.60,
        5: 1.80, 6: 2.00, 7: 2.20, 8: 2.40, 9: 2.65,
        10: 3.00, 11: 3.50, 12: 4.00, 13: 4.60, 14: 5.30,
        15: 6.50, 16: 8.50, 17: 11.00, 18: 14.00, 19: 17.50,
        20: 22.00, 21: 28.00,
        22: 36.00, 23: 45.00, 24: 58.00,
        25: 80.00, 26: 105.00, 27: 135.00, 28: 175.00, 29: 230.00,
        30: 300.00
    }
    yield_mult = yield_table.get(lvl, 1.00)

    # Guaranteed Bonus Points per Mine (BUFFED: 5성 돌 곡괭이부터 매 채굴마다 무조건 확정 지급되는 추가 현금)
    # 0~4성 0P -> 5성 5천P -> 10성 1.5만P -> 15성 6만P -> 20성 28만P -> 22성 50만P -> 25성 120만P -> 30성 500만P
    bonus_points_table = {
        0: 0, 1: 0, 2: 0, 3: 0, 4: 0,
        5: 5000, 6: 6500, 7: 8000, 8: 10000, 9: 12000,
        10: 15000, 11: 20000, 12: 25000, 13: 32000, 14: 40000,
        15: 60000, 16: 85000, 17: 120000, 18: 160000, 19: 210000,
        20: 280000, 21: 380000,
        22: 500000, 23: 650000, 24: 850000,
        25: 1200000, 26: 1600000, 27: 2100000, 28: 2800000, 29: 3700000,
        30: 5000000
    }
    bonus_points = bonus_points_table.get(lvl, 0)

    # Crit bonus (BUFFED)
    # 0성 0% -> 10성 20% -> 15성 45% -> 20성 85% -> 22성 100% -> 25성 150% -> 30성 300%
    crit_table = {
        0: 0.0, 1: 1.5, 2: 3.0, 3: 4.5, 4: 6.0,
        5: 8.0, 6: 10.0, 7: 12.0, 8: 14.0, 9: 16.0,
        10: 20.0, 11: 24.0, 12: 28.0, 13: 32.0, 14: 36.0,
        15: 45.0, 16: 52.0, 17: 60.0, 18: 68.0, 19: 76.0,
        20: 85.0, 21: 92.0,
        22: 100.0, 23: 110.0, 24: 120.0,
        25: 150.0, 26: 175.0, 27: 200.0, 28: 230.0, 29: 265.0,
        30: 300.0
    }
    crit = crit_table.get(lvl, 0.0)

    # Cooldown minutes (BUFFED: 15분 -> 10분 -> 8분 -> 6분 -> 5분 -> 4분 -> 3분 -> 2분)
    if lvl >= 28:
        cd_min = 2
    elif lvl >= 25:
        cd_min = 3
    elif lvl >= 22:
        cd_min = 4
    elif lvl >= 20:
        cd_min = 5
    elif lvl >= 17:
        cd_min = 6
    elif lvl >= 15:
        cd_min = 8
    elif lvl >= 10:
        cd_min = 10
    elif lvl >= 5:
        cd_min = 13
    else:
        cd_min = 15

    desc_parts = [f"채굴량 {yield_mult}배"]
    if bonus_points > 0:
        desc_parts.append(f"확정 +{bonus_points:,}P")
    desc_parts.append(f"크리 +{crit}%")
    desc_parts.append(f"쿨 {cd_min}분")
    if lvl >= 15:
        desc_parts.append("석탄 면제(꽝 0%)")
    desc = ", ".join(desc_parts)

    return {
        "level": lvl,
        "name": name,
        "base_name": base_name,
        "upgrade_cost": cost,
        "base_cost": base_cost,
        "is_discounted": has_discount,
        "is_guaranteed_100": is_guaranteed_100,
        "yield_multiplier": yield_mult,
        "bonus_points": bonus_points,
        "crit_bonus": crit,
        "cooldown_minutes": cd_min,
        "cooldown_seconds": cd_min * 60,
        "success_rate": s_rate,
        "maintain_rate": m_rate,
        "drop_rate": d_rate,
        "destroy_rate": dest_rate,
        "desc": desc
    }

# Backwards compatibility dictionary mapping
PICKAXE_TIERS: Dict[int, Dict[str, Any]] = {i: get_pickaxe_info(i) for i in range(31)}

# 채굴 등급 및 크리티컬 확률/보상 테이블 (일확천금 신화급 잭팟 추가)
MINING_TIERS = [
    {
        "code": "EX",
        "name": "🀄🌟 [천화(天和) 신화급 국고 잭팟!! (0.2%)]",
        "prob": 0.2,
        "multiplier": 20.0,
        "bonus_cash_pct": 0.10,  # 국고 10% 일시불 (최소 5만P ~ 최대 30만P)
        "min_cash": 50000,
        "max_cash": 300000,
        "bonus_10x": 5.0,        # 10X 레버리지 5주!
        "cooldown_reduction": 15, # 쿨타임 즉시 초기화
    },
    {
        "code": "UR+",
        "name": "🀄 [순정 구련보등 더블역만 광맥!! (0.8%)]",
        "prob": 0.8,
        "multiplier": 10.0,
        "bonus_cash_pct": 0.05,  # 국고 5% (최소 2만P ~ 최대 10만P)
        "min_cash": 20000,
        "max_cash": 100000,
        "bonus_10x": 2.0,        # 10X 레버리지 2주!
        "cooldown_reduction": 10, # 쿨타임 10분 단축
    },
    {
        "code": "UR",
        "name": "🀄 [국사무쌍 13면대기 역만급 초대박 광맥!! (2.0%)]",
        "prob": 2.0,
        "multiplier": 5.0,
        "bonus_cash": 15000,
        "bonus_10x": 1.0,
        "cooldown_reduction": 7,  # 쿨타임 7분 단축
    },
    {
        "code": "SSR",
        "name": "💎 [다이아몬드 광맥 슈퍼 크리티컬! (5.0%)]",
        "prob": 5.0,
        "multiplier": 3.0,
        "bonus_cash": 7000,
        "bonus_10x": 0.0,
        "cooldown_reduction": 5,   # 쿨타임 5분 단축
    },
    {
        "code": "SR",
        "name": "⚡ [황금 광맥 더블 크리티컬! (14.0%)]",
        "prob": 14.0,
        "multiplier": 2.0,
        "bonus_cash": 2000,
        "bonus_10x": 0.0,
        "cooldown_reduction": 0,
    },
    {
        "code": "R",
        "name": "✨ [풍부한 은 광맥 보너스 채굴 (23.0%)]",
        "prob": 23.0,
        "multiplier_range": (1.3, 1.5),
        "bonus_cash": 0,
        "bonus_10x": 0.0,
        "cooldown_reduction": 0,
    },
    {
        "code": "N",
        "name": "⛏️ [평범한 구리 광맥 일반 채굴 (37.0%)]",
        "prob": 37.0,
        "multiplier": 1.0,
        "bonus_cash": 0,
        "bonus_10x": 0.0,
        "cooldown_reduction": 0,
    },
    {
        "code": "C",
        "name": "🪨 [석탄·자갈 광맥 소박 채굴 (18.0%)]",
        "prob": 18.0,
        "multiplier_range": (0.6, 0.8),
        "bonus_cash": 0,
        "bonus_10x": 0.0,
        "cooldown_reduction": 0,
    }
]

def roll_mining_tier(crit_bonus: float = 0.0, pickaxe_level: int = 0) -> Dict[str, Any]:
    """
    Roll random mining tier based on weighted probabilities.
    Higher-level pickaxes grant a crit_bonus which boosts EX/UR+/UR/SSR/SR/R rates.
    ★15성(황금 곡괭이) 이상 장착 시 석탄(C) 광맥 출현율 0% 영구 면제.
    """
    cb = max(0.0, float(crit_bonus or 0.0))
    lvl = max(0, int(pickaxe_level or 0))
    is_golden_or_above = (lvl >= 15) or (cb >= 45.0)

    # Calculate dynamic weights
    weights = []
    for tier in MINING_TIERS:
        code = tier["code"]
        base_prob = tier["prob"]
        if lvl >= 20 or cb >= 85.0:
            # ★ 20성 이상 초고강화 마스터 역만 특화 비례 곱연산 증폭 (합산 역만 28%)
            if code == "EX":
                w = base_prob * (1.0 + cb * 0.350)      # 천화 신화 잭팟 대폭 증폭 (약 4.7%)
            elif code == "UR+":
                w = base_prob * (1.0 + cb * 0.180)      # 구련보등 더블역만 대폭 증폭 (약 10.0%)
            elif code == "UR":
                w = base_prob * (1.0 + cb * 0.090)      # 국사무쌍 역만 대폭 증폭 (약 13.3%)
            elif code == "SSR":
                w = base_prob * (1.0 + cb * 0.038)      # 다이아몬드 광맥
            elif code == "SR":
                w = base_prob * (1.0 + cb * 0.018)      # 황금 광맥
            elif code == "R":
                w = base_prob * (1.0 + cb * 0.002)      # 은 광맥
            elif code == "N":
                w = max(0.0, base_prob / (1.0 + cb * 0.030))  # 일반 구리 광맥 감소
            elif code == "C":
                w = 0.0  # 석탄 광맥 0% 완전 면제
            else:
                w = base_prob
        elif is_golden_or_above:
            # ★ 15성(황금 곡괭이) 이상 여유롭고 풍성한 고등급 채굴 곱연산 비례 보정
            if code == "EX":
                w = base_prob * (1.0 + cb * 0.240)      # 천화 신화 잭팟 곱연산 증폭
            elif code == "UR+":
                w = base_prob * (1.0 + cb * 0.115)      # 구련보등 더블역만 곱연산 증폭
            elif code == "UR":
                w = base_prob * (1.0 + cb * 0.055)      # 국사무쌍 역만 곱연산 증폭
            elif code == "SSR":
                w = base_prob * (1.0 + cb * 0.038)      # 다이아몬드 광맥 곱연산 증폭
            elif code == "SR":
                w = base_prob * (1.0 + cb * 0.018)      # 황금 광맥 곱연산 증폭
            elif code == "R":
                w = base_prob * (1.0 + cb * 0.002)      # 은 광맥 곱연산 증폭
            elif code == "N":
                w = max(0.0, base_prob / (1.0 + cb * 0.030))  # 일반 구리 광맥 감소
            elif code == "C":
                w = 0.0  # ★15성(황금 곡괭이) 이상 석탄 광맥 0% 완전 면제
            else:
                w = base_prob
        else:
            # 15성 미만 일반 성장 곱연산 비례 보정
            if code == "EX":
                w = base_prob * (1.0 + cb * 0.140)      # 천화 신화 잭팟
            elif code == "UR+":
                w = base_prob * (1.0 + cb * 0.070)      # 구련보등 더블역만
            elif code == "UR":
                w = base_prob * (1.0 + cb * 0.035)      # 국사무쌍 역만
            elif code == "SSR":
                w = base_prob * (1.0 + cb * 0.026)      # 다이아몬드 광맥
            elif code == "SR":
                w = base_prob * (1.0 + cb * 0.012)      # 황금 광맥
            elif code == "R":
                w = base_prob * (1.0 + cb * 0.004)      # 은 광맥
            elif code == "N":
                w = max(0.0, base_prob / (1.0 + cb * 0.015))  # 일반 구리 광맥 감소율
            elif code == "C":
                w = max(0.0, base_prob / (1.0 + cb * 0.015))  # 석탄 꽝 감소율
            else:
                w = base_prob
        weights.append(max(0.0, w))

    total_w = sum(weights)
    if total_w <= 0:
        tier_choice = MINING_TIERS[6]
    else:
        tier_choice = random.choices(MINING_TIERS, weights=weights, k=1)[0]

    t = dict(tier_choice)
    if "multiplier_range" in t:
        low, high = t["multiplier_range"]
        t["multiplier"] = round(random.uniform(low, high), 2)
    return t

# =========================================================
# 자동 채굴 (Auto Mining) 시스템
# - 곡괭이 등급(스타포스)에 따른 세션 지속 시간 (0성 30분 ~ 25성 24시간)
# - 최대 황금 광맥(SR)까지만 출현 (EX, UR+, UR, SSR 잭팟 제외)
# - 기본 확률 및 배율 하향(너프) 조정으로 AFK 패시브 밸런스 유지
# =========================================================
AUTO_MINING_DURATION_HOURS: Dict[int, float] = {
    0: 0.5,    # 30분 (나무 곡괭이 0성)
    1: 0.6,    # 36분
    2: 0.75,   # 45분
    3: 0.85,   # 51분
    4: 1.0,    # 1시간
    5: 2.0,    # 2시간 (돌 곡괭이 5성)
    6: 2.25,   # 2시간 15분
    7: 2.5,    # 2시간 30분
    8: 3.0,    # 3시간
    9: 3.5,    # 3시간 30분
    10: 4.0,   # 4시간 (철 곡괭이 10성)
    11: 4.5,   # 4시간 30분
    12: 5.0,   # 5시간
    13: 5.5,   # 5시간 30분
    14: 6.0,   # 6시간
    15: 8.0,   # 8시간 (황금 곡괭이 15성)
    16: 9.0,   # 9시간
    17: 10.0,  # 10시간
    18: 11.0,  # 11시간
    19: 12.0,  # 12시간
    20: 14.0,  # 14시간 (다이아 곡괭이 20성)
    21: 16.0,  # 16시간
    22: 20.0,  # 20시간 (옵시디언 22성)
    23: 21.0,  # 21시간
    24: 22.0,  # 22시간
    25: 24.0,  # 24시간 (미스릴 곡괭이 25성)
    26: 28.0,  # 28시간
    27: 32.0,  # 32시간
    28: 36.0,  # 36시간 (아다만티움 곡괭이 28성)
    29: 42.0,  # 42시간
    30: 48.0   # 48시간 (오리하르콘 곡괭이 30성 종결 MAX)
}

def get_auto_mining_duration_hours(level: int) -> float:
    lvl = max(0, min(30, int(level or 0)))
    return AUTO_MINING_DURATION_HOURS.get(lvl, 0.5)

def format_duration_hours(hours: float) -> str:
    total_min = int(round(hours * 60))
    h, m = divmod(total_min, 60)
    if h > 0 and m > 0:
        return f"{h}시간 {m}분"
    elif h > 0:
        return f"{h}시간"
    else:
        return f"{m}분"

AUTO_MINING_TIERS = [
    {
        "code": "SR",
        "name": "⚡ [자동 채굴] 황금 광맥 크리티컬! (5.0%)",
        "prob": 5.0,
        "multiplier": 1.6,
        "bonus_cash": 1000,
        "bonus_10x": 0.0,
        "cooldown_reduction": 0
    },
    {
        "code": "R",
        "name": "✨ [자동 채굴] 은 광맥 보너스 채굴 (18.0%)",
        "prob": 18.0,
        "multiplier_range": (1.1, 1.3),
        "bonus_cash": 0,
        "bonus_10x": 0.0,
        "cooldown_reduction": 0
    },
    {
        "code": "N",
        "name": "⛏️ [자동 채굴] 구리 광맥 일반 채굴 (42.0%)",
        "prob": 42.0,
        "multiplier": 0.9,
        "bonus_cash": 0,
        "bonus_10x": 0.0,
        "cooldown_reduction": 0
    },
    {
        "code": "C",
        "name": "🪨 [자동 채굴] 석탄·자갈 광맥 소박 채굴 (35.0%)",
        "prob": 35.0,
        "multiplier_range": (0.5, 0.7),
        "bonus_cash": 0,
        "bonus_10x": 0.0,
        "cooldown_reduction": 0
    }
]

def roll_auto_mining_tier(crit_bonus: float = 0.0) -> Dict[str, Any]:
    """
    Roll random tier specifically for auto-mining:
    - Maximum tier is 황금 광맥 (SR). Never rolls EX, UR+, UR, SSR.
    - Probabilities and multipliers are nerfed compared to manual mining.
    """
    cb = max(0.0, float(crit_bonus or 0.0))
    w_sr = min(12.0, 5.0 + cb * 0.05)
    w_r = min(25.0, 18.0 + cb * 0.08)
    w_n = max(30.0, 42.0 - cb * 0.06)
    w_c = max(20.0, 35.0 - cb * 0.07)

    tier_choice = random.choices(AUTO_MINING_TIERS, weights=[w_sr, w_r, w_n, w_c], k=1)[0]
    t = dict(tier_choice)
    if "multiplier_range" in t:
        low, high = t["multiplier_range"]
        t["multiplier"] = round(random.uniform(low, high), 2)
    return t

def execute_auto_mining_tick(
    db: Session,
    user: User,
    now_utc: Optional[datetime] = None
) -> Optional[Dict[str, Any]]:
    """
    Execute a single auto-mining tick for a user if auto-mining is enabled and cooldown is ready.
    """
    if not bool(getattr(user, "auto_mining_enabled", False)):
        return None

    now_utc = now_utc or datetime.now(timezone.utc)
    now_ts = now_utc.timestamp()
    end_time = float(getattr(user, "auto_mining_end_time", 0.0) or 0.0)

    # 1. Expiration check
    if end_time <= 0 or now_ts >= end_time:
        user.auto_mining_enabled = False
        user.auto_mining_end_time = 0.0
        try:
            db.commit()
        except Exception:
            pass
        return None

    # 2. Pickaxe and cooldown check
    equipped_item = get_user_equipped_item(db, user)
    star = equipped_item.starforce if equipped_item else getattr(user, "pickaxe_level", 0)
    star = max(0, min(30, int(star or 0)))
    pickaxe = get_pickaxe_info(star)
    pot_eff = get_equipment_potential_effects(equipped_item) if equipped_item else {}
    pot_cd_red = pot_eff.get("mining_cd_reduction", 0)
    heavy_cd_add = pot_eff.get("heavy_mining_cd_add", 0)
    effective_cd_min = max(2, pickaxe["cooldown_minutes"] - pot_cd_red + heavy_cd_add)
    cooldown_sec = effective_cd_min * 60
    pickaxe_bonus_cash = pickaxe.get("bonus_points", 0)

    if user.last_mined_at:
        last_time = user.last_mined_at
        if last_time.tzinfo is None:
            last_time = last_time.replace(tzinfo=timezone.utc)
        elapsed = (now_utc - last_time).total_seconds()
        if elapsed < cooldown_sec:
            return None

    # 3. Dynamic Base Reward & Tier Roll
    state = get_market_state(db)
    current_price = state.current_price
    target_cash = min(float(current_price), max(current_price * 0.2, state.treasury_pool * 0.05))
    base_shares = round(target_cash / current_price, 2)
    if base_shares <= 0.05:
        base_shares = 0.1
    base_shares = round(base_shares * pickaxe["yield_multiplier"], 2)

    tier = roll_auto_mining_tier(crit_bonus=pickaxe.get("crit_bonus", 0.0))
    multiplier = tier["multiplier"]
    bonus_cash = tier.get("bonus_cash", 0)
    total_bonus_cash = bonus_cash + pickaxe_bonus_cash

    shares_awarded = round(base_shares * multiplier, 2)
    if shares_awarded <= 0.05:
        shares_awarded = 0.05

    heavy_reward_pct = pot_eff.get("heavy_mining_reward_pct", 0.0)
    if heavy_reward_pct > 0:
        heavy_mult = 1.0 + (heavy_reward_pct / 100.0)
        shares_awarded = round(shares_awarded * heavy_mult, 2)
        total_bonus_cash = int(round(total_bonus_cash * heavy_mult))

    actual_cost = int(round(shares_awarded * current_price))
    total_mined_cost = actual_cost + total_bonus_cash

    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL
    state.treasury_pool = max(0.0, state.treasury_pool - total_mined_cost)

    # 4. Debt payoff or shares credit
    user_debt = getattr(user, "debt", 0) or 0
    if user_debt > 0:
        total_payout = actual_cost + total_bonus_cash
        repay_amt = min(user_debt, total_payout)
        user.debt = user_debt - repay_amt
        state.treasury_pool += repay_amt
        excess = total_payout - repay_amt
        if excess > 0:
            user.points += excess
    else:
        pos = db.query(Position).filter_by(user_id=user.id, product_type=ProductType.ONE_X).first()
        if pos and pos.quantity > 0:
            pos.quantity += shares_awarded
            pos.invested_cash += actual_cost
            pos.entry_price = pos.invested_cash / pos.quantity
        else:
            if not pos:
                pos = Position(
                    user_id=user.id,
                    product_type=ProductType.ONE_X,
                    quantity=shares_awarded,
                    entry_price=current_price,
                    invested_cash=actual_cost
                )
                db.add(pos)
            else:
                pos.quantity = shares_awarded
                pos.entry_price = current_price
                pos.invested_cash = actual_cost
        if total_bonus_cash > 0:
            user.points += total_bonus_cash

    # 5. Session and lifetime stats
    user.total_mined = float(getattr(user, "total_mined", 0.0) or 0.0) + shares_awarded
    user.auto_mining_session_mined = float(getattr(user, "auto_mining_session_mined", 0.0) or 0.0) + shares_awarded
    user.auto_mining_session_points = int(getattr(user, "auto_mining_session_points", 0) or 0) + actual_cost + total_bonus_cash
    user.last_mined_at = now_utc

    db.commit()
    db.refresh(user)
    db.refresh(state)

    return {
        "user_id": user.id,
        "username": user.username,
        "shares_awarded": shares_awarded,
        "bonus_cash": total_bonus_cash,
        "actual_cost": actual_cost,
        "tier_name": tier["name"],
        "tier_code": tier["code"],
        "pickaxe_name": pickaxe["name"],
        "session_mined": user.auto_mining_session_mined,
        "session_points": user.auto_mining_session_points
    }

def process_all_auto_mining(db: Session) -> List[Dict[str, Any]]:
    """Runs a single auto-mining pass for all users with auto-mining enabled."""
    users = db.query(User).filter(User.auto_mining_enabled == True).all()
    results = []
    now_utc = datetime.now(timezone.utc)
    for u in users:
        tick = execute_auto_mining_tick(db, u, now_utc=now_utc)
        if tick:
            results.append(tick)
    return results

def set_auto_mining(
    db: Session,
    user_id: str,
    username: str,
    enable: bool
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Turn Auto-Mining ON or OFF for a user."""
    user = get_or_create_user(db, user_id, username)
    equipped_item = get_user_equipped_item(db, user)
    star = equipped_item.starforce if equipped_item else getattr(user, "pickaxe_level", 0)
    star = max(0, min(30, int(star or 0)))

    if enable:
        pot_effects = get_equipment_potential_effects(equipped_item)
        extra_pct = min(200.0, float(pot_effects.get("auto_duration_pct", 0.0)))
        dur_hours = get_auto_mining_duration_hours(star) * (1.0 + extra_pct / 100.0)
        dur_sec = dur_hours * 3600.0
        now = time.time()
        user.auto_mining_enabled = True
        user.auto_mining_end_time = now + dur_sec
        user.auto_mining_session_mined = 0.0
        user.auto_mining_session_points = 0
        db.commit()
        db.refresh(user)

        dur_str = format_duration_hours(dur_hours)
        if extra_pct > 0:
            dur_str += f" (⏰잠재 +{int(extra_pct)}% 연장)"
        info = get_pickaxe_info(star)
        reply = (
            f"⛏️🤖 [자동 채굴 활성화 (ON)] {user.username}님의 자동 채굴이 시작되었습니다!\n"
            f"• 장착 장비: {equipped_item.name} (★{star}성, 쿨타임 {info['cooldown_minutes']}분)\n"
            f"• 지속 시간: {dur_str} (만료 전 !자동채굴 갱신 으로 연장 가능)\n"
            f"• 채굴 규칙: 쿨마다 자동 채굴 진행 (최대 황금 광맥 출현, 기본 확률 조정 적용)\n"
            f"💡 명령어: !자동채굴 (상태 확인), !자동채굴 갱신, !자동채굴 끄기"
        )
        details = {
            "auto_mining_enabled": True,
            "duration_hours": dur_hours,
            "end_time": user.auto_mining_end_time,
            "starforce": star,
            "pickaxe_name": equipped_item.name
        }
        return True, reply, details
    else:
        if not bool(user.auto_mining_enabled):
            return False, "⚠️ 현재 자동 채굴이 켜져 있지 않습니다. (!자동채굴 켜기 로 시작 가능)", None

        mined = float(getattr(user, "auto_mining_session_mined", 0.0) or 0.0)
        pts = int(getattr(user, "auto_mining_session_points", 0) or 0)
        user.auto_mining_enabled = False
        user.auto_mining_end_time = 0.0
        db.commit()
        db.refresh(user)

        reply = (
            f"🛑🤖 [자동 채굴 비활성화 (OFF)] {user.username}님의 자동 채굴을 중지했습니다.\n"
            f"• 이번 세션 누적 수확: 1X {mined:.2f}주 (+{pts:,}P 가치)"
        )
        details = {
            "auto_mining_enabled": False,
            "session_mined": mined,
            "session_points": pts
        }
        return True, reply, details

def renew_auto_mining(
    db: Session,
    user_id: str,
    username: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Renew/Extend Auto-Mining session based on currently equipped pickaxe."""
    user = get_or_create_user(db, user_id, username)
    equipped_item = get_user_equipped_item(db, user)
    star = equipped_item.starforce if equipped_item else getattr(user, "pickaxe_level", 0)
    star = max(0, min(30, int(star or 0)))

    pot_effects = get_equipment_potential_effects(equipped_item)
    extra_pct = min(200.0, float(pot_effects.get("auto_duration_pct", 0.0)))
    dur_hours = get_auto_mining_duration_hours(star) * (1.0 + extra_pct / 100.0)
    dur_sec = dur_hours * 3600.0
    now = time.time()

    user.auto_mining_enabled = True
    user.auto_mining_end_time = now + dur_sec
    db.commit()
    db.refresh(user)

    dur_str = format_duration_hours(dur_hours)
    if extra_pct > 0:
        dur_str += f" (⏰잠재 +{int(extra_pct)}% 연장)"
    reply = (
        f"🔄🤖 [자동 채굴 갱신 완료!] {user.username}님의 자동 채굴 지속 시간이 지금부터 {dur_str} 동안 연장되었습니다!\n"
        f"• 현재 장착: {equipped_item.name} (★{star}성)\n"
        f"• 쿨타임 주기마다 최대 황금 광맥 자동 채굴이 계속 유지됩니다."
    )
    details = {
        "auto_mining_enabled": True,
        "duration_hours": dur_hours,
        "end_time": user.auto_mining_end_time,
        "starforce": star,
        "pickaxe_name": equipped_item.name
    }
    return True, reply, details

def get_auto_mining_status(db: Session, user_id: str, username: str) -> str:
    """Returns detailed status of user's Auto-Mining state."""
    user = get_or_create_user(db, user_id, username)
    # Quick catch-up tick
    execute_auto_mining_tick(db, user)

    equipped_item = get_user_equipped_item(db, user)
    star = equipped_item.starforce if equipped_item else getattr(user, "pickaxe_level", 0)
    star = max(0, min(30, int(star or 0)))
    info = get_pickaxe_info(star)

    now = time.time()
    end_time = float(getattr(user, "auto_mining_end_time", 0.0) or 0.0)
    is_active = bool(getattr(user, "auto_mining_enabled", False) and end_time > now)

    if not is_active and getattr(user, "auto_mining_enabled", False):
        user.auto_mining_enabled = False
        user.auto_mining_end_time = 0.0
        db.commit()

    if is_active:
        rem_sec = max(0, int(end_time - now))
        rem_h, rem_sec_mod = divmod(rem_sec, 3600)
        rem_m, rem_s = divmod(rem_sec_mod, 60)
        time_str = f"{rem_h}시간 {rem_m}분 {rem_s}초" if rem_h > 0 else f"{rem_m}분 {rem_s}초"

        # Next mining countdown
        cd_sec = info["cooldown_seconds"]
        next_cd_str = "잠시 후 진행 예정"
        if user.last_mined_at:
            now_utc = datetime.now(timezone.utc)
            last_t = user.last_mined_at if user.last_mined_at.tzinfo else user.last_mined_at.replace(tzinfo=timezone.utc)
            el = (now_utc - last_t).total_seconds()
            if el < cd_sec:
                rem_cd = int(cd_sec - el)
                next_cd_str = f"{rem_cd // 60}분 {rem_cd % 60}초 후"

        session_mined = float(getattr(user, "auto_mining_session_mined", 0.0) or 0.0)
        session_pts = int(getattr(user, "auto_mining_session_points", 0) or 0)

        return (
            f"⛏️🤖 [자동 채굴 상태: 가동 중 (ON)]\n"
            f"• 장비: {equipped_item.name} (★{star}성, 쿨 {info['cooldown_minutes']}분)\n"
            f"• 남은 지속 시간: {time_str} (만료 전 !자동채굴 갱신 으로 연장 가능)\n"
            f"• 다음 채굴: {next_cd_str}\n"
            f"• 이번 세션 수확: 1X {session_mined:.2f}주 (+{session_pts:,}P 가치)\n"
            f"• 규칙: 최대 황금 광맥(5%)까지만 출현하며 기본 확률이 하향 조정됩니다.\n"
            f"💡 명령어: !자동채굴 끄기, !자동채굴 갱신"
        )
    else:
        max_dur = format_duration_hours(get_auto_mining_duration_hours(star))
        return (
            f"💤🤖 [자동 채굴 상태: 정지 (OFF)]\n"
            f"• 내 장비: {equipped_item.name} (★{star}성)\n"
            f"• 1회 지속 시간: {max_dur} (곡괭이 등급이 높을수록 30분에서 최대 24시간까지 대폭 증가!)\n"
            f"• 기능: 켜두면 쿨타임마다 자동으로 광맥을 채굴하여 1X 주식으로 적립합니다.\n"
            f"• 제약: 최대 황금 광맥(5%)까지만 출현하며 기본 확률이 하향 조정됩니다.\n"
            f"👉 시작하기: !자동채굴 켜기 (또는 !자동채굴 on) | 갱신: !자동채굴 갱신"
        )

def ensure_user_equipment(db: Session, user: User) -> List[UserEquipment]:
    """Ensures user has at least one equipment in user_equipments table, with one equipped."""
    items = db.query(UserEquipment).filter_by(user_id=user.id).order_by(UserEquipment.id.asc()).all()
    if not items:
        star = max(0, min(30, int(getattr(user, "pickaxe_level", 0) or 0)))
        info = get_pickaxe_info(star)
        item = UserEquipment(
            user_id=user.id,
            equipment_type="PICKAXE",
            name=info["name"],
            starforce=star,
            is_equipped=True
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        items = [item]
    else:
        # Items actively listed for sale on the marketplace cannot be equipped
        active_listed_ids = {
            l.equipment_id for l in db.query(EquipmentListing.equipment_id)
            .filter(EquipmentListing.seller_id == user.id, EquipmentListing.status == "ACTIVE").all()
        }
        # Unequip any actively listed items
        for it in items:
            if it.id in active_listed_ids and it.is_equipped:
                it.is_equipped = False

        unlisted_items = [it for it in items if it.id not in active_listed_ids]
        if not unlisted_items:
            # User has all items on sale in marketplace! Grant a basic starter 0-star pickaxe
            info0 = get_pickaxe_info(0)
            starter = UserEquipment(
                user_id=user.id,
                equipment_type="PICKAXE",
                name=info0["name"],
                starforce=0,
                is_equipped=True,
                created_at=datetime.now(timezone.utc)
            )
            db.add(starter)
            db.commit()
            db.refresh(starter)
            items.append(starter)
            unlisted_items = [starter]

        equipped = [i for i in unlisted_items if i.is_equipped]
        if not equipped:
            # Equip highest starforce unlisted item
            unlisted_items.sort(key=lambda x: x.starforce, reverse=True)
            unlisted_items[0].is_equipped = True
            equipped = [unlisted_items[0]]
            db.commit()
        elif len(equipped) > 1:
            for eq in equipped[1:]:
                eq.is_equipped = False
            db.commit()
            equipped = [equipped[0]]

        # If user.pickaxe_level was updated directly outside (e.g. legacy unit test) and there is only 1 item,
        # sync it ONLY if it is not an actively listed marketplace item
        if (
            len(items) == 1
            and equipped
            and equipped[0].id not in active_listed_ids
            and getattr(user, "pickaxe_level", None) is not None
            and user.pickaxe_level != equipped[0].starforce
        ):
            equipped[0].starforce = max(0, min(30, int(user.pickaxe_level)))
            equipped[0].name = get_pickaxe_info(equipped[0].starforce)["name"]
            db.commit()
        elif equipped:
            user.pickaxe_level = equipped[0].starforce
    return items

def get_user_equipped_item(db: Session, user: User) -> UserEquipment:
    """Returns the currently equipped item for user."""
    items = ensure_user_equipment(db, user)
    for it in items:
        if it.is_equipped:
            return it
    items[0].is_equipped = True
    db.commit()
    return items[0]


def get_user_cooldown_status(db: Session, user_id: str, username: str) -> str:
    """
    Returns dedicated status breakdown of mining cooldown, auto-mining timer, and server timers.
    Used by !쿨타임 (!쿨, !cooldown, !cd, !채굴쿨).
    """
    user = get_or_create_user(db, user_id, username)
    # Quick catch-up tick for auto-mining
    try:
        execute_auto_mining_tick(db, user)
    except Exception:
        pass

    state = get_market_state(db)
    now = time.time()
    now_utc = datetime.now(timezone.utc)

    # 1. Pickaxe & Mining Cooldown
    equipped_item = get_user_equipped_item(db, user)
    star = equipped_item.starforce if equipped_item else getattr(user, "pickaxe_level", 0) or 0
    star = max(0, min(30, int(star)))
    user.pickaxe_level = star
    pick_info = get_pickaxe_info(star)
    cd_min = pick_info["cooldown_minutes"]
    pot_eff = get_equipment_potential_effects(equipped_item) if equipped_item else {}
    pot_cd_red = pot_eff.get("mining_cd_reduction", 0)
    heavy_cd_add = pot_eff.get("heavy_mining_cd_add", 0)
    effective_cd_min = max(2, cd_min - pot_cd_red + heavy_cd_add)
    cd_sec = effective_cd_min * 60

    cd_tip_parts = []
    if pot_cd_red > 0:
        cd_tip_parts.append(f"⚡단축 -{pot_cd_red}분")
    if heavy_cd_add > 0:
        cd_tip_parts.append(f"🌋과충전 +{heavy_cd_add}분(보상+{int(pot_eff.get('heavy_mining_reward_pct', 0))}%)")
    cd_tip = f"쿨 {effective_cd_min}분" if not cd_tip_parts else f"쿨 {effective_cd_min}분({'/'.join(cd_tip_parts)})"
    eq_name = equipped_item.name if equipped_item else pick_info["name"]

    if user.last_mined_at:
        last_t = user.last_mined_at if user.last_mined_at.tzinfo else user.last_mined_at.replace(tzinfo=timezone.utc)
        elapsed = (now_utc - last_t).total_seconds()
        if elapsed < cd_sec:
            rem_cd = int(cd_sec - elapsed)
            rem_m, rem_s = divmod(rem_cd, 60)
            mine_status = f"⏳ {rem_m}분 {rem_s}초 남음 ({eq_name}, ★{star}성, {cd_tip})"
        else:
            mine_status = f"✨ 즉시 채굴 가능! ({eq_name}, ★{star}성, {cd_tip}) ➔ !채굴"
    else:
        mine_status = f"✨ 즉시 채굴 가능! ({eq_name}, ★{star}성, {cd_tip}) ➔ !채굴"

    # 2. Auto-Mining Status
    end_am = float(getattr(user, "auto_mining_end_time", 0.0) or 0.0)
    am_enabled = bool(getattr(user, "auto_mining_enabled", False))
    if am_enabled and end_am > now:
        rem_am = int(end_am - now)
        h_am, mod_am = divmod(rem_am, 3600)
        m_am, s_am = divmod(mod_am, 60)
        time_am_str = f"{h_am}시간 {m_am}분 {s_am}초" if h_am > 0 else f"{m_am}분 {s_am}초"
        auto_status = f"🟢 가동 중 (잔여: {time_am_str} | 연장: !자동채굴 갱신)"
    elif am_enabled:
        auto_status = f"⚠️ 세션 만료 (!자동채굴 갱신 필요)"
    else:
        auto_status = f"💤 OFF (시작: !자동채굴 on)"

    # 3. Market Trading Status
    end_t = float(getattr(state, "free_trading_end_time", 0.0) or 0.0)
    is_locked = bool(getattr(state, "is_trading_locked", True))
    rem_trade = max(0, int(end_t - now)) if (not is_locked and end_t > 0) else 0
    if not is_locked and rem_trade > 0:
        m_t, s_t = divmod(rem_trade, 60)
        trade_status = f"🟢 장 열림 ({m_t}분 {s_t}초 후 마감)"
    elif not is_locked:
        trade_status = "🟢 장 열림 (자유 거래)"
    else:
        trade_status = "🔒 거래 마감 (경기 중)"

    # 4. Casino Status
    c_state = get_casino_state(db)
    if c_state["is_open"]:
        rem_c = c_state["remaining_sec"]
        if 0 < rem_c < 99999:
            m_c, s_c = divmod(rem_c, 60)
            casino_status = f"🎰 오픈 ({m_c}분 {s_c}초 남음)"
        else:
            casino_status = "🎰 오픈 (무제한)"
    else:
        casino_status = "💤 마감"

    # 5. Star Force Fever Status
    sf_state = get_starforce_event_state(db)
    if sf_state.get("is_active"):
        rem_sf = sf_state["remaining_sec"]
        m_sf, s_sf = divmod(rem_sf, 60)
        sf_status = f"🔥 {sf_state['event_type_name']} ({m_sf}분 {s_sf}초 남음) ➔ !강화"
    else:
        next_m = sf_state["next_remaining_sec"] // 60
        next_h, next_mod_m = divmod(next_m, 60)
        if next_h > 0:
            next_str = f"약 {next_h}시간 {next_mod_m}분 후 예정"
        elif next_m > 0:
            next_str = f"약 {next_m}분 후 예정"
        else:
            next_str = "곧 발생 예정"
        sf_status = f"💤 대기 중 ({next_str})"

    return (
        f"⏳ [{username}님의 쿨타임 & 타이머 현황]\n"
        f"• ⛏️ 채굴 쿨: {mine_status}\n"
        f"• 🤖 자동 채굴: {auto_status}\n"
        f"• 📈 주식장: {trade_status} | 🎰 카지노: {casino_status}\n"
        f"• ⭐ 스타포스 피버: {sf_status}"
    )


def execute_mining(
    db: Session,
    user_id: str,
    username: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Execute !채굴 (Proof of Watch mining with pickaxe level, random critical hits & rewards).
    """
    state = get_market_state(db)
    user = get_or_create_user(db, user_id, username)
    now_utc = datetime.now(timezone.utc)

    # 1. Pickaxe Item Info from equipped equipment
    equipped_item = get_user_equipped_item(db, user)
    curr_level = equipped_item.starforce if equipped_item else getattr(user, "pickaxe_level", 0)
    if curr_level is None:
        curr_level = 0
    curr_level = max(0, min(30, int(curr_level)))
    user.pickaxe_level = curr_level
    pickaxe = get_pickaxe_info(curr_level)
    cooldown_sec = pickaxe["cooldown_seconds"]
    cooldown_min = pickaxe["cooldown_minutes"]
    pickaxe_bonus_cash = pickaxe.get("bonus_points", 0)

    # Aggregate potential effects from equipped item
    pot_effects = get_equipment_potential_effects(equipped_item)
    pot_crit_bonus = pot_effects.get("crit_boost", 0.0)
    pot_yield_bonus = pot_effects.get("yield_boost", 0.0)
    pot_bonus_cash = pot_effects.get("bonus_cash", 0)
    pot_cd_reset_pct = pot_effects.get("cd_reset_pct", 0.0)
    pot_cd_red = pot_effects.get("mining_cd_reduction", 0)
    heavy_cd_add = pot_effects.get("heavy_mining_cd_add", 0)
    effective_cd_min = max(2, cooldown_min - pot_cd_red + heavy_cd_add)
    cooldown_sec = effective_cd_min * 60

    # 2. Cooldown check based on pickaxe cooldown
    if user.last_mined_at:
        last_time = user.last_mined_at
        if last_time.tzinfo is None:
            last_time = last_time.replace(tzinfo=timezone.utc)
        elapsed = (now_utc - last_time).total_seconds()
        if elapsed < cooldown_sec:
            rem = int(cooldown_sec - elapsed)
            rem_m, rem_s = divmod(rem, 60)
            return False, f"⏳ [채굴 쿨타임] 다음 채굴까지 {rem_m}분 {rem_s}초 남았습니다. ({pickaxe['name']} 쿨타임: {effective_cd_min}분)", {"remaining_seconds": rem}

    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL

    current_price = state.current_price
    # 3. Dynamic Base Reward based on Treasury Pool & Pickaxe Yield (boosted by potential yield)
    target_cash = min(float(current_price), max(current_price * 0.2, state.treasury_pool * 0.05))
    base_shares = round(target_cash / current_price, 2)
    if base_shares <= 0.05:
        base_shares = 0.1 # Minimum faucet floor
    total_yield = pickaxe["yield_multiplier"] + pot_yield_bonus
    base_shares = round(base_shares * total_yield, 2)

    # 4. Roll Random Mining Tier & Critical Hits (boosted by pickaxe crit_bonus + potential crit)
    total_crit = pickaxe.get("crit_bonus", 0.0) + pot_crit_bonus
    try:
        tier = roll_mining_tier(crit_bonus=total_crit, pickaxe_level=curr_level)
    except TypeError:
        try:
            tier = roll_mining_tier(total_crit)
        except TypeError:
            tier = roll_mining_tier()
    multiplier = tier["multiplier"]
    if "bonus_cash_pct" in tier:
        treasury = float(state.treasury_pool or DEFAULT_TREASURY_POOL)
        pct = tier["bonus_cash_pct"]
        min_c = tier.get("min_cash", 10000)
        max_c = tier.get("max_cash", 300000)
        bonus_cash = int(max(min_c, min(max_c, round(treasury * pct))))
    else:
        bonus_cash = tier.get("bonus_cash", 0)

    total_bonus_cash = bonus_cash + pickaxe_bonus_cash + pot_bonus_cash

    # Potential: TREASURY_LOOT_PCT (국고 털이범)
    pot_loot_pct = pot_effects.get("treasury_loot_pct", 0.0)
    treasury_looted_cash = 0
    if pot_loot_pct > 0 and state.treasury_pool > 0:
        treasury_looted_cash = min(500000, int(round(state.treasury_pool * (pot_loot_pct / 100.0))))
        if treasury_looted_cash > 0:
            state.treasury_pool = max(0.0, state.treasury_pool - treasury_looted_cash)
            total_bonus_cash += treasury_looted_cash

    # Potential: GOBLIN_JACKPOT_CHANCE (황금 고블린 잭팟)
    pot_goblin_chance = pot_effects.get("goblin_chance", 0.0)
    pot_goblin_reward = pot_effects.get("goblin_reward", 0)
    goblin_triggered = False
    if pot_goblin_chance > 0 and random.uniform(0, 100) < pot_goblin_chance:
        goblin_triggered = True
        total_bonus_cash += pot_goblin_reward

    bonus_10x = tier.get("bonus_10x", 0.0)
    cd_reduction = tier.get("cooldown_reduction", 0)
    tier_name = tier["name"]
    tier_code = tier["code"]

    shares_awarded = round(base_shares * multiplier, 2)
    if shares_awarded <= 0.05:
        shares_awarded = 0.05

    heavy_reward_pct = pot_effects.get("heavy_mining_reward_pct", 0.0)
    heavy_mult = 1.0 + (heavy_reward_pct / 100.0)
    if heavy_reward_pct > 0:
        shares_awarded = round(shares_awarded * heavy_mult, 2)
        total_bonus_cash = int(round(total_bonus_cash * heavy_mult))
        if bonus_10x > 0:
            bonus_10x = round(bonus_10x * heavy_mult, 2)

    actual_cost = int(round(shares_awarded * current_price))
    bonus_10x_cost = int(round(bonus_10x * current_price))

    # Deduct total mining package cost from treasury pool
    total_mined_cost = actual_cost + total_bonus_cash + bonus_10x_cost
    state.treasury_pool = max(0.0, state.treasury_pool - total_mined_cost)

    # Cooldown setup (boosted on critical hit or potential CD reset)
    cd_reset_triggered = False
    if pot_cd_reset_pct > 0 and random.uniform(0, 100) < pot_cd_reset_pct:
        cd_reset_triggered = True
        user.last_mined_at = None
        next_cd_msg = "⚡ [잠재 쿨초 발동!] 지금 바로 재채굴 가능!"
    elif cd_reduction > 0:
        boosted_cd = max(0, effective_cd_min - cd_reduction)
        if boosted_cd == 0:
            user.last_mined_at = None
            next_cd_msg = "⚡ 쿨타임 즉시 초기화!! (지금 바로 재채굴 가능)"
        else:
            user.last_mined_at = now_utc - timedelta(minutes=cd_reduction)
            next_cd_msg = f"{boosted_cd}분 (부스터 발동!)"
    else:
        user.last_mined_at = now_utc
        next_cd_msg = f"{effective_cd_min}분"


    # 5. Check if user has debt -> Forced Labor Mode (탄광 노역 채굴)
    user_debt = getattr(user, "debt", 0) or 0
    if user_debt > 0:
        total_payout = actual_cost + total_bonus_cash
        repay_amt = min(user_debt, total_payout)
        user.debt = user_debt - repay_amt
        # Mined value returned to treasury as debt payoff
        state.treasury_pool += repay_amt

        # Excess cash if mined value exceeds remaining debt
        excess = total_payout - repay_amt
        if excess > 0:
            user.points += excess

        # Credit bonus 10X if won
        if bonus_10x > 0:
            pos_10x = db.query(Position).filter_by(user_id=user.id, product_type=ProductType.TEN_X).first()
            if pos_10x and pos_10x.quantity > 0:
                pos_10x.quantity += bonus_10x
                pos_10x.invested_cash += bonus_10x_cost
                pos_10x.entry_price = pos_10x.invested_cash / pos_10x.quantity
            else:
                if not pos_10x:
                    pos_10x = Position(
                        user_id=user.id,
                        product_type=ProductType.TEN_X,
                        quantity=bonus_10x,
                        entry_price=float(current_price),
                        invested_cash=float(bonus_10x_cost)
                    )
                    db.add(pos_10x)
                else:
                    pos_10x.quantity = bonus_10x
                    pos_10x.entry_price = float(current_price)
                    pos_10x.invested_cash = float(bonus_10x_cost)

        db.commit()
        db.refresh(user)
        db.refresh(state)

        bonus_10x_str = f" + 10X {format_quantity(bonus_10x)}주 획득!" if bonus_10x > 0 else ""
        excess_str = f" (빚 완제 후 잔여 {excess:,}P 현금 입금)" if excess > 0 else ""
        jackpot_tag = "🌟🎰 [탄광 노역 일확천금 대탈출!!] " if tier_code in ["EX", "UR+"] else ""
        crit_flair = f" 💥[CRITICAL! 크리티컬 {int(total_crit)}% 폭발!]" if total_crit >= 20.0 and tier_code in ["EX", "UR+", "UR", "SSR", "SR"] else ""
        msg = (
            f"{jackpot_tag}⛏️ [채굴 완료] [{pickaxe['name']}]{crit_flair} [탄광 노역 채굴] {tier_name} {user.username}님 탄광 노역으로 총 {total_payout:,}P 상당 채굴! "
            f"수익 {repay_amt:,}P가 국고 빚 상환에 즉시 충당되었습니다!{bonus_10x_str}{excess_str} "
            f"(남은 빚: {user.debt:,}P | 다음 채굴: {next_cd_msg})"
        )
        return True, msg, {
            "user_id": user.id,
            "username": user.username,
            "pickaxe_level": curr_level,
            "pickaxe_name": pickaxe["name"],
            "tier": tier_code,
            "tier_name": tier_name,
            "multiplier": multiplier,
            "shares_awarded": shares_awarded,
            "cash_value": actual_cost,
            "bonus_cash": bonus_cash,
            "pickaxe_bonus_cash": pickaxe_bonus_cash,
            "total_bonus_cash": total_bonus_cash,
            "bonus_10x_shares": bonus_10x,
            "cooldown_reduction_minutes": cd_reduction,
            "repaid_debt": repay_amt,
            "remaining_debt": user.debt,
            "treasury_pool": state.treasury_pool,
            "is_forced_labor": True
        }

    # 6. Standard Mining Reward: Credit 1X position to user
    pos = db.query(Position).filter_by(user_id=user.id, product_type=ProductType.ONE_X).first()
    if pos and pos.quantity > 0:
        pos.quantity += shares_awarded
        pos.invested_cash += actual_cost
        pos.entry_price = pos.invested_cash / pos.quantity
    else:
        if not pos:
            pos = Position(
                user_id=user.id,
                product_type=ProductType.ONE_X,
                quantity=shares_awarded,
                entry_price=float(current_price),
                invested_cash=float(actual_cost)
            )
            db.add(pos)
        else:
            pos.quantity = shares_awarded
            pos.entry_price = float(current_price)
            pos.invested_cash = float(actual_cost)

    # Credit bonus cash (tier jackpot + pickaxe fixed cash)
    if total_bonus_cash > 0:
        user.points += total_bonus_cash

    # Credit bonus 10X share
    if bonus_10x > 0:
        pos_10x = db.query(Position).filter_by(user_id=user.id, product_type=ProductType.TEN_X).first()
        if pos_10x and pos_10x.quantity > 0:
            pos_10x.quantity += bonus_10x
            pos_10x.invested_cash += bonus_10x_cost
            pos_10x.entry_price = pos_10x.invested_cash / pos_10x.quantity
        else:
            if not pos_10x:
                pos_10x = Position(
                    user_id=user.id,
                    product_type=ProductType.TEN_X,
                    quantity=bonus_10x,
                    entry_price=float(current_price),
                    invested_cash=float(bonus_10x_cost)
                )
                db.add(pos_10x)
            else:
                pos_10x.quantity = bonus_10x
                pos_10x.entry_price = float(current_price)
                pos_10x.invested_cash = float(bonus_10x_cost)

    user.total_mined = (user.total_mined or 0.0) + shares_awarded

    db.commit()
    db.refresh(user)
    db.refresh(state)

    extras = []
    if bonus_cash > 0:
        extras.append(f"잭팟 현금 +{bonus_cash:,}P")
    if pickaxe_bonus_cash > 0:
        extras.append(f"곡괭이 보너스 +{pickaxe_bonus_cash:,}P")
    if pot_bonus_cash > 0:
        extras.append(f"잠재 현금 +{pot_bonus_cash:,}P")
    if treasury_looted_cash > 0:
        extras.append(f"🏛️국고 털이 +{treasury_looted_cash:,}P")
    if goblin_triggered:
        extras.append(f"👹황금고블린 잭팟 +{pot_goblin_reward:,}P")
    if heavy_reward_pct > 0:
        extras.append(f"🌋과충전({heavy_mult:.1f}배)")
    if bonus_10x > 0:
        extras.append(f"🔥 10X 레버리지 +{format_quantity(bonus_10x)}주")
    if cd_reset_triggered:
        extras.append("⚡잠재 쿨초 발동")
    extras_str = f" + {' / '.join(extras)}" if extras else ""

    qty_str = format_quantity(shares_awarded)
    jackpot_tag = "🌟🎰 [일확천금 신화 탄생!!] " if tier_code in ["EX", "UR+"] else ""
    goblin_banner = f"🎉👹💰 [황금 고블린 토벌 잭팟!!] +{pot_goblin_reward:,}P 초대형 보너스!\n" if goblin_triggered else ""
    crit_flair = f" 💥[CRITICAL! 크리티컬 {int(total_crit)}% 폭발!]" if total_crit >= 20.0 and tier_code in ["EX", "UR+", "UR", "SSR", "SR"] else ""
    msg = (
        f"{goblin_banner}{jackpot_tag}⛏️ [채굴 완료] [{pickaxe['name']}]{crit_flair} {tier_name} {user.username}님 1X {qty_str}주가 1X 보유에 합산되었습니다! "
        f"(+{actual_cost:,}P 상당{extras_str} | 보유 현금: {user.points:,}P | 국고 잔여: {int(state.treasury_pool):,}P | 다음 채굴: {next_cd_msg})"
    )
    return True, msg, {
        "user_id": user.id,
        "username": user.username,
        "pickaxe_level": curr_level,
        "pickaxe_name": pickaxe["name"],
        "tier": tier_code,
        "tier_name": tier_name,
        "multiplier": multiplier,
        "shares_awarded": shares_awarded,
        "cash_value": actual_cost,
        "bonus_cash": bonus_cash,
        "pickaxe_bonus_cash": pickaxe_bonus_cash,
        "potential_bonus_cash": pot_bonus_cash,
        "treasury_looted_cash": treasury_looted_cash,
        "goblin_triggered": goblin_triggered,
        "goblin_reward": pot_goblin_reward if goblin_triggered else 0,
        "total_bonus_cash": total_bonus_cash,
        "bonus_10x_shares": bonus_10x,
        "cooldown_reduction_minutes": cd_reduction,
        "cd_reset_triggered": cd_reset_triggered,
        "heavy_mult": heavy_mult,
        "heavy_reward_pct": heavy_reward_pct,
        "heavy_cd_add": heavy_cd_add,
        "treasury_pool": state.treasury_pool,
        "total_mined": user.total_mined,
        "is_forced_labor": False
    }

def find_user_equipment(db: Session, user: User, item_id_or_index: Optional[str]) -> Optional[UserEquipment]:
    """Finds user equipment by ID (#123) or 1-based inventory index (1, 2, 3...). Defaults to equipped item if None."""
    items = ensure_user_equipment(db, user)
    if not items:
        return None
    if not item_id_or_index or str(item_id_or_index).strip() in ["", "현재", "기본", "장착", "equipped"]:
        for it in items:
            if it.is_equipped:
                return it
        return items[0]

    clean_arg = str(item_id_or_index).strip().lstrip("#")
    # 1. Match by equipment primary key ID
    for it in items:
        if str(it.id) == clean_arg:
            return it
    # 2. Match by 1-based index in user's inventory
    if clean_arg.isdigit():
        idx = int(clean_arg) - 1
        if 0 <= idx < len(items):
            return items[idx]
    return None

def execute_pickaxe_upgrade(
    db: Session,
    user_id: str,
    username: str,
    item_id_or_index: Optional[str] = None,
    use_shield: Optional[bool] = None,
    use_boost: Optional[bool] = None,
    use_downgrade: Optional[bool] = None,
    use_shield_100: Optional[bool] = None,
    use_downgrade_100: Optional[bool] = None
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Execute !강화 / !업그레이드 [장비번호/슬롯] (MapleStory Star Force pickaxe enhancement).
    - 2025/2026 메이플 스타포스 30성 시스템 반영
    - 0성 ~ 14성: 파괴 확률 없음 (0%), 실패 시 하락 없이 등급 유지 (100%)
    - 15성 ~ 29성: 실패 시 단계 하락 없이 등급 유지, 파괴 확률 존재 (파괴 시 12성 장비의 흔적으로 복원)
    - 강화 비용은 성공/실패/파괴 무관 100% 국고 채굴풀로 환원
    - 주문서는 유저가 지정(!강화 파방/하강/상승/절대파방/절대하강/풀)하거나 상시 설정(!주문서)했을 때만 사용
    """
    state = get_market_state(db)
    user = get_or_create_user(db, user_id, username)
    target_item = find_user_equipment(db, user, item_id_or_index)

    if not target_item:
        return False, f"⚠️ 지정한 장비('{item_id_or_index}')를 보유하고 있지 않습니다! (내 장비 확인: !내장비, !인벤토리)", None

    # Check if item is listed in an active marketplace trade
    active_listing = db.query(EquipmentListing).filter_by(equipment_id=target_item.id, status="ACTIVE").first()
    if active_listing:
        return False, f"⚠️ [장비 #{target_item.id}]은(는) 현재 거래소/직거래에 판매 등록 중입니다! 거래 취소(!장비회수) 후 강화해주세요.", None

    curr_level = max(0, min(30, int(target_item.starforce or 0)))

    if curr_level >= 30:
        max_item = get_pickaxe_info(30)
        return False, f"✨ [장비 #{target_item.id}]은(는) 이미 최고 등급 종결 장비인 [{max_item['name']}]입니다!", None

    sf_state = get_starforce_event_state(db)
    current_item = get_pickaxe_info(curr_level, event_state=sf_state)
    cost = current_item["upgrade_cost"]

    # Potential effects: cost discount & safeguard
    pot_effects = get_equipment_potential_effects(target_item)
    pot_discount_pct = min(50.0, float(pot_effects.get("starforce_discount_pct", 0.0)))
    safeguard_pct = min(90.0, float(pot_effects.get("safeguard_pct", 0.0)))
    if pot_discount_pct > 0:
        cost = max(100, int(round(cost * (1.0 - pot_discount_pct / 100.0))))

    if user.points < cost:
        return False, f"⚠️ 포인트가 부족합니다! (필요: {cost:,}P | 보유: {user.points:,}P | 부족: {cost - user.points:,}P)", None

    # Scroll confirmed auto-use check: default to True if user holds scrolls, unless explicitly disabled
    arm_s = getattr(user, "arm_shield", None)
    effective_use_shield = use_shield if use_shield is not None else (True if arm_s is None or arm_s is True else False)
    arm_d = getattr(user, "arm_downgrade", None)
    effective_use_downgrade = use_downgrade if use_downgrade is not None else (True if arm_d is None or arm_d is True else False)
    effective_use_boost = use_boost if use_boost is not None else bool(getattr(user, "arm_boost", False))

    arm_s100 = getattr(user, "arm_shield_100", None)
    effective_use_shield_100 = use_shield_100 if use_shield_100 is not None else (True if arm_s100 is None or arm_s100 is True else False)
    arm_d100 = getattr(user, "arm_downgrade_100", None)
    effective_use_downgrade_100 = use_downgrade_100 if use_downgrade_100 is not None else (True if arm_d100 is None or arm_d100 is True else False)

    # If user explicitly requested standard shield/downgrade, do not consume precious 100% scrolls
    if use_shield is True and use_shield_100 is None:
        effective_use_shield_100 = False
    if use_downgrade is True and use_downgrade_100 is None:
        effective_use_downgrade_100 = False

    # If user explicitly requested 100% scrolls, do not consume standard scrolls
    if use_shield_100 is True and use_shield is None:
        effective_use_shield = False
    if use_downgrade_100 is True and use_downgrade is None:
        effective_use_downgrade = False

    if use_shield_100 is True and (getattr(user, "shield_100_scroll_count", 0) or 0) <= 0:
        return False, "⚠️ [절대 파괴방어권(100%)]을 보유하고 있지 않습니다! (보유: 0장 | 신비상인에게서 구매 가능)", None

    if use_downgrade_100 is True and (getattr(user, "downgrade_100_scroll_count", 0) or 0) <= 0:
        return False, "⚠️ [절대 하강방지권(100%)]을 보유하고 있지 않습니다! (보유: 0장 | 신비상인에게서 구매 가능)", None

    if use_shield is True and (getattr(user, "shield_scroll_count", 0) or 0) <= 0:
        return False, "⚠️ [파괴방어권]을 보유하고 있지 않습니다! (보유: 0장 | 신비상인 또는 !거래소에서 구매 가능)", None

    if use_boost is True and (getattr(user, "boost_scroll_count", 0) or 0) <= 0:
        return False, "⚠️ [강화확률상승권]을 보유하고 있지 않습니다! (보유: 0장 | 신비상인 또는 !거래소에서 구매 가능)", None

    if use_downgrade is True and (getattr(user, "downgrade_scroll_count", 0) or 0) <= 0:
        return False, "⚠️ [하강방지권]을 보유하고 있지 않습니다! (보유: 0장 | 신비상인 또는 !거래소에서 구매 가능)", None

    # Deduct cost and credit 100% to Treasury regardless of result
    user.points -= cost
    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL
    state.treasury_pool += cost

    # Roll outcome based on Star Force tier probabilities
    roll = random.uniform(0, 100)
    s_rate = current_item["success_rate"]
    m_rate = current_item["maintain_rate"]
    d_rate = current_item["drop_rate"]

    # Multiplicative potential success boost (기존 확률에 대한 곱연산 비례 버프)
    pot_success_boost = min(30.0, float(pot_effects.get("starforce_success_boost", 0.0)))
    if pot_success_boost > 0 and s_rate < 100.0:
        boost = min(s_rate * (pot_success_boost / 100.0), 99.0 - s_rate)
        s_rate += boost
        if d_rate >= boost:
            d_rate -= boost
        else:
            rem = boost - d_rate
            d_rate = 0.0
            m_rate = max(0.0, m_rate - rem)

    # Check and consume enhancement success boost scroll (강화확률상승권) - Multiplicative +25% boost
    used_boost_scroll = False
    if effective_use_boost and (getattr(user, "boost_scroll_count", 0) or 0) > 0 and s_rate < 100.0:
        user.boost_scroll_count -= 1
        boost_scroll_val = min(s_rate * 0.25, 99.0 - s_rate)
        s_rate += boost_scroll_val
        if d_rate >= boost_scroll_val:
            d_rate -= boost_scroll_val
        else:
            rem = boost_scroll_val - d_rate
            d_rate = 0.0
            m_rate = max(0.0, m_rate - rem)
        used_boost_scroll = True

    pot_suffix = ""
    if pot_discount_pct > 0:
        pot_suffix += f" (🔨잠재 {int(pot_discount_pct)}%할인)"
    if pot_success_boost > 0:
        pot_suffix += f" (⭐성공률 곱연산 +{pot_success_boost:.0f}% 증폭)"
    if used_boost_scroll:
        pot_suffix += f" (⚡확률상승권 +25% 곱연산 증폭 | 잔여 {user.boost_scroll_count}장)"

    fever_suffix = ""
    if current_item.get("is_discounted"):
        fever_suffix = " (🔥30% 할인 피버 적용)"
    fever_suffix += pot_suffix

    used_downgrade_scroll = False
    used_shield_scroll = False
    used_downgrade_100_scroll = False
    used_shield_100_scroll = False

    if roll < s_rate:
        outcome = "success"
        new_level = curr_level + 1
        target_item.starforce = new_level
        new_item = get_pickaxe_info(new_level, event_state=sf_state)
        target_item.name = new_item["name"]
        bp_info = f" + 확정 +{new_item['bonus_points']:,}P" if new_item.get('bonus_points', 0) > 0 else ""
        if current_item.get("is_guaranteed_100"):
            success_tag = f"🔨✨ [★{curr_level}성 100% 확정 성공 피버!!]"
        elif current_item.get("is_discounted"):
            success_tag = "🔨✨ [스타포스 강화 대성공! (🔥30% 할인)]"
        else:
            success_tag = "🔨✨ [스타포스 강화 대성공!!]"

        reply = (
            f"{success_tag} {user.username}님 {cost:,}P를 소모하여 [장비 #{target_item.id} {new_item['name']}] 강화에 성공했습니다!{pot_suffix} "
            f"(채굴량: {new_item['yield_multiplier']}배{bp_info} | 크리: +{new_item['crit_bonus']}% | 쿨: {new_item['cooldown_minutes']}분 | "
            f"국고 환원: +{cost:,}P | 잔여 현금: {user.points:,}P)"
        )
    elif roll < (s_rate + m_rate):
        outcome = "maintain"
        new_level = curr_level
        target_item.starforce = new_level
        new_item = current_item
        reply = (
            f"🔨💨 [강화 실패 (등급 유지){fever_suffix}] {user.username}님 {cost:,}P를 소모하였으나 [장비 #{target_item.id}] 강화에 실패했습니다. (메이플 룰: 실패 시 하락 없이 등급 유지) "
            f"(현재: [{current_item['name']}] | 국고 환원: +{cost:,}P | 잔여 현금: {user.points:,}P)"
        )
    elif roll < (s_rate + m_rate + d_rate):
        if effective_use_downgrade_100 and (getattr(user, "downgrade_100_scroll_count", 0) or 0) > 0:
            user.downgrade_100_scroll_count -= 1
            used_downgrade_100_scroll = True
            outcome = "downgrade_prevented_100"
            new_level = curr_level
            target_item.starforce = new_level
            new_item = current_item
            reply = (
                f"🛡️📉✨ [절대 하강방지권 100% 무적 방어 성공!{fever_suffix}] {user.username}님 {cost:,}P를 소모하여 [장비 #{target_item.id}] 강화에 실패했으나, "
                f"절대 하강방지권을 소모하여 100% 확률로 1성 하락을 완벽히 방어했습니다! (남은 절대 하강방지권: {user.downgrade_100_scroll_count}장 | 현재: [{current_item['name']}] | 국고 환원: +{cost:,}P | 잔여 현금: {user.points:,}P)"
            )
        elif effective_use_downgrade and (getattr(user, "downgrade_scroll_count", 0) or 0) > 0:
            user.downgrade_scroll_count -= 1
            used_downgrade_scroll = True
            downgrade_defend_roll = random.uniform(0, 100)
            if downgrade_defend_roll < 70.0:
                outcome = "downgrade_prevented"
                new_level = curr_level
                target_item.starforce = new_level
                new_item = current_item
                reply = (
                    f"🛡️📉 [하강방지권 방어 성공! (70% 확률){fever_suffix}] {user.username}님 {cost:,}P를 소모하여 [장비 #{target_item.id}] 강화에 실패했으나, "
                    f"하강방지권을 소모하여 1성 하락을 막아냈습니다! (남은 하강방지권: {user.downgrade_scroll_count}장 | 현재: [{current_item['name']}] | 국고 환원: +{cost:,}P | 잔여 현금: {user.points:,}P)"
                )
            else:
                outcome = "drop"
                new_level = max(0, curr_level - 1)
                target_item.starforce = new_level
                new_item = get_pickaxe_info(new_level, event_state=sf_state)
                target_item.name = new_item["name"]
                reply = (
                    f"🔨📉 [하강방지권 방어 실패! (30% 뚫림){fever_suffix}] {user.username}님 {cost:,}P를 소모하여 하강방지권을 사용했으나, "
                    f"하락 압력을 이겨내지 못하고 1성 하락했습니다! ㅠㅠ ([{current_item['name']}] ➔ [{new_item['name']}] | 남은 하강방지권: {user.downgrade_scroll_count}장 | 국고 환원: +{cost:,}P | 잔여 현금: {user.points:,}P)"
                )
        else:
            outcome = "drop"
            new_level = max(0, curr_level - 1)
            target_item.starforce = new_level
            new_item = get_pickaxe_info(new_level, event_state=sf_state)
            target_item.name = new_item["name"]
            reply = (
                f"🔨📉 [강화 실패 (등급 하락!){fever_suffix}] {user.username}님 {cost:,}P를 소모하였으나 [장비 #{target_item.id}] 강화 실패로 1성 하락했습니다! ㅠㅠ "
                f"([{current_item['name']}] ➔ [{new_item['name']}] | 국고 환원: +{cost:,}P | 잔여 현금: {user.points:,}P)"
            )
    else:
        # Destroyed / Blown up! (Only possible at 15성+)
        shield_defended = False
        if effective_use_shield_100 and (getattr(user, "shield_100_scroll_count", 0) or 0) > 0:
            user.shield_100_scroll_count -= 1
            used_shield_100_scroll = True
            shield_defended = True
            outcome = "destruction_prevented_100"
            new_level = curr_level
            target_item.starforce = new_level
            new_item = current_item
            reply = (
                f"🛡️✨💎 [절대 파괴방어권 100% 무적 방어 성공!{fever_suffix}] {user.username}님 {cost:,}P를 소모하여 [장비 #{target_item.id}] 강화 중 장비가 폭발 파괴될 위기였으나, "
                f"절대 파괴방어권의 무적 방어막으로 폭발을 100% 완벽히 차단하고 성수를 지켜냈습니다! (남은 절대 파괴방어권: {user.shield_100_scroll_count}장 | 현재: [{current_item['name']}] | 국고 환원: +{cost:,}P | 잔여 현금: {user.points:,}P)"
            )
        elif effective_use_shield and (getattr(user, "shield_scroll_count", 0) or 0) > 0:
            user.shield_scroll_count -= 1
            used_shield_scroll = True
            dest_defend_roll = random.uniform(0, 100)
            if dest_defend_roll < 60.0:
                shield_defended = True
                outcome = "destruction_prevented"
                new_level = curr_level
                target_item.starforce = new_level
                new_item = current_item
                reply = (
                    f"🛡️✨ [파괴방어권 아슬아슬 방어 성공! (60% 확률){fever_suffix}] {user.username}님 {cost:,}P를 소모하여 [장비 #{target_item.id}] 강화 중 장비가 폭발 파괴될 위기였으나, "
                    f"파괴방어권이 엉성한 방어막으로 가까스로 폭발을 막아내고 성수를 지켜냈습니다! (방어 성공! 남은 파괴방어권: {user.shield_scroll_count}장 | 현재: [{current_item['name']}] | 국고 환원: +{cost:,}P | 잔여 현금: {user.points:,}P)"
                )
            else:
                shield_defended = False

        if not shield_defended:
            if safeguard_pct > 0 and random.uniform(0, 100) < safeguard_pct:
                # Safeguarded! Drop 1 star instead of falling to 12
                outcome = "safeguarded_drop"
                new_level = max(0, curr_level - 1)
                target_item.starforce = new_level
                new_item = get_pickaxe_info(new_level, event_state=sf_state)
                target_item.name = new_item["name"]
                reply = (
                    f"🛡️✨ [강화 파괴 방지 성공! (세이프가드 {safeguard_pct:.0f}% 발동!){fever_suffix}] {user.username}님 {cost:,}P를 소모하여 "
                    f"[장비 #{target_item.id}] 강화가 폭발 파괴될 위기였으나, 잠재능력 파괴 방지(★1성 하락 보호)가 발동하여 장비 폭발을 막아냈습니다! "
                    f"([{current_item['name']}] ➔ [{new_item['name']}] | 국고 환원: +{cost:,}P | 잔여 현금: {user.points:,}P)"
                )
            else:
                outcome = "destroyed"
                # MapleStory Starforce rule: Destroys into Equipment Trace (장비의 흔적, 12성 복원)
                target_item.starforce = 12
                new_item = get_pickaxe_info(12, event_state=sf_state)
                target_item.name = new_item["name"]

                # Check Bank Insurance
                ins_payout_msg = ""
                b_data = get_user_bank_data(user)
                ins = b_data.get("insurance")
                if ins and isinstance(ins, dict) and ins.get("active") and ins.get("claims_left", 0) > 0:
                    cov = int(ins.get("coverage_amount", 1000000))
                    user.bank_balance = (getattr(user, "bank_balance", 0) or 0) + cov
                    ins["claims_left"] = 0
                    ins["active"] = False
                    ins["claimed_payout"] = cov
                    save_user_bank_data(user, b_data)
                    ins_payout_msg = (
                        f"\n🏥🛡️ [치즈나베 중앙은행 파괴보험금 지급!] 스타포스 안심 파괴 보험이 발동하여 "
                        f"보험금 +{cov:,}P가 보통예금으로 즉시 지급되었습니다! (보통예금 잔액: {user.bank_balance:,}P)"
                    )

                shield_fail_tag = " [파괴방어권 뚫림! 장비 폭발 대참사! (40% 뚫림)" if used_shield_scroll else " [스타포스 강화 실패: 장비 파괴!"
                reply = (
                    f"💥💀{shield_fail_tag}{fever_suffix}] {user.username}님 {cost:,}P를 소모하여 [장비 #{target_item.id}] 강화 중 "
                    f"{'파괴방어막이 뚫려 ' if used_shield_scroll else ''}장비가 폭발 파괴되었습니다! ㅠㅠ "
                    f"(메이플 스타포스 규칙에 따라 [장비의 흔적(★12성 {new_item['name']})]으로 복원되었습니다. | 국고 환원: +{cost:,}P | 잔여 현금: {user.points:,}P){ins_payout_msg}"
                )

    if target_item.is_equipped:
        user.pickaxe_level = target_item.starforce

    db.commit()
    db.refresh(user)
    db.refresh(target_item)
    db.refresh(state)

    details = {
        "user_id": user.id,
        "username": user.username,
        "equipment_id": target_item.id,
        "previous_level": curr_level,
        "new_level": target_item.starforce,
        "outcome": outcome,
        "pickaxe_name": new_item["name"],
        "cost": cost,
        "base_cost": current_item.get("base_cost", cost),
        "remaining_points": user.points,
        "treasury_pool": state.treasury_pool,
        "event_type": sf_state.get("event_type"),
        "discount_applied": current_item.get("is_discounted", False),
        "guaranteed_100": current_item.get("is_guaranteed_100", False),
        "pot_success_boost": pot_success_boost,
        "pot_discount_pct": pot_discount_pct,
        "safeguard_pct": safeguard_pct,
        "used_boost_scroll": used_boost_scroll,
        "used_downgrade_scroll": used_downgrade_scroll,
        "used_shield_scroll": used_shield_scroll,
        "used_shield_100_scroll": used_shield_100_scroll,
        "used_downgrade_100_scroll": used_downgrade_100_scroll,
        "remaining_boost_scrolls": getattr(user, "boost_scroll_count", 0) or 0,
        "remaining_downgrade_scrolls": getattr(user, "downgrade_scroll_count", 0) or 0,
        "remaining_shield_scrolls": getattr(user, "shield_scroll_count", 0) or 0,
        "remaining_shield_100_scrolls": getattr(user, "shield_100_scroll_count", 0) or 0,
        "remaining_downgrade_100_scrolls": getattr(user, "downgrade_100_scroll_count", 0) or 0
    }
    return True, reply, details

def execute_buy_equipment(
    db: Session,
    user_id: str,
    username: str,
    tier_token: str = "0"
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Buy a new equipment/pickaxe from the store for points.
    Available options:
    - 0성 나무 곡괭이 (10,000P)
    - 5성 돌 곡괭이 (80,000P)
    - 10성 철 곡괭이 (350,000P)
    """
    user = get_or_create_user(db, user_id, username)
    state = get_market_state(db)

    clean_tier = str(tier_token).strip().lower()
    shop_options = {
        "0": (0, 10000), "나무": (0, 10000), "기본": (0, 10000), "wood": (0, 10000), "": (0, 10000),
        "5": (5, 80000), "돌": (5, 80000), "stone": (5, 80000),
        "10": (10, 350000), "철": (10, 350000), "iron": (10, 350000)
    }

    if clean_tier not in shop_options:
        return False, (
            "⛏️ [장비 상점 안내] 구매할 곡괭이 종류를 입력해주세요: '!곡괭이구매 [종류]'\n"
            "• 🪵 0성 나무 곡괭이: 10,000P (!곡괭이구매 0 또는 !곡괭이구매 나무)\n"
            "• 🪨 5성 돌 곡괭이: 80,000P (!곡괭이구매 5 또는 !곡괭이구매 돌)\n"
            "• ⛓️ 10성 철 곡괭이: 350,000P (!곡괭이구매 10 또는 !곡괭이구매 철)"
        ), None

    target_star, cost = shop_options[clean_tier]

    if user.points < cost:
        return False, f"⚠️ 포인트가 부족합니다! (필요: {cost:,}P | 보유: {user.points:,}P | 부족: {cost - user.points:,}P)", None

    user.points -= cost
    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL
    state.treasury_pool += cost

    user_items = ensure_user_equipment(db, user)
    has_equipped = any(it.is_equipped for it in user_items)
    auto_equip = not has_equipped

    info = get_pickaxe_info(target_star)
    new_eq = UserEquipment(
        user_id=user.id,
        equipment_type="PICKAXE",
        name=info["name"],
        starforce=target_star,
        is_equipped=auto_equip
    )
    db.add(new_eq)
    db.commit()
    db.refresh(new_eq)

    if auto_equip:
        user.pickaxe_level = target_star
        db.commit()
        equip_msg = " [현재 주 장비로 자동 장착됨 🟢]"
    else:
        equip_msg = f" [인벤토리 보관 📦 | 장착: !장착 {new_eq.id}]"

    reply = (
        f"⛏️✨ [새 장비 구매 완료!] {user.username}님이 {cost:,}P로 [장비 #{new_eq.id} {info['name']}]{equip_msg}을(를) 구매했습니다! "
        f"(국고 환원: +{cost:,}P | 잔여 현금: {user.points:,}P | 강화: !강화 {new_eq.id} | 목록: !내장비)"
    )

    details = {
        "equipment_id": new_eq.id,
        "name": info["name"],
        "starforce": target_star,
        "cost": cost,
        "is_equipped": auto_equip,
        "user_id": user.id,
        "username": user.username,
        "remaining_points": user.points,
        "treasury_pool": state.treasury_pool
    }
    return True, reply, details

def execute_equip_item(
    db: Session,
    user_id: str,
    username: str,
    item_id_or_index: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Equip / Swap active pickaxe for mining.
    """
    user = get_or_create_user(db, user_id, username)
    user_items = ensure_user_equipment(db, user)
    target_item = find_user_equipment(db, user, item_id_or_index)

    if not target_item:
        return False, f"⚠️ 장비 '{item_id_or_index}'를 보유하고 있지 않습니다! (!내장비 또는 !인벤토리로 확인)", None

    if target_item.is_equipped:
        return False, f"💡 이미 [장비 #{target_item.id} {target_item.name}]을(를) 장착 중입니다.", None

    active_listing = db.query(EquipmentListing).filter_by(equipment_id=target_item.id, status="ACTIVE").first()
    if active_listing:
        return False, f"⚠️ [장비 #{target_item.id}]은(는) 현재 거래소에 판매 등록 중입니다! 등록 취소(!장비회수 {active_listing.id}) 후 장착해주세요.", None

    for it in user_items:
        it.is_equipped = (it.id == target_item.id)

    user.pickaxe_level = target_item.starforce
    db.commit()
    db.refresh(user)
    db.refresh(target_item)

    info = get_pickaxe_info(target_item.starforce)
    bp_str = f" | 확정: +{info['bonus_points']:,}P" if info.get("bonus_points", 0) > 0 else ""
    reply = (
        f"⛏️🔄 [장비 교체 완료!] {user.username}님이 [장비 #{target_item.id} {info['name']}]을(를) 주 장비로 장착했습니다! "
        f"(채굴량 {info['yield_multiplier']}배{bp_str} | 크리 +{info['crit_bonus']}% | 쿨 {info['cooldown_minutes']}분)"
    )

    details = {
        "equipment_id": target_item.id,
        "name": info["name"],
        "starforce": target_item.starforce,
        "user_id": user.id,
        "username": user.username
    }
    return True, reply, details

def execute_list_equipment(
    db: Session,
    user_id: str,
    username: str,
    item_id_token: str,
    price_token: str,
    target_buyer_token: Optional[str] = None
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    List equipment for sale on the marketplace or as a 1:1 direct trade to a specific player.
    5% transaction fee is charged upon sale and credited to Treasury.
    """
    user = get_or_create_user(db, user_id, username)
    user_items = ensure_user_equipment(db, user)
    target_item = find_user_equipment(db, user, item_id_token)

    if not target_item:
        return False, f"⚠️ 판매할 장비 '{item_id_token}'를 보유하고 있지 않습니다! (!내장비로 장비번호 확인)", None

    active_listing = db.query(EquipmentListing).filter_by(equipment_id=target_item.id, status="ACTIVE").first()
    if active_listing:
        return False, f"⚠️ [장비 #{target_item.id}]은(는) 이미 거래소(거래번호: #{active_listing.id})에 등록되어 있습니다!", None

    clean_price = re.sub(r"[^0-9]", "", str(price_token))
    if not clean_price:
        return False, f"⚠️ 올바른 판매 가격을 입력해주세요: '{price_token}' (예: !장비등록 2 50000)", None

    price = int(clean_price)
    if price < 1000:
        return False, "⚠️ 최소 판매 등록 가격은 1,000P입니다.", None
    if price > 1000000000:
        return False, "⚠️ 최대 판매 등록 가격은 1,000,000,000P입니다.", None

    target_buyer_id = None
    target_buyer_name = None
    if target_buyer_token:
        clean_buyer = str(target_buyer_token).strip().lstrip("@")
        buyer_user = db.query(User).filter(func.lower(User.username) == clean_buyer.lower()).first()
        if not buyer_user:
            return False, f"⚠️ 구매 대상 유저 '{clean_buyer}'님을 찾을 수 없습니다.", None
        if buyer_user.id == user.id:
            return False, "⚠️ 본인에게는 장비를 직거래로 판매할 수 없습니다.", None
        target_buyer_id = buyer_user.id
        target_buyer_name = buyer_user.username

    # Calculate 5% transaction tax fee
    tax_fee = max(50, int(round(price * 0.05)))

    # If item was equipped, unequip it and equip another item if available
    if target_item.is_equipped:
        target_item.is_equipped = False

    active_listed_ids = {
        l.equipment_id for l in db.query(EquipmentListing.equipment_id)
        .filter(EquipmentListing.seller_id == user.id, EquipmentListing.status == "ACTIVE").all()
    }
    active_listed_ids.add(target_item.id)

    remaining = [it for it in user_items if it.id != target_item.id and it.id not in active_listed_ids]
    if remaining:
        if not any(it.is_equipped for it in remaining):
            remaining.sort(key=lambda x: x.starforce, reverse=True)
            remaining[0].is_equipped = True
            user.pickaxe_level = remaining[0].starforce
    else:
        # User has no unlisted items left to equip; create a starter 0-star pickaxe so user always has an active pickaxe
        info0 = get_pickaxe_info(0)
        starter = UserEquipment(
            user_id=user.id,
            equipment_type="PICKAXE",
            name=info0["name"],
            starforce=0,
            is_equipped=True,
            created_at=datetime.now(timezone.utc)
        )
        db.add(starter)
        user.pickaxe_level = 0

    listing = EquipmentListing(
        seller_id=user.id,
        seller_name=user.username,
        buyer_id=target_buyer_id,
        buyer_name=target_buyer_name,
        equipment_id=target_item.id,
        price=price,
        tax_fee=tax_fee,
        status="ACTIVE",
        created_at=datetime.now(timezone.utc)
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)

    if target_buyer_name:
        reply = (
            f"🤝📦 [장비 1:1 직거래 등록!] {user.username}님이 {target_buyer_name}님 전용으로 "
            f"[장비 #{target_item.id} {target_item.name}]을(를) {price:,}P (거래세 5%: {tax_fee:,}P 국고 환원)에 등록했습니다! (거래번호: #{listing.id})\n"
            f"👉 {target_buyer_name}님 구매: '!장비수락 {listing.id}' 또는 '!장비구매 {listing.id}' | 취소: '!장비회수 {listing.id}'"
        )
    else:
        reply = (
            f"🏪📦 [장비 거래소 등록 완료!] {user.username}님이 [장비 #{target_item.id} {target_item.name}]을(를) "
            f"거래소에 {price:,}P (판매 시 5% 수수료: {tax_fee:,}P 국고 환원)에 등록했습니다! (거래번호: #{listing.id})\n"
            f"👉 누구나 구매: '!장비구매 {listing.id}' | 등록 취소: '!장비회수 {listing.id}' | 장터 확인: '!장비장터'"
        )

    details = {
        "listing_id": listing.id,
        "equipment_id": target_item.id,
        "seller_id": user.id,
        "seller_name": user.username,
        "buyer_id": target_buyer_id,
        "buyer_name": target_buyer_name,
        "price": price,
        "tax_fee": tax_fee,
        "equipment_name": target_item.name,
        "starforce": target_item.starforce
    }
    return True, reply, details

def execute_buy_equipment_listing(
    db: Session,
    buyer_id: str,
    buyer_name: str,
    listing_id_token: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Buy an equipment from the marketplace or accept a 1:1 direct trade offer.
    Deducts price from buyer, credits 5% fee to Treasury, pays net price to seller, and transfers equipment.
    """
    clean_id = re.sub(r"[^0-9]", "", str(listing_id_token))
    if not clean_id:
        return False, f"⚠️ 올바른 거래 번호를 입력해주세요: '{listing_id_token}' (예: !장비구매 1 | 장터 확인: !장비장터)", None

    listing_id = int(clean_id)
    listing = db.query(EquipmentListing).filter_by(id=listing_id).first()
    if not listing or listing.status != "ACTIVE":
        return False, f"⚠️ 해당 거래(#{listing_id})가 존재하지 않거나 이미 판매 완료/취소되었습니다.", None

    if buyer_id == listing.seller_id:
        return False, f"⚠️ 본인이 등록한 장비는 직접 구매할 수 없습니다! (등록 취소: !장비회수 {listing.id})", None

    if listing.buyer_id and buyer_id != listing.buyer_id:
        return False, f"⚠️ 이 거래는 {listing.buyer_name}님 전용 1:1 직거래입니다! 다른 유저는 구매할 수 없습니다.", None

    buyer = get_or_create_user(db, buyer_id, buyer_name)
    state = get_market_state(db)

    # Debt check: cannot buy if points below debt
    buyer_debt = getattr(buyer, "debt", 0) or 0
    if buyer_debt > 0 and (buyer.points - listing.price) < buyer_debt:
        return False, f"⚠️ 채무(빚: {buyer_debt:,}P)가 있는 상태에서는 빚보다 적은 잔여금을 남기는 장비 구매를 할 수 없습니다! 먼저 !상환을 진행해주세요.", None

    if buyer.points < listing.price:
        return False, f"⚠️ 포인트가 부족합니다! (필요: {listing.price:,}P | 보유: {buyer.points:,}P | 부족: {listing.price - buyer.points:,}P)", None

    eq = db.query(UserEquipment).filter_by(id=listing.equipment_id).first()
    if not eq:
        listing.status = "CANCELLED"
        db.commit()
        return False, "⚠️ 등록된 장비 데이터를 찾을 수 없어 거래가 자동 취소되었습니다.", None

    seller = db.query(User).filter_by(id=listing.seller_id).first()
    tax_fee = listing.tax_fee
    seller_payout = listing.price - tax_fee

    # Financial transfers
    buyer.points -= listing.price
    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL
    state.treasury_pool += tax_fee
    if seller:
        seller.points += seller_payout

    # Transfer equipment ownership
    eq.user_id = buyer.id
    eq.is_equipped = False

    # Auto equip if buyer currently has no equipped items or only a 0-star starter pickaxe
    buyer_items = db.query(UserEquipment).filter_by(user_id=buyer.id).all()
    equipped = [it for it in buyer_items if it.is_equipped]
    if not equipped or (len(equipped) == 1 and equipped[0].starforce == 0 and eq.starforce > 0):
        for it in buyer_items:
            it.is_equipped = False
        eq.is_equipped = True
        buyer.pickaxe_level = eq.starforce

    # Mark listing as sold
    listing.status = "SOLD"
    listing.resolved_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(buyer)
    if seller:
        db.refresh(seller)
    db.refresh(eq)
    db.refresh(state)

    reply = (
        f"🎉🤝 [장비 거래 성사!] {buyer.username}님이 {listing.seller_name}님의 [장비 #{eq.id} {eq.name}]을(를) {listing.price:,}P에 인수했습니다! "
        f"(국고 거래세: +{tax_fee:,}P | 판매자 정산: +{seller_payout:,}P | 내 잔여: {buyer.points:,}P | 장착: !장착 {eq.id})"
    )

    details = {
        "listing_id": listing.id,
        "equipment_id": eq.id,
        "equipment_name": eq.name,
        "starforce": eq.starforce,
        "seller_id": listing.seller_id,
        "seller_name": listing.seller_name,
        "buyer_id": buyer.id,
        "buyer_name": buyer.username,
        "price": listing.price,
        "tax_fee": tax_fee,
        "seller_payout": seller_payout,
        "remaining_points": buyer.points,
        "treasury_pool": state.treasury_pool
    }
    return True, reply, details

def execute_cancel_equipment_listing(
    db: Session,
    user_id: str,
    username: str,
    listing_id_token: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Cancel an active equipment marketplace listing and reclaim the item.
    """
    clean_id = re.sub(r"[^0-9]", "", str(listing_id_token))
    if not clean_id:
        return False, f"⚠️ 올바른 거래 번호를 입력해주세요: '{listing_id_token}' (예: !장비회수 1)", None

    listing_id = int(clean_id)
    listing = db.query(EquipmentListing).filter_by(id=listing_id).first()
    if not listing or listing.status != "ACTIVE":
        return False, f"⚠️ 거래 #{listing_id}는 존재하지 않거나 이미 마감/취소된 거래입니다.", None

    if listing.seller_id != user_id:
        return False, "⚠️ 본인이 등록한 거래만 취소할 수 있습니다!", None

    user = get_or_create_user(db, user_id, username)
    listing.status = "CANCELLED"
    listing.resolved_at = datetime.now(timezone.utc)

    eq = listing.equipment
    if eq:
        # If user currently has no equipped item or only has a 0-star starter pickaxe, auto-equip the reclaimed item!
        user_items = db.query(UserEquipment).filter_by(user_id=user.id).all()
        equipped = [it for it in user_items if it.is_equipped]
        if not equipped or (len(equipped) == 1 and equipped[0].starforce < eq.starforce):
            for it in user_items:
                it.is_equipped = (it.id == eq.id)
            eq.is_equipped = True
            user.pickaxe_level = eq.starforce
    db.commit()

    eq_name = eq.name if eq else "장비"
    star_str = f" (★{eq.starforce}성)" if eq else ""
    reply = f"📦↩️ [장비 등록 취소] 거래 #{listing.id}의 [{eq_name}{star_str}] 판매 등록이 취소되어 인벤토리로 안전하게 회수되었습니다!"
    if eq and eq.is_equipped:
        reply += " (주 장비로 자동 재장착되었습니다!)"
    else:
        reply += f" (장착: !장착 {eq.id if eq else ''})"
    return True, reply, {"listing_id": listing.id, "equipment_id": eq.id if eq else None}


def toggle_user_scroll_arm(
    db: Session,
    user_id: str,
    username: str,
    scroll_type: Optional[str] = None,
    state_str: Optional[str] = None
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Toggle user designated scroll auto-use setting or use snipe scroll directly (!주문서 [파방/하강/상승/저격/전체] [on/off/옵션])."""
    user = get_or_create_user(db, user_id, username)

    # If no argument, show current arming status
    if not scroll_type:
        s_cnt = getattr(user, "shield_scroll_count", 0) or 0
        d_cnt = getattr(user, "downgrade_scroll_count", 0) or 0
        b_cnt = getattr(user, "boost_scroll_count", 0) or 0
        s100_cnt = getattr(user, "shield_100_scroll_count", 0) or 0
        d100_cnt = getattr(user, "downgrade_100_scroll_count", 0) or 0
        snipe_cnt = getattr(user, "snipe_scroll_count", 0) or 0
        s_arm = "🟢확정(ON)" if getattr(user, "arm_shield", True) else "🔴OFF"
        d_arm = "🟢확정(ON)" if getattr(user, "arm_downgrade", True) else "🔴OFF"
        b_arm = "🟢ON" if getattr(user, "arm_boost", False) else "🔴OFF"
        s100_arm = "🟢확정(ON)" if getattr(user, "arm_shield_100", True) else "🔴OFF"
        d100_arm = "🟢확정(ON)" if getattr(user, "arm_downgrade_100", True) else "🔴OFF"
        snipe_arm = "🟢ON" if getattr(user, "arm_snipe", False) else "🔴OFF"

        special_scrolls = get_user_special_snipe_scrolls(user)
        special_txt = ""
        if special_scrolls:
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
            sp_lines = [f"• {special_names.get(k, f'🎯 {k} 전용 저격주문서')}: {v:,}장" for k, v in special_scrolls.items()]
            special_txt = "\n[🌟 보유 중인 특수 전용 저격주문서 (1줄 88% 확정급!)]\n" + "\n".join(sp_lines)

        reply = (
            f"📜 [{user.username}님의 주문서 상시 사용 설정 및 보유 현황]\n"
            f"• 🛡️ 파괴방어권(60%): {s_arm} (보유: {s_cnt}장) [강화 시 자동 사용 | 설정: !주문서 파방 on/off]\n"
            f"• 📉 하강방지권(70%): {d_arm} (보유: {d_cnt}장) [강화 시 자동 사용 | 설정: !주문서 하강 on/off]\n"
            f"• 🛡️✨ 절대 파괴방어권(100% 무적): {s100_arm} (보유: {s100_cnt}장) [설정: !주문서 절대파방 on/off]\n"
            f"• 📉✨ 절대 하강방지권(100% 무적): {d100_arm} (보유: {d100_cnt}장) [설정: !주문서 절대하강 on/off]\n"
            f"• ⚡ 강화확률상승권: {b_arm} (보유: {b_cnt}장) [설정: !주문서 상승 on/off]\n"
            f"• 🎯 잠재저격주문서: {snipe_arm} (보유: {snipe_cnt}장) [사용: !주문서 저격 [옵션명] | 설정: !주문서 저격 on/off]{special_txt}\n"
            f"💡 저격 주문서 사용: `!주문서 저격 고블린`, `!주문서 저격 과충전`, `!주문서 저격 쿨초`, `!주문서 저격 크리`\n"
            f"💡 강화 주문서 설정: `!주문서 절대파방 on`, `!주문서 절대하강 on`, `!주문서 파방 off`, `!주문서 하강 off`, `!주문서 전체 on`"
        )
        return True, reply, {
            "arm_shield": bool(getattr(user, "arm_shield", True)),
            "arm_downgrade": bool(getattr(user, "arm_downgrade", True)),
            "arm_shield_100": bool(getattr(user, "arm_shield_100", True)),
            "arm_downgrade_100": bool(getattr(user, "arm_downgrade_100", True)),
            "arm_boost": bool(getattr(user, "arm_boost", False)),
            "arm_snipe": bool(getattr(user, "arm_snipe", False))
        }

    clean_target = scroll_type.strip().lower()
    target_state = None
    if state_str:
        s_clean = state_str.strip().lower()
        if s_clean in ["on", "켜기", "활성", "1", "true", "start"]:
            target_state = True
        elif s_clean in ["off", "끄기", "비활성", "0", "false", "stop"]:
            target_state = False

    # 0-1. 🛡️✨ 절대 파괴방어권 100% (Shield 100% - Item 6)
    if clean_target in ["6", "절대파방", "절대파방권", "절대방어권", "shield100", "shield_100", "100파방", "100파방권", "100파괴방어"] or any(k in clean_target for k in ["절대파방", "100파방", "절대파괴"]):
        new_val = target_state if target_state is not None else not bool(getattr(user, "arm_shield_100", True))
        user.arm_shield_100 = new_val
        db.commit()
        stat = "🟢활성화(ON)" if new_val else "🔴비활성화(OFF)"
        return True, f"🛡️✨ [절대 파괴방어권(100%) 상시사용] 설정이 {stat}되었습니다. (보유: {getattr(user, 'shield_100_scroll_count', 0)}장)", {"arm_shield_100": new_val}

    # 0-2. 📉✨ 절대 하강방지권 100% (Downgrade 100% - Item 7)
    elif clean_target in ["7", "절대하강", "절대하방", "절대하방권", "downgrade100", "downgrade_100", "100하강", "100하방", "100하강권"] or any(k in clean_target for k in ["절대하강", "100하강", "절대하방", "100하방"]):
        new_val = target_state if target_state is not None else not bool(getattr(user, "arm_downgrade_100", True))
        user.arm_downgrade_100 = new_val
        db.commit()
        stat = "🟢활성화(ON)" if new_val else "🔴비활성화(OFF)"
        return True, f"📉✨ [절대 하강방지권(100%) 상시사용] 설정이 {stat}되었습니다. (보유: {getattr(user, 'downgrade_100_scroll_count', 0)}장)", {"arm_downgrade_100": new_val}

    # 1. 🛡️ 파괴방어권 (Shield - Item 1)
    elif clean_target in ["1", "파방", "파방권", "방어권", "shield"] or any(k in clean_target for k in ["파괴방어", "파괴방지", "파괴", "파방"]):
        new_val = target_state if target_state is not None else not bool(getattr(user, "arm_shield", True))
        user.arm_shield = new_val
        db.commit()
        stat = "🟢활성화(ON)" if new_val else "🔴비활성화(OFF)"
        return True, f"🛡️ [파괴방어권 상시사용] 설정이 {stat}되었습니다. (보유: {user.shield_scroll_count}장)", {"arm_shield": new_val}

    # 2. ⚡ 강화확률상승권 (Boost - Item 2)
    elif clean_target in ["2", "상승", "상승권", "boost", "강화", "성공"] or any(k in clean_target for k in ["강화확률", "확률상승", "강화상승", "상승", "성공", "강화", "확률"]):
        new_val = target_state if target_state is not None else not bool(getattr(user, "arm_boost", False))
        user.arm_boost = new_val
        db.commit()
        stat = "🟢활성화(ON)" if new_val else "🔴비활성화(OFF)"
        return True, f"⚡ [강화확률상승권 상시사용] 설정이 {stat}되었습니다. (보유: {user.boost_scroll_count}장)", {"arm_boost": new_val}

    # 3. 📉 하강방지권 (Downgrade - Item 3)
    elif clean_target in ["3", "하방", "하방권", "하강", "downgrade", "down"] or any(k in clean_target for k in ["하강방지", "하강"]):
        new_val = target_state if target_state is not None else not bool(getattr(user, "arm_downgrade", True))
        user.arm_downgrade = new_val
        db.commit()
        stat = "🟢활성화(ON)" if new_val else "🔴비활성화(OFF)"
        return True, f"📉 [하강방지권 상시사용] 설정이 {stat}되었습니다. (보유: {user.downgrade_scroll_count}장)", {"arm_downgrade": new_val}

    # 4. 🎯 잠재저격주문서 (Snipe - Item 4)
    elif clean_target in ["4", "저격", "snipe", "저격권", "저격주문서"] or any(k in clean_target for k in ["잠재저격", "저격"]):
        if target_state is not None:
            user.arm_snipe = target_state
            db.commit()
            stat = "🟢활성화(ON)" if target_state else "🔴비활성화(OFF)"
            return True, f"🎯 [잠재저격주문서 상시사용] 설정이 {stat}되었습니다. (보유: {getattr(user, 'snipe_scroll_count', 0)}장)", {"arm_snipe": target_state}
        elif state_str:
            # User passed a keyword e.g. !주문서 저격 과충전 -> Direct usage of snipe scroll!
            sp_code = None
            u_specials = get_user_special_snipe_scrolls(user)
            _, matched_codes = match_potential_target(state_str)
            if matched_codes:
                for c in matched_codes:
                    if u_specials.get(c, 0) > 0:
                        sp_code = c
                        break
            return execute_cube_use(db, user_id, username, target_keyword=state_str, use_snipe=True, special_snipe_code=sp_code)
        else:
            snipe_cnt = getattr(user, "snipe_scroll_count", 0) or 0
            return False, (
                f"💡 [잠재저격주문서 사용법] `!주문서 저격 [옵션명]` (예: `!주문서 저격 고블린`, `!주문서 저격 과충전`, `!주문서 저격 쿨초` | 보유: {snipe_cnt}장)\n"
                f"• 지원 키워드: 고블린, 과충전, 쿨초, 쿨감, 크리, 채굴량, 현금, 국고, 자동, 성공률, 할인, 파괴방지, 배당, 수수료, 야수, 슬롯, 주사위, 마작, 경마, 채굴, 스타포스, 주식, 카지노\n"
                f"• 전체 옵션 상세 도감 및 설명 확인: `!저격목록` (또는 `!옵션목록`)\n"
                f"• 상시 설정 토글: `!주문서 저격 on` / `!주문서 저격 off`"
            ), None

    # 4-1. 🌟 특수 전용 저격주문서 직접 사용 (!주문서 전용 [옵션])
    elif clean_target in ["전용", "전용저격", "특수", "특수저격", "special"]:
        if not state_str:
            u_specials = get_user_special_snipe_scrolls(user)
            if not u_specials:
                return False, "⚠️ 현재 보유 중인 특수 전용 저격주문서가 없습니다! (신비상인 또는 거래소에서 구매 가능)", None
            s_list = ", ".join([f"{k}({v}장)" for k, v in u_specials.items()])
            return False, f"💡 [전용 저격주문서 사용법] `!주문서 전용 [옵션명]` (예: `!주문서 전용 과충전`, `!주문서 전용 고블린` | 보유 목록: {s_list})", None
        _, matched_codes = match_potential_target(state_str)
        sp_code = None
        u_specials = get_user_special_snipe_scrolls(user)
        if matched_codes:
            for c in matched_codes:
                if u_specials.get(c, 0) > 0:
                    sp_code = c
                    break
        if not sp_code and state_str.upper() in u_specials:
            sp_code = state_str.upper()
        if not sp_code:
            return False, f"⚠️ 입력하신 옵션('{state_str}')에 해당하는 전용 저격주문서를 보유하고 있지 않습니다! (보유: {list(u_specials.keys())})", None
        return execute_cube_use(db, user_id, username, target_keyword=state_str, use_snipe=True, special_snipe_code=sp_code)

    # 5. 📜 전체 (All) - Snipe / Special Snipe is strictly excluded from "전체 on"!
    elif clean_target in ["전체", "all", "풀", "모두", "다"]:
        new_val = target_state if target_state is not None else not bool(getattr(user, "arm_shield", True))
        user.arm_shield = new_val
        user.arm_downgrade = new_val
        user.arm_boost = new_val
        user.arm_shield_100 = new_val
        user.arm_downgrade_100 = new_val
        # Exclude snipe scroll from '전체 on' to prevent unintended burning
        if not new_val:
            user.arm_snipe = False
        db.commit()
        stat = "🟢강화 주문서 전체 활성화(ON, 저격 제외)" if new_val else "🔴전체 비활성화(OFF)"
        return True, f"📜 [강화 주문서 전체 상시사용] 설정이 {stat}되었습니다. (⚠️ 잠재저격주문서는 원치 않는 소모를 방지하기 위해 전체 ON에서 제외됩니다)", {
            "arm_shield": user.arm_shield,
            "arm_downgrade": user.arm_downgrade,
            "arm_boost": user.arm_boost,
            "arm_shield_100": user.arm_shield_100,
            "arm_downgrade_100": user.arm_downgrade_100,
            "arm_snipe": user.arm_snipe
        }

    else:
        if target_state is not None:
            return False, "⚠️ 올바른 주문서 종류를 입력해주세요: 파방(1), 상승(2/강화), 하강(3), 저격(4), 전체 (예: !주문서 상승 on, !주문서 강화 on, !주문서 2 on, !주문서 파방 on, !주문서 전체 on)", None

        # Only if NOT an on/off toggle and user explicitly specified a potential target keyword (excluding generic starforce)
        matched_label, matched_codes = match_potential_target(clean_target)
        if matched_codes and clean_target not in ["강화", "스타포스", "starforce", "2", "상승"]:
            sp_code = None
            u_specials = get_user_special_snipe_scrolls(user)
            if matched_codes:
                for c in matched_codes:
                    if u_specials.get(c, 0) > 0:
                        sp_code = c
                        break
            return execute_cube_use(db, user_id, username, target_keyword=clean_target, use_snipe=True, special_snipe_code=sp_code)
        return False, "⚠️ 올바른 주문서 종류를 입력해주세요: 파방(1), 상승(2/강화), 하강(3), 저격(4), 전체 (예: !주문서 상승 on, !주문서 강화 on, !주문서 2 on, !주문서 파방 on, !주문서 전체 off)", None


CONSUMABLE_TRADE_ITEMS: Dict[str, Dict[str, Any]] = {
    "shield": {
        "field": "shield_scroll_count",
        "name": "🛡️ 파괴방어권",
        "unit": "장",
        "aliases": ["파괴방어권", "파방", "파방권", "파괴방어", "방어권", "shield", "1"]
    },
    "boost": {
        "field": "boost_scroll_count",
        "name": "⚡ 강화확률상승권",
        "unit": "장",
        "aliases": ["강화확률상승권", "확률상승권", "상승권", "상승", "boost", "2"]
    },
    "downgrade": {
        "field": "downgrade_scroll_count",
        "name": "📉 하강방지권",
        "unit": "장",
        "aliases": ["하강방지권", "하강권", "하강방지", "방지권", "downgrade", "3"]
    },
    "cube": {
        "field": "cube_count",
        "name": "🔮 미라클 큐브",
        "unit": "개",
        "aliases": ["미라클큐브", "큐브", "cube"]
    },
    "snipe": {
        "field": "snipe_scroll_count",
        "name": "🎯 잠재저격주문서",
        "unit": "장",
        "aliases": ["잠재저격주문서", "저격주문서", "저격권", "저격", "snipe", "target", "4"]
    }
}


def execute_list_item(
    db: Session,
    user_id: str,
    username: str,
    item_token: str,
    quantity_token: str,
    price_token: str,
    target_buyer_token: Optional[str] = None
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    List consumable items (scrolls/cubes) for sale on the exchange.
    Items are safely escrowed from seller's inventory while listed.
    5% transaction fee is charged upon sale and credited to Treasury.
    """
    user = get_or_create_user(db, user_id, username)
    clean_item = item_token.strip().lower()

    matched_type = None
    for it_type, conf in CONSUMABLE_TRADE_ITEMS.items():
        if clean_item in conf["aliases"]:
            matched_type = it_type
            break
    if not matched_type:
        valid_names = ", ".join([conf["name"] for conf in CONSUMABLE_TRADE_ITEMS.values()])
        return False, f"⚠️ 판매 가능한 아이템이 아닙니다: '{item_token}'\n(판매 가능 아이템: {valid_names} | 예: !아이템판매 파방 1 350000)", None

    conf = CONSUMABLE_TRADE_ITEMS[matched_type]
    field = conf["field"]
    user_stock = getattr(user, field, 0) or 0

    clean_qty = re.sub(r"[^0-9]", "", str(quantity_token))
    if not clean_qty or int(clean_qty) <= 0:
        return False, f"⚠️ 올바른 판매 수량을 입력해주세요: '{quantity_token}' (예: !아이템판매 파방 1 350000)", None
    qty = int(clean_qty)

    if user_stock < qty:
        return False, f"⚠️ 보유 수량이 부족합니다! (보유: {user_stock}{conf['unit']} | 요청: {qty}{conf['unit']})", None

    clean_price = re.sub(r"[^0-9]", "", str(price_token))
    if not clean_price:
        return False, f"⚠️ 올바른 판매 가격을 입력해주세요: '{price_token}' (예: !아이템판매 파방 1 350000)", None
    price = int(clean_price)
    if price < 1000:
        return False, "⚠️ 최소 판매 등록 가격은 1,000P입니다.", None
    if price > 1000000000:
        return False, "⚠️ 최대 판매 등록 가격은 1,000,000,000P입니다.", None

    target_buyer_id = None
    target_buyer_name = None
    if target_buyer_token:
        clean_buyer = str(target_buyer_token).strip().lstrip("@")
        buyer_user = db.query(User).filter(func.lower(User.username) == clean_buyer.lower()).first()
        if not buyer_user:
            return False, f"⚠️ 구매 대상 유저 '{clean_buyer}'님을 찾을 수 없습니다.", None
        if buyer_user.id == user.id:
            return False, "⚠️ 본인에게는 직거래로 판매할 수 없습니다.", None
        target_buyer_id = buyer_user.id
        target_buyer_name = buyer_user.username

    tax_fee = max(50, int(round(price * 0.05)))

    # Deduct items from user inventory immediately (Escrow)
    setattr(user, field, user_stock - qty)

    listing = ItemListing(
        seller_id=user.id,
        seller_name=user.username,
        buyer_id=target_buyer_id,
        buyer_name=target_buyer_name,
        item_type=matched_type,
        item_name=conf["name"],
        quantity=qty,
        price=price,
        tax_fee=tax_fee,
        status="ACTIVE",
        created_at=datetime.now(timezone.utc)
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)

    target_tag = f"[{target_buyer_name} 전용 1:1 직거래]" if target_buyer_name else "[거래소 공개 등록]"
    reply = (
        f"🏪📦 {target_tag} {user.username}님이 [{conf['name']} x{qty}{conf['unit']}]을(를) "
        f"총 {price:,}P (개당 {price // qty:,}P | 5% 수수료: {tax_fee:,}P)에 등록했습니다! (거래번호: #I{listing.id})\n"
        f"👉 구매: '!거래소구매 I{listing.id}' | 취소: '!거래소취소 I{listing.id}'"
    )
    details = {
        "listing_id": listing.id,
        "item_type": matched_type,
        "item_name": conf["name"],
        "quantity": qty,
        "price": price,
        "tax_fee": tax_fee,
        "seller_id": user.id,
        "seller_name": user.username,
        "buyer_id": target_buyer_id,
        "buyer_name": target_buyer_name
    }
    return True, reply, details


def execute_buy_item_listing(
    db: Session,
    buyer_id: str,
    buyer_name: str,
    listing_id_token: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Buy an item listing from the exchange."""
    clean_id = re.sub(r"[^0-9]", "", str(listing_id_token))
    if not clean_id:
        return False, f"⚠️ 올바른 거래 번호를 입력해주세요: '{listing_id_token}' (예: !거래소구매 I1)", None

    listing_id = int(clean_id)
    listing = db.query(ItemListing).filter_by(id=listing_id).first()
    if not listing or listing.status != "ACTIVE":
        return False, f"⚠️ 해당 아이템 거래(#I{listing_id})가 존재하지 않거나 이미 판매 완료/취소되었습니다.", None

    if buyer_id == listing.seller_id:
        return False, f"⚠️ 본인이 등록한 물품은 직접 구매할 수 없습니다! (취소: !거래소취소 I{listing.id})", None

    if listing.buyer_id and buyer_id != listing.buyer_id:
        return False, f"⚠️ 이 거래는 {listing.buyer_name}님 전용 1:1 직거래입니다! 다른 유저는 구매할 수 없습니다.", None

    buyer = get_or_create_user(db, buyer_id, buyer_name)
    state = get_market_state(db)

    buyer_debt = getattr(buyer, "debt", 0) or 0
    if buyer_debt > 0 and (buyer.points - listing.price) < buyer_debt:
        return False, f"⚠️ 채무(빚: {buyer_debt:,}P)가 있는 상태에서는 빚보다 적은 잔여금을 남기는 구매를 할 수 없습니다! 먼저 !상환을 진행해주세요.", None

    if buyer.points < listing.price:
        return False, f"⚠️ 포인트가 부족합니다! (필요: {listing.price:,}P | 보유: {buyer.points:,}P | 부족: {listing.price - buyer.points:,}P)", None

    seller = db.query(User).filter_by(id=listing.seller_id).first()
    tax_fee = listing.tax_fee
    seller_payout = listing.price - tax_fee

    # Financial transfers
    buyer.points -= listing.price
    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL
    state.treasury_pool += tax_fee
    if seller:
        seller.points += seller_payout

    # Transfer items to buyer
    conf = CONSUMABLE_TRADE_ITEMS.get(listing.item_type)
    if conf:
        field = conf["field"]
        setattr(buyer, field, (getattr(buyer, field, 0) or 0) + listing.quantity)

    listing.status = "SOLD"
    listing.resolved_at = datetime.now(timezone.utc)
    db.commit()

    reply = (
        f"🎉🤝 [거래소 아이템 구매 완료!] {buyer.username}님이 {listing.seller_name}님의 [{listing.item_name} x{listing.quantity}개]을(를) {listing.price:,}P에 구매했습니다! "
        f"(국고 거래세: +{tax_fee:,}P | 판매자 정산: +{seller_payout:,}P | 내 잔여: {buyer.points:,}P | 인벤토리: !아이템)"
    )
    details = {
        "listing_id": listing.id,
        "item_type": listing.item_type,
        "item_name": listing.item_name,
        "quantity": listing.quantity,
        "price": listing.price,
        "tax_fee": tax_fee,
        "seller_payout": seller_payout,
        "buyer_id": buyer.id,
        "buyer_name": buyer.username,
        "remaining_points": buyer.points
    }
    return True, reply, details


def execute_cancel_item_listing(
    db: Session,
    user_id: str,
    username: str,
    listing_id_token: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Cancel an item listing and return items from escrow to seller."""
    clean_id = re.sub(r"[^0-9]", "", str(listing_id_token))
    if not clean_id:
        return False, f"⚠️ 올바른 거래 번호를 입력해주세요: '{listing_id_token}' (예: !거래소취소 I1)", None

    listing_id = int(clean_id)
    listing = db.query(ItemListing).filter_by(id=listing_id).first()
    if not listing or listing.status != "ACTIVE":
        return False, f"⚠️ 거래 #I{listing_id}는 존재하지 않거나 이미 마감/취소된 거래입니다.", None

    if listing.seller_id != user_id:
        return False, "⚠️ 본인이 등록한 거래만 취소할 수 있습니다!", None

    user = get_or_create_user(db, user_id, username)
    conf = CONSUMABLE_TRADE_ITEMS.get(listing.item_type)
    if conf:
        field = conf["field"]
        setattr(user, field, (getattr(user, field, 0) or 0) + listing.quantity)

    listing.status = "CANCELLED"
    listing.resolved_at = datetime.now(timezone.utc)
    db.commit()

    reply = f"📦↩️ [아이템 등록 취소] 거래 #I{listing.id}의 [{listing.item_name} x{listing.quantity}개] 판매가 취소되어 인벤토리로 안전하게 반환되었습니다!"
    return True, reply, {"listing_id": listing.id, "item_type": listing.item_type, "quantity": listing.quantity}


def execute_buy_exchange(
    db: Session,
    buyer_id: str,
    buyer_name: str,
    listing_token: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Unified buy function for !거래소구매 [E1/I1/1]. Handles both Equipment and Item listings."""
    raw = str(listing_token).strip().lstrip("#")
    upper = raw.upper()
    if upper.startswith("E") or upper.startswith("EQ") or upper.startswith("장비"):
        clean_num = re.sub(r"[^0-9]", "", raw)
        return execute_buy_equipment_listing(db, buyer_id, buyer_name, clean_num)
    elif upper.startswith("I") or upper.startswith("ITEM") or upper.startswith("아이템"):
        clean_num = re.sub(r"[^0-9]", "", raw)
        return execute_buy_item_listing(db, buyer_id, buyer_name, clean_num)
    elif raw.isdigit():
        lid = int(raw)
        it_listing = db.query(ItemListing).filter_by(id=lid, status="ACTIVE").first()
        eq_listing = db.query(EquipmentListing).filter_by(id=lid, status="ACTIVE").first()
        if eq_listing and it_listing:
            return False, f"⚠️ 거래 번호 #{lid}번에 장비(E{lid})와 아이템(I{lid}) 매물이 모두 존재합니다! '!거래소구매 E{lid}' 또는 '!거래소구매 I{lid}'로 지정해주세요.", None
        elif it_listing:
            return execute_buy_item_listing(db, buyer_id, buyer_name, str(lid))
        elif eq_listing:
            return execute_buy_equipment_listing(db, buyer_id, buyer_name, str(lid))
        else:
            return False, f"⚠️ 거래 번호 #{lid}의 활성화된 매물을 찾을 수 없습니다! (목록 확인: !거래소)", None
    else:
        return False, f"⚠️ 올바른 거래 번호를 입력해주세요: '{listing_token}' (예: !거래소구매 I1 또는 !거래소구매 E1)", None


def execute_cancel_exchange(
    db: Session,
    user_id: str,
    username: str,
    listing_token: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Unified cancel function for !거래소취소 [E1/I1/1]. Handles both Equipment and Item listings."""
    raw = str(listing_token).strip().lstrip("#")
    upper = raw.upper()
    if upper.startswith("E") or upper.startswith("EQ") or upper.startswith("장비"):
        clean_num = re.sub(r"[^0-9]", "", raw)
        return execute_cancel_equipment_listing(db, user_id, username, clean_num)
    elif upper.startswith("I") or upper.startswith("ITEM") or upper.startswith("아이템"):
        clean_num = re.sub(r"[^0-9]", "", raw)
        return execute_cancel_item_listing(db, user_id, username, clean_num)
    elif raw.isdigit():
        lid = int(raw)
        it_listing = db.query(ItemListing).filter_by(id=lid, status="ACTIVE", seller_id=user_id).first()
        eq_listing = db.query(EquipmentListing).filter_by(id=lid, status="ACTIVE", seller_id=user_id).first()
        if it_listing and eq_listing:
            return False, f"⚠️ 내 등록 거래 #{lid}번에 장비(E{lid})와 아이템(I{lid})이 모두 존재합니다! '!거래소취소 E{lid}' 또는 '!거래소취소 I{lid}'로 지정해주세요.", None
        elif it_listing:
            return execute_cancel_item_listing(db, user_id, username, str(lid))
        elif eq_listing:
            return execute_cancel_equipment_listing(db, user_id, username, str(lid))
        else:
            return False, f"⚠️ 취소 가능한 내 활성 거래 #{lid}를 찾을 수 없습니다.", None
    else:
        return False, f"⚠️ 올바른 거래 번호를 입력해주세요: '{listing_token}' (예: !거래소취소 I1 또는 !거래소취소 E1)", None


def execute_buy_cubes(
    db: Session,
    user_id: str,
    username: str,
    quantity_str: Optional[str] = "1"
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Execute !큐브구매 [수량/최대] (MapleStory Miracle Cube purchase).
    - Cost: 15,000P per cube, 100% credited to Treasury pool.
    - Adds to user.cube_count.
    """
    state = get_market_state(db)
    user = get_or_create_user(db, user_id, username)

    raw = (quantity_str or "1").strip().lower()

    if raw in ["최대", "올인", "max", "all", "전액", "전부"]:
        qty = user.points // CUBE_COST
        if qty <= 0:
            return False, f"⚠️ 포인트가 부족하여 큐브를 구매할 수 없습니다! (보유: {user.points:,}P | 1개당 {CUBE_COST:,}P)", None
    else:
        try:
            qty = int(raw.replace(",", "").replace("개", "").replace("p", "").replace("원", ""))
        except ValueError:
            return False, f"💡 큐브 구매 사용법: !큐브구매 [수량/최대] (예: !큐브구매 1, !큐브구매 10 | 1개당 {CUBE_COST:,}P)", None

    if qty <= 0:
        return False, "⚠️ 구매 수량은 1개 이상의 양수여야 합니다.", None

    total_cost = qty * CUBE_COST

    if user.points < total_cost:
        max_possible = user.points // CUBE_COST
        return False, f"⚠️ 포인트가 부족합니다! (필요: {total_cost:,}P | 보유: {user.points:,}P | 최대 구매 가능: {max_possible}개)", None

    # Deduct cost and credit to Treasury
    user.points -= total_cost
    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL
    state.treasury_pool += total_cost

    # Add cubes to user inventory
    user.cube_count = (getattr(user, "cube_count", 0) or 0) + qty

    db.commit()
    db.refresh(user)
    db.refresh(state)

    reply = (
        f"🔮 [미라클 큐브 구매 완료] {user.username}님이 큐브 {qty:,}개를 구매했습니다!\n"
        f"  • 결제 금액: -{total_cost:,}P (전액 국고 상금풀 적립)\n"
        f"  • 📦 보유 큐브: {user.cube_count:,}개 | 💰 잔여 포인트: {user.points:,}P\n"
        f"💡 사용법: !큐브 (장착 곡괭이에 1개 사용) 또는 !큐브 [장비번호]"
    )

    details = {
        "user_id": user.id,
        "username": user.username,
        "quantity": qty,
        "cost_per_cube": CUBE_COST,
        "total_cost": total_cost,
        "cube_count": user.cube_count,
        "remaining_points": user.points
    }
    return True, reply, details

def execute_cube_use(
    db: Session,
    user_id: str,
    username: str,
    item_id_or_index: Optional[str] = None,
    target_keyword: Optional[str] = None,
    use_snipe: bool = False,
    lock_lines: Optional[List[int]] = None,
    special_snipe_code: Optional[str] = None
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Execute !큐브 [장비번호/슬롯] [저격 옵션] (MapleStory Miracle Cube potential reset).
    - Requires pre-purchased cube (!큐브구매). Consumes 1 cube from user.cube_count.
    - If special_snipe_code is specified, consumes 1 specific option sniper scroll and applies
      88% targeted snipe chance on Line 1 + 10x weight on other lines!
    - If target_keyword is specified or use_snipe=True, consumes 1 generic snipe scroll (!상인구매 4)
      and provides 35% targeted snipe chance on Line 1 + 3.5x weight across all lines.
    - Equipment Cube Lock: If target_item.is_cube_locked is True, cube rerolls are blocked.
    - Potential Line Lock: If lines are locked, consumes 20x current price (300,000P or 20 cubes) and preserves locked lines.
    - Tier order: NONE -> RARE -> EPIC -> UNIQUE -> LEGENDARY
    - Promotion rates: NONE->RARE 100%, RARE->EPIC 15%, EPIC->UNIQUE 3.5%, UNIQUE->LEGENDARY 1.4%
    - Pity guarantees: RARE->EPIC 10 cubes, EPIC->UNIQUE 42 cubes, UNIQUE->LEGENDARY 107 cubes
    - 1 Cube Fragment per normal use (20 fragments for 20x line-locked use).
    """
    state = get_market_state(db)
    user = get_or_create_user(db, user_id, username)
    target_item = find_user_equipment(db, user, item_id_or_index)

    if not target_item:
        return False, f"⚠️ 지정한 장비('{item_id_or_index}')를 보유하고 있지 않습니다! (내 장비 확인: !내장비, !인벤토리)", None

    active_listing = db.query(EquipmentListing).filter_by(equipment_id=target_item.id, status="ACTIVE").first()
    if active_listing:
        return False, f"⚠️ [장비 #{target_item.id}]은(는) 현재 거래소/직거래에 판매 등록 중입니다! 등록 취소(!장비회수) 후 큐브를 사용해주세요.", None

    if getattr(target_item, "is_cube_locked", False):
        return False, (
            f"🔒 [장비 #{target_item.id} {target_item.name}]은(는) 큐브 잠금(보호) 상태입니다!\n"
            f"실수로 잠재능력이 변경되는 것을 방지 중입니다. (잠금 해제: '!큐브잠금 {target_item.id}' 또는 '!큐브해제')"
        ), None

    effective_locked = set(lock_lines or [])
    if getattr(target_item, "is_line1_locked", False):
        effective_locked.add(1)
    if getattr(target_item, "is_line2_locked", False):
        effective_locked.add(2)
    if getattr(target_item, "is_line3_locked", False):
        effective_locked.add(3)

    if len(effective_locked) > 1:
        return False, "⚠️ 잠재능력 라인 잠금은 최대 1줄까지만 가능합니다! (옵션잠금 해제 후 다시 시도해주세요)", None

    curr_tier = (target_item.potential_tier or "NONE").upper()
    if curr_tier not in CUBE_TIER_ORDER:
        curr_tier = "NONE"

    if effective_locked and (curr_tier == "NONE" or not target_item.potential_line_1):
        return False, "⚠️ 잠재능력이 개방되지 않은 장비(일반)는 라인을 잠글 수 없습니다! 먼저 큐브를 돌려 잠재를 개방해주세요.", None

    user_cube_count = getattr(user, "cube_count", 0) or 0
    cost_desc = ""
    frag_gain = 1

    if effective_locked:
        required_cubes = 20
        total_point_cost = required_cubes * CUBE_COST  # 300,000P
        if user_cube_count >= required_cubes:
            user.cube_count = user_cube_count - required_cubes
            cost_desc = "보유 큐브 20개 소모 (라인 잠금 20배)"
        else:
            needed_cubes = required_cubes - user_cube_count
            needed_points = needed_cubes * CUBE_COST
            if user.points < needed_points:
                return False, (
                    f"⚠️ 잠재 라인 잠금 큐브는 현 가격의 20배(큐브 20개 또는 {total_point_cost:,}P)가 필요합니다!\n"
                    f"현재 보유: 큐브 {user_cube_count}개, 잔고 {user.points:,}P (부족: {needed_points - user.points:,}P)\n"
                    f"💡 라인 잠금 해제: !옵션잠금 해제"
                ), None
            user.points -= needed_points
            state.treasury_pool = (getattr(state, "treasury_pool", 0.0) or 0.0) + needed_points
            used_cubes = user_cube_count
            user.cube_count = 0
            if used_cubes > 0:
                cost_desc = f"큐브 {used_cubes}개 + {needed_points:,}P 소모 (라인 잠금 20배)"
            else:
                cost_desc = f"{total_point_cost:,}P 소모 (라인 잠금 20배)"
        frag_gain = 20
        user.cube_fragments = (getattr(user, "cube_fragments", 0) or 0) + 20
    else:
        if user_cube_count <= 0:
            return False, (
                f"⚠️ 보유한 큐브가 없습니다! 상점에서 큐브를 먼저 구매해주세요.\n"
                f"💡 구매 명령어: !큐브구매 [수량] (1개당 {CUBE_COST:,}P | 내 포인트: {user.points:,}P)"
            ), None
        user.cube_count = max(0, user_cube_count - 1)
        frag_gain = 1
        user.cube_fragments = (getattr(user, "cube_fragments", 0) or 0) + 1
        cost_desc = "큐브 1개 소모"

    # Special Snipe Scroll Verification
    target_label = None
    target_codes = None
    used_snipe = False
    used_special_snipe = False

    if special_snipe_code:
        u_specials = get_user_special_snipe_scrolls(user)
        if u_specials.get(special_snipe_code, 0) <= 0:
            return False, f"⚠️ [{special_snipe_code}] 전용 저격주문서를 보유하고 있지 않습니다! (보유: 0장)", None
        opt_info = POTENTIAL_OPTIONS.get(special_snipe_code)
        if not opt_info:
            return False, f"⚠️ 알 수 없는 잠재 옵션 코드입니다: {special_snipe_code}", None
        consume_user_special_snipe_scroll(user, special_snipe_code)
        target_codes = [special_snipe_code]
        target_label = f"[{opt_info['name']}] 전용 저격(1줄 88%!)"
        used_snipe = True
        used_special_snipe = True
    else:
        # Generic Snipe scroll verification
        if not use_snipe and not target_keyword and getattr(user, "arm_snipe", False):
            if (getattr(user, "snipe_scroll_count", 0) or 0) > 0:
                use_snipe = True

        if target_keyword or use_snipe:
            snipe_stock = getattr(user, "snipe_scroll_count", 0) or 0
            if snipe_stock <= 0:
                return False, "⚠️ [잠재저격주문서]를 보유하고 있지 않습니다! (보유: 0장 | 신비상인 또는 !거래소에서 구매 가능)", None

            if target_keyword:
                clean_kw = target_keyword.strip().lower()
                if clean_kw in ["목록", "리스트", "가이드", "도감", "설명", "options", "list", "help", "도움말"]:
                    return True, get_snipe_options_guide_text(), None
                target_label, target_codes = match_potential_target(target_keyword)
                if not target_codes:
                    return False, f"⚠️ 지정한 저격 키워드('{target_keyword}')를 찾을 수 없습니다! (지원: 고블린, 과충전, 쿨초, 크리, 채굴량, 성공률, 할인, 배당, 야수 등 | 전체 목록: !저격목록)", None
            else:
                return False, "⚠️ 저격할 잠재 옵션을 입력해주세요! (예: !주문서 저격 고블린, !큐브 저격 고블린, !큐브 1 저격 과충전 | 전체 옵션 확인: !저격목록)", None

            user.snipe_scroll_count = snipe_stock - 1
            used_snipe = True

    old_tier = curr_tier
    promoted = False
    pity_triggered = False

    if curr_tier == "NONE":
        new_tier = "RARE"
        promoted = True
        target_item.pity_count = 0
    elif curr_tier == "RARE":
        ceiling = CUBE_PITY_CEILINGS["RARE"]
        target_item.pity_count = (target_item.pity_count or 0) + 1
        if target_item.pity_count >= ceiling:
            new_tier = "EPIC"
            promoted = True
            pity_triggered = True
            target_item.pity_count = 0
        else:
            if random.uniform(0, 100) < CUBE_PROMOTION_RATES["RARE"]:
                new_tier = "EPIC"
                promoted = True
                target_item.pity_count = 0
            else:
                new_tier = "RARE"
    elif curr_tier == "EPIC":
        ceiling = CUBE_PITY_CEILINGS["EPIC"]
        target_item.pity_count = (target_item.pity_count or 0) + 1
        if target_item.pity_count >= ceiling:
            new_tier = "UNIQUE"
            promoted = True
            pity_triggered = True
            target_item.pity_count = 0
        else:
            if random.uniform(0, 100) < CUBE_PROMOTION_RATES["EPIC"]:
                new_tier = "UNIQUE"
                promoted = True
                target_item.pity_count = 0
            else:
                new_tier = "EPIC"
    elif curr_tier == "UNIQUE":
        ceiling = CUBE_PITY_CEILINGS["UNIQUE"]
        target_item.pity_count = (target_item.pity_count or 0) + 1
        if target_item.pity_count >= ceiling:
            new_tier = "LEGENDARY"
            promoted = True
            pity_triggered = True
            target_item.pity_count = 0
        else:
            if random.uniform(0, 100) < CUBE_PROMOTION_RATES["UNIQUE"]:
                new_tier = "LEGENDARY"
                promoted = True
                target_item.pity_count = 0
            else:
                new_tier = "UNIQUE"
    else:  # LEGENDARY
        new_tier = "LEGENDARY"
        target_item.pity_count = 0

    target_item.potential_tier = new_tier

    # Existing lines for preservation
    old_l1 = None
    old_l2 = None
    old_l3 = None
    try:
        old_l1 = json.loads(target_item.potential_line_1) if target_item.potential_line_1 else None
    except Exception:
        pass
    try:
        old_l2 = json.loads(target_item.potential_line_2) if target_item.potential_line_2 else None
    except Exception:
        pass
    try:
        old_l3 = json.loads(target_item.potential_line_3) if target_item.potential_line_3 else None
    except Exception:
        pass

    # Roll 3 lines (with snipe target if used)
    r_l1, r_l2, r_l3 = roll_cube_potential(
        new_tier,
        target_codes=target_codes if used_snipe else None,
        line1_snipe_chance=88.0 if used_special_snipe else 35.0,
        is_special_snipe=used_special_snipe
    )

    line1 = old_l1 if (1 in effective_locked and old_l1) else r_l1
    line2 = old_l2 if (2 in effective_locked and old_l2) else r_l2
    line3 = old_l3 if (3 in effective_locked and old_l3) else r_l3

    target_item.potential_line_1 = json.dumps(line1, ensure_ascii=False)
    target_item.potential_line_2 = json.dumps(line2, ensure_ascii=False)
    target_item.potential_line_3 = json.dumps(line3, ensure_ascii=False)

    db.commit()
    db.refresh(user)
    db.refresh(target_item)
    db.refresh(state)

    promo_banner = ""
    if promoted:
        old_disp = CUBE_TIER_DISPLAY.get(old_tier, old_tier)
        new_disp = CUBE_TIER_DISPLAY.get(new_tier, new_tier)
        pity_tag = " (⭐등급 상승 보장 천장 발동!)" if pity_triggered else " (🌟승급 성공!)"
        promo_banner = f"\n🎉🎉 [잠재 등급 상승 대성공!!] [{old_disp} ➔ {new_disp}]{pity_tag}"

    snipe_banner = ""
    if used_snipe and target_label and target_codes:
        hit_target = any(l.get("code") in target_codes for l in [line1, line2, line3])
        rem_scroll_msg = (
            f"(남은 전용저격: {get_user_special_snipe_scrolls(user).get(special_snipe_code, 0)}장)"
            if used_special_snipe else
            f"(남은 저격주문서: {user.snipe_scroll_count}장)"
        )
        if hit_target:
            star_fx = "🎯🌟✨ [특수 전용 저격(88%) 대성공!]" if used_special_snipe else "🎯✨ [잠재 저격 주문서 발동!]"
            snipe_banner = f"\n{star_fx} [{target_label}] 저격 유도 적중! {rem_scroll_msg}"
        else:
            snipe_banner = f"\n🎯💨 [잠재 저격 유도 빗나감] 다음 기회에... {rem_scroll_msg}"

    if new_tier in CUBE_PITY_CEILINGS:
        ceil_val = CUBE_PITY_CEILINGS[new_tier]
        pity_info = f"• 등급 상승 보장 천장: {target_item.pity_count}/{ceil_val}회"
    else:
        pity_info = "• 🌟 최고 등급(레전드리) 도달 완료! (종결 옵션 3줄을 노려보세요)"

    cube_tag = "🔮🌟 [특수전용저격 미라클 큐브 사용]" if used_special_snipe else ("🔮🎯 [잠재저격 미라클 큐브 사용]" if used_snipe else "🔮✨ [미라클 큐브 사용]")
    l1_tag = " 🔒[잠금유지]" if (1 in effective_locked) else ""
    l2_tag = " 🔒[잠금유지]" if (2 in effective_locked) else ""
    l3_tag = " 🔒[잠금유지]" if (3 in effective_locked) else ""

    lock_summary = f" [🔒라인 {len(effective_locked)}줄 잠금 적용]" if effective_locked else ""
    reply = (
        f"{cube_tag} {user.username}님이 [장비 #{target_item.id} {target_item.name}]에 큐브를 사용했습니다!{lock_summary} "
        f"({cost_desc}){promo_banner}{snipe_banner}\n"
        f"📋 [잠재 등급: {CUBE_TIER_DISPLAY.get(new_tier, new_tier)}]\n"
        f"  • 줄 1: {line1['text']}{l1_tag}\n"
        f"  • 줄 2: {line2['text']}{l2_tag}\n"
        f"  • 줄 3: {line3['text']}{l3_tag}\n"
        f"{pity_info}\n"
        f"🧩 큐브 조각: {user.cube_fragments}개 (+{frag_gain}개 적립 | !큐브조각 환급) | 📦 보유 큐브: {user.cube_count:,}개"
    )

    details = {
        "user_id": user.id,
        "username": user.username,
        "equipment_id": target_item.id,
        "equipment_name": target_item.name,
        "old_tier": old_tier,
        "new_tier": new_tier,
        "promoted": promoted,
        "pity_triggered": pity_triggered,
        "pity_count": target_item.pity_count,
        "cube_cost": CUBE_COST,
        "cube_count": user.cube_count,
        "cube_fragments": user.cube_fragments,
        "locked_lines": list(effective_locked),
        "lines": [line1, line2, line3],
        "used_snipe": used_snipe,
        "used_special_snipe": used_special_snipe,
        "special_snipe_code": special_snipe_code,
        "remaining_points": user.points,
        "treasury_pool": state.treasury_pool
    }
    return True, reply, details

def execute_cube_fragment_exchange(
    db: Session,
    user_id: str,
    username: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Exchange 10 Cube Fragments for 15,000P refund (MapleStory Cube Fragment homage).
    """
    user = get_or_create_user(db, user_id, username)
    frags = getattr(user, "cube_fragments", 0) or 0
    sets = frags // CUBE_FRAGMENT_EXCHANGE_COST
    if sets <= 0:
        return False, (
            f"⚠️ 보유하신 큐브 조각이 부족합니다! (보유: {frags}개 / 필요: {CUBE_FRAGMENT_EXCHANGE_COST}개)\n"
            f"💡 큐브를 1회 돌릴 때마다 큐브 조각 1개를 획득합니다. (!큐브)"
        ), None

    used_frags = sets * CUBE_FRAGMENT_EXCHANGE_COST
    total_reward = sets * CUBE_FRAGMENT_EXCHANGE_REWARD

    user.cube_fragments = frags - used_frags
    user.points += total_reward

    db.commit()
    db.refresh(user)

    set_msg = f"{sets}세트({used_frags}개)" if sets > 1 else f"{CUBE_FRAGMENT_EXCHANGE_COST}개"
    reply = (
        f"🧩✨ [큐브 조각 교환 완료] {user.username}님이 큐브 조각 {set_msg}를 일괄 교환 완료하여 "
        f"+{total_reward:,}P를 페이백 환급받았습니다! "
        f"(남은 큐브 조각: {user.cube_fragments}개 | 현재 보유 포인트: {user.points:,}P)"
    )
    details = {
        "user_id": user.id,
        "username": user.username,
        "sets": sets,
        "exchanged_fragments": used_frags,
        "reward_points": total_reward,
        "remaining_fragments": user.cube_fragments,
        "remaining_points": user.points
    }
    return True, reply, details


def execute_equipment_cube_lock(
    db: Session,
    user_id: str,
    username: str,
    item_id_or_index: Optional[str] = None,
    state_str: Optional[str] = None
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Execute !큐브잠금 [장비번호/장비명] [on/off] (Lock equipment against cube potential resets).
    Protects valuable equipment from accidental cube rolls.
    """
    user = get_or_create_user(db, user_id, username)

    target_state = None
    target_eq_arg = item_id_or_index

    if item_id_or_index:
        clean_arg = str(item_id_or_index).lower().strip()
        if clean_arg in ["on", "1", "true", "켜기", "잠금", "잠그기", "설정"]:
            target_state = True
            target_eq_arg = None
        elif clean_arg in ["off", "0", "false", "끄기", "해제", "풀기", "해제하기"]:
            target_state = False
            target_eq_arg = None

    if state_str:
        clean_state = str(state_str).lower().strip()
        if clean_state in ["on", "1", "true", "켜기", "잠금", "잠그기", "설정"]:
            target_state = True
        elif clean_state in ["off", "0", "false", "끄기", "해제", "풀기", "해제하기"]:
            target_state = False

    target_item = find_user_equipment(db, user, target_eq_arg)
    if not target_item:
        return False, f"⚠️ 지정한 장비('{target_eq_arg or '장착장비'}')를 보유하고 있지 않습니다! (내 장비 확인: !내장비, !인벤토리)", None

    active_listing = db.query(EquipmentListing).filter_by(equipment_id=target_item.id, status="ACTIVE").first()
    if active_listing:
        return False, f"⚠️ [장비 #{target_item.id}]은(는) 현재 거래소/직거래에 판매 등록 중입니다! 거래 취소 후 설정해주세요.", None

    if target_state is None:
        target_item.is_cube_locked = not bool(target_item.is_cube_locked)
    else:
        target_item.is_cube_locked = bool(target_state)

    db.commit()
    db.refresh(target_item)

    if target_item.is_cube_locked:
        reply = (
            f"🔒 [장비 #{target_item.id} {target_item.name}]의 큐브 잠금(보호)이 활성화되었습니다!\n"
            f"앞으로 실수로 !큐브, !주문서 저격 사용이 차단됩니다. (잠금 해제: '!큐브잠금 {target_item.id}' 또는 '!큐브해제')"
        )
    else:
        reply = (
            f"🔓 [장비 #{target_item.id} {target_item.name}]의 큐브 잠금이 해제되었습니다!\n"
            f"이제 !큐브 및 !주문서 저격을 정상적으로 사용할 수 있습니다."
        )

    details = {
        "user_id": user.id,
        "username": user.username,
        "equipment_id": target_item.id,
        "equipment_name": target_item.name,
        "is_cube_locked": target_item.is_cube_locked
    }
    return True, reply, details


def execute_potential_line_lock(
    db: Session,
    user_id: str,
    username: str,
    line_arg: Optional[str] = None,
    state_str: Optional[str] = None,
    item_id_or_index: Optional[str] = None
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Execute !옵션잠금 [1~3] [on/off] (Lock individual potential lines during cube rerolls).
    Rolling with locked lines costs 20x the cube price (300,000P or 20 cubes).
    """
    user = get_or_create_user(db, user_id, username)
    target_item = find_user_equipment(db, user, item_id_or_index)
    if not target_item:
        return False, f"⚠️ 지정한 장비('{item_id_or_index or '장착장비'}')를 보유하고 있지 않습니다! (내 장비 확인: !내장비, !인벤토리)", None

    curr_tier = (target_item.potential_tier or "NONE").upper()
    if curr_tier == "NONE" or not target_item.potential_line_1:
        return False, "⚠️ 잠재능력이 개방되지 않은 장비(일반)는 라인을 잠글 수 없습니다! 먼저 큐브를 돌려 잠재를 개방해주세요.", None

    def _get_line_desc(line_raw, fallback):
        if not line_raw:
            return fallback
        try:
            d = json.loads(line_raw) if isinstance(line_raw, str) else line_raw
            return d.get("text") or d.get("name") or fallback
        except Exception:
            return str(line_raw)

    l1_desc = _get_line_desc(target_item.potential_line_1, "1번줄 잠재")
    l2_desc = _get_line_desc(target_item.potential_line_2, "2번줄 잠재")
    l3_desc = _get_line_desc(target_item.potential_line_3, "3번줄 잠재")

    clean_arg = str(line_arg or "").strip().lower()

    # If no argument or query status
    if not clean_arg or clean_arg in ["상태", "현황", "보기", "조회", "status", "info"]:
        l1_tag = "🔒 [잠금]" if target_item.is_line1_locked else "🔓 [해제]"
        l2_tag = "🔒 [잠금]" if target_item.is_line2_locked else "🔓 [해제]"
        l3_tag = "🔒 [잠금]" if target_item.is_line3_locked else "🔓 [해제]"
        locked_cnt = sum([target_item.is_line1_locked, target_item.is_line2_locked, target_item.is_line3_locked])
        cost_tip = "현 가격의 20배(300,000P 또는 큐브 20개)" if locked_cnt > 0 else "기본 큐브 1개(15,000P)"
        return True, (
            f"🔮📋 [장비 #{target_item.id} {target_item.name}] 잠재 옵션 라인 잠금 현황:\n"
            f"  • 줄 1: {l1_desc} {l1_tag}\n"
            f"  • 줄 2: {l2_desc} {l2_tag}\n"
            f"  • 줄 3: {l3_desc} {l3_tag}\n"
            f"💰 다음 큐브 소모: {cost_tip} (현재 잠긴 줄: {locked_cnt}줄)\n"
            f"💡 사용법: !옵션잠금 [1~3] (토글) | 전체해제: !옵션잠금 해제"
        ), {
            "equipment_id": target_item.id,
            "line1_locked": target_item.is_line1_locked,
            "line2_locked": target_item.is_line2_locked,
            "line3_locked": target_item.is_line3_locked
        }

    # Unlock all lines
    if clean_arg in ["전체해제", "해제", "초기화", "off", "alloff", "clear", "풀기"]:
        target_item.is_line1_locked = False
        target_item.is_line2_locked = False
        target_item.is_line3_locked = False
        db.commit()
        return True, (
            f"🔓✨ [장비 #{target_item.id} {target_item.name}]의 모든 잠재 옵션 라인 잠금이 해제되었습니다!\n"
            f"이제 일반 큐브 비용(1개당 15,000P)으로 3줄 전체 재설정됩니다."
        ), {
            "equipment_id": target_item.id,
            "line1_locked": False,
            "line2_locked": False,
            "line3_locked": False
        }

    # Parse target lines
    target_lines = []
    for c in ["1", "2", "3"]:
        if c in clean_arg:
            target_lines.append(int(c))
    if state_str:
        clean_s = str(state_str).strip().lower()
        for c in ["1", "2", "3"]:
            if c in clean_s:
                target_lines.append(int(c))
    target_lines = sorted(list(set(target_lines)))

    if not target_lines:
        return False, "⚠️ 잠글 라인 번호(1~3)를 입력해주세요! (예: !옵션잠금 1, !옵션잠금 해제)", None

    if len(target_lines) > 1:
        return False, "⚠️ 잠재 옵션 라인 잠금은 최대 1줄까지만 가능합니다! (한 번에 1개의 줄만 지정해주세요)", None

    target_line = target_lines[0]

    explicit_state = None
    if state_str:
        clean_s = str(state_str).strip().lower()
        if clean_s in ["on", "1", "true", "잠금", "설정"]:
            explicit_state = True
        elif clean_s in ["off", "0", "false", "해제", "풀기"]:
            explicit_state = False

    curr_val = getattr(target_item, f"is_line{target_line}_locked", False)
    new_val = explicit_state if explicit_state is not None else not curr_val

    switched = False
    other_locked = [i for i in [1, 2, 3] if i != target_line and getattr(target_item, f"is_line{i}_locked", False)]
    if new_val:
        if other_locked:
            switched = True
        # Enforce maximum 1 line locked: clear other lines and set target_line
        target_item.is_line1_locked = (target_line == 1)
        target_item.is_line2_locked = (target_line == 2)
        target_item.is_line3_locked = (target_line == 3)
    else:
        setattr(target_item, f"is_line{target_line}_locked", False)

    db.commit()
    db.refresh(target_item)

    l1_tag = "🔒 [잠금]" if target_item.is_line1_locked else "🔓 [해제]"
    l2_tag = "🔒 [잠금]" if target_item.is_line2_locked else "🔓 [해제]"
    l3_tag = "🔒 [잠금]" if target_item.is_line3_locked else "🔓 [해제]"
    locked_cnt = sum([target_item.is_line1_locked, target_item.is_line2_locked, target_item.is_line3_locked])
    cost_tip = "현 가격의 20배(300,000P 또는 큐브 20개)" if locked_cnt > 0 else "기본 큐브 1개(15,000P)"

    if switched:
        action_note = f" (기존 {other_locked[0]}번줄 해제 ➔ {target_line}번줄 잠금 전환)"
    elif new_val:
        action_note = f" ({target_line}번줄 잠금)"
    else:
        action_note = f" ({target_line}번줄 잠금 해제)"

    if new_val:
        reply = (
            f"🔮🔒 [장비 #{target_item.id} {target_item.name}] 잠재 옵션 라인 잠금 설정 완료!{action_note}\n"
            f"  • 줄 1: {l1_desc} {l1_tag}\n"
            f"  • 줄 2: {l2_desc} {l2_tag}\n"
            f"  • 줄 3: {l3_desc} {l3_tag}\n"
            f"💰 다음 큐브 소모: {cost_tip} (최대 1줄 잠금 가능)\n"
            f"💡 라인 잠금 해제: !옵션잠금 해제"
        )
    else:
        reply = (
            f"🔓✨ [장비 #{target_item.id} {target_item.name}] 줄 {target_line}번 잠금이 해제되었습니다!\n"
            f"  • 줄 1: {l1_desc} {l1_tag}\n"
            f"  • 줄 2: {l2_desc} {l2_tag}\n"
            f"  • 줄 3: {l3_desc} {l3_tag}\n"
            f"💰 다음 큐브 소모: {cost_tip}\n"
            f"💡 다른 줄 잠금: !옵션잠금 [1~3]"
        )
    details = {
        "equipment_id": target_item.id,
        "line1_locked": target_item.is_line1_locked,
        "line2_locked": target_item.is_line2_locked,
        "line3_locked": target_item.is_line3_locked,
        "locked_count": locked_cnt
    }
    return True, reply, details


def get_unified_market_listings(db: Session, target_user_id: Optional[str] = None) -> str:
    """Returns active marketplace listings for both equipment and consumable items."""
    eq_query = db.query(EquipmentListing).filter_by(status="ACTIVE").order_by(EquipmentListing.id.desc()).limit(10).all()
    it_query = db.query(ItemListing).filter_by(status="ACTIVE").order_by(ItemListing.id.desc()).limit(10).all()

    if not eq_query and not it_query:
        return (
            "🏪 [나베 통합 거래소 (거래 수수료 5% 국고 환원)]\n"
            "현재 거래소에 등록된 판매 매물이 없습니다!\n"
            "💡 아이템 판매: !아이템판매 [파방/하강/상승/큐브] [수량] [가격]\n"
            "💡 장비 판매: !장비등록 [내장비번호] [가격] | 1:1 직거래: !장비판매 [유저] [내장비번호] [가격]"
        )

    lines = ["🏪 [나베 통합 거래소 매물 목록 (수수료 5% 국고 환원)]"]
    if eq_query:
        lines.append("📦 [장비 매물]")
        for l in eq_query:
            eq = l.equipment
            eq_name = eq.name if eq else "곡괭이"
            star = eq.starforce if eq else 0
            info = get_pickaxe_info(star)
            target_tag = f"🔒 [{l.buyer_name} 전용]" if l.buyer_name else "🌐 [공개]"
            pot_tag = ""
            if eq and eq.potential_tier and eq.potential_tier != "NONE":
                pot_tag = f" [{CUBE_TIER_DISPLAY.get(eq.potential_tier, eq.potential_tier)}]"
            lines.append(
                f"• [거래 #E{l.id}] {target_tag} 판매자: {l.seller_name} | {eq_name}{pot_tag} (★{star}성, {info['yield_multiplier']}배) | "
                f"가격: {l.price:,}P 👉 구매: !거래소구매 E{l.id}"
            )

    if it_query:
        lines.append("💎 [소비/주문서 아이템 매물]")
        for l in it_query:
            target_tag = f"🔒 [{l.buyer_name} 전용]" if l.buyer_name else "🌐 [공개]"
            per_price = l.price // l.quantity if l.quantity > 0 else l.price
            lines.append(
                f"• [거래 #I{l.id}] {target_tag} 판매자: {l.seller_name} | {l.item_name} x{l.quantity}개 | "
                f"총 {l.price:,}P (개당 {per_price:,}P) 👉 구매: !거래소구매 I{l.id}"
            )

    lines.append("💡 판매: `!아이템판매 [파방/하강/상승/큐브] [수량] [가격]` | `!장비등록 [장비번호] [가격]`")
    lines.append("💡 구매: `!거래소구매 [거래번호]` (예: !거래소구매 I1, !거래소구매 E1) | 취소: `!거래소취소 [거래번호]`")
    return "\n".join(lines)


def get_equipment_market_listings(db: Session, target_user_id: Optional[str] = None) -> str:
    """Returns active marketplace listings."""
    query = db.query(EquipmentListing).filter_by(status="ACTIVE").order_by(EquipmentListing.id.desc())
    listings = query.limit(10).all()

    if not listings:
        return (
            "🏪 [나베 장비 거래소 (수수료 5% 국고 환원)]\n"
            "현재 등록된 판매 매물이 없습니다!\n"
            "💡 내 장비 판매 등록: !장비등록 [장비번호] [가격] | 1:1 직거래: !장비판매 [유저] [장비번호] [가격]"
        )

    lines = ["🏪 [나베 장비 거래소 매물 목록 (수수료 5% 국고 환원)]"]
    for l in listings:
        eq = l.equipment
        eq_name = eq.name if eq else "곡괭이"
        star = eq.starforce if eq else 0
        info = get_pickaxe_info(star)
        target_tag = f"🔒 [{l.buyer_name} 전용]" if l.buyer_name else "🌐 [공개]"
        pot_tag = ""
        if eq and eq.potential_tier and eq.potential_tier != "NONE":
            pot_tag = f" [{CUBE_TIER_DISPLAY.get(eq.potential_tier, eq.potential_tier)}]"
        lines.append(
            f"• [거래 #{l.id}] {target_tag} 판매자: {l.seller_name} | {eq_name}{pot_tag} (★{star}성, {info['yield_multiplier']}배) | "
            f"가격: {l.price:,}P (수수료: {l.tax_fee:,}P) 👉 구매: !장비구매 {l.id}"
        )
    lines.append("💡 명령어: !장비구매 [거래번호] | !장비등록 [내장비번호] [가격] | !장비회수 [거래번호]")
    return "\n".join(lines)

def get_user_inventory_status(db: Session, user_id: str, username: str) -> str:
    """Returns full inventory of equipments for a user."""
    user = get_or_create_user(db, user_id, username)
    items = ensure_user_equipment(db, user)
    sf_state = get_starforce_event_state(db)

    active_listing_map = {
        l.equipment_id: l.id for l in
        db.query(EquipmentListing).filter(EquipmentListing.seller_id == user.id, EquipmentListing.status == "ACTIVE").all()
    }

    lines = [f"🎒 [내 장비 인벤토리] {user.username}님의 보유 장비 ({len(items)}개):"]
    if sf_state.get("is_active"):
        rem_m, rem_s = divmod(sf_state["remaining_sec"], 60)
        lines.append(f"🔥 [피버 진행중: {sf_state['title']} ({rem_m}분 {rem_s}초 남음)]")

    for idx, it in enumerate(items, start=1):
        info = get_pickaxe_info(it.starforce, event_state=sf_state)
        bp_str = f" +{info['bonus_points']:,}P" if info.get("bonus_points", 0) > 0 else ""
        tags = []
        if it.is_equipped:
            tags.append("🟢장착중")
        else:
            tags.append("📦보관")
        if it.id in active_listing_map:
            tags.append(f"🏷️거래#{active_listing_map[it.id]}판매중")
        if getattr(it, "is_cube_locked", False):
            tags.append("🔒큐브잠금")
        tag_str = "[" + "/".join(tags) + "]"

        pot_badge = ""
        if it.potential_tier and it.potential_tier != "NONE":
            pot_badge = f" [{CUBE_TIER_DISPLAY.get(it.potential_tier, it.potential_tier)}]"

        if it.starforce >= 25:
            next_str = "MAX"
        else:
            cost_label = f"{info['upgrade_cost']:,}P"
            if info.get("is_discounted"):
                cost_label += " (30%할인)"
            if info.get("is_guaranteed_100"):
                cost_label += " (100%확정)"
            next_str = f"다음강화 {cost_label}"

        lines.append(
            f"• #{it.id} {tag_str} {it.name}{pot_badge} | 채굴 {info['yield_multiplier']}배{bp_str}, 크리+{info['crit_bonus']}%, 쿨{info['cooldown_minutes']}분 ({next_str})"
        )
        if it.potential_tier and it.potential_tier != "NONE":
            sub_pot_lines = []
            for ln_idx, raw in enumerate([it.potential_line_1, it.potential_line_2, it.potential_line_3], start=1):
                if raw:
                    try:
                        p_data = json.loads(raw) if isinstance(raw, str) else raw
                        p_name = p_data.get("name") or p_data.get("text", "")
                        p_val = p_data.get("val")
                        p_unit = p_data.get("unit", "")
                        p_icon = p_data.get("icon", "")
                        lock_ico = "🔒" if getattr(it, f"is_line{ln_idx}_locked", False) else ""
                        sub_pot_lines.append(f"{lock_ico}{p_icon}{p_name}({p_val}{p_unit})")
                    except Exception:
                        sub_pot_lines.append(str(raw)[:20])
            if sub_pot_lines:
                lines.append(f"  └ 🔮 [잠재] {' | '.join(sub_pot_lines)}")
        else:
            lines.append("  └ 🔮 [잠재: 없음] (!큐브 로 개방 가능)")

    cube_cnt = getattr(user, "cube_count", 0) or 0
    frag_cnt = getattr(user, "cube_fragments", 0) or 0
    s_cnt = getattr(user, "shield_scroll_count", 0) or 0
    b_cnt = getattr(user, "boost_scroll_count", 0) or 0
    d_cnt = getattr(user, "downgrade_scroll_count", 0) or 0
    snipe_cnt = getattr(user, "snipe_scroll_count", 0) or 0
    lines.append(
        f"📦 [소비 인벤토리] 🔮 큐브: {cube_cnt:,}개 | 🧩 조각: {frag_cnt:,}개 | 🛡️ 파방: {s_cnt:,}장 | ⚡ 상승: {b_cnt:,}장 | 📉 하강: {d_cnt:,}장 | 🎯 저격: {snipe_cnt:,}장 (!아이템)"
    )
    special_scrolls = get_user_special_snipe_scrolls(user)
    if special_scrolls:
        special_names = {
            "DIVIDEND_BOOST_PCT": "📈배당",
            "MINING_CD_RESET": "⚡쿨초",
            "STARFORCE_SUCCESS_BOOST": "⭐성공",
            "GOBLIN_JACKPOT_CHANCE": "👹고블린",
            "MINING_YIELD_BOOST": "⛏️채굴량",
            "MINING_BONUS_CASH": "🪙현금",
            "MAHJONG_TILE_BOOST": "🀄마작",
            "HEAVY_MINING": "🌋과충전",
            "STARFORCE_DISCOUNT": "🔨할인",
        }
        sp_parts = [f"{special_names.get(k, k)}:{v:,}장" for k, v in special_scrolls.items()]
        lines.append(f"🌟 [전용 저격주문서 (88%확정)] {' | '.join(sp_parts)} (!주문서 전용 [옵션])")
    lines.append(
        "💡 명령어 안내:\n"
        "• 상세 스펙 확인: !곡괭이 [번호] (예: !곡괭이 1, !곡괭이 2)\n"
        "• 장비 교체: !장착 [장비번호]\n"
        "• 큐브 잠금(보호): !큐브잠금 [장비번호] | 라인 잠금(20배): !옵션잠금 [1~3] (전체해제: !옵션잠금 해제)\n"
        "• 큐브 사용: !큐브 [장비번호] [저격 옵션] (예: !큐브 1, !큐브 저격 고블린)\n"
        "• 소비 아이템 확인: !아이템 (상인구매: !상인구매 [1/2/3/4] [수량] | 거래소: !거래소)\n"
        "• 선택 강화: !강화 [장비번호] [파방/하강/상승/풀]\n"
        "• 새 곡괭이 구매: !곡괭이구매 [0/5/10]\n"
        "• 피버 확인: !피버 | 거래소: !거래소, !아이템판매"
    )
    return "\n".join(lines)

def get_user_pickaxe_status(
    db: Session,
    user_id: str,
    username: str,
    item_id_or_index: Optional[str] = None,
    force_detail: bool = False
) -> str:
    """Returns detailed pickaxe status / RPG spec window or inventory for a user."""
    user = get_or_create_user(db, user_id, username)
    items = ensure_user_equipment(db, user)

    # If specific item requested, find it
    if item_id_or_index:
        target = find_user_equipment(db, user, item_id_or_index)
        if not target:
            return f"⚠️ 지정한 장비('{item_id_or_index}')를 보유하고 있지 않습니다! (내 장비 확인: !내장비, !인벤토리)"
        equipped = target
    elif force_detail or len(items) <= 1:
        # Show currently equipped item in full detail
        equipped = get_user_equipped_item(db, user) or items[0]
    else:
        # Multiple equipments and no specific item requested -> show inventory list
        return get_user_inventory_status(db, user_id, username)

    curr_lvl = equipped.starforce if equipped else 0
    curr_lvl = max(0, min(30, int(curr_lvl)))
    sf_state = get_starforce_event_state(db)
    item = get_pickaxe_info(curr_lvl, event_state=sf_state)
    bp = item.get("bonus_points", 0)
    bp_str = f" | 매 채굴 확정: +{bp:,}P" if bp > 0 else ""

    fever_banner = ""
    if sf_state.get("is_active"):
        rem_m, rem_s = divmod(sf_state["remaining_sec"], 60)
        fever_banner = f"🔥 [피버 진행중: {sf_state['title']} ({rem_m}분 {rem_s}초 남음)]\n"

    pot_tier = (equipped.potential_tier or "NONE").upper() if equipped else "NONE"
    if pot_tier != "NONE":
        ceiling = CUBE_PITY_CEILINGS.get(pot_tier, 0)
        pity_str = f" | 천장: {equipped.pity_count}/{ceiling}회" if ceiling > 0 else " | 🌟최고 등급"
        pot_lines = []
        for i, line_raw in enumerate([equipped.potential_line_1, equipped.potential_line_2, equipped.potential_line_3], start=1):
            if line_raw:
                try:
                    data = json.loads(line_raw) if isinstance(line_raw, str) else line_raw
                    line_text = data.get('text', '')
                    code = data.get('code')
                    val = data.get('val')
                    if code == "STARFORCE_SUCCESS_BOOST" and "& 실패" not in line_text and val:
                        line_text = f"⭐ 강화 성공률 증가 & 실패율 감소 (성공 +{float(val):.1f}% / 실패 -{float(val):.1f}%)"
                    elif code == "STARFORCE_SAFEGUARD" and "15성" not in line_text and val:
                        line_text = f"🛡️ 15성+ 파괴 방지 (15성 이상 강화 실패 시 {float(val):.0f}% 확률 파괴 방어)"
                    elif code == "LEVERAGE_20X_UNLOCK":
                        line_text = "🦁 야수의 심장 (1줄: 20배, 2줄: 40배, 3줄: 60배 해금)"
                    lock_tag = " 🔒[잠금]" if getattr(equipped, f"is_line{i}_locked", False) else ""
                    pot_lines.append(f"  • 줄 {i}: {line_text}{lock_tag}")
                except Exception:
                    lock_tag = " 🔒[잠금]" if getattr(equipped, f"is_line{i}_locked", False) else ""
                    pot_lines.append(f"  • 줄 {i}: {line_raw}{lock_tag}")
        pot_block = f"\n🔮 [잠재능력: {CUBE_TIER_DISPLAY.get(pot_tier, pot_tier)}{pity_str}]\n" + "\n".join(pot_lines)
    else:
        pot_block = "\n🔮 [잠재능력: 없음] (!큐브구매 후 !큐브 로 3줄 잠재 개방 가능!)"

    cube_cnt = getattr(user, "cube_count", 0) or 0
    frag_cnt = getattr(user, "cube_fragments", 0) or 0
    frag_str = (
        f"\n📦 보유 큐브: {cube_cnt:,}개 (!큐브 로 사용 | 구매: !큐브구매 [수량])\n"
        f"🧩 큐브 조각: {frag_cnt:,}개 (!큐브조각 으로 10개당 15,000P 환급)"
    )

    other_items_note = f"\n🎒 다른 보유 장비: 총 {len(items)}개 (!내장비 로 전체 목록 확인)" if len(items) > 1 else ""

    pot_effects = get_equipment_potential_effects(equipped)
    pot_cd_red = pot_effects.get("mining_cd_reduction", 0)
    eff_cd = max(2, item['cooldown_minutes'] - pot_cd_red)
    cd_info = f"{eff_cd}분" if pot_cd_red == 0 else f"{eff_cd}분(⚡잠재 -{pot_cd_red}분)"
    cube_lock_tag = " 🔒[큐브잠금]" if getattr(equipped, "is_cube_locked", False) else ""

    if curr_lvl >= 30:
        return (
            f"{fever_banner}⛏️📋 [상태창 / 내 곡괭이 정보] {user.username}님의 장비: [장비 #{equipped.id} {item['name']}]{cube_lock_tag}\n"
            f"• 효과: 채굴량 {item['yield_multiplier']}배{bp_str} | 크리티컬 보너스: +{item['crit_bonus']}% | 쿨타임: {cd_info}\n"
            f"👑✨ 메이플 30성 신화 종결 곡괭이를 달성한 전설의 광부입니다! (채굴 300배 + 확정 500만P + 크리티컬 300% 종결){pot_block}{frag_str}{other_items_note}\n"
            f"💡 명령어: !강화 [장비번호], !큐브 [장비번호], !큐브잠금, !옵션잠금 [1~3], !내장비, !장비장터"
        )
    else:
        next_item = get_pickaxe_info(curr_lvl + 1, event_state=sf_state)
        cost = item["upgrade_cost"]
        pot_sf_disc = min(50.0, float(pot_effects.get("starforce_discount_pct", 0.0)))
        if pot_sf_disc > 0:
            cost = max(100, int(round(cost * (1.0 - pot_sf_disc / 100.0))))
        cost_str = f"{cost:,}P"
        if item.get("is_discounted"):
            cost_str += f" (🔥30% 할인! 기존: {item['base_cost']:,}P)"
        elif pot_sf_disc > 0:
            cost_str += f" (🔨잠재 {int(pot_sf_disc)}% 할인)"

        s_rate = item["success_rate"]
        m_rate = item["maintain_rate"]
        d_rate = item["drop_rate"]
        dest_rate = item["destroy_rate"]

        d_red = 0.0
        m_red = 0.0
        pot_sb = min(20.0, float(pot_effects.get("starforce_success_boost", 0.0)))
        if pot_sb > 0 and s_rate < 100.0:
            boost = min(pot_sb, 99.0 - s_rate)
            s_rate += boost
            if d_rate >= boost:
                d_rate -= boost
                d_red = boost
            else:
                d_red = d_rate
                rem = boost - d_rate
                d_rate = 0.0
                m_rate = max(0.0, m_rate - rem)
                m_red = rem

        def _fmt_pct(val: float) -> str:
            v_round = round(val, 3)
            if v_round % 1 == 0:
                return f"{int(v_round)}%"
            elif round(v_round, 2) == v_round:
                return f"{v_round:.2f}%"
            else:
                return f"{v_round:.3f}%"

        s_val_str = _fmt_pct(s_rate)
        if pot_sb > 0 and s_rate < 100.0:
            s_tag = f"성공 {s_val_str}(⭐+{boost:.1f}%)"
        else:
            s_tag = f"성공 {s_val_str}"

        rate_parts = [s_tag]
        if item.get("is_guaranteed_100"):
            rate_parts[0] = "⭐성공 100% (피버 확정!)"

        if m_rate > 0:
            m_val_str = _fmt_pct(m_rate)
            if m_red > 0:
                rate_parts.append(f"유지 {m_val_str}(🔻-{m_red:.1f}%)")
            else:
                rate_parts.append(f"유지 {m_val_str}")

        if d_rate > 0:
            d_val_str = _fmt_pct(d_rate)
            if d_red > 0:
                rate_parts.append(f"하락 {d_val_str}(🔻-{d_red:.1f}%)")
            else:
                rate_parts.append(f"하락 {d_val_str}")

        safeguard_pct = min(90.0, float(pot_effects.get("safeguard_pct", 0.0)))
        if dest_rate > 0:
            dest_val_str = _fmt_pct(dest_rate)
            if safeguard_pct > 0:
                eff_dest = dest_rate * (1.0 - safeguard_pct / 100.0)
                rate_parts.append(f"💥파괴 {dest_val_str}(🛡️방어 {int(safeguard_pct)}% / 실질 {_fmt_pct(eff_dest)})")
            else:
                rate_parts.append(f"💥파괴 {dest_val_str}")

        rate_str = " | ".join(rate_parts)

        if item.get("is_guaranteed_100"):
            destroy_warning = " (⭐피버 이벤트: 파괴/하락 0% 확정 성공!)"
        elif dest_rate > 0:
            if safeguard_pct > 0:
                destroy_warning = f"\n  ⚠️ 15성 이상: 파괴 위험 존재 (🛡️잠재 세이프가드 {int(safeguard_pct)}% 발동 시 파괴 방어 & 1성 하락 보호!)"
            else:
                destroy_warning = "\n  ⚠️ 15성 이상: 파괴(터짐) 위험 존재! (파괴 시 12성 복원)"
        else:
            destroy_warning = " (15성 미만: 절대 안 터짐!)"

        return (
            f"{fever_banner}⛏️📋 [상태창 / 내 곡괭이 정보] {user.username}님의 장비: [장비 #{equipped.id} {item['name']}]{cube_lock_tag}\n"
            f"• 현재 효과: 채굴량 {item['yield_multiplier']}배{bp_str} | 크리 보너스 +{item['crit_bonus']}% | 쿨타임: {cd_info}\n"
            f"• 다음 강화: ★{curr_lvl + 1}성 도전 [비용: {cost_str}]\n"
            f"  └ 확률: {rate_str}{destroy_warning}\n"
            f"  └ 다음 효과: {next_item['desc']}{pot_block}{frag_str}{other_items_note}\n"
            f"💡 명령어: !강화 [장비번호], !큐브 [장비번호], !큐브잠금 [장비번호], !옵션잠금 [1~3], !내장비, !장비장터"
        )

def get_pickaxe_table_guide() -> str:
    """Returns concise pickaxe tiers & Star Force rate guide (30성 확장 & 실패 하락 전면 삭제)."""
    return (
        "⛏️📋 [메이플 스타일 스타포스 강화표 (★30성 종결)] (!강화로 업그레이드)\n"
        "• 0~14성: 파괴 0%! 실패 시 하락 없이 100% 등급 유지 (10성: 채굴 3배 | 15성: 채굴 6.5배)\n"
        "• 15~16성: 성공 31.5% / 유지 66.4% / 💥파괴 2.055% (파괴 시 12성 흔적 복원, 하락 없음!)\n"
        "• 17~19성: 성공 15.75% / 유지 75~77.5% / 💥파괴 6.74~8.425% (17성 파방 가능!)\n"
        "• 20성: 대박 찬스! 성공 31.5% / 유지 58.2% / 💥파괴 10.275% (채굴 22배 + 28만P)\n"
        "• 21~22성: 성공 15.75% / 유지 67~71.6% / 💥파괴 12.6~16.85% (22성 국민졸업: 채굴 36배 + 50만P)\n"
        "• 23~25성: 고자본 영역! 성공 10.5% / 유지 71.6% / 💥파괴 17.9% (25성: 채굴 80배 + 120만P)\n"
        "• 26~29성: 신화의 영역! 성공 1.05~7.35% / 유지 74~79% / 💥파괴 18.5~19.8%\n"
        "• ★30성 종결 MAX: 👑오리하르콘 곡괭이 (채굴 300배 + 확정 500만P + 크리 300% + 쿨 2분!)\n"
        "* 2025/2026 메이플 룰 적용: 실패 시 단계 하락이 완전히 없으며 등급이 유지됩니다!\n"
        "* 15강까진 절대 안 터집니다 (파괴 확률 0%), 15성 이후 파괴 시 12성(장비의 흔적)으로 복원됩니다.\n"
        "* 🔥 돌발 피버 이벤트: 비용 30% 할인 또는 5/10/15성 100% 확정 성공 발동! (확인: !피버)\n"
        "* 강화비는 성공/실패/파괴 무관 100% 국고 채굴풀로 환원됩니다!"
    )

def execute_borrow(
    db: Session,
    user_id: str,
    username: str,
    amount_str: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Execute !대출 [금액/최대/올인] (Margin Loan from Treasury Pool).
    Allows viewers to borrow according to their personal Credit Tier Limit (최대 50,000,000P).
    """
    state = get_market_state(db)
    user = get_or_create_user(db, user_id, username)
    current_debt = getattr(user, "debt", 0) or 0

    credit_info = get_user_credit_info(user, db=db, market_state=state)
    user_loan_limit = credit_info["loan_limit"]

    if user_loan_limit <= 0:
        return False, f"🚫 {user.username}님은 신용등급({credit_info['tier_name']}) 제한으로 신규 대출이 불가합니다. (한도: 0P, 신용점수: {credit_info['score']}점 | 신용조회: !신용등급)", None

    if current_debt >= user_loan_limit:
        return False, f"⚠️ 이미 {user.username}님의 신용등급({credit_info['tier_name']}) 기준 최대 대출 한도({user_loan_limit:,}P)에 도달하여 추가 대출이 불가합니다. (현재 빚: {current_debt:,}P | 신용조회: !신용등급)", None

    max_possible = user_loan_limit - current_debt

    cleaned = (amount_str or "").strip().lower()
    if cleaned in ["최대", "올인", "max", "all", "전액", "풀대출", "전부"]:
        borrow_amount = min(max_possible, int(state.treasury_pool))
    else:
        try:
            val = int(cleaned.replace(",", "").replace("p", "").replace("원", ""))
            if val <= 0:
                return False, "⚠️ 대출 금액은 1P 이상이어야 합니다.", None
            if val > max_possible:
                return False, f"⚠️ {user.username}님의 신용등급({credit_info['tier_name']}) 기준 최대 대출 한도는 {user_loan_limit:,}P입니다. 추가 대출 가능 한도: {max_possible:,}P (현재 빚: {current_debt:,}P)", None
            borrow_amount = val
        except ValueError:
            return False, "💡 대출 사용법: !대출 [금액/최대] (예: !대출 30000, !대출 최대 | 신용확인: !신용등급)", None

    if borrow_amount <= 0:
        return False, "⚠️ 대출 가능한 금액이 없습니다.", None

    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL

    if state.treasury_pool < borrow_amount:
        return False, f"🏛️ 국고 잔고가 부족하여 대출을 실행할 수 없습니다. (현재 국고 대출 가능액: {int(state.treasury_pool):,}P)", None

    # Execute loan
    state.treasury_pool -= borrow_amount
    user.debt = current_debt + borrow_amount
    user.points += borrow_amount

    db.commit()
    db.refresh(user)
    db.refresh(state)

    reply = (
        f"💳 [국고 마진론 대출] {user.username}님 {borrow_amount:,}P 대출 실행 완료! | "
        f"신용등급: {credit_info['tier_name']} | 보유 현금: {user.points:,}P | 총 채무(빚): {user.debt:,}P "
        f"(경기당 이자: {credit_info['interest_rate_pct']:.1f}% 국고 납부)"
    )
    details = {
        "user_id": user.id,
        "username": user.username,
        "amount": borrow_amount,
        "total_debt": user.debt,
        "cash": user.points,
        "credit_tier": credit_info["tier"],
        "credit_score": credit_info["score"],
        "credit_grade": credit_info["grade"],
        "loan_limit": user_loan_limit,
        "treasury_pool": state.treasury_pool
    }
    return True, reply, details

def execute_repay(
    db: Session,
    user_id: str,
    username: str,
    amount_str: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Execute !상환 [금액/전액/올인] (Repay Margin Loan).
    """
    state = get_market_state(db)
    user = get_or_create_user(db, user_id, username)
    current_debt = getattr(user, "debt", 0) or 0

    if current_debt <= 0:
        return False, f"💡 {user.username}님은 갚아야 할 대출금(빚)이 없습니다. (빚: 0P)", None

    if user.points <= 0:
        return False, "⚠️ 보유 현금이 0P라 상환할 수 없습니다. (주식 매도/청산 또는 !채굴 후 상환 가능)", None

    cleaned = (amount_str or "").strip().lower()
    if cleaned in ["전액", "올인", "all", "max", "최대"] or not cleaned:
        repay_amount = min(current_debt, user.points)
    else:
        try:
            val = int(cleaned.replace(",", "").replace("p", "").replace("원", ""))
            if val <= 0:
                return False, "⚠️ 상환 금액은 1P 이상이어야 합니다.", None
            if user.points < val:
                return False, f"⚠️ 보유 현금({user.points:,}P)이 부족합니다.", None
            repay_amount = min(current_debt, val)
        except ValueError:
            return False, "💡 상환 사용법: !상환 [금액/전액] (예: !상환 20000, !상환 전액)", None

    if repay_amount <= 0:
        return False, "⚠️ 상환 가능한 금액이 없습니다.", None

    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL

    user.points -= repay_amount
    user.debt = current_debt - repay_amount
    state.treasury_pool += repay_amount
    user.repay_count = (getattr(user, "repay_count", 0) or 0) + 1
    user.total_repaid = (getattr(user, "total_repaid", 0) or 0) + repay_amount

    db.commit()
    db.refresh(user)
    db.refresh(state)

    new_credit = get_user_credit_info(user, db=db, market_state=state)

    if user.debt == 0:
        reply = (
            f"🎉 [빚 전액 청산] {user.username}님 {repay_amount:,}P 전액 상환 완료! "
            f"국고 채무를 모두 청산하여 자유의 몸이 되었습니다! (보유 현금: {user.points:,}P) | "
            f"📈 성실 상환으로 신용등급: {new_credit['tier_name']} (신용점수: {new_credit['score']}점, 대출 한도: {new_credit['loan_limit']:,}P)"
        )
    else:
        reply = (
            f"💰 [대출 상환] {user.username}님 {repay_amount:,}P 상환 완료! | "
            f"잔여 빚: {user.debt:,}P | 보유 현금: {user.points:,}P | "
            f"📈 신용등급: {new_credit['tier_name']} (점수: {new_credit['score']}점, 한도: {new_credit['loan_limit']:,}P)"
        )

    details = {
        "user_id": user.id,
        "username": user.username,
        "amount": repay_amount,
        "remaining_debt": user.debt,
        "cash": user.points,
        "treasury_pool": state.treasury_pool
    }
    return True, reply, details

def execute_transfer(
    db: Session,
    sender_id: str,
    sender_username: str,
    target_name: str,
    amount_str: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Execute account transfer between users:
    !송금 [상대닉네임] [금액] / !이체 [상대닉네임] [금액]
    - If transfer amount >= 10,000P, transfer tax is levied and credited to National Treasury Pool.
    - If sender has debt, borrowed money cannot be transferred out to prevent bankruptcy laundering.
    """
    state = get_market_state(db)
    sender = get_or_create_user(db, sender_id, sender_username)

    clean_target = (target_name or "").strip().lstrip("@").strip()
    if not clean_target:
        return False, "💡 계좌이체 사용법: !송금 [닉네임] [금액/올인] (예: !송금 치즈나베 10000, !이체 @CYTFT 5만)", None

    # Prevent self-transfer by input name
    if clean_target.lower() == sender.username.lower() or clean_target == sender.id:
        return False, "⚠️ 본인 계좌로는 이체할 수 없습니다.", None

    # Find recipient in database
    recipient = db.query(User).filter(func.lower(User.username) == clean_target.lower()).first()
    if not recipient:
        recipient = db.query(User).filter(User.id == clean_target).first()
    if not recipient:
        candidates = db.query(User).filter(User.username.ilike(f"%{clean_target}%")).all()
        if len(candidates) == 1:
            recipient = candidates[0]

    if not recipient:
        return False, f"⚠️ 받으실 유저 '{clean_target}' 님을 찾을 수 없습니다. (채팅에 참여하여 등록된 유저에게만 이체 가능)", None

    if recipient.id == sender.id:
        return False, "⚠️ 본인 계좌로는 이체할 수 없습니다.", None

    # Debt protection: Cannot transfer borrowed funds out to launder before bankruptcy
    sender_debt = getattr(sender, "debt", 0) or 0
    if sender_debt > 0 and sender.points <= sender_debt:
        return False, f"⚠️ 채무(빚: {sender_debt:,}P)가 보유 현금({sender.points:,}P) 이상입니다. 파산 악용 방지를 위해 먼저 !상환을 진행해주세요.", None

    max_sendable = sender.points - sender_debt if sender_debt > 0 else sender.points

    clean_amount_str = (amount_str or "").strip().lower()
    if clean_amount_str in ["올인", "all", "전액", "전부", "다", "최대"]:
        amount = max_sendable
    else:
        amount = parse_korean_amount(clean_amount_str)
        if amount is None:
            return False, f"⚠️ 유효하지 않은 이체 금액입니다: '{amount_str}' (예: !송금 {clean_target} 10000, 5만, 올인)", None

    if amount <= 0:
        return False, "⚠️ 이체 금액은 최소 1P 이상이어야 합니다.", None

    if amount > sender.points:
        return False, f"⚠️ 보유 현금이 부족합니다! (현재 잔액: {sender.points:,}P | 요청 금액: {amount:,}P)", None

    if sender_debt > 0 and amount > max_sendable:
        return False, f"⚠️ 채무(빚: {sender_debt:,}P)를 제외한 순수 이체 가능 한도는 {max_sendable:,}P입니다. 먼저 !상환을 진행해주세요.", None

    # Calculate Tax
    tax, tax_rate, tax_label = calculate_transfer_tax(amount)
    tax_rate_pct = round(tax_rate * 100, 2)
    fee_disc = get_user_fee_discount_pct(db, sender)
    if fee_disc > 0 and tax > 0:
        tax = int(round(tax * (1.0 - fee_disc / 100.0)))
    tax_rate_str = f"{tax_rate_pct:g}%"
    recipient_net = amount - tax

    # Execute transfer
    sender.points -= amount
    recipient.points += recipient_net

    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL
    state.treasury_pool += tax

    db.commit()
    db.refresh(sender)
    db.refresh(recipient)
    db.refresh(state)

    disc_str = f" (잠재 -{int(fee_disc)}% 감면)" if (fee_disc > 0 and tax > 0) else ""
    if tax > 0:
        reply = (
            f"💸 [계좌이체 완료] {sender.username}님 ➡️ {recipient.username}님께 {amount:,}P 이체 완료! "
            f"(실수령: {recipient_net:,}P | {tax_label}({tax_rate_str}){disc_str}: {tax:,}P 국고 적립 | "
            f"보낸 분 잔액: {sender.points:,}P)"
        )
    else:
        reply = (
            f"💸 [계좌이체 완료] {sender.username}님 ➡️ {recipient.username}님께 {amount:,}P 이체 완료! "
            f"(1만P 미만 면세 | 실수령: {recipient_net:,}P | 보낸 분 잔액: {sender.points:,}P)"
        )

    details = {
        "sender_id": sender.id,
        "sender_username": sender.username,
        "recipient_id": recipient.id,
        "recipient_username": recipient.username,
        "amount": amount,
        "tax": tax,
        "tax_rate_pct": tax_rate_pct,
        "tax_label": tax_label,
        "recipient_net": recipient_net,
        "sender_remaining": sender.points,
        "recipient_remaining": recipient.points,
        "treasury_pool": state.treasury_pool
    }
    return True, reply, details

def submit_bankruptcy_application(
    db: Session,
    user_id: str,
    username: str,
    reason: str = ""
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Submit bankruptcy / rehabilitation application to the Streamer's Court.
    Enters PENDING status waiting for Streamer's verdict on Admin Panel.
    """
    state = get_market_state(db)
    user = get_or_create_user(db, user_id, username)
    current_debt = getattr(user, "debt", 0) or 0

    if current_debt <= 0:
        return False, f"💡 {user.username}님은 갚아야 할 대출금(빚)이 없어 파산 대상이 아닙니다. (빚: 0P) 국고 대출(!대출 최대)이나 채굴(!채굴)을 이용해주세요!", None

    # Check if user already has an active pending application
    pending_app = db.query(BankruptcyApplication).filter_by(
        user_id=user.id,
        status=BankruptcyStatus.PENDING
    ).first()
    if pending_app:
        return False, f"⚖️ 이미 접수되어 심사 대기 중인 회생 신청(사건 #{pending_app.id})이 있습니다. 나베 판사님의 판결을 기다려주세요!", None

    # Calculate total gross assets (cash + active positions valuation)
    portfolio_val = 0
    for p in user.positions:
        if p.quantity > 0:
            val = calculate_position_valuation(p, state.current_price)
            portfolio_val += int(round(val["current_value"]))

    gross_assets = user.points + portfolio_val

    # If user still has enough assets to pay the debt, reject bankruptcy request
    if gross_assets >= current_debt:
        return False, f"⚖️ [신청 불가] 보유 총자산({gross_assets:,}P)이 빚({current_debt:,}P) 이상입니다. !청산 또는 !상환으로 직접 변제 가능합니다.", None

    # Cooldown check (15 minutes = 900 seconds)
    now_utc = datetime.now(timezone.utc)
    if user.last_bankrupt_at:
        last_b = user.last_bankrupt_at
        if last_b.tzinfo is None:
            last_b = last_b.replace(tzinfo=timezone.utc)
        elapsed = (now_utc - last_b).total_seconds()
        if elapsed < 900:
            rem_m = max(1, int(900 - elapsed) // 60)
            return False, f"⏳ [회생 신청 대기] 최근 파산 심사 이력이 있습니다. 다음 신청까지 약 {rem_m}분 남았습니다.", None

    clean_reason = (reason or "").strip()
    if not clean_reason:
        clean_reason = "10X 타다가 전재산 날렸습니다. 살려주세요!"
    if len(clean_reason) > 150:
        clean_reason = clean_reason[:150] + "..."

    app = BankruptcyApplication(
        user_id=user.id,
        username=user.username,
        debt=current_debt,
        gross_assets=gross_assets,
        cash=user.points,
        portfolio_value=portfolio_val,
        reason=clean_reason,
        status=BankruptcyStatus.PENDING,
        created_at=now_utc
    )
    db.add(app)
    db.commit()
    db.refresh(app)

    reply = (
        f"🏛️ [개인회생 접수] {user.username}님의 회생 신청(사건 #{app.id})이 나베 판사의 법정에 접수되었습니다! "
        f"(채무: {current_debt:,}P | 사유: \"{clean_reason}\") 판사님의 판결을 기다려주세요."
    )
    details = {
        "id": app.id,
        "user_id": user.id,
        "username": user.username,
        "debt": app.debt,
        "gross_assets": app.gross_assets,
        "cash": app.cash,
        "portfolio_value": app.portfolio_value,
        "reason": app.reason,
        "status": app.status.value,
        "created_at": app.created_at.strftime("%H:%M:%S") if app.created_at else ""
    }
    return True, reply, details

def get_pending_bankruptcy_applications(db: Session) -> List[Dict[str, Any]]:
    """Return all pending bankruptcy applications for streamer court review."""
    apps = (
        db.query(BankruptcyApplication)
        .filter_by(status=BankruptcyStatus.PENDING)
        .order_by(BankruptcyApplication.created_at.asc())
        .all()
    )
    res = []
    for a in apps:
        res.append({
            "id": a.id,
            "user_id": a.user_id,
            "username": a.username,
            "debt": a.debt,
            "gross_assets": a.gross_assets,
            "cash": a.cash,
            "portfolio_value": a.portfolio_value,
            "reason": a.reason,
            "status": a.status.value,
            "created_at": a.created_at.strftime("%H:%M:%S") if a.created_at else ""
        })
    return res

def judge_bankruptcy_application(
    db: Session,
    app_id: int,
    verdict: str,
    admin_comment: str = ""
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Judge a pending bankruptcy application.
    verdict:
      - 'full': 100% debt forgiven, points set to 10,000P survival fund, positions wiped.
      - 'half': 50% debt forgiven, remaining 50% debt preserved.
      - 'reject': 0% debt forgiven, request dismissed with cooldown ("탄광 노역형").
    """
    app = db.query(BankruptcyApplication).filter_by(id=app_id).first()
    if not app or app.status != BankruptcyStatus.PENDING:
        return False, "⚠️ 대기 중인 회생 신청 사건을 찾을 수 없거나 이미 판결이 완료되었습니다.", None

    user = db.query(User).filter_by(id=app.user_id).first()
    if not user:
        return False, "⚠️ 신청 유저 정보를 찾을 수 없습니다.", None

    state = get_market_state(db)
    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL

    now_utc = datetime.now(timezone.utc)
    comment = (admin_comment or "").strip()
    v = (verdict or "").strip().lower()

    if v in ["full", "전액", "전액탕감", "인가"]:
        # 1. Liquidate lingering positions
        for p in user.positions:
            p.quantity = 0.0
            p.invested_cash = 0.0
            p.entry_price = 0.0

        # 2. Absorb remaining cash into treasury
        absorbed = max(0, user.points)
        state.treasury_pool += absorbed

        forgiven = user.debt
        user.debt = 0
        user.points = 10000  # Basic survival fund
        user.last_bankrupt_at = now_utc

        app.status = BankruptcyStatus.APPROVED_FULL
        app.verdict = "full"
        app.admin_comment = comment if comment else None
        app.resolved_at = now_utc

        db.commit()
        db.refresh(user)
        db.refresh(state)

        c_str = f" [판사 판결문: \"{comment}\"]" if comment else ""
        reply = (
            f"⚖️ [회생 인가] 나베 판사님이 {user.username}님의 회생을 인가했습니다! "
            f"채무 {forgiven:,}P 전액 탕감 & 기본 생계 자금 10,000P 지급!{c_str}"
        )
        details = {
            "app_id": app.id,
            "user_id": user.id,
            "username": user.username,
            "verdict": "full",
            "verdict_title": "전액 탕감 (인가)",
            "forgiven_debt": forgiven,
            "remaining_debt": 0,
            "points": user.points,
            "comment": comment,
            "treasury_pool": state.treasury_pool
        }
        return True, reply, details

    elif v in ["half", "50%", "절반", "워크아웃"]:
        forgiven = user.debt // 2
        user.debt = user.debt - forgiven
        user.last_bankrupt_at = now_utc

        app.status = BankruptcyStatus.APPROVED_HALF
        app.verdict = "half"
        app.admin_comment = comment if comment else None
        app.resolved_at = now_utc

        db.commit()
        db.refresh(user)

        c_str = f" [판사 판결문: \"{comment}\"]" if comment else ""
        reply = (
            f"⚖️ [조건부 워크아웃] 나베 판사님이 {user.username}님의 채무 {forgiven:,}P(50%)를 감면했습니다! "
            f"(남은 빚: {user.debt:,}P - 채굴과 건전한 투자로 변제하세요){c_str}"
        )
        details = {
            "app_id": app.id,
            "user_id": user.id,
            "username": user.username,
            "verdict": "half",
            "verdict_title": "조건부 50% 탕감 (워크아웃)",
            "forgiven_debt": forgiven,
            "remaining_debt": user.debt,
            "points": user.points,
            "comment": comment,
            "treasury_pool": state.treasury_pool
        }
        return True, reply, details

    elif v in ["reject", "기각", "탄광", "노역"]:
        user.last_bankrupt_at = now_utc

        app.status = BankruptcyStatus.REJECTED
        app.verdict = "reject"
        app.admin_comment = comment if comment else None
        app.resolved_at = now_utc

        db.commit()
        db.refresh(user)

        c_str = f" [판사 판결문: \"{comment}\"]" if comment else " \"탄광 가서 !채굴로 갚아라!\""
        reply = (
            f"🔨 [파산 기각] 나베 판사님이 {user.username}님의 파산 신청을 기각했습니다! "
            f"채무 {user.debt:,}P 전액 유지!{c_str}"
        )
        details = {
            "app_id": app.id,
            "user_id": user.id,
            "username": user.username,
            "verdict": "reject",
            "verdict_title": "파산 기각 (탄광 노역형)",
            "forgiven_debt": 0,
            "remaining_debt": user.debt,
            "points": user.points,
            "comment": comment,
            "treasury_pool": state.treasury_pool
        }
        return True, reply, details

    else:
        return False, f"⚠️ 알 수 없는 판결입니다: {verdict} (가능한 판결: full, half, reject)", None

def execute_bankruptcy(
    db: Session,
    user_id: str,
    username: str,
    reason: str = ""
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Compatibility alias to submit_bankruptcy_application."""
    return submit_bankruptcy_application(db, user_id, username, reason)

def get_treasury_info(db: Session) -> Dict[str, Any]:
    state = get_market_state(db)
    pool = getattr(state, "treasury_pool", DEFAULT_TREASURY_POOL) or DEFAULT_TREASURY_POOL
    return {
        "treasury_pool": pool,
        "fee_rate": TRADING_FEE_RATE,
        "fee_rate_pct": TRADING_FEE_RATE * 100.0,
        "victory_dividend_rate": 0.05,
        "second_dividend_rate": 0.01,
        "mining_cooldown_seconds": 900,
        "max_loan_limit": MAX_LOAN_LIMIT,
        "loan_interest_rate": LOAN_INTEREST_RATE,
        "loan_interest_pct": LOAN_INTEREST_RATE * 100.0
    }

def get_leaderboard(db: Session, top_n: int = 3) -> List[Dict[str, Any]]:
    """Calculate and return top richest shareholders by net asset valuation (cash + positions - debt)."""
    state = get_market_state(db)
    users = db.query(User).all()
    records = []

    for u in users:
        # Exclude dummy and test accounts from leaderboard rankings
        uid_lower = (u.id or "").lower()
        uname_lower = (u.username or "").lower()
        if (
            any(uid_lower.startswith(p) for p in ("fresh_", "test_", "viewer_", "strictly_", "dummy_", "sim_", "bug_", "user_temp", "u_"))
            or any(uname_lower.startswith(p) for p in ("테스터", "유저_", "새유저", "철통잠금", "더미", "테스트", "임시유저", "임시"))
            or uname_lower in ("테스트유저", "시청자1", "타이머만료유저", "후원테스터", "마진유저", "임시유저")
            or uid_lower in ("user_temp_123", "u_매수_10x_올인")
        ):
            continue

        portfolio_val = 0
        active_positions = []
        for p in u.positions:
            if p.quantity > 0:
                val = calculate_position_valuation(p, state.current_price)
                p_val = int(round(val["current_value"]))
                portfolio_val += p_val
                active_positions.append({
                    "product": p.product_type.value,
                    "quantity": p.quantity,
                    "value": p_val,
                    "pnl_pct": val["pnl_pct"]
                })

        debt = getattr(u, "debt", 0) or 0
        gross_assets = u.points + portfolio_val
        net_assets = gross_assets - debt
        total_pnl = net_assets - STARTING_POINTS  # Starting fund 50,000P
        total_pnl_pct = (total_pnl / float(STARTING_POINTS)) * 100.0

        records.append({
            "user_id": u.id,
            "username": u.username,
            "cash": u.points,
            "debt": debt,
            "gross_assets": gross_assets,
            "portfolio_value": portfolio_val,
            "total_assets": net_assets,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "positions": active_positions
        })

    records.sort(key=lambda r: r["total_assets"], reverse=True)

    ranked = []
    for idx, r in enumerate(records[:top_n], start=1):
        r["rank"] = idx
        ranked.append(r)

    return ranked

def get_current_buyers(db: Session, limit: int = 100) -> Dict[str, Any]:
    """
    Retrieve all current shareholders/buyers holding active positions (quantity > 0).
    Includes detailed per-position information, valuation, PnL, and market breakdown summary.
    """
    state = get_market_state(db)
    current_price = state.current_price

    positions = db.query(Position).filter(Position.quantity > 0).all()

    buyers = []
    unique_users = set()
    total_invested = 0
    total_current_val = 0
    long_count = 0
    short_count = 0
    long_value = 0
    short_value = 0

    # Friendly Korean labels for each product
    product_names = {
        ProductType.ONE_X: "1X 본주",
        ProductType.TWO_X: "2X 레버리지",
        ProductType.THREE_X: "3X 레버리지",
        ProductType.FIVE_X: "5X 레버리지",
        ProductType.TEN_X: "10X 레버리지 (10배 롱)",
        ProductType.INV: "1X 인버스 (1배 숏)",
        ProductType.TWO_X_INV: "2X 곱버스 (2배 숏)",
        ProductType.THREE_X_INV: "3X 인버스",
        ProductType.FIVE_X_INV: "5X 인버스",
        ProductType.TEN_X_INV: "10X 인버스 (10배 숏)",
    }

    for pos in positions:
        user = pos.user
        if not user:
            continue
        uid_lower = (user.id or "").lower()
        uname_lower = (user.username or "").lower()
        if (
            any(uid_lower.startswith(p) for p in ("fresh_", "test_", "viewer_", "strictly_", "dummy_", "sim_", "bug_", "user_temp", "u_"))
            or any(uname_lower.startswith(p) for p in ("테스터", "유저_", "새유저", "철통잠금", "더미", "테스트", "임시유저", "임시"))
            or uname_lower in ("테스트유저", "시청자1", "타이머만료유저", "후원테스터", "마진유저", "임시유저")
            or uid_lower in ("user_temp_123", "u_매수_10x_올인")
        ):
            continue

        val = calculate_position_valuation(pos, current_price)
        curr_val = int(round(val["current_value"]))
        invested = int(round(pos.invested_cash))
        unrealized = int(round(val["unrealized_pnl"]))
        pnl_pct = round(val["pnl_pct"], 2)

        unique_users.add(user.id)
        total_invested += invested
        total_current_val += curr_val

        is_short = ("_INV" in pos.product_type.value) or (pos.product_type == ProductType.INV)
        if is_short:
            short_count += 1
            short_value += curr_val
        else:
            long_count += 1
            long_value += curr_val

        qty_display = int(pos.quantity) if float(pos.quantity).is_integer() else round(float(pos.quantity), 2)
        entry_p = int(round(pos.entry_price)) if pos.entry_price else current_price

        buyers.append({
            "user_id": user.id,
            "username": user.username,
            "product_type": pos.product_type.value,
            "product_name": product_names.get(pos.product_type, pos.product_type.value),
            "is_short": is_short,
            "quantity": qty_display,
            "entry_price": entry_p,
            "invested_cash": invested,
            "current_value": curr_val,
            "unrealized_pnl": unrealized,
            "pnl_pct": pnl_pct,
            "user_cash": user.points,
            "has_debt": (getattr(user, "debt", 0) or 0) > 0,
            "debt": getattr(user, "debt", 0) or 0
        })

    # Sort buyers by current valuation descending
    buyers.sort(key=lambda b: b["current_value"], reverse=True)
    if limit > 0:
        buyers = buyers[:limit]

    total_val_all = long_value + short_value
    long_ratio = round((long_value / total_val_all * 100.0), 1) if total_val_all > 0 else 50.0
    short_ratio = round(100.0 - long_ratio, 1) if total_val_all > 0 else 50.0

    day_open = getattr(state, "day_open_price", current_price) or current_price
    day_diff = current_price - day_open
    day_diff_pct = round((day_diff / float(day_open)) * 100.0, 2) if day_open > 0 else 0.0

    return {
        "buyers": buyers,
        "summary": {
            "total_buyers": len(unique_users),
            "total_positions": len(buyers),
            "total_invested": total_invested,
            "total_current_value": total_current_val,
            "long_count": long_count,
            "short_count": short_count,
            "long_value": long_value,
            "short_value": short_value,
            "long_ratio": long_ratio,
            "short_ratio": short_ratio,
            "current_price": current_price,
            "day_open_price": day_open,
            "day_diff": day_diff,
            "day_diff_pct": day_diff_pct,
            "is_market_locked": is_market_locked(db, state)
        }
    }

# ---------------------------------------------------------
# Chzzk Donation -> Point Charging (1 KRW : 1000 Points)
# ---------------------------------------------------------
POINT_PER_KRW = 1000  # 1 KRW = 1000 Points

def validate_and_process_donation(
    db: Session,
    donation_data: Dict[str, Any]
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Validates a Chzzk Session DONATION event and credits points at 1:1000 ratio.
    Ensures idempotency/deduplication, atomic transaction, and auto-backup.
    """
    if not isinstance(donation_data, dict):
        return False, "⚠️ 후원 데이터 형식이 올바르지 않습니다.", None

    # 1. Parse and validate payAmount
    raw_amount = donation_data.get("payAmount") or donation_data.get("pay_amount")
    if raw_amount is None:
        return False, "⚠️ 후원 금액(payAmount)이 누락되었습니다.", None

    try:
        clean_amount_str = str(raw_amount).replace(",", "").strip()
        pay_amount = int(float(clean_amount_str))
    except (ValueError, TypeError):
        return False, f"⚠️ 유효하지 않은 후원 금액입니다: '{raw_amount}'", None

    if pay_amount <= 0:
        return False, f"⚠️ 후원 금액은 0원보다 커야 합니다. (입력: {pay_amount:,}원)", None

    if pay_amount > 50_000_000:
        return False, f"⚠️ 1회 최대 후원 한도(50,000,000원)를 초과했습니다. (입력: {pay_amount:,}원)", None

    # 2. Extract and sanitize donator info
    donator_nickname = str(donation_data.get("donatorNickname") or donation_data.get("donator_nickname") or "익명후원자").strip()
    if not donator_nickname:
        donator_nickname = "익명후원자"

    donator_channel_id = str(donation_data.get("donatorChannelId") or donation_data.get("donator_channel_id") or "").strip()

    # Resolve real existing user by channel ID or nickname
    existing_user = None
    if donator_channel_id:
        existing_user = get_user_by_identifier(db, donator_channel_id)
    if not existing_user and donator_nickname and donator_nickname != "익명후원자":
        existing_user = get_user_by_identifier(db, donator_nickname)

    if existing_user:
        user_id = existing_user.id
    else:
        user_id = donator_channel_id if donator_channel_id else f"chzzk_{donator_nickname}"

    channel_id = str(donation_data.get("channelId") or donation_data.get("channel_id") or "")
    donation_type = str(donation_data.get("donationType") or donation_data.get("donation_type") or "CHAT")
    donation_text = str(donation_data.get("donationText") or donation_data.get("donation_text") or "").strip()
    message_time = str(donation_data.get("messageTime") or donation_data.get("message_time") or "")

    # 3. Deduplication Key Generation (Idempotency)
    explicit_id = donation_data.get("donationId") or donation_data.get("donation_id")
    if explicit_id:
        donation_id = str(explicit_id)
    else:
        raw_hash_seed = f"{channel_id}:{user_id}:{pay_amount}:{donation_text}:{message_time}"
        donation_id = f"don_{hashlib.sha256(raw_hash_seed.encode('utf-8')).hexdigest()[:24]}"

    # Check for duplicate processing
    existing = db.query(DonationRecord).filter_by(donation_id=donation_id).first()
    if existing:
        return False, f"⚠️ 이미 충전 처리된 후원 내역입니다 (후원ID: {donation_id}, 충전포인트: {existing.points_credited:,}P)", None

    # Secondary idempotency check: prevent duplicate charging if both official and unofficial sockets receive same donation within 60 seconds
    try:
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=60)
        recent = db.query(DonationRecord).filter(
            DonationRecord.user_id == user_id,
            DonationRecord.pay_amount == pay_amount,
            DonationRecord.created_at >= cutoff
        ).all()
        for r in recent:
            if r.donation_text == donation_text:
                return False, f"⚠️ 최근 60초 내 이미 처리된 동일 후원 내역입니다 (기존 후원ID: {r.donation_id})", None
    except Exception as e:
        print(f"[TradingEngine] ⚠️ 최근 중복 후원 검사 예외: {e}")

    # 4. Point calculation (1 KRW : 100 Points)
    points_to_credit = pay_amount * POINT_PER_KRW

    # 5. Database safety auto-backup before point mutation
    try:
        from db_backup import create_backup
        create_backup(reason="pre_donation")
    except Exception as e:
        print(f"[TradingEngine] ⚠️ 사전 백업 경고 (충전은 계속 진행): {e}")

    # 6. Execute atomic user update and log creation
    try:
        user = get_or_create_user(db, user_id, donator_nickname)
        if user.username != donator_nickname and donator_nickname != "익명후원자":
            user.username = donator_nickname

        # Overflow boundary check
        if user.points + points_to_credit > 2_000_000_000:
            return False, "⚠️ 보유 포인트 상한(20억P)을 초과하여 충전할 수 없습니다.", None

        user.points += points_to_credit

        record = DonationRecord(
            donation_id=donation_id,
            channel_id=channel_id,
            donator_channel_id=donator_channel_id if donator_channel_id else None,
            donator_nickname=donator_nickname,
            pay_amount=pay_amount,
            points_credited=points_to_credit,
            user_id=user.id,
            donation_type=donation_type,
            donation_text=donation_text,
            raw_payload=json.dumps(donation_data, ensure_ascii=False)
        )
        db.add(record)
        db.commit()
        db.refresh(user)
        db.refresh(record)

        msg = (
            f"🎉 [후원 포인트 충전] {donator_nickname}님이 {pay_amount:,}원을 후원하셨습니다! "
            f"(1:1000 비율로 +{points_to_credit:,}P 충전 완료! 현재 잔고: {user.points:,}P)"
        )
        details = {
            "donation_id": donation_id,
            "user_id": user.id,
            "username": user.username,
            "pay_amount": pay_amount,
            "points_credited": points_to_credit,
            "remaining_points": user.points,
            "donation_text": donation_text,
            "donation_type": donation_type
        }
        return True, msg, details
    except Exception as e:
        db.rollback()
        return False, f"⚠️ 후원 포인트 충전 처리 중 DB 트랜잭션 에러: {e}", None

def get_donation_history(db: Session, limit: int = 20) -> List[Dict[str, Any]]:
    """Fetch recent donation history records."""
    records = db.query(DonationRecord).order_by(DonationRecord.id.desc()).limit(limit).all()
    res = []
    for r in records:
        res.append({
            "id": r.id,
            "donation_id": r.donation_id,
            "donator_nickname": r.donator_nickname,
            "donator_channel_id": r.donator_channel_id,
            "pay_amount": r.pay_amount,
            "points_credited": r.points_credited,
            "donation_type": r.donation_type,
            "donation_text": r.donation_text,
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else ""
        })
    return res

# =========================================================
# Community Treasury Casino & Gambling Engine (국고 카지노)
# =========================================================
DEFAULT_CASINO_MAX_BET: int = 10000000
MIN_CASINO_BET: int = 100
MAX_CASINO_PAYOUT: int = 100000  # 1회 주사위 도박 등 국고 최대 순지급액 상한선 (국고 보호)

SLOT_SYMBOLS = ["💣", "🍒", "🍇", "🔔", "💎", "🀄", "7️⃣"]
SLOT_WEIGHTS = [10, 30, 25, 20, 9, 4, 2]

def get_casino_state(db: Session) -> Dict[str, Any]:
    """Retrieve current casino state with automatic time expiry handling."""
    state = get_market_state(db)
    is_open = bool(getattr(state, "casino_is_open", False))
    end_time = float(getattr(state, "casino_end_time", 0.0) or 0.0)
    raw_max = getattr(state, "casino_max_bet", None)
    if raw_max is None or int(raw_max) <= 0 or int(raw_max) <= 10000:
        max_bet = DEFAULT_CASINO_MAX_BET
        state.casino_max_bet = DEFAULT_CASINO_MAX_BET
        try:
            db.commit()
        except Exception:
            pass
    else:
        max_bet = int(raw_max)

    now = time.time()
    if is_open and end_time > 0 and now >= end_time:
        state.casino_is_open = False
        state.casino_end_time = 0.0
        try:
            db.commit()
            db.refresh(state)
        except Exception:
            pass
        is_open = False

    remaining_sec = max(0, int(end_time - now)) if (is_open and end_time > 0) else (999999 if (is_open and end_time == 0) else 0)

    return {
        "is_open": is_open,
        "end_time": end_time,
        "remaining_sec": remaining_sec,
        "remaining_seconds": remaining_sec,
        "max_bet": max_bet,
        "treasury_pool": getattr(state, "treasury_pool", DEFAULT_TREASURY_POOL)
    }

def open_casino(db: Session, duration_minutes: float = 3.0, max_bet: int = 10000000) -> Tuple[bool, str, Dict[str, Any]]:
    """Open community treasury casino for specified minutes (0 = unlimited)."""
    state = get_market_state(db)
    now = time.time()
    end_time = (now + duration_minutes * 60.0) if duration_minutes > 0 else 0.0
    if max_bet is None or max_bet <= 0:
        max_bet = DEFAULT_CASINO_MAX_BET
    max_bet = max(MIN_CASINO_BET, int(max_bet))

    state.casino_is_open = True
    state.casino_end_time = end_time
    state.casino_max_bet = max_bet
    db.commit()
    db.refresh(state)

    duration_str = f"{int(duration_minutes)}분 동안" if duration_minutes > 0 else "무제한"
    msg = (
        f"🎰 [국고 카지노 OPEN] 스트리머가 국고 도박장을 열었습니다! ({duration_str}, 1회 최대: {max_bet:,}P) "
        f"지금 채팅창에 '!경마 [1~4/마명] [금액]' (1위 3.6배 배당), '!슬롯 [베팅금]', '!주사위 [홀/짝] [금액]', '!마작패 [패/역만] [금액]'으로 국고를 털어보세요! (현재 국고: {int(state.treasury_pool):,}P)"
    )
    details = {
        "is_open": True,
        "duration_minutes": duration_minutes,
        "end_time": end_time,
        "max_bet": max_bet,
        "treasury_pool": state.treasury_pool
    }
    return True, msg, details

def close_casino(db: Session) -> Tuple[bool, str, Dict[str, Any]]:
    """Close community treasury casino immediately."""
    state = get_market_state(db)
    state.casino_is_open = False
    state.casino_end_time = 0.0
    db.commit()
    db.refresh(state)

    msg = f"🔒 [국고 카지노 CLOSED] 국고 도박장이 마감되었습니다! (현재 국고 잔고: {int(state.treasury_pool):,}P)"
    details = {
        "is_open": False,
        "treasury_pool": state.treasury_pool
    }
    return True, msg, details

def execute_slot_gamble(
    db: Session,
    user_id: str,
    username: str,
    bet_token: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Execute 3-reel Jackpot Slot (Uncapped Payouts!):
    Payouts (Rebalanced):
    - 7️⃣ 7️⃣ 7️⃣ : MEGA JACKPOT (15% of treasury pool, uncapped, min 12x bet)
    - 🀄 🀄 🀄 : 8.0x Yakuman Jackpot (Net +7.0x, uncapped)
    - 💎 💎 💎 : 5.0x Diamond Triple (Net +4.0x, uncapped)
    - 🔔 🔔 🔔 : 3.5x Golden Bell (Net +2.5x, uncapped)
    - 🍇 🍇 🍇 : 2.5x Grape Triple (Net +1.5x, uncapped)
    - 🍒 🍒 🍒 : 1.8x Cherry Triple (Net +0.8x, uncapped)
    - High 2-pair (7, 🀄, 💎): 1.8x payout (+0.8x net, uncapped)
    - Standard 2-pair (🔔, 🍇, 🍒): 1.4x payout (+0.4x net, uncapped)
    - Non-matched / 💣: Loss (Absorbed into Treasury Pool, with potential payback if equipped)
    """
    c_state = get_casino_state(db)
    if not c_state["is_open"]:
        return False, "⚠️ 현재 국고 카지노가 오픈되어 있지 않습니다! 스트리머가 열 때까지 기다려주세요.", None

    user = get_or_create_user(db, user_id, username)
    state = get_market_state(db)

    # Parse bet amount
    clean_bet = str(bet_token).strip().lower()
    max_bet = c_state.get("max_bet", 100000)
    if max_bet <= 10000:
        max_bet = 100000
    if clean_bet in ["올인", "all", "풀베팅", "전액", "최대"]:
        bet = min(user.points, max_bet)
    else:
        try:
            bet = int(float(clean_bet))
        except ValueError:
            return False, f"⚠️ 올바른 베팅 금액을 입력해주세요: '{bet_token}' (예: !슬롯 1000, !슬롯 올인)", None

    if bet < MIN_CASINO_BET:
        return False, f"⚠️ 최소 베팅 금액은 {MIN_CASINO_BET:,}P입니다.", None

    if bet > max_bet:
        return False, f"⚠️ 1회 최대 베팅 한도는 {max_bet:,}P입니다. (입력: {bet:,}P)", None

    if user.points < bet:
        return False, f"⚠️ 보유 포인트가 부족합니다! (보유: {user.points:,}P, 베팅: {bet:,}P)", None

    # Spin 3 reels
    s1, s2, s3 = random.choices(SLOT_SYMBOLS, weights=SLOT_WEIGHTS, k=3)
    display_reels = f"[ {s1} | {s2} | {s3} ]"

    is_jackpot = False
    won = False
    multiplier = 0.0
    net_payout = 0

    if s1 == s2 == s3:
        if s1 == "7️⃣":
            is_jackpot = True
            won = True
            pool_share = int(round(state.treasury_pool * 0.15))
            guaranteed = bet * 12
            net_payout = max(guaranteed, pool_share)
            multiplier = round((net_payout + bet) / bet, 1) if bet > 0 else 12.0
        elif s1 == "🀄":
            is_jackpot = True
            won = True
            multiplier = 8.0
            net_payout = int(round(bet * 7.0))
        elif s1 == "💎":
            won = True
            multiplier = 5.0
            net_payout = int(round(bet * 4.0))
        elif s1 == "🔔":
            won = True
            multiplier = 3.5
            net_payout = int(round(bet * 2.5))
        elif s1 == "🍇":
            won = True
            multiplier = 2.5
            net_payout = int(round(bet * 1.5))
        elif s1 == "🍒":
            won = True
            multiplier = 1.8
            net_payout = int(round(bet * 0.8))
        elif s1 == "💣":
            won = False
            net_payout = -bet
    elif (s1 == s2 and s1 != "💣") or (s2 == s3 and s2 != "💣") or (s1 == s3 and s1 != "💣"):
        # 2 matching symbols (not bomb pair)
        won = True
        matched_sym = s1 if (s1 == s2 or s1 == s3) else s2
        if matched_sym in ["7️⃣", "🀄", "💎"]:
            multiplier = 2.0
            net_payout = max(10, int(round(bet * 1.0))) # Net gain +1.0x (2.0x total payout)
        else: # 🔔, 🍇, 🍒
            multiplier = 1.6
            net_payout = max(10, int(round(bet * 0.6))) # Net gain +0.6x (1.6x total payout)
    else:
        won = False
        net_payout = -bet

    if won:
        # Check slot winning boost potential (Slot potential boosts winning payouts)
        equipped_item = get_user_equipped_item(db, user)
        pot_effects = get_equipment_potential_effects(equipped_item)
        slot_boost_pct = min(35.0, float(pot_effects.get("slot_boost_pct", 0.0)))
        boost_amt = 0
        if slot_boost_pct > 0:
            total_win_payout = net_payout + bet
            boost_amt = int(round(total_win_payout * (slot_boost_pct / 100.0)))
            net_payout += boost_amt

        user.points += net_payout
        state.treasury_pool = max(10000.0, state.treasury_pool - net_payout)
        boost_str = f" (🎰잠재 당첨 보너스 +{int(slot_boost_pct)}% 발동: +{boost_amt:,}P 추가 지급!)" if boost_amt > 0 else ""
        if is_jackpot and s1 == "7️⃣":
            msg = (
                f"🚨🚨🚨 [MEGA 777 JACKPOT!] {user.username}님이 {display_reels} 대박 터짐! "
                f"국고의 15%인 +{net_payout:,}P를 싹쓸이 강탈했습니다!{boost_str} (잔여: {user.points:,}P | 남은 국고: {int(state.treasury_pool):,}P)"
            )
        elif is_jackpot and s1 == "🀄":
            msg = (
                f"🀄🔥 [역만 잭팟 당첨!] {user.username}님이 {display_reels} 적중! "
                f"배팅금 8배인 +{net_payout:,}P를 국고에서 출금 지급!{boost_str} (잔여: {user.points:,}P)"
            )
        else:
            gain_label = f"{multiplier}배" if multiplier > 0 else "보너스"
            msg = (
                f"🎉 [슬롯 당첨!] {user.username}님이 {display_reels} 적중! "
                f"({gain_label} 당첨으로 +{net_payout:,}P 획득!{boost_str} 잔여: {user.points:,}P)"
            )
    else:
        # Slot failure: no payback (Slot potential is winning bonus; Dice potential is payback)
        net_loss = bet
        net_payout = -net_loss
        user.points -= net_loss
        state.treasury_pool += net_loss
        msg = (
            f"💣 [슬롯 꽝!] {user.username}님이 {display_reels} 꽝! "
            f"베팅금 {bet:,}P는 국고로 압류되었습니다! (잔여: {user.points:,}P | 현재 국고: {int(state.treasury_pool):,}P)"
        )

    db.commit()
    db.refresh(user)
    db.refresh(state)

    details = {
        "game_type": "slot",
        "user_id": user.id,
        "username": user.username,
        "bet": bet,
        "reels": [s1, s2, s3],
        "won": won,
        "is_jackpot": is_jackpot,
        "net_payout": net_payout,
        "remaining_points": user.points,
        "treasury_pool": state.treasury_pool
    }
    return True, msg, details

def execute_dice_gamble(
    db: Session,
    user_id: str,
    username: str,
    choice_token: str,
    bet_token: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Execute 2-Dice High-Roller Gamble (Uncapped Payouts!):
    Choices (Rebalanced):
    - '홀' (Odd - 1.8x), '짝' (Even - 1.8x), '대' (8~12 High - 1.8x), '소' (2~6 Low - 1.8x).
    - Sum 7 on High/Low: PUSH (무승부 - 베팅금 100% 전액 환급, 원금 보존).
    - Special: Double 1-1 or 6-6 gives 2.2x CRITICAL JACKPOT!
    """
    c_state = get_casino_state(db)
    if not c_state["is_open"]:
        return False, "⚠️ 현재 국고 카지노가 오픈되어 있지 않습니다! 스트리머가 열 때까지 기다려주세요.", None

    user = get_or_create_user(db, user_id, username)
    state = get_market_state(db)

    # Normalize choice
    choice = str(choice_token).strip().lower()
    choice_map = {
        "홀": "ODD", "odd": "ODD", "홀수": "ODD",
        "짝": "EVEN", "even": "EVEN", "짝수": "EVEN",
        "대": "HIGH", "high": "HIGH", "크다": "HIGH",
        "소": "LOW", "low": "LOW", "작다": "LOW",
    }
    if choice not in choice_map:
        return False, f"⚠️ 올바른 주사위 선택을 입력해주세요: '{choice_token}' (선택 가능: 홀, 짝, 대, 소. 예: !주사위 홀 5000)", None
    target_choice = choice_map[choice]

    # Parse bet amount
    clean_bet = str(bet_token).strip().lower()
    max_bet = c_state.get("max_bet", 100000)
    if max_bet <= 10000:
        max_bet = 100000
    if clean_bet in ["올인", "all", "풀베팅", "전액", "최대"]:
        bet = min(user.points, max_bet)
    else:
        try:
            bet = int(float(clean_bet))
        except ValueError:
            return False, f"⚠️ 올바른 베팅 금액을 입력해주세요: '{bet_token}' (예: !주사위 홀 1000, !주사위 짝 올인)", None

    if bet < MIN_CASINO_BET:
        return False, f"⚠️ 최소 베팅 금액은 {MIN_CASINO_BET:,}P입니다.", None

    if bet > max_bet:
        return False, f"⚠️ 1회 최대 베팅 한도는 {max_bet:,}P입니다. (입력: {bet:,}P)", None

    if user.points < bet:
        return False, f"⚠️ 보유 포인트가 부족합니다! (보유: {user.points:,}P, 베팅: {bet:,}P)", None

    # Roll two dice
    d1 = random.randint(1, 6)
    d2 = random.randint(1, 6)
    total = d1 + d2
    is_odd = (total % 2 == 1)
    is_high = (total >= 8)
    is_low = (total <= 6)
    is_seven = (total == 7)

    is_push = False
    is_correct = False
    if target_choice == "ODD" and is_odd:
        is_correct = True
    elif target_choice == "EVEN" and not is_odd:
        is_correct = True
    elif target_choice == "HIGH":
        if is_high:
            is_correct = True
        elif is_seven:
            is_push = True
    elif target_choice == "LOW":
        if is_low:
            is_correct = True
        elif is_seven:
            is_push = True

    is_critical = is_correct and ((d1 == 1 and d2 == 1) or (d1 == 6 and d2 == 6))

    if is_critical:
        # 2.2x Critical Payout (Net profit 1.2x)
        net_payout = int(round(bet * 1.2))
        user.points += net_payout
        state.treasury_pool = max(10000.0, state.treasury_pool - net_payout)
        msg = (
            f"🎲🔥 [주사위 2.2배 크리티컬 잭팟!] {user.username}님이 더블 잭팟 적중! "
            f"[ 🎲{d1} + 🎲{d2} = {total} ] 2.2배 크리티컬 당첨으로 +{net_payout:,}P 국고 획득! (잔여: {user.points:,}P)"
        )
    elif is_correct:
        # 1.8x Payout (Net profit 0.8x)
        net_payout = int(round(bet * 0.8))
        gain_label = "1.8배"
        user.points += net_payout
        state.treasury_pool = max(10000.0, state.treasury_pool - net_payout)
        odd_label = "홀" if is_odd else "짝"
        msg = (
            f"🎲✨ [주사위 적중!] {user.username}님이 '{choice}' 선택 적중! "
            f"[ 🎲{d1} + 🎲{d2} = {total} ({odd_label}) ] {gain_label} 당첨으로 +{net_payout:,}P 획득! (잔여: {user.points:,}P)"
        )
    elif is_push:
        net_payout = 0
        msg = (
            f"🎲⚖️ [주사위 무승부!] {user.username}님의 대/소 예측 중 럭키 7 발생! "
            f"[ 🎲{d1} + 🎲{d2} = 7 ] 베팅금 {bet:,}P는 전액 환급됩니다! (잔여: {user.points:,}P)"
        )
    else:
        # Check dice payback potential (capped at 30%)
        equipped_item = get_user_equipped_item(db, user)
        pot_effects = get_equipment_potential_effects(equipped_item)
        payback_pct = min(30.0, float(pot_effects.get("dice_payback_pct", 0.0)))
        payback_amt = 0
        if payback_pct > 0:
            payback_amt = int(round(bet * (payback_pct / 100.0)))

        net_loss = bet - payback_amt
        net_payout = -net_loss
        user.points -= net_loss
        state.treasury_pool += net_loss
        odd_label = "홀" if is_odd else "짝"
        payback_str = f" (🎲잠재 환급 {int(payback_pct)}% 발동: {payback_amt:,}P 환급!)" if payback_amt > 0 else ""
        msg = (
            f"🎲💀 [주사위 실패!] {user.username}님의 예측 빗나감! "
            f"[ 🎲{d1} + 🎲{d2} = {total} ({odd_label}) ] 베팅금 {bet:,}P 중 {net_loss:,}P가 국고로 귀속되었습니다!{payback_str} (잔여: {user.points:,}P)"
        )

    db.commit()
    db.refresh(user)
    db.refresh(state)

    details = {
        "game_type": "dice",
        "user_id": user.id,
        "username": user.username,
        "bet": bet,
        "choice": target_choice,
        "dice": [d1, d2],
        "total": total,
        "won": is_correct,
        "is_push": is_push,
        "is_critical": is_critical,
        "net_payout": net_payout,
        "remaining_points": user.points,
        "treasury_pool": state.treasury_pool
    }
    return True, msg, details


MAHJONG_SUIT_ALIASES = {
    "만": "만", "만수": "만", "m": "만", "man": "만",
    "삭": "삭", "삭수": "삭", "s": "삭", "sou": "삭",
    "통": "통", "통수": "통", "p": "통", "pin": "통",
}

MAHJONG_TILES = (
    [f"{i}만" for i in range(1, 10)] +
    [f"{i}삭" for i in range(1, 10)] +
    [f"{i}통" for i in range(1, 10)]
)

def parse_mahjong_choice(raw_choice: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Parses user input into (bet_type, target, display_label).
    Returns (None, None, None) if unrecognized.
    bet_type can be:
      - 'suit': target is '만'/'삭'/'통', display_label is '만수'/'삭수'/'통수'
      - 'exact': target is '7통', display_label is '7통'
      - 'ting': target is '1만,4만,7만', display_label is '화료패 3종 (1만, 4만, 7만) [8.10배]'
    """
    token = (raw_choice or "").strip().lower()
    if not token:
        return None, None, None

    # Strip prefixes like 화료, 대기, 화료패, 대기패, 패
    token = re.sub(r'^(화료|대기|화료패|대기패|패)\s*', '', token).strip()

    # Check suit
    clean_no_space = token.replace(" ", "")
    if clean_no_space in MAHJONG_SUIT_ALIASES:
        suit = MAHJONG_SUIT_ALIASES[clean_no_space]
        return "suit", suit, f"{suit}수"

    # Extract tiles (supports e.g. "147만", "1만,4만,7만", "1만 4만 7만", "1m 4m 7m")
    found_tiles = []
    for m in re.finditer(r'([1-9]+)\s*([만삭통mpssoupin]+)', token):
        digits = m.group(1)
        s_raw = m.group(2)
        suit = MAHJONG_SUIT_ALIASES.get(s_raw)
        if suit:
            for d in digits:
                tile = f"{d}{suit}"
                if tile in MAHJONG_TILES and tile not in found_tiles:
                    found_tiles.append(tile)

    if not found_tiles:
        return None, None, None

    if len(found_tiles) == 1:
        return "exact", found_tiles[0], found_tiles[0]

    if len(found_tiles) > 24:
        return None, None, None

    target = ",".join(found_tiles)
    k = len(found_tiles)
    mult = max(1.01, round(24.3 / k, 2))
    return "ting", target, f"화료패 {k}종 ({', '.join(found_tiles)}) [{mult:.2f}배]"


def execute_mahjong_tile_gamble(
    db: Session,
    user_id: str,
    username: str,
    choice_token: str,
    bet_token: Any
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Execute Mahjong Tile Guess Gamble (!마작 [만/삭/통 or 1만~9통 or 1만,4만,7만] [베팅금]):
    - 27 tiles (1~9만, 1~9삭, 1~9통 - no honors)
    - Suit Guess (만/삭/통): 1/3 (33.33%) probability, 2.7x payout (RTP 90.0%)
    - Exact Tile Guess (1만~9통): 1/27 (3.704%) probability, 24.3x payout (RTP 90.0%)
    - Multi-tile Ting Guess (1~24 tiles): K/27 probability, round(24.3 / K, 2) payout (RTP 90.0%)
    - Potential: MAHJONG_TILE_BOOST increases win payout (Legendary +11.1% achieves 100% RTP)
    """
    c_state = get_casino_state(db)
    if not c_state["is_open"]:
        return False, "⚠️ 현재 국고 카지노가 오픈되어 있지 않습니다! 스트리머가 열 때까지 기다려주세요.", None

    user = get_or_create_user(db, user_id, username)
    state = get_market_state(db)

    bet_type, target, display_label = parse_mahjong_choice(choice_token)
    if not bet_type:
        return False, (
            "💡 [마작패 / 화료패 맞추기 사용법] !마작 [선택패들] [베팅금] 또는 !화료 [패목록] [베팅금]\n"
            "• 종류 맞추기: 만 / 삭 / 통 (확률 1/3, 배당 2.7배)\n"
            "• 1종 정확히 맞추기: 1만~9만, 1삭~9삭, 1통~9통 (확률 1/27, 배당 24.3배)\n"
            "• 화료패(다면 대기) 맞추기: 원하는 만큼 여러 개 패 선택 (개수에 따라 배율 조정)\n"
            "  - 2종 대기: 12.15배 | 3종 대기: 8.1배 | 4종: 6.08배 | 9종: 2.7배\n"
            "예시: !마작 만 10000, !마작 7통 5000, !화료 1만,4만,7만 10000, !화료 147만 5000"
        ), None

    max_bet = c_state.get("max_bet", 100000)
    if max_bet <= 10000:
        max_bet = 100000

    clean_bet = str(bet_token).strip().lower().replace(",", "")
    if clean_bet in ["올인", "all", "풀베팅", "전액", "최대", "max"]:
        bet = min(user.points, max_bet)
    else:
        # Check Korean units
        if clean_bet.endswith("만"):
            try:
                bet = int(float(clean_bet[:-1]) * 10000)
            except ValueError:
                return False, f"⚠️ 올바른 베팅 금액을 입력해주세요: '{bet_token}'", None
        elif clean_bet.endswith("천") or clean_bet.endswith("k"):
            try:
                bet = int(float(clean_bet[:-1]) * 1000)
            except ValueError:
                return False, f"⚠️ 올바른 베팅 금액을 입력해주세요: '{bet_token}'", None
        else:
            try:
                bet = int(float(clean_bet))
            except ValueError:
                return False, f"⚠️ 올바른 베팅 금액을 입력해주세요: '{bet_token}' (예: !마작 만 1000, !마작 7통 올인)", None

    if bet < MIN_CASINO_BET:
        return False, f"⚠️ 최소 베팅 금액은 {MIN_CASINO_BET:,}P입니다.", None
    if bet > max_bet:
        return False, f"⚠️ 1회 최대 베팅 한도는 {max_bet:,}P입니다. (입력: {bet:,}P)", None
    if user.points < bet:
        return False, f"⚠️ 보유 포인트가 부족합니다! (보유: {user.points:,}P, 베팅: {bet:,}P)", None

    # Draw 1 tile out of 27
    drawn_tile = random.choice(MAHJONG_TILES)
    drawn_suit = drawn_tile[-1]  # '만', '삭', '통'

    won = False
    multiplier = 0.0
    if bet_type == "suit":
        multiplier = 2.7
        won = (target == drawn_suit)
    elif bet_type == "exact":
        multiplier = 24.3
        won = (target == drawn_tile)
    elif bet_type == "ting":
        target_tiles = [t.strip() for t in target.split(",") if t.strip()]
        k = len(target_tiles)
        multiplier = max(1.01, round(24.3 / k, 2))
        won = (drawn_tile in target_tiles)

    if won:
        gross_payout = int(round(bet * multiplier))
        net_payout = gross_payout - bet

        # Potential: MAHJONG_TILE_BOOST
        equipped_item = get_user_equipped_item(db, user)
        pot_effects = get_equipment_potential_effects(equipped_item)
        boost_pct = min(30.0, float(pot_effects.get("mahjong_boost_pct", 0.0)))
        boost_amt = 0
        if boost_pct > 0:
            boost_amt = int(round(gross_payout * (boost_pct / 100.0)))
            net_payout += boost_amt

        user.points += net_payout
        state.treasury_pool = max(10000.0, state.treasury_pool - net_payout)
        boost_str = f" (🀄잠재 배당 보너스 +{boost_pct}%: +{boost_amt:,}P 추가!)" if boost_amt > 0 else ""
        if bet_type == "exact":
            msg = (
                f"🀄🌟 [마작패 단기 적중 대박!] {user.username}님이 1/{len(MAHJONG_TILES)} 확률의 [{drawn_tile}] 정확히 적중! "
                f"24.3배 대박 당첨으로 +{net_payout:,}P 국고 획득!{boost_str} (잔여: {user.points:,}P)"
            )
        elif bet_type == "ting":
            msg = (
                f"🀄🀄 [화료! {display_label} 적중!] {user.username}님의 화료패 [{drawn_tile}] 쯔모/적중! "
                f"{multiplier:.2f}배 당첨으로 +{net_payout:,}P 획득!{boost_str} (잔여: {user.points:,}P)"
            )
        else:
            msg = (
                f"🀄🎉 [마작패 {display_label} 적중!] {user.username}님 예측 성공! "
                f"나온 패: [{drawn_tile}] | 2.7배 배당으로 +{net_payout:,}P 획득!{boost_str} (잔여: {user.points:,}P)"
            )
    else:
        net_loss = bet
        net_payout = -net_loss
        user.points -= net_loss
        state.treasury_pool += net_loss
        msg = (
            f"🀄💀 [마작패 빗나감!] {user.username}님의 '{display_label}' 예측 실패! "
            f"나온 패: [{drawn_tile}] | 베팅금 {bet:,}P는 국고로 귀속되었습니다! (잔여: {user.points:,}P)"
        )

    db.commit()
    db.refresh(user)
    db.refresh(state)

    details = {
        "game_type": "mahjong",
        "user_id": user.id,
        "username": user.username,
        "bet": bet,
        "bet_type": bet_type,
        "choice": target,
        "display_label": display_label,
        "drawn_tile": drawn_tile,
        "drawn_suit": drawn_suit,
        "won": won,
        "multiplier": multiplier,
        "net_payout": net_payout,
        "remaining_points": user.points,
        "treasury_pool": state.treasury_pool
    }
    return True, msg, details


YAKUMAN_RUNNERS = [
    {"num": 1, "name": "대삼원", "icon": "🐉", "title": "🐉 1번마 대삼원", "aliases": ["1", "대삼원", "용", "dragon", "daisangen"]},
    {"num": 2, "name": "스안커", "icon": "🀄", "title": "🀄 2번마 스안커", "aliases": ["2", "스안커", "사안커", "사암각", "anko", "suuankou"]},
    {"num": 3, "name": "국사무쌍", "icon": "🌸", "title": "🌸 3번마 국사무쌍", "aliases": ["3", "국사무쌍", "국사", "kokushi"]},
    {"num": 4, "name": "구련보등", "icon": "⚡", "title": "⚡ 4번마 구련보등", "aliases": ["4", "구련보등", "구련", "chuuren"]},
]

def parse_race_runner(raw_choice: str) -> Optional[Dict[str, Any]]:
    token = (raw_choice or "").strip().lower().replace(" ", "")
    for r in YAKUMAN_RUNNERS:
        if token == str(r["num"]) or token == r["name"].lower() or token in r["aliases"]:
            return r
    return None

def execute_yakuman_race_gamble(
    db: Session,
    user_id: str,
    username: str,
    choice_token: str,
    bet_token: Any
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Execute Yakuman 4-Greats Race Gamble (!경마 / !레이스 [1~4 or 마명] [베팅금]):
    - 4 runners: 🐉대삼원(1), 🀄스안커(2), 🌸국사무쌍(3), ⚡구련보등(4)
    - 1st place (Win): 25% chance, 3.6x payout (Base RTP 90.0%)
    - 2nd place (Safety): 25% chance, potential payback with RACE_SAFETY_PAYBACK (Legendary 40% gives 100% RTP)
    - 3rd / 4th place: Loss
    """
    c_state = get_casino_state(db)
    if not c_state["is_open"]:
        return False, "⚠️ 현재 국고 카지노가 오픈되어 있지 않습니다! 스트리머가 열 때까지 기다려주세요.", None

    user = get_or_create_user(db, user_id, username)
    state = get_market_state(db)

    runner = parse_race_runner(choice_token)
    if not runner:
        return False, (
            "💡 [역만 4대 천왕 경마 사용법] !경마 [말이름/번호] [베팅금] (또는 !레이스)\n"
            "• 1번마 🐉 대삼원 (배당 3.6배, 우승 확률 25%)\n"
            "• 2번마 🀄 스안커 (배당 3.6배, 우승 확률 25%)\n"
            "• 3번마 🌸 국사무쌍 (배당 3.6배, 우승 확률 25%)\n"
            "• 4번마 ⚡ 구련보등 (배당 3.6배, 우승 확률 25%)\n"
            "예시: !경마 대삼원 10000, !레이스 2 5000, !경마 스안커 올인"
        ), None

    max_bet = c_state.get("max_bet", 100000)
    if max_bet <= 10000:
        max_bet = 100000

    clean_bet = str(bet_token).strip().lower().replace(",", "")
    if clean_bet in ["올인", "all", "풀베팅", "전액", "최대", "max"]:
        bet = min(user.points, max_bet)
    else:
        if clean_bet.endswith("만"):
            try:
                bet = int(float(clean_bet[:-1]) * 10000)
            except ValueError:
                return False, f"⚠️ 올바른 베팅 금액을 입력해주세요: '{bet_token}'", None
        elif clean_bet.endswith("천") or clean_bet.endswith("k"):
            try:
                bet = int(float(clean_bet[:-1]) * 1000)
            except ValueError:
                return False, f"⚠️ 올바른 베팅 금액을 입력해주세요: '{bet_token}'", None
        else:
            try:
                bet = int(float(clean_bet))
            except ValueError:
                return False, f"⚠️ 올바른 베팅 금액을 입력해주세요: '{bet_token}' (예: !경마 대삼원 1000, !레이스 1 올인)", None

    if bet < MIN_CASINO_BET:
        return False, f"⚠️ 최소 베팅 금액은 {MIN_CASINO_BET:,}P입니다.", None
    if bet > max_bet:
        return False, f"⚠️ 1회 최대 베팅 한도는 {max_bet:,}P입니다. (입력: {bet:,}P)", None
    if user.points < bet:
        return False, f"⚠️ 보유 포인트가 부족합니다! (보유: {user.points:,}P, 베팅: {bet:,}P)", None

    # Run race: random permutation of 4 runners
    race_results = random.sample(YAKUMAN_RUNNERS, len(YAKUMAN_RUNNERS))
    p1 = race_results[0]
    p2 = race_results[1]
    p3 = race_results[2]
    p4 = race_results[3]

    order_str = f"🥇1위 {p1['icon']}{p1['name']} | 🥈2위 {p2['icon']}{p2['name']} | 🥉3위 {p3['icon']}{p3['name']} | 4위 {p4['icon']}{p4['name']}"

    won = (runner["num"] == p1["num"])
    is_second = (runner["num"] == p2["num"])

    multiplier = 3.6
    if won:
        gross_payout = int(round(bet * multiplier))
        net_payout = gross_payout - bet
        user.points += net_payout
        state.treasury_pool = max(10000.0, state.treasury_pool - net_payout)
        msg = (
            f"🏇🏁 [역만 레이스 1위 우승!!] {user.username}님의 '{runner['icon']} {runner['name']}' 폭풍 질주 1위 골인!\n"
            f"[ {order_str} ] 3.6배 배당으로 +{net_payout:,}P 국고 획득! (잔여: {user.points:,}P)"
        )
    elif is_second:
        # Check RACE_SAFETY_PAYBACK potential
        equipped_item = get_user_equipped_item(db, user)
        pot_effects = get_equipment_potential_effects(equipped_item)
        safety_pct = min(60.0, float(pot_effects.get("race_safety_pct", 0.0)))
        payback_amt = 0
        if safety_pct > 0:
            payback_amt = int(round(bet * (safety_pct / 100.0)))

        net_loss = bet - payback_amt
        net_payout = -net_loss
        user.points -= net_loss
        state.treasury_pool += net_loss
        payback_str = f" (🏇잠재 세이프티 {int(safety_pct)}% 발동: {payback_amt:,}P 환급!)" if payback_amt > 0 else ""
        msg = (
            f"🏇🥈 [역만 레이스 아쉬운 2등!] {user.username}님의 '{runner['icon']} {runner['name']}' 간발의 차로 준우승!\n"
            f"[ {order_str} ] 베팅금 {bet:,}P 중 {net_loss:,}P 국고 귀속{payback_str} (잔여: {user.points:,}P)"
        )
    else:
        net_loss = bet
        net_payout = -net_loss
        user.points -= net_loss
        state.treasury_pool += net_loss
        msg = (
            f"🏇💀 [역만 레이스 순위권 밖!] {user.username}님의 '{runner['icon']} {runner['name']}' 역전 실패 탈락!\n"
            f"[ {order_str} ] 베팅금 {bet:,}P는 국고로 전액 귀속되었습니다! (잔여: {user.points:,}P)"
        )

    db.commit()
    db.refresh(user)
    db.refresh(state)

    details = {
        "game_type": "race",
        "user_id": user.id,
        "username": user.username,
        "bet": bet,
        "choice": runner["name"],
        "choice_num": runner["num"],
        "won": won,
        "is_second": is_second,
        "p1": p1["name"],
        "p2": p2["name"],
        "p3": p3["name"],
        "p4": p4["name"],
        "ranking": [p1["num"], p2["num"], p3["num"], p4["num"]],
        "ranking_names": [p1["name"], p2["name"], p3["name"], p4["name"]],
        "net_payout": net_payout,
        "remaining_points": user.points,
        "treasury_pool": state.treasury_pool
    }
    return True, msg, details


# ==========================================
# 📈 18. 개인별 자산 히스토리 & 성장 추이 엔진 (User Asset History Engine)
# ==========================================

def calculate_user_net_worth(
    db: Session,
    user: User,
    current_price: Optional[float] = None
) -> Tuple[int, int, float, int]:
    """
    Calculate user's real-time net worth, cash, stock value, and debt.
    Returns: (net_worth, cash, stock_value, debt)
    """
    cash = getattr(user, "points", 0) or 0
    debt = getattr(user, "debt", 0) or 0
    stock_value = 0.0

    if current_price is None:
        state = get_market_state(db)
        current_price = state.current_price

    if getattr(user, "positions", None):
        for p in user.positions:
            if p.quantity > 0:
                val = calculate_position_valuation(p, current_price)
                stock_value += round(val["current_value"], 1)

    net_worth = int(round(cash + stock_value - debt))
    return net_worth, cash, stock_value, debt


def record_user_asset_snapshot(
    db: Session,
    user: User,
    event_type: str = "SNAPSHOT",
    note: str = "",
    force: bool = False
) -> Optional[UserAssetHistory]:
    """
    Records an asset snapshot into user_asset_history.
    Throttled to avoid duplicate entries unless force=True or event is significant.
    """
    if not user or not user.id:
        return None

    net_worth, cash, stock_val, debt = calculate_user_net_worth(db, user)
    credit_info = get_user_credit_info(user, db=db)
    score = credit_info.get("score", 500)

    # Throttling check for ordinary snapshots
    if not force and event_type not in ["INITIAL", "SETTLEMENT", "PVP_WIN", "PVP_LOSS", "LOAN", "REPAY", "TRADE"]:
        last = db.query(UserAssetHistory).filter_by(user_id=user.id).order_by(UserAssetHistory.id.desc()).first()
        if last and last.net_worth == net_worth and last.event_type == event_type:
            now_dt = datetime.now(timezone.utc)
            if last.created_at and (now_dt - last.created_at.replace(tzinfo=timezone.utc if last.created_at.tzinfo is None else None)).total_seconds() < 60:
                return last

    hist = UserAssetHistory(
        user_id=user.id,
        net_worth=net_worth,
        cash=cash,
        stock_value=stock_val,
        debt=debt,
        credit_score=score,
        event_type=event_type,
        note=note or "",
        created_at=datetime.now(timezone.utc)
    )
    db.add(hist)
    db.commit()
    db.refresh(hist)
    return hist


def seed_single_user_asset_history(db: Session, user: User, auto_commit: bool = True) -> List[UserAssetHistory]:
    """
    Generates a realistic 5~6 point milestone trend curve if user has 0 asset history records,
    so their individual asset line chart is immediately beautiful on first display.
    """
    existing = db.query(UserAssetHistory).filter_by(user_id=user.id).order_by(UserAssetHistory.id.asc()).all()
    if len(existing) >= 2:
        return existing

    curr_nw, curr_cash, curr_stock, curr_debt = calculate_user_net_worth(db, user)
    credit_info = get_user_credit_info(user, db=db)
    curr_score = credit_info.get("score", 500)
    now_dt = datetime.now(timezone.utc)

    # Initial anchor 24 hours ago
    t_minus_24 = now_dt - timedelta(hours=24)
    t_minus_18 = now_dt - timedelta(hours=18)
    t_minus_12 = now_dt - timedelta(hours=12)
    t_minus_6 = now_dt - timedelta(hours=6)
    t_minus_1 = now_dt - timedelta(hours=1)

    points = [
        UserAssetHistory(
            user_id=user.id,
            net_worth=50000,
            cash=50000,
            stock_value=0.0,
            debt=0,
            credit_score=500,
            event_type="INITIAL",
            note="가입 지원금 수령 (50,000P)",
            created_at=t_minus_24
        ),
        UserAssetHistory(
            user_id=user.id,
            net_worth=int(round(50000 + (curr_nw - 50000) * 0.18)),
            cash=int(round(50000 + (curr_cash - 50000) * 0.20)),
            stock_value=max(0.0, round(curr_stock * 0.15, 1)),
            debt=0,
            credit_score=520,
            event_type="MINE",
            note="초기 광산 채굴 및 포지션 진입",
            created_at=t_minus_18
        ),
        UserAssetHistory(
            user_id=user.id,
            net_worth=int(round(50000 + (curr_nw - 50000) * 0.48)),
            cash=int(round(50000 + (curr_cash - 50000) * 0.50)),
            stock_value=max(0.0, round(curr_stock * 0.45, 1)),
            debt=int(round(curr_debt * 0.3)),
            credit_score=max(300, min(900, int(500 + (curr_score - 500) * 0.45))),
            event_type="SETTLEMENT",
            note="마작 경기 1차 정산",
            created_at=t_minus_12
        ),
        UserAssetHistory(
            user_id=user.id,
            net_worth=int(round(50000 + (curr_nw - 50000) * 0.78)),
            cash=int(round(50000 + (curr_cash - 50000) * 0.75)),
            stock_value=max(0.0, round(curr_stock * 0.80, 1)),
            debt=int(round(curr_debt * 0.7)),
            credit_score=max(300, min(900, int(500 + (curr_score - 500) * 0.78))),
            event_type="TRADE",
            note="주식 매매 및 레버리지 운용",
            created_at=t_minus_6
        ),
        UserAssetHistory(
            user_id=user.id,
            net_worth=int(round(50000 + (curr_nw - 50000) * 0.94)),
            cash=int(round(50000 + (curr_cash - 50000) * 0.94)),
            stock_value=max(0.0, round(curr_stock * 0.94, 1)),
            debt=curr_debt,
            credit_score=curr_score,
            event_type="SETTLEMENT",
            note="직전 경기 정산",
            created_at=t_minus_1
        ),
        UserAssetHistory(
            user_id=user.id,
            net_worth=curr_nw,
            cash=curr_cash,
            stock_value=curr_stock,
            debt=curr_debt,
            credit_score=curr_score,
            event_type="SNAPSHOT",
            note="현재 자산 스냅샷",
            created_at=now_dt
        ),
    ]

    for p in points:
        db.add(p)
    if auto_commit:
        db.commit()

    return db.query(UserAssetHistory).filter_by(user_id=user.id).order_by(UserAssetHistory.id.asc()).all()


def seed_initial_asset_history_if_needed(db: Session):
    """Ensures all existing users have seeded asset history."""
    users = db.query(User).all()
    seeded = False
    for u in users:
        cnt = db.query(UserAssetHistory).filter_by(user_id=u.id).count()
        if cnt == 0:
            seed_single_user_asset_history(db, u, auto_commit=False)
            seeded = True
    if seeded:
        db.commit()


def get_user_asset_history(db: Session, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Fetches user asset history snapshot list."""
    entries = db.query(UserAssetHistory).filter_by(user_id=user_id).order_by(UserAssetHistory.id.asc()).all()
    if not entries:
        user = db.query(User).filter_by(id=user_id).first()
        if user:
            entries = seed_single_user_asset_history(db, user)

    return [
        {
            "id": e.id,
            "net_worth": e.net_worth,
            "cash": e.cash,
            "stock_value": round(e.stock_value, 1),
            "debt": e.debt,
            "credit_score": e.credit_score,
            "event_type": e.event_type,
            "note": e.note,
            "created_at": e.created_at.isoformat() if e.created_at else None
        }
        for e in entries[-limit:]
    ]


# ==========================================
# ⚔️ 19. 지하 투기장 1:1 맞짱 데스매치 엔진 (PvP Arena Engine)
# ==========================================

MIN_ARENA_BET: int = 1000
MAX_ARENA_BET: int = 10000000
ARENA_TAX_RATE: float = 0.02  # 2% 국고 수수료
CHALLENGE_TIMEOUT_SECONDS: int = 90
OPEN_MATCH_TIMEOUT_SECONDS: int = 180

PENDING_ARENA_CHALLENGES: Dict[str, Dict[str, Any]] = {}
OPEN_ARENA_MATCHES: Dict[str, Dict[str, Any]] = {}


def clean_expired_arena_challenges():
    """Removes expired pending challenges and open arena matches."""
    now_t = time.time()
    expired_t = [tid for tid, c in PENDING_ARENA_CHALLENGES.items() if now_t > c.get("expires_at", 0)]
    for tid in expired_t:
        PENDING_ARENA_CHALLENGES.pop(tid, None)

    expired_h = [hid for hid, m in OPEN_ARENA_MATCHES.items() if now_t > m.get("expires_at", 0)]
    for hid in expired_h:
        OPEN_ARENA_MATCHES.pop(hid, None)


def _parse_arena_bet(bet_str: str, user_points: int) -> Tuple[Optional[int], Optional[str]]:
    """Parses and validates arena bet string."""
    cleaned = str(bet_str or "").strip().lower().replace(",", "").replace("p", "").replace("원", "")
    if cleaned in ["올인", "all", "전액", "풀", "전부", "최대", "max"]:
        val = min(user_points, MAX_ARENA_BET)
        if val < MIN_ARENA_BET:
            return None, f"⚠️ 지하 투기장 최소 베팅금은 {MIN_ARENA_BET:,}P입니다. (현재 보유: {user_points:,}P)"
        return val, None

    multiplier = 1
    if cleaned.endswith("만"):
        multiplier = 10000
        cleaned = cleaned[:-1]
    elif cleaned.endswith("천"):
        multiplier = 1000
        cleaned = cleaned[:-1]
    elif cleaned.endswith("k"):
        multiplier = 1000
        cleaned = cleaned[:-1]
    elif cleaned.endswith("m"):
        multiplier = 1000000
        cleaned = cleaned[:-1]

    try:
        val = int(float(cleaned) * multiplier)
    except ValueError:
        return None, f"⚠️ 올바른 베팅 금액을 입력해주세요: '{bet_str}' (예: !대결 @닉네임 50000, !대결 @닉네임 5만)"

    if val < MIN_ARENA_BET:
        return None, f"⚠️ 지하 투기장 최소 베팅 금액은 {MIN_ARENA_BET:,}P입니다."
    if val > MAX_ARENA_BET:
        return None, f"⚠️ 지하 투기장 1회 최대 베팅 한도는 {MAX_ARENA_BET:,}P입니다. (입력: {val:,}P)"
    if user_points < val:
        return None, f"⚠️ 보유 포인트가 부족합니다! (보유: {user_points:,}P, 베팅: {val:,}P)"

    return val, None


def _execute_duel(
    db: Session,
    challenger: User,
    defender: User,
    bet: int,
    match_type: str = "DIRECT"
) -> Tuple[bool, str, Dict[str, Any]]:
    """Executes the 1d100 PvP duel resolution."""
    if challenger.points < bet:
        return False, f"⚠️ 도전자 {challenger.username}님의 보유 현금({challenger.points:,}P)이 베팅금({bet:,}P)보다 부족하여 대결이 취소되었습니다.", {}
    if defender.points < bet:
        return False, f"⚠️ 상대방 {defender.username}님의 보유 현금({defender.points:,}P)이 베팅금({bet:,}P)보다 부족하여 대결이 취소되었습니다.", {}

    state = get_market_state(db)
    if getattr(state, "treasury_pool", None) is None:
        state.treasury_pool = DEFAULT_TREASURY_POOL

    # Roll 1d100 for each player
    roll1 = random.randint(1, 100)
    roll2 = random.randint(1, 100)
    reroll_count = 0
    while roll1 == roll2 and reroll_count < 10:
        roll1 = random.randint(1, 100)
        roll2 = random.randint(1, 100)
        reroll_count += 1
    if roll1 == roll2:
        roll1 = min(100, roll1 + 1)

    if roll1 > roll2:
        winner, loser = challenger, defender
    else:
        winner, loser = defender, challenger

    pot_total = bet * 2
    tax_fee = int(math.ceil(pot_total * ARENA_TAX_RATE))
    winner_reward = pot_total - tax_fee
    net_profit = winner_reward - bet

    # Update points & treasury
    loser.points = max(0, loser.points - bet)
    winner.points += net_profit
    state.treasury_pool += tax_fee

    # Log match
    log_entry = ArenaMatchLog(
        challenger_id=challenger.id,
        challenger_name=challenger.username,
        defender_id=defender.id,
        defender_name=defender.username,
        bet_amount=bet,
        winner_id=winner.id,
        winner_name=winner.username,
        loser_id=loser.id,
        loser_name=loser.username,
        challenger_roll=roll1,
        defender_roll=roll2,
        pot_total=pot_total,
        winner_reward=winner_reward,
        tax_fee=tax_fee,
        match_type=match_type,
        created_at=datetime.now(timezone.utc)
    )
    db.add(log_entry)
    db.commit()
    db.refresh(winner)
    db.refresh(loser)
    db.refresh(state)

    # Record Asset History snapshots
    record_user_asset_snapshot(
        db, winner,
        event_type="PVP_WIN",
        note=f"⚔️ 투기장 승리 vs {loser.username} (+{net_profit:,}P)",
        force=True
    )
    record_user_asset_snapshot(
        db, loser,
        event_type="PVP_LOSS",
        note=f"⚔️ 투기장 패배 vs {winner.username} (-{bet:,}P)",
        force=True
    )

    reroll_txt = f" (🔥동점 재굴림 {reroll_count}회!)" if reroll_count > 0 else ""
    reply = (
        f"⚔️🩸 [지하 투기장 1:1 맞짱 데스매치 결과]{reroll_txt}\n"
        f"🎲 [{challenger.username}]: {roll1}점  vs  🎲 [{defender.username}]: {roll2}점\n"
        f"👑🏆 【승자: {winner.username}】 판돈 {pot_total:,}P 중 {winner_reward:,}P 독식! (순수익: +{net_profit:,}P | 잔여: {winner.points:,}P)\n"
        f"💀 【패자: {loser.username}】 -{bet:,}P 전액 손실 (잔여: {loser.points:,}P) | 🏛️ 국고 수수료 2%: {tax_fee:,}P"
    )

    details = {
        "event_type": "pvp_duel",
        "game_type": "pvp_duel",
        "challenger_id": challenger.id,
        "challenger_name": challenger.username,
        "defender_id": defender.id,
        "defender_name": defender.username,
        "bet": bet,
        "pot_total": pot_total,
        "challenger_roll": roll1,
        "defender_roll": roll2,
        "winner_id": winner.id,
        "winner_name": winner.username,
        "loser_id": loser.id,
        "loser_name": loser.username,
        "winner_reward": winner_reward,
        "net_profit": net_profit,
        "tax_fee": tax_fee,
        "match_type": match_type,
        "winner_points": winner.points,
        "loser_points": loser.points,
        "treasury_pool": state.treasury_pool
    }
    return True, reply, details


def create_pvp_challenge(
    db: Session,
    challenger_id: str,
    challenger_name: str,
    target_token: str,
    bet_token: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Issues a 1:1 direct duel challenge to another viewer."""
    clean_expired_arena_challenges()
    challenger = get_or_create_user(db, challenger_id, challenger_name)

    target_str = str(target_token or "").strip().lstrip("@")
    if not target_str:
        return False, "💡 대결 신청 사용법: !대결 @상대닉네임 [금액/올인] (예: !대결 @메루1 50000)", None

    bet, err = _parse_arena_bet(bet_token, challenger.points)
    if err:
        return False, err, None

    # Find target user
    target = db.query(User).filter(func.lower(User.username) == target_str.lower()).first()
    if not target:
        target = db.query(User).filter(User.id == target_str).first()
    if not target:
        target = db.query(User).filter(User.username.ilike(f"%{target_str}%")).first()

    if not target:
        return False, f"⚠️ 상대방 '{target_str}' 유저를 찾을 수 없습니다. (등록된 시청자 닉네임을 확인해주세요)", None

    if target.id == challenger.id:
        return False, "⚠️ 자기 자신에게는 대결을 신청할 수 없습니다!", None

    if target.points < bet:
        return False, f"⚠️ 상대방 {target.username}님의 보유 현금({target.points:,}P)이 베팅금({bet:,}P)보다 적어 대결을 신청할 수 없습니다.", None

    now_t = time.time()
    PENDING_ARENA_CHALLENGES[target.id] = {
        "challenger_id": challenger.id,
        "challenger_name": challenger.username,
        "target_id": target.id,
        "target_name": target.username,
        "bet": bet,
        "created_at": now_t,
        "expires_at": now_t + CHALLENGE_TIMEOUT_SECONDS
    }

    pot_total = bet * 2
    winner_share = int(round(pot_total * 0.98))
    tax_amt = pot_total - winner_share

    reply = (
        f"⚔️💥 [지하 투기장 1:1 맞짱 신청!] {challenger.username}님이 @{target.username}님에게 {bet:,}P 데스매치를 신청했습니다!\n"
        f"• 총 판돈: {pot_total:,}P (승자 98% 독식: {winner_share:,}P | 국고 수수료 2%: {tax_amt:,}P)\n"
        f"👉 @{target.username}님은 90초 이내에 '!수락' 또는 '!거절'을 입력해주세요!"
    )
    details = {
        "event_type": "pvp_challenge",
        "challenger_id": challenger.id,
        "challenger_name": challenger.username,
        "target_id": target.id,
        "target_name": target.username,
        "bet": bet,
        "pot_total": pot_total,
        "expires_at": now_t + CHALLENGE_TIMEOUT_SECONDS
    }
    return True, reply, details


def accept_pvp_challenge(
    db: Session,
    user_id: str,
    username: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Accepts a pending direct duel or an open public arena match."""
    clean_expired_arena_challenges()
    user = get_or_create_user(db, user_id, username)

    # 1. Direct challenge
    if user.id in PENDING_ARENA_CHALLENGES:
        challenge = PENDING_ARENA_CHALLENGES.pop(user.id)
        if time.time() > challenge["expires_at"]:
            return False, "⚠️ 결투 신청 시간이 만료되었습니다.", None
        challenger = db.query(User).filter_by(id=challenge["challenger_id"]).first()
        if not challenger:
            return False, "⚠️ 도전자를 찾을 수 없습니다.", None
        return _execute_duel(db, challenger, user, challenge["bet"], match_type="DIRECT")

    # 2. Open arena match
    for host_id, open_match in list(OPEN_ARENA_MATCHES.items()):
        if host_id != user.id and time.time() <= open_match["expires_at"]:
            if user.points < open_match["bet"]:
                return False, f"⚠️ 공개 투기장 참가에 필요한 베팅금({open_match['bet']:,}P)이 부족합니다. (보유: {user.points:,}P)", None
            OPEN_ARENA_MATCHES.pop(host_id, None)
            host = db.query(User).filter_by(id=host_id).first()
            if not host:
                return False, "⚠️ 개설자를 찾을 수 없습니다.", None
            return _execute_duel(db, host, user, open_match["bet"], match_type="OPEN")

    return False, (
        f"⚠️ 현재 {user.username}님에게 도착한 1:1 대결 신청이나 참가 가능한 공개 투기장이 없습니다!\n"
        f"💡 맞짱 신청: !대결 @상대닉네임 [금액] | 공개 투기장 개설: !투기장 오픈 [금액]"
    ), None


def decline_pvp_challenge(
    db: Session,
    user_id: str,
    username: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Declines a pending direct duel challenge."""
    clean_expired_arena_challenges()
    user = get_or_create_user(db, user_id, username)
    if user.id in PENDING_ARENA_CHALLENGES:
        challenge = PENDING_ARENA_CHALLENGES.pop(user.id)
        reply = f"💨 [결투 거절] {user.username}님이 {challenge['challenger_name']}님의 결투 신청을 정중히 거절하고 도망쳤습니다! 🏃💨"
        return True, reply, {"event_type": "pvp_declined", "target_id": user.id, "challenger_id": challenge["challenger_id"]}
    return False, f"⚠️ 현재 {user.username}님에게 도착한 대결 신청이 없습니다.", None


def open_public_arena_match(
    db: Session,
    user_id: str,
    username: str,
    bet_token: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Opens a public arena match for any viewer to challenge."""
    clean_expired_arena_challenges()
    user = get_or_create_user(db, user_id, username)
    bet, err = _parse_arena_bet(bet_token, user.points)
    if err:
        return False, err, None

    now_t = time.time()
    OPEN_ARENA_MATCHES[user.id] = {
        "host_id": user.id,
        "host_name": user.username,
        "bet": bet,
        "created_at": now_t,
        "expires_at": now_t + OPEN_MATCH_TIMEOUT_SECONDS
    }

    pot_total = bet * 2
    winner_share = int(round(pot_total * 0.98))
    reply = (
        f"⚔️🏟️ [지하 투기장 공개 결투장 개설!] {user.username}님이 판돈 {bet:,}P의 공개 결투를 열었습니다!\n"
        f"• 총 판돈: {pot_total:,}P (승자독식 98%: {winner_share:,}P | 180초 대기)\n"
        f"👉 누구나 '!투기장 참가' 또는 '!수락'을 입력하면 즉시 1:1 데스매치가 시작됩니다!"
    )
    details = {
        "event_type": "pvp_open",
        "host_id": user.id,
        "host_name": user.username,
        "bet": bet,
        "pot_total": pot_total,
        "expires_at": now_t + OPEN_MATCH_TIMEOUT_SECONDS
    }
    return True, reply, details


def join_public_arena_match(
    db: Session,
    user_id: str,
    username: str,
    target_host: Optional[str] = None
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Joins an open public arena match."""
    clean_expired_arena_challenges()
    user = get_or_create_user(db, user_id, username)

    matched_host_id = None
    if target_host:
        target_clean = str(target_host).strip().lstrip("@").lower()
        for hid, m in OPEN_ARENA_MATCHES.items():
            if (m["host_name"].lower() == target_clean or hid.lower() == target_clean) and hid != user.id:
                matched_host_id = hid
                break
    else:
        for hid, m in OPEN_ARENA_MATCHES.items():
            if hid != user.id:
                matched_host_id = hid
                break

    if not matched_host_id:
        return False, "⚠️ 현재 참가 가능한 공개 결투장이 없습니다! (개설: !투기장 오픈 [금액])", None

    open_match = OPEN_ARENA_MATCHES.pop(matched_host_id)
    if time.time() > open_match["expires_at"]:
        return False, "⚠️ 결투장 모집 시간이 만료되었습니다.", None

    if user.points < open_match["bet"]:
        return False, f"⚠️ 공개 투기장 참가에 필요한 베팅금({open_match['bet']:,}P)이 부족합니다. (보유: {user.points:,}P)", None

    host = db.query(User).filter_by(id=matched_host_id).first()
    if not host:
        return False, "⚠️ 개설자를 찾을 수 없습니다.", None

    return _execute_duel(db, host, user, open_match["bet"], match_type="OPEN")


def get_arena_status(db: Session) -> str:
    """Returns the current arena status, active open matches, and recent logs."""
    clean_expired_arena_challenges()
    lines = ["⚔️🏟️ [지하 투기장 1:1 맞짱 데스매치 현황]"]

    if OPEN_ARENA_MATCHES:
        lines.append("• 📢 현재 열려있는 공개 결투장:")
        for hid, m in list(OPEN_ARENA_MATCHES.items())[:3]:
            rem = max(0, int(m["expires_at"] - time.time()))
            lines.append(f"  └ [{m['host_name']}] 판돈 {m['bet']:,}P ({rem}초 남음) 👉 '!투기장 참가'")
    else:
        lines.append("• 📢 현재 대기 중인 공개 결투장이 없습니다. (!투기장 오픈 [금액])")

    if PENDING_ARENA_CHALLENGES:
        lines.append(f"• ⏳ 진행 중인 1:1 대결 신청: {len(PENDING_ARENA_CHALLENGES)}건")

    # Recent logs
    recent_logs = db.query(ArenaMatchLog).order_by(ArenaMatchLog.id.desc()).limit(3).all()
    if recent_logs:
        lines.append("• 📜 최근 전적:")
        for r in recent_logs:
            lines.append(f"  └ 👑 {r.winner_name} (+{r.winner_reward - r.bet_amount:,}P) vs 💀 {r.loser_name} (-{r.bet_amount:,}P)")

    lines.append("💡 명령어: !대결 @유저 [금액] | !수락 | !거절 | !투기장 오픈 [금액] | !투기장 참가")
    return "\n".join(lines)


# ---------------------------------------------------------
# Web Viewer Lounge / Desk Secure Authentication Engine
# ---------------------------------------------------------
ACTIVE_AUTH_CHALLENGES: Dict[str, Dict[str, Any]] = {}
WEB_AUTH_CHALLENGE_TIMEOUT_SECONDS = 180  # 3 minutes

PENDING_WEB_LOGIN_CODES: Dict[str, Dict[str, Any]] = {}
WEB_LOGIN_CODE_TIMEOUT_SECONDS = 300  # 5 minutes

LOGIN_FAILED_ATTEMPTS: Dict[str, List[float]] = {}
LOGIN_LOCKOUTS: Dict[str, float] = {}
MAX_LOGIN_FAILURES = 5
LOCKOUT_DURATION_SECONDS = 900  # 15 minutes


def create_web_auth_challenge() -> Dict[str, Any]:
    """
    Creates a new reverse authentication challenge for web login.
    User types '!인증 [code]' in Chzzk stream chat to authorize this web session.
    Completely eliminates public chat credential exposure & session hijacking.
    """
    now = time.time()
    # Purge expired challenges
    for k in list(ACTIVE_AUTH_CHALLENGES.keys()):
        if ACTIVE_AUTH_CHALLENGES[k]["expires_at"] < now:
            ACTIVE_AUTH_CHALLENGES.pop(k, None)

    active_codes = {v["code"] for v in ACTIVE_AUTH_CHALLENGES.values() if v["status"] == "PENDING"}
    code = None
    for _ in range(100):
        c = f"{random.randint(1000, 9999)}"
        if c not in active_codes:
            code = c
            break
    if not code:
        code = f"{random.randint(10000, 99999)}"

    challenge_id = uuid.uuid4().hex
    ACTIVE_AUTH_CHALLENGES[challenge_id] = {
        "challenge_id": challenge_id,
        "code": code,
        "created_at": now,
        "expires_at": now + WEB_AUTH_CHALLENGE_TIMEOUT_SECONDS,
        "status": "PENDING",
        "user_id": None,
        "username": None,
        "token": None
    }
    return {
        "challenge_id": challenge_id,
        "code": code,
        "command": f"!인증 {code}",
        "expires_in": WEB_AUTH_CHALLENGE_TIMEOUT_SECONDS
    }


def verify_chat_auth_challenge(db: Session, user_id: str, username: str, code: str) -> Tuple[bool, str, Optional[str]]:
    """
    Processes chat command '!인증 [code]' sent by user in streaming chat.
    Validates challenge and binds web session to the user.
    Returns (success, reply_message, session_token).
    """
    clean_code = str(code or "").strip()
    now = time.time()

    user = get_or_create_user(db, user_id, username)

    # Find matching pending challenge
    matched_id = None
    for ch_id, ch in ACTIVE_AUTH_CHALLENGES.items():
        if ch["code"] == clean_code and ch["status"] == "PENDING" and ch["expires_at"] >= now:
            matched_id = ch_id
            break

    if not matched_id:
        return False, "⚠️ 유효하지 않거나 만료된 인증 코드입니다! 웹 라운지 [🔑 로그인] 창에서 번호를 새로 확인해주세요.", None

    ch = ACTIVE_AUTH_CHALLENGES[matched_id]
    token = f"tk_{secrets.token_urlsafe(32)}"
    user.web_token = token
    db.commit()

    ch["status"] = "AUTHORIZED"
    ch["user_id"] = user.id
    ch["username"] = user.username
    ch["token"] = token

    return True, f"✅ [치즈나베] @{username} 님의 웹 라운지 인증이 완료되었습니다! 웹 화면으로 돌아가시면 자동 접속됩니다.", token


def poll_web_auth_challenge(db: Session, challenge_id: str) -> Dict[str, Any]:
    """
    Polls status of a web authentication challenge.
    Returns status: PENDING | AUTHORIZED | EXPIRED | INVALID
    """
    now = time.time()
    ch = ACTIVE_AUTH_CHALLENGES.get(challenge_id)
    if not ch:
        return {"status": "INVALID", "message": "존재하지 않는 인증 세션입니다."}

    if ch["status"] == "AUTHORIZED":
        user = db.query(User).filter_by(id=ch["user_id"]).first()
        token = ch["token"]
        # Consume challenge so it cannot be reused
        ACTIVE_AUTH_CHALLENGES.pop(challenge_id, None)
        return {
            "status": "AUTHORIZED",
            "token": token,
            "user_id": user.id if user else ch["user_id"],
            "username": user.username if user else ch["username"]
        }

    if ch["expires_at"] < now:
        ACTIVE_AUTH_CHALLENGES.pop(challenge_id, None)
        return {"status": "EXPIRED", "message": "인증 유효 시간이 만료되었습니다. 다시 시도해주세요."}

    return {
        "status": "PENDING",
        "remaining_sec": max(0, int(ch["expires_at"] - now))
    }


def check_login_lockout(key: str) -> Tuple[bool, int]:
    """Returns (is_locked, remaining_seconds)."""
    now = time.time()
    lock_until = LOGIN_LOCKOUTS.get(key, 0)
    if now < lock_until:
        return True, int(lock_until - now)
    return False, 0


def record_login_failure(key: str) -> Tuple[bool, int]:
    """Records a failed attempt. If >= 5 failures, locks out for 15 minutes."""
    now = time.time()
    if key not in LOGIN_FAILED_ATTEMPTS:
        LOGIN_FAILED_ATTEMPTS[key] = []
    # Keep attempts within last 10 minutes (600s)
    LOGIN_FAILED_ATTEMPTS[key] = [t for t in LOGIN_FAILED_ATTEMPTS[key] if now - t < 600]
    LOGIN_FAILED_ATTEMPTS[key].append(now)

    if len(LOGIN_FAILED_ATTEMPTS[key]) >= MAX_LOGIN_FAILURES:
        LOGIN_LOCKOUTS[key] = now + LOCKOUT_DURATION_SECONDS
        LOGIN_FAILED_ATTEMPTS.pop(key, None)
        return True, LOCKOUT_DURATION_SECONDS
    remaining_attempts = MAX_LOGIN_FAILURES - len(LOGIN_FAILED_ATTEMPTS[key])
    return False, remaining_attempts


def clear_login_failures(key: str):
    LOGIN_FAILED_ATTEMPTS.pop(key, None)
    LOGIN_LOCKOUTS.pop(key, None)


def generate_web_login_code(user_id: str, username: str) -> str:
    """Generates a 4-digit temporary login code for web viewer desk."""
    now = time.time()
    for k in list(PENDING_WEB_LOGIN_CODES.keys()):
        if PENDING_WEB_LOGIN_CODES[k]["expires_at"] < now:
            PENDING_WEB_LOGIN_CODES.pop(k, None)

    code = f"{random.randint(1000, 9999)}"
    PENDING_WEB_LOGIN_CODES[code] = {
        "user_id": user_id,
        "username": username,
        "expires_at": now + WEB_LOGIN_CODE_TIMEOUT_SECONDS
    }
    return code


def set_user_web_pin(db: Session, user_id: str, pin: str) -> Tuple[bool, str]:
    """Sets a permanent 4-digit PIN for web login."""
    clean_pin = re.sub(r"[^0-9]", "", str(pin or "")).strip()
    if len(clean_pin) != 4:
        return False, "⚠️ 비밀번호는 4자리 숫자(0000~9999)로 설정해주세요! (예: !비번 1234)"

    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        return False, "⚠️ 유저를 찾을 수 없습니다."

    user.web_pin = clean_pin
    db.commit()
    return True, f"🔐 [웹 비밀번호 설정 완료] @{user.username} 님의 4자리 PIN({clean_pin})이 안전하게 등록되었습니다!\n웹 라운지 로그인 시 닉네임과 이 비밀번호로 접속할 수 있습니다. (공개 채팅에 비밀번호를 노출하지 않도록 주의하세요!)"


def verify_web_login(
    db: Session,
    username_or_id: str,
    code_or_pin: str,
    client_ip: Optional[str] = None
) -> Tuple[bool, Optional[str], Optional[User], str]:
    """Verifies 4-digit code or permanent PIN with brute-force protection and lockout."""
    clean_target = str(username_or_id or "").strip().lstrip("@")
    clean_code = str(code_or_pin or "").strip()
    lock_key = f"{client_ip or 'unknown'}:{clean_target.lower()}"

    is_locked, rem_lock = check_login_lockout(lock_key)
    if is_locked:
        m, s = divmod(rem_lock, 60)
        return False, None, None, f"🚫 비밀번호 5회 연속 오류로 계정이 일시 잠겼습니다. ({m}분 {s}초 후 재시도 가능)"

    if not clean_target:
        return False, None, None, "⚠️ 닉네임 또는 채널 ID를 입력해주세요."
    if not clean_code:
        return False, None, None, "⚠️ 4자리 접속 코드 또는 비밀번호를 입력해주세요."

    user = get_user_by_identifier(db, clean_target)
    if not user:
        user = db.query(User).filter(func.lower(User.username) == clean_target.lower()).first()
    if not user:
        user = db.query(User).filter(User.id == clean_target).first()

    if not user:
        record_login_failure(lock_key)
        return False, None, None, f"⚠️ '{clean_target}' 시청자 정보를 찾을 수 없습니다."

    now = time.time()
    # 1. Check permanent 4-digit PIN
    if getattr(user, "web_pin", None) and str(user.web_pin).strip() == clean_code:
        clear_login_failures(lock_key)
        token = f"tk_{secrets.token_urlsafe(32)}"
        user.web_token = token
        db.commit()
        return True, token, user, "로그인에 성공했습니다!"

    # 2. Check one-time temporary code
    if clean_code in PENDING_WEB_LOGIN_CODES:
        entry = PENDING_WEB_LOGIN_CODES[clean_code]
        if entry["expires_at"] >= now:
            if entry["user_id"] == user.id or entry["username"].lower() == user.username.lower():
                PENDING_WEB_LOGIN_CODES.pop(clean_code, None)
                clear_login_failures(lock_key)
                token = f"tk_{secrets.token_urlsafe(32)}"
                user.web_token = token
                db.commit()
                return True, token, user, "로그인에 성공했습니다!"

    locked_now, rem = record_login_failure(lock_key)
    if locked_now:
        return False, None, None, "🚫 비밀번호 5회 연속 오류로 15분간 로그인이 잠겼습니다."
    return False, None, None, (
        f"⚠️ 비밀번호 또는 코드가 올바르지 않습니다. (남은 시도: {rem}회 / 5회 오류 시 15분 잠금)\n"
        f"💡 채팅창에 '!인증 [코드]'를 입력하는 [간편 채팅 인증]을 이용하시면 비밀번호 없이 1초만에 안전 로그인됩니다!"
    )


def get_user_by_token(db: Session, token: Optional[str]) -> Optional[User]:
    """Retrieves user by web session token."""
    if not token or not isinstance(token, str) or not token.startswith("tk_"):
        return None
    return db.query(User).filter_by(web_token=token).first()
    """Retrieves user by web session token."""
    if not token or not isinstance(token, str) or not token.startswith("tk_"):
        return None
    return db.query(User).filter_by(web_token=token).first()


def get_active_market_listings_data(
    db: Session,
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """Retrieves structured exchange listings for web marketplace GUI."""
    # Item Listings
    it_query = db.query(ItemListing).filter_by(status="ACTIVE").order_by(ItemListing.id.desc()).all()
    items = []
    my_listings = []

    for l in it_query:
        is_mine = bool(user_id and l.seller_id == user_id)
        if l.buyer_id and l.buyer_id != user_id and l.seller_id != user_id:
            continue

        item_dict = {
            "id": l.id,
            "token_id": f"I{l.id}",
            "type": "ITEM",
            "item_type": l.item_type,
            "item_name": l.item_name,
            "quantity": l.quantity,
            "price": l.price,
            "unit_price": l.price // l.quantity if l.quantity > 0 else l.price,
            "tax_fee": l.tax_fee,
            "seller_id": l.seller_id,
            "seller_name": l.seller_name,
            "buyer_id": l.buyer_id,
            "buyer_name": l.buyer_name,
            "is_direct": bool(l.buyer_id),
            "is_mine": is_mine,
            "created_at": l.created_at.isoformat() if l.created_at else None
        }
        items.append(item_dict)
        if is_mine:
            my_listings.append(item_dict)

    # Equipment Listings
    eq_query = db.query(EquipmentListing).filter_by(status="ACTIVE").order_by(EquipmentListing.id.desc()).all()
    equipments = []

    for l in eq_query:
        is_mine = bool(user_id and l.seller_id == user_id)
        if l.buyer_id and l.buyer_id != user_id and l.seller_id != user_id:
            continue

        eq = l.equipment
        lines = []
        if eq:
            for raw_l in [eq.potential_line_1, eq.potential_line_2, eq.potential_line_3]:
                if raw_l:
                    try:
                        p = json.loads(raw_l) if isinstance(raw_l, str) else raw_l
                        lines.append(p.get("text", str(p)) if isinstance(p, dict) else str(p))
                    except Exception:
                        lines.append(str(raw_l))
                else:
                    lines.append(None)

        eq_dict = {
            "id": l.id,
            "token_id": f"E{l.id}",
            "type": "EQUIPMENT",
            "equipment_id": l.equipment_id,
            "equipment_name": eq.name if eq else f"장비 #{l.equipment_id}",
            "starforce": eq.starforce if eq else 0,
            "potential_tier": (eq.potential_tier or "NONE").upper() if eq else "NONE",
            "potential_tier_display": CUBE_TIER_DISPLAY.get((eq.potential_tier or "NONE").upper(), "일반") if eq else "일반",
            "potential_lines": lines,
            "price": l.price,
            "tax_fee": l.tax_fee,
            "seller_id": l.seller_id,
            "seller_name": l.seller_name,
            "buyer_id": l.buyer_id,
            "buyer_name": l.buyer_name,
            "is_direct": bool(l.buyer_id),
            "is_mine": is_mine,
            "created_at": l.created_at.isoformat() if l.created_at else None
        }
        equipments.append(eq_dict)
        if is_mine:
            my_listings.append(eq_dict)

    return {
        "items": items,
        "equipments": equipments,
        "my_listings": my_listings,
        "total_active": len(items) + len(equipments)
    }


def get_arena_data(
    db: Session,
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """Retrieves structured PvP arena state for web desk GUI."""
    clean_expired_arena_challenges()
    now_t = time.time()

    open_matches = []
    for hid, m in list(OPEN_ARENA_MATCHES.items()):
        rem = max(0, int(m["expires_at"] - now_t))
        if rem <= 0:
            continue
        is_mine = bool(user_id and hid == user_id)
        open_matches.append({
            "host_id": hid,
            "host_name": m["host_name"],
            "bet": m["bet"],
            "pot_total": m.get("pot_total", m["bet"] * 2),
            "expires_in": rem,
            "is_mine": is_mine
        })

    pending_challenge = None
    if user_id and user_id in PENDING_ARENA_CHALLENGES:
        ch = PENDING_ARENA_CHALLENGES[user_id]
        rem = max(0, int(ch["expires_at"] - now_t))
        if rem > 0:
            pending_challenge = {
                "challenger_id": ch["challenger_id"],
                "challenger_name": ch["challenger_name"],
                "bet": ch["bet"],
                "pot_total": ch.get("pot_total", ch["bet"] * 2),
                "expires_in": rem
            }

    recent_logs = db.query(ArenaMatchLog).order_by(ArenaMatchLog.id.desc()).limit(10).all()
    recent_matches = []
    for r in recent_logs:
        recent_matches.append({
            "id": r.id,
            "winner_name": r.winner_name,
            "loser_name": r.loser_name,
            "challenger_roll": r.challenger_roll,
            "defender_roll": r.defender_roll,
            "bet_amount": r.bet_amount,
            "winner_reward": r.winner_reward,
            "tax_fee": r.tax_fee,
            "match_type": r.match_type,
            "created_at": r.created_at.isoformat() if r.created_at else None
        })

    return {
        "open_matches": open_matches,
        "pending_challenge": pending_challenge,
        "recent_matches": recent_matches
    }


# =====================================================================
# Central Bank (치즈나베 중앙은행) System Functions
# =====================================================================

def get_user_bank_info(*args, **kwargs) -> Dict[str, Any]:
    """Returns aggregated central bank status for a user (accepts (db, user), (user, db=db), (db=db, user=user))."""
    db = kwargs.get("db")
    user = kwargs.get("user")
    state = kwargs.get("state")

    for a in args:
        if isinstance(a, User) or (hasattr(a, "username") and hasattr(a, "points")):
            user = a
        elif isinstance(a, MarketState) or hasattr(a, "current_price"):
            state = a
        elif hasattr(a, "query") and hasattr(a, "commit"):
            db = a
        elif db is None:
            db = a
        elif user is None:
            user = a
        elif state is None:
            state = a

    if state is None and db is not None:
        try:
            state = get_market_state(db)
        except Exception:
            pass

    b_data = get_user_bank_data(user) if user else {}
    bank_balance = int(getattr(user, "bank_balance", 0) or 0) if user else 0
    debt = int(getattr(user, "debt", 0) or 0) if user else 0
    credit_info = get_user_credit_info(user, db=db, market_state=state) if user else {}

    # 1. Savings
    sav = b_data.get("savings")
    savings_info = None
    if sav and isinstance(sav, dict):
        total_dep = int(sav.get("total_deposited", 0))
        target_r = int(sav.get("target_rounds", 5))
        curr_r = int(sav.get("current_rounds", 0))
        bonus_pct = float(sav.get("bonus_pct", 0.20))
        est_bonus = int(round(total_dep * bonus_pct))
        progress_pct = round((curr_r / max(1, target_r)) * 100.0, 1)
        savings_info = {
            "plan_name": sav.get("plan_name", "정기적금"),
            "bonus_pct": bonus_pct,
            "bonus_pct_display": f"+{int(bonus_pct * 100)}%",
            "per_round": int(sav.get("per_round", 0)),
            "target_rounds": target_r,
            "current_rounds": curr_r,
            "total_deposited": total_dep,
            "missed_rounds": int(sav.get("missed_rounds", 0)),
            "estimated_bonus": est_bonus,
            "estimated_payout": total_dep + est_bonus,
            "progress_pct": min(100.0, progress_pct)
        }

    # 2. Diversified Funds
    navs = get_all_fund_navs(state)
    funds_dict = b_data.get("funds", {})
    if not isinstance(funds_dict, dict):
        funds_dict = {}

    # Migration for legacy single-fund data
    legacy_units = float(b_data.get("fund_units", 0.0) or 0.0)
    legacy_invested = int(b_data.get("fund_invested", 0) or 0)
    if legacy_units > 0 and "index" not in funds_dict:
        funds_dict["index"] = {"units": legacy_units, "invested": legacy_invested}
        b_data["funds"] = funds_dict
        save_user_bank_data(user, b_data)

    funds_portfolio = {}
    total_fund_val = 0
    total_fund_invested = 0

    for fid, fdef in DIVERSIFIED_FUNDS.items():
        f_nav = float(navs.get(fid, fdef.get("initial_nav", 1000.0)))
        u_hold = funds_dict.get(fid, {})
        u_units = float(u_hold.get("units", 0.0) or 0.0)
        u_inv = int(u_hold.get("invested", 0) or 0)
        u_val = int(round(u_units * f_nav))
        u_pnl = u_val - u_inv
        u_pnl_pct = round((u_pnl / u_inv * 100.0), 2) if u_inv > 0 else 0.0

        total_fund_val += u_val
        total_fund_invested += u_inv

        funds_portfolio[fid] = {
            "id": fid,
            "name": fdef["name"],
            "risk_tier": fdef["risk_tier"],
            "risk_stars": fdef["risk_stars"],
            "desc": fdef["desc"],
            "beginner_guide": fdef["beginner_guide"],
            "min_invest": fdef["min_invest"],
            "nav": f_nav,
            "units": round(u_units, 4),
            "invested": u_inv,
            "valuation": u_val,
            "pnl": u_pnl,
            "pnl_pct": u_pnl_pct
        }

    # Primary fund (index) for backwards compatibility
    idx_fund = funds_portfolio.get("index", {})
    fund_info = {
        "nav": idx_fund.get("nav", 1000.0),
        "units": idx_fund.get("units", 0.0),
        "invested": idx_fund.get("invested", 0),
        "valuation": idx_fund.get("valuation", 0),
        "pnl": idx_fund.get("pnl", 0),
        "pnl_pct": idx_fund.get("pnl_pct", 0.0)
    }

    # 3. Insurance
    ins = b_data.get("insurance")
    insurance_info = None
    if ins and isinstance(ins, dict) and ins.get("active"):
        insurance_info = {
            "active": True,
            "plan_id": ins.get("plan_id", "standard"),
            "plan_name": ins.get("plan_name", "표준형 플랜"),
            "claims_left": int(ins.get("claims_left", 1)),
            "matches_left": int(ins.get("matches_left", 5)),
            "coverage_amount": int(ins.get("coverage_amount", 1000000))
        }

    available_savings = [
        {"rounds": p["rounds"], "name": p["name"], "bonus_pct": p["bonus_pct"], "bonus_label": f"+{int(p['bonus_pct']*100)}%", "min": p["min_per_round"], "max": p["max_per_round"], "desc": p["desc"]}
        for p in SAVINGS_PLANS.values()
    ]
    available_insurance = [
        {"id": p["id"], "name": p["name"], "cost": p["cost"], "coverage": p["coverage"], "desc": p["desc"]}
        for p in INSURANCE_PLANS.values()
    ]

    return {
        "bank_balance": bank_balance,
        "points": user.points,
        "interest_rate_pct": 0.5,
        "savings": savings_info,
        "fund": fund_info,
        "funds": funds_portfolio,
        "total_fund_valuation": total_fund_val,
        "total_fund_invested": total_fund_invested,
        "total_fund_pnl": total_fund_val - total_fund_invested,
        "insurance": insurance_info,
        "credit": credit_info,
        "debt": debt,
        "available_savings_plans": available_savings,
        "available_insurance_plans": available_insurance,
        "available_funds": list(funds_portfolio.values()),
        "last_maturity_notice": b_data.get("last_maturity_notice"),
        "special_snipe_scrolls": get_user_special_snipe_scrolls(user)
    }


def execute_bank_deposit(
    db: Session,
    user_id: str,
    username: str,
    amount_str: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Deposit cash into demand deposit (!입금 [금액/올인])."""
    user = get_or_create_user(db, user_id, username)
    clean_amt = (amount_str or "").strip().lower().replace(",", "").replace("p", "").replace("원", "")

    if clean_amt in ["올인", "all", "전액", "전부", "다", "최대", "max"]:
        amt = user.points
    else:
        try:
            amt = int(clean_amt)
        except (ValueError, TypeError):
            return False, "⚠️ 올바른 입금 금액을 입력해주세요. (예: !입금 50000, !입금 올인)", None

    if amt <= 0:
        return False, "⚠️ 입금 금액은 1P 이상이어야 합니다.", None

    if user.points < amt:
        return False, f"⚠️ 보유 포인트가 부족합니다! (보유: {user.points:,}P | 요청: {amt:,}P)", None

    user.points -= amt
    user.bank_balance = (getattr(user, "bank_balance", 0) or 0) + amt
    db.commit()
    db.refresh(user)

    reply = (
        f"🏛️💰 [중앙은행 보통예금 입금 완료] {user.username}님이 {amt:,}P를 보통예금 계좌에 입금하셨습니다!\n"
        f"• 보통예금 잔액: {user.bank_balance:,}P (경기 종료마다 +0.5% 복리 이자 지급)\n"
        f"• 보유 현금: {user.points:,}P"
    )
    details = {
        "user_id": user.id,
        "username": user.username,
        "deposit_amount": amt,
        "bank_balance": user.bank_balance,
        "points": user.points
    }
    return True, reply, details


def execute_bank_withdraw(
    db: Session,
    user_id: str,
    username: str,
    amount_str: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Withdraw cash from demand deposit (!출금 [금액/전액])."""
    user = get_or_create_user(db, user_id, username)
    clean_amt = (amount_str or "").strip().lower().replace(",", "").replace("p", "").replace("원", "")
    cur_bank = getattr(user, "bank_balance", 0) or 0

    if clean_amt in ["올인", "all", "전액", "전부", "다", "최대", "max"]:
        amt = cur_bank
    else:
        try:
            amt = int(clean_amt)
        except (ValueError, TypeError):
            return False, "⚠️ 올바른 출금 금액을 입력해주세요. (예: !출금 50000, !출금 전액)", None

    if amt <= 0:
        return False, "⚠️ 출금 금액은 1P 이상이어야 합니다.", None

    if cur_bank < amt:
        return False, f"⚠️ 보통예금 잔액이 부족합니다! (예금 잔액: {cur_bank:,}P | 요청: {amt:,}P)", None

    user.bank_balance = cur_bank - amt
    user.points += amt
    db.commit()
    db.refresh(user)

    reply = (
        f"🏛️💸 [중앙은행 보통예금 출금 완료] {user.username}님이 {amt:,}P를 현금으로 인출하셨습니다!\n"
        f"• 보통예금 잔액: {user.bank_balance:,}P | 보유 현금: {user.points:,}P"
    )
    details = {
        "user_id": user.id,
        "username": user.username,
        "withdraw_amount": amt,
        "bank_balance": user.bank_balance,
        "points": user.points
    }
    return True, reply, details


def execute_open_savings(
    db: Session,
    user_id: str,
    username: str,
    per_round_str: str,
    rounds_str: str = "5"
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Start installment savings (!적금 [회당금액] [3/5/10/20 또는 스피드/표준/고래/연금])."""
    user = get_or_create_user(db, user_id, username)
    b_data = get_user_bank_data(user)

    if b_data.get("savings"):
        sav = b_data["savings"]
        return False, (
            f"⚠️ 이미 가입 중인 정기적금이 있습니다! ({sav.get('plan_name', '적금')} {sav.get('current_rounds', 0)}/{sav.get('target_rounds', 5)}회차 진행 중 | "
            f"누적: {sav.get('total_deposited', 0):,}P | 해지: !적금 해지)"
        ), None

    try:
        per_round = int((per_round_str or "").strip().lower().replace(",", "").replace("p", "").replace("원", ""))
    except (ValueError, TypeError):
        return False, "⚠️ 올바른 회당 납입 금액을 입력해주세요. (예: !적금 10000 5, !적금 50000 고래)", None

    plan = resolve_savings_plan(rounds_str)
    rounds = plan["rounds"]
    min_amt = plan["min_per_round"]
    max_amt = plan["max_per_round"]
    bonus_pct = plan["bonus_pct"]
    bonus_label = f"+{int(bonus_pct * 100)}%"

    if per_round < min_amt or per_round > max_amt:
        return False, f"⚠️ [{plan['name']}] 회당 납입금은 {min_amt:,}P ~ {max_amt:,}P 사이로 설정 가능합니다.", None

    # 1st installment deduction
    paid_from = "points"
    if user.points >= per_round:
        user.points -= per_round
    elif (getattr(user, "bank_balance", 0) or 0) >= per_round:
        user.bank_balance -= per_round
        paid_from = "bank_balance"
    else:
        return False, f"⚠️ 적금 1회차 납입금({per_round:,}P)이 부족합니다! (보유: {user.points:,}P, 예금: {getattr(user, 'bank_balance', 0):,}P)", None

    b_data["savings"] = {
        "plan_name": plan["name"],
        "bonus_pct": bonus_pct,
        "per_round": per_round,
        "target_rounds": rounds,
        "current_rounds": 1,
        "total_deposited": per_round,
        "missed_rounds": 0,
        "created_at": time.time()
    }
    save_user_bank_data(user, b_data)
    db.commit()
    db.refresh(user)

    est_bonus = int(round(per_round * rounds * bonus_pct))
    est_total = (per_round * rounds) + est_bonus
    reply = (
        f"🏛️📅 [{plan['name']} 가입 완료] {user.username}님 매 경기 {per_round:,}P 적립 ({rounds}회 만기) 플랜 시작!\n"
        f"• 1회차 납입 완료 (1/{rounds}회 | 납입: {per_round:,}P)\n"
        f"• 만기 예상 보너스: {bonus_label} ({est_bonus:,}P 특별 보너스 이자!) ➔ 만기 수령액: {est_total:,}P\n"
        f"• 매 경기 마작 정산 시 보유 현금(부족 시 예금)에서 자동 차감 적립됩니다."
    )
    details = {
        "plan_name": plan["name"],
        "bonus_pct": bonus_pct,
        "per_round": per_round,
        "target_rounds": rounds,
        "current_rounds": 1,
        "total_deposited": per_round,
        "estimated_payout": est_total
    }
    return True, reply, details


def execute_cancel_savings(
    db: Session,
    user_id: str,
    username: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Cancel installment savings early (!적금 해지)."""
    user = get_or_create_user(db, user_id, username)
    b_data = get_user_bank_data(user)
    sav = b_data.get("savings")
    if not sav:
        return False, "⚠️ 현재 가입 중인 정기적금이 없습니다.", None

    refund = int(sav.get("total_deposited", 0))
    user.bank_balance = (getattr(user, "bank_balance", 0) or 0) + refund
    del b_data["savings"]
    save_user_bank_data(user, b_data)
    db.commit()
    db.refresh(user)

    reply = (
        f"🏛️🔒 [정기적금 중도해지 완료] {user.username}님의 정기적금이 해지되었습니다.\n"
        f"• 납입 원금 {refund:,}P가 보통예금 계좌로 전액 환급되었습니다. (중도해지 시 만기 보너스 이자 미지급)\n"
        f"• 보통예금 잔액: {user.bank_balance:,}P"
    )
    return True, reply, {"refund": refund, "bank_balance": user.bank_balance}


def execute_buy_fund(
    db: Session,
    user_id: str,
    username: str,
    amount_str: str,
    fund_str: str = "index"
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Invest points in diversified fund (!펀드매수 [금액/올인] [지수/배당/야수/인프라])."""
    user = get_or_create_user(db, user_id, username)
    state = get_market_state(db)
    clean_amt = (amount_str or "").strip().lower().replace(",", "").replace("p", "").replace("원", "")

    if clean_amt in ["올인", "all", "전액", "전부", "다", "최대", "max"]:
        amt = user.points
    else:
        try:
            amt = int(clean_amt)
        except (ValueError, TypeError):
            return False, "⚠️ 올바른 펀드 매수 금액을 입력해주세요. (예: !펀드매수 50000, !펀드매수 올인 배당)", None

    plan = resolve_fund_plan(fund_str)
    min_inv = plan["min_invest"]

    if amt < min_inv:
        return False, f"⚠️ [{plan['name']}] 최소 투자 금액은 {min_inv:,}P입니다.", None

    if user.points < amt:
        return False, f"⚠️ 보유 포인트가 부족합니다! (보유: {user.points:,}P | 요청: {amt:,}P)", None

    navs = get_all_fund_navs(state)
    cur_nav = float(navs.get(plan["id"], plan["initial_nav"]))
    units_bought = round(amt / cur_nav, 4)

    user.points -= amt
    b_data = get_user_bank_data(user)
    funds = b_data.get("funds", {})
    if not isinstance(funds, dict):
        funds = {}

    fid = plan["id"]
    u_hold = funds.get(fid, {"units": 0.0, "invested": 0})
    new_units = round(float(u_hold.get("units", 0.0) or 0.0) + units_bought, 4)
    new_invested = int(u_hold.get("invested", 0) or 0) + amt
    funds[fid] = {"units": new_units, "invested": new_invested}
    b_data["funds"] = funds

    # Legacy field sync for primary index fund
    if fid == "index":
        b_data["fund_units"] = new_units
        b_data["fund_invested"] = new_invested

    save_user_bank_data(user, b_data)
    db.commit()
    db.refresh(user)

    valuation = int(round(new_units * cur_nav))
    reply = (
        f"🏛️📊 [{plan['name']} 매수 완료] {user.username}님이 {amt:,}P를 투자하여 {units_bought:,.4f}좌를 매수하셨습니다!\n"
        f"• 기준가(NAV): {cur_nav:,.2f}P | 총 보유: {new_units:,.4f}좌 (평가금: {valuation:,}P)\n"
        f"• 위험도: {plan['risk_stars']} ({plan['risk_tier']}) | {plan['desc']}"
    )
    details = {
        "fund_id": fid,
        "fund_name": plan["name"],
        "invested": amt,
        "units_bought": units_bought,
        "nav": cur_nav,
        "total_units": new_units,
        "valuation": valuation
    }
    return True, reply, details


def execute_sell_fund(
    db: Session,
    user_id: str,
    username: str,
    units_str: str = "전부",
    fund_str: str = "index"
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Sell/Redeem units of a diversified fund (!펀드환매 [좌수/전부] [지수/배당/야수/인프라])."""
    user = get_or_create_user(db, user_id, username)
    state = get_market_state(db)
    b_data = get_user_bank_data(user)
    plan = resolve_fund_plan(fund_str)
    fid = plan["id"]

    funds = b_data.get("funds", {})
    u_hold = funds.get(fid, {}) if isinstance(funds, dict) else {}
    cur_units = float(u_hold.get("units", 0.0) or 0.0)

    # Legacy check for index fund
    if cur_units <= 0.0001 and fid == "index":
        cur_units = float(b_data.get("fund_units", 0.0) or 0.0)

    if cur_units <= 0.0001:
        return False, f"⚠️ 보유 중인 [{plan['name']}] 좌수가 없습니다. (보유: 0.0000좌)", None

    clean_u = (units_str or "").strip().lower().replace("좌", "").replace("개", "")
    if clean_u in ["올인", "all", "전액", "전부", "다", "최대", "max", ""]:
        units_to_sell = cur_units
    else:
        try:
            units_to_sell = float(clean_u)
        except (ValueError, TypeError):
            return False, "⚠️ 올바른 환매 좌수를 입력해주세요. (예: !펀드환매 10.5, !펀드환매 전부)", None

    if units_to_sell <= 0:
        return False, "⚠️ 환매 좌수는 0보다 커야 합니다.", None

    units_to_sell = min(cur_units, units_to_sell)
    navs = get_all_fund_navs(state)
    cur_nav = float(navs.get(fid, plan["initial_nav"]))
    payout = int(round(units_to_sell * cur_nav))

    # Cost basis deduction
    orig_invested = int(u_hold.get("invested", 0) or b_data.get("fund_invested", 0) or 0)
    cost_basis = int(round(orig_invested * (units_to_sell / cur_units))) if cur_units > 0 else orig_invested
    pnl = payout - cost_basis

    rem_units = round(max(0.0, cur_units - units_to_sell), 4)
    rem_inv = max(0, orig_invested - cost_basis)

    if not isinstance(funds, dict):
        funds = {}
    funds[fid] = {"units": rem_units, "invested": rem_inv}
    b_data["funds"] = funds

    if fid == "index":
        b_data["fund_units"] = rem_units
        b_data["fund_invested"] = rem_inv

    save_user_bank_data(user, b_data)
    user.points += payout
    db.commit()
    db.refresh(user)

    pnl_sign = f"+{pnl:,}" if pnl >= 0 else f"{pnl:,}"
    reply = (
        f"🏛️📊 [{plan['name']} 환매 완료] {user.username}님이 {units_to_sell:,.4f}좌를 환매하여 {payout:,}P를 수령하셨습니다!\n"
        f"• 기준가(NAV): {cur_nav:,.2f}P | 실현 손익: {pnl_sign}P | 남은 펀드: {rem_units:,.4f}좌\n"
        f"• 보유 현금: {user.points:,}P"
    )
    details = {
        "fund_id": fid,
        "fund_name": plan["name"],
        "units_sold": units_to_sell,
        "payout": payout,
        "pnl": pnl,
        "nav": cur_nav,
        "remaining_units": rem_units
    }
    return True, reply, details


def execute_buy_insurance(
    db: Session,
    user_id: str,
    username: str,
    plan_str: str = "standard"
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Purchase Starforce Destruction Insurance (!보험 가입 [실속/표준/프리미엄/VVIP])."""
    user = get_or_create_user(db, user_id, username)
    b_data = get_user_bank_data(user)
    ins = b_data.get("insurance")

    if ins and isinstance(ins, dict) and ins.get("active") and ins.get("claims_left", 0) > 0:
        return False, (
            f"⚠️ 이미 유효한 [{ins.get('plan_name', '파괴안심보험')}]에 가입되어 있습니다!\n"
            f"• 잔여 경기: {ins.get('matches_left', 0)}경기 | 보장 횟수: {ins.get('claims_left', 0)}회 | 보장금: {ins.get('coverage_amount', 1000000):,}P"
        ), None

    plan = resolve_insurance_plan(plan_str)
    cost = plan["cost"]
    coverage = plan["coverage"]

    if user.points < cost:
        return False, f"⚠️ [{plan['name']}] 보험료({cost:,}P)가 부족합니다! (보유: {user.points:,}P)", None

    user.points -= cost
    state = get_market_state(db)
    state.treasury_pool = (getattr(state, "treasury_pool", 0.0) or 0.0) + cost

    b_data["insurance"] = {
        "active": True,
        "plan_id": plan["id"],
        "plan_name": plan["name"],
        "claims_left": plan["claims"],
        "matches_left": plan["matches"],
        "coverage_amount": coverage,
        "bought_at": time.time()
    }
    save_user_bank_data(user, b_data)
    db.commit()
    db.refresh(user)

    reply = (
        f"🏥🛡️ [{plan['name']} 가입 완료] {user.username}님 보험 가입 완료!\n"
        f"• 보험료: {cost:,}P | 보장 기간: 앞으로 {plan['matches']}경기 동안 유효\n"
        f"• 보장 혜택: 15성 이상 스타포스 강화 실패로 곡괭이가 폭발 파괴될 경우, 즉시 보통예금으로 위로 보상금 {coverage:,}P 지급!\n"
        f"• 고성수 강화 도전을 안심하고 즐기세요!"
    )
    return True, reply, b_data["insurance"]





