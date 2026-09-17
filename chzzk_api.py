import os
import json
import asyncio
from typing import Optional, Dict, Any, Tuple, List
import httpx
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("CLIENT_ID", "")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "")
CHANNEL_ID = os.getenv("CHANNEL_ID", "")

TOKENS_FILE = os.path.join(os.path.dirname(__file__), "tokens.json")

class ChzzkApiClient:
    """
    Manages Chzzk Official Open API authentication (OAuth2) and chat sending.
    Also coordinates with fallback websocket bot if tokens are expired.
    """
    def __init__(self):
        self.client_id = CLIENT_ID
        self.client_secret = CLIENT_SECRET
        self.channel_id = CHANNEL_ID
        self.tokens: Dict[str, Any] = self.load_tokens()
        self._lock = asyncio.Lock()

    def load_tokens(self) -> Dict[str, Any]:
        """Load tokens from tokens.json if present."""
        if os.path.exists(TOKENS_FILE):
            try:
                with open(TOKENS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[ChzzkAPI] ⚠️ tokens.json 읽기 실패: {e}")
        return {}

    def save_tokens(self, tokens: Dict[str, Any]):
        """Persist tokens to tokens.json, merging with any existing values."""
        merged = dict(self.tokens or {})
        merged.update(tokens)
        self.tokens = merged
        self._openapi_disabled = False
        self._openapi_send_disabled = False
        self._not_streamer_warned = False
        try:
            with open(TOKENS_FILE, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
            print("[ChzzkAPI] 💾 tokens.json 저장 완료")
        except Exception as e:
            print(f"[ChzzkAPI] ❌ tokens.json 저장 실패: {e}")

    @property
    def access_token(self) -> Optional[str]:
        return self.tokens.get("accessToken")

    @access_token.setter
    def access_token(self, val: Optional[str]):
        if val is None:
            self.tokens.pop("accessToken", None)
        else:
            self.tokens["accessToken"] = val
        self.save_tokens(self.tokens)

    @property
    def refresh_token(self) -> Optional[str]:
        return self.tokens.get("refreshToken")

    def get_auth_url(self, redirect_uri: str, state: str = "chzzk_auth") -> str:
        """Generate official Chzzk OAuth Account Interlock URL."""
        return (
            f"https://chzzk.naver.com/account-interlock"
            f"?clientId={self.client_id}&redirectUri={redirect_uri}&state={state}"
        )

    async def exchange_code(self, code: str, state: str = "chzzk_auth") -> Tuple[bool, str]:
        """Exchange authorization code for Access & Refresh tokens."""
        clean_code = (code or "").strip()
        if "code=" in clean_code:
            try:
                import urllib.parse
                parsed = urllib.parse.urlparse(clean_code)
                qs = urllib.parse.parse_qs(parsed.query or parsed.path)
                if "code" in qs:
                    clean_code = qs["code"][0]
                if "state" in qs and (not state or state == "chzzk_auth"):
                    state = qs["state"][0]
            except Exception:
                pass

        url = "https://openapi.chzzk.naver.com/auth/v1/token"
        payload = {
            "grantType": "authorization_code",
            "clientId": self.client_id,
            "clientSecret": self.client_secret,
            "code": clean_code,
            "state": state or "chzzk_auth"
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
                if res.status_code == 200:
                    data = res.json()
                    # Official token endpoint returns either top-level or {"content": {...}}
                    token_data = data.get("content") if (isinstance(data.get("content"), dict) and data.get("content").get("accessToken")) else data
                    if token_data.get("accessToken"):
                        self._openapi_disabled = False
                        self.save_tokens(token_data)
                        print(f"[ChzzkAPI] ✅ Access Token 신규 발급 성공 (만료: {token_data.get('expiresIn', 86400)}초)")
                        return True, "토큰 발급 성공"
                return False, f"토큰 발급 실패 (상태 코드: {res.status_code}, {res.text})"
        except Exception as e:
            return False, f"토큰 교환 요청 에러: {e}"

    async def refresh_token_if_needed(self) -> bool:
        """Refresh access token using refreshToken and Client ID/Secret."""
        rf = self.refresh_token
        if not rf or not self.client_id or not self.client_secret:
            return False

        async with self._lock:
            url = "https://openapi.chzzk.naver.com/auth/v1/token"
            payload = {
                "grantType": "refresh_token",
                "refreshToken": rf,
                "clientId": self.client_id,
                "clientSecret": self.client_secret
            }
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    res = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
                    if res.status_code == 200:
                        data = res.json()
                        token_data = data.get("content") if (isinstance(data.get("content"), dict) and data.get("content").get("accessToken")) else data
                        if token_data.get("accessToken"):
                            self.save_tokens(token_data)
                            print("[ChzzkAPI] 🔄 Access Token 자동 갱신 성공")
                            return True
                    print(f"[ChzzkAPI] ❌ 토큰 갱신 실패 ({res.status_code}): {res.text}")
                    return False
            except Exception as e:
                print(f"[ChzzkAPI] ❌ 토큰 갱신 통신 에러: {e}")
                return False

    @property
    def is_openapi_available(self) -> bool:
        if getattr(self, "_openapi_disabled", False):
            return False
        return bool(self.access_token)

    async def send_single_message_openapi(self, message: str) -> bool:
        """
        Send a single message (<= 100 characters) via official Open API:
        POST https://openapi.chzzk.naver.com/open/v1/chats/send
        """
        if getattr(self, "_openapi_disabled", False) or getattr(self, "_openapi_send_disabled", False):
            return False
        acc = self.access_token
        if not acc:
            return False

        # Max length in Chzzk Open API is 100 characters
        trimmed_msg = message[:100]
        url = "https://openapi.chzzk.naver.com/open/v1/chats/send"
        headers = {
            "Authorization": f"Bearer {acc}",
            "Content-Type": "application/json"
        }

        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.post(url, headers=headers, json={"message": trimmed_msg})
                if res.status_code == 200:
                    return True

                # When the authorized account is a bot/viewer rather than the channel streamer
                if res.status_code == 400 and "스트리머가 아닙니다" in res.text:
                    if not getattr(self, "_not_streamer_warned", False):
                        print("[ChzzkAPI] ℹ️ 현재 OAuth 연동 계정(봇/매니저 계정)은 스트리머 권한이 없으므로, 채팅은 ChzzkBot 웹소켓 전용 모드로 자동 전환됩니다.")
                        self._not_streamer_warned = True
                    self._openapi_send_disabled = True
                    return False

                # If 401 Unauthorized, try refreshing token once
                if res.status_code == 401:
                    print("[ChzzkAPI] ⚠️ 401 INVALID_TOKEN 감지 -> 토큰 갱신 시도 중...")
                    refreshed = await self.refresh_token_if_needed()
                    if refreshed and self.access_token:
                        headers["Authorization"] = f"Bearer {self.access_token}"
                        retry_res = await client.post(url, headers=headers, json={"message": trimmed_msg})
                        if retry_res.status_code == 200:
                            return True
                    else:
                        print("[ChzzkAPI] ⚠️ 토큰 갱신 실패로 openapi 비활성화 -> WebSocket 세션 전담 모드 전환")
                        self._openapi_disabled = True
                        self.access_token = None
                print(f"[ChzzkAPI] ❌ 오픈 API 전송 실패 ({res.status_code}): {res.text}")
                return False
        except Exception as e:
            print(f"[ChzzkAPI] ❌ 오픈 API 전송 예외: {e}")
            return False

    async def create_session_url(self) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Requests socket session connection URL:
        1. Attempts User session (GET /open/v1/sessions/auth) with Access Token.
        2. If 401 or invalid, tries token refresh.
        3. Falls back to Client session (GET /open/v1/sessions/auth/client) with Client-Id & Client-Secret.
        Returns: (success, session_url, mode_or_error)
        """
        acc = self.access_token
        if acc:
            url = "https://openapi.chzzk.naver.com/open/v1/sessions/auth"
            headers = {
                "Authorization": f"Bearer {acc}",
                "Content-Type": "application/json"
            }
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    res = await client.get(url, headers=headers)
                    if res.status_code == 200:
                        data = res.json()
                        content = data.get("content", {}) or data
                        session_url = content.get("url")
                        if session_url:
                            return True, session_url, "user"
                    elif res.status_code == 401:
                        print("[ChzzkAPI] ⚠️ 유저 세션 401 -> 토큰 갱신 시도 중...")
                        refreshed = await self.refresh_token_if_needed()
                        if refreshed and self.access_token:
                            headers["Authorization"] = f"Bearer {self.access_token}"
                            res2 = await client.get(url, headers=headers)
                            if res2.status_code == 200:
                                data = res2.json()
                                content = data.get("content", {}) or data
                                session_url = content.get("url")
                                if session_url:
                                    return True, session_url, "user"
            except Exception as e:
                print(f"[ChzzkAPI] ⚠️ 유저 세션 URL 요청 실패: {e}")

        # Fallback to Client Session
        if self.client_id and self.client_secret:
            client_url = "https://openapi.chzzk.naver.com/open/v1/sessions/auth/client"
            headers = {
                "Client-Id": self.client_id,
                "Client-Secret": self.client_secret,
                "Content-Type": "application/json"
            }
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    res = await client.get(client_url, headers=headers)
                    if res.status_code == 200:
                        data = res.json()
                        content = data.get("content", {}) or data
                        session_url = content.get("url")
                        if session_url:
                            return True, session_url, "client"
                        return False, None, f"클라이언트 세션 URL 미포함: {res.text}"
                    return False, None, f"클라이언트 세션 발급 실패 ({res.status_code}): {res.text}"
            except Exception as e:
                return False, None, f"클라이언트 세션 통신 에러: {e}"

        return False, None, "유효한 치지직 인증 정보가 없습니다 (Access Token 또는 Client ID/Secret 필요)"

    async def subscribe_session_event(
        self,
        session_key: str,
        event_type: str = "donation",
        channel_id: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Subscribes to session events:
        POST https://openapi.chzzk.naver.com/open/v1/sessions/events/subscribe/{event_type}
        event_type: 'donation' | 'chat' | 'subscription'
        Query param: sessionKey, channelId
        """
        cid = channel_id or self.channel_id
        url = f"https://openapi.chzzk.naver.com/open/v1/sessions/events/subscribe/{event_type}"
        params = {"sessionKey": session_key}
        if cid and event_type != "donation":
            params["channelId"] = cid

        headers = {}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        if self.client_id and self.client_secret:
            headers["Client-Id"] = self.client_id
            headers["Client-Secret"] = self.client_secret

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, headers=headers, params=params)
                if res.status_code in [200, 201]:
                    return True, f"'{event_type}' 이벤트 구독 성공 (채널: {cid})"
                
                # If 401 Unauthorized, try refreshing token once
                if res.status_code == 401 and self.refresh_token:
                    print(f"[ChzzkAPI] ⚠️ 이벤트 구독 중 401 감지 -> 토큰 갱신 후 재시도...")
                    refreshed = await self.refresh_token_if_needed()
                    if refreshed and self.access_token:
                        headers["Authorization"] = f"Bearer {self.access_token}"
                        retry_res = await client.post(url, headers=headers, params=params)
                        if retry_res.status_code in [200, 201]:
                            return True, f"'{event_type}' 이벤트 구독 성공 (토큰 갱신 완료)"
                
                return False, f"구독 요청 실패 ({res.status_code}): {res.text}"
        except Exception as e:
            return False, f"구독 요청 에러: {e}"

    def get_status(self) -> Dict[str, Any]:
        """Return diagnostic status of Chzzk API setup."""
        has_id = bool(self.client_id)
        has_secret = bool(self.client_secret)
        has_token = bool(self.access_token)
        has_refresh = bool(self.refresh_token)
        expires_in = self.tokens.get("expiresIn")
        scope = self.tokens.get("scope", "")

        return {
            "has_client_id": has_id,
            "has_client_secret": has_secret,
            "has_access_token": has_token,
            "has_refresh_token": has_refresh,
            "expires_in": expires_in,
            "scope": scope,
            "is_configured": has_id and has_secret
        }

# Singleton instance
chzzk_api = ChzzkApiClient()

def split_message_into_chunks(text: str, max_chars: int = 100) -> List[str]:
    """
    Splits a multi-line or long message into chunks of <= max_chars.
    Respects newline boundaries first so bullet points/lines stay legible.
    """
    lines = [line.strip() for line in text.strip().split("\n") if line.strip()]
    chunks: List[str] = []

    for line in lines:
        if len(line) <= max_chars:
            chunks.append(line)
        else:
            # Line is longer than max_chars, split by spaces or length
            words = line.split(" ")
            current_chunk = ""
            for word in words:
                if not current_chunk:
                    current_chunk = word
                elif len(current_chunk) + 1 + len(word) <= max_chars:
                    current_chunk += " " + word
                else:
                    chunks.append(current_chunk)
                    current_chunk = word
            if current_chunk:
                chunks.append(current_chunk)

    return chunks

async def dispatch_chat_notice(text: str, fallback_bot: Optional[Any] = None) -> bool:
    """
    High-level dispatch function for bot announcements.
    1. Splits multi-line responses into <= 100 char chunks.
    2. Tries official Open API with CLIENT_ID / CLIENT_SECRET.
    3. If Open API is unavailable or expired, seamlessly falls back to the live WebSocket session.
    """
    if not text:
        return False

    chunks = split_message_into_chunks(text, max_chars=100)
    all_success = True

    for chunk in chunks:
        sent = False
        # 1. Attempt Official OpenAPI
        if chzzk_api.is_openapi_available:
            sent = await chzzk_api.send_single_message_openapi(chunk)
            if sent:
                print(f"[ChzzkAPI] 🌐 [OpenAPI 체결/안내 전송] {chunk}")

        # 2. Fallback to active WebSocket session
        if not sent and fallback_bot and getattr(fallback_bot, "send_chat", None):
            try:
                res = await fallback_bot.send_chat(chunk)
                if res is not False:
                    print(f"[ChzzkAPI] 🤖 [Websocket 세션 안내 전송] {chunk}")
                    sent = True
            except Exception as e:
                print(f"[ChzzkAPI] ❌ WebSocket 폴백 전송 실패: {e}")

        if not sent:
            all_success = False

        # Brief pause between multiple messages to avoid chat rate limits
        if len(chunks) > 1:
            await asyncio.sleep(0.35)

    return all_success
