import os
import json
import time
import asyncio
import urllib.parse
from typing import Optional, Dict, Any, Callable
import httpx
import websockets
from dotenv import load_dotenv

from chzzk_api import chzzk_api

load_dotenv()
DEFAULT_CHANNEL_ID = os.getenv("CHANNEL_ID", "4495f96624a2c60bd1ed5a6139014d20")

class ChzzkSessionWorker:
    """
    Manages the official Chzzk OpenAPI Socket.IO / WebSocket session.
    1. Requests official session URL via chzzk_api.create_session_url()
    2. Connects to the Engine.IO v3 / Socket.IO server via WebSocket
    3. Handles Engine.IO ping/pong heartbeats ('2' -> '3')
    4. Upon receiving SYSTEM 'connected' event, captures sessionKey and subscribes to DONATION events
    5. Dispatches real-time DONATION events to the trading engine and OBS overlays
    6. Automatically reconnects with exponential backoff on disconnects
    """
    def __init__(
        self,
        channel_id: Optional[str] = None,
        on_donation: Optional[Callable[[Dict[str, Any]], Any]] = None,
        fallback_bot: Optional[Any] = None
    ):
        self.channel_id = channel_id or DEFAULT_CHANNEL_ID
        self.on_donation = on_donation
        self.fallback_bot = fallback_bot

        self.session_key: Optional[str] = None
        self.session_mode: Optional[str] = None  # 'user' or 'client'
        self.ws = None
        self.is_running = False
        self.is_connected = False
        self.subscribed_donation = False
        self.last_error: Optional[str] = None
        self.last_donation: Optional[Dict[str, Any]] = None
        self.reconnect_delay = 5
        self._task: Optional[asyncio.Task] = None

    def get_status(self) -> Dict[str, Any]:
        """Returns diagnostic status of the official session socket connection."""
        return {
            "is_running": self.is_running,
            "is_connected": self.is_connected,
            "session_mode": self.session_mode,
            "session_key": self.session_key,
            "channel_id": self.channel_id,
            "subscribed_donation": self.subscribed_donation,
            "last_error": self.last_error,
            "last_donation": self.last_donation
        }

    async def subscribe_donation_event(self) -> bool:
        """Subscribes the active session to real-time donation events for channel_id."""
        if not self.session_key:
            self.last_error = "세션 키가 없어 후원 이벤트를 구독할 수 없습니다."
            return False

        ok, msg = await chzzk_api.subscribe_session_event(
            session_key=self.session_key,
            event_type="donation",
            channel_id=self.channel_id
        )
        if ok:
            self.subscribed_donation = True
            self.last_error = None
            print(f"[ChzzkSession] 🎯 치지직 후원(DONATION) 이벤트 구독 성공! (채널: {self.channel_id}, 세션: {self.session_key})")
            return True
        else:
            self.last_error = f"후원 이벤트 구독 실패: {msg}"
            print(f"[ChzzkSession] ⚠️ {self.last_error}")
            return False

    async def handle_socket_event(self, payload_str: str):
        """Processes incoming Socket.IO events (e.g. 42["EVENT_NAME", data] or ["EVENT_NAME", data])."""
        if payload_str.startswith("42"):
            payload_str = payload_str[2:]
        try:
            arr = json.loads(payload_str)
            if not isinstance(arr, list) or len(arr) < 2:
                return
            event_name = arr[0]
            event_data = arr[1]
            if isinstance(event_data, str):
                try:
                    event_data = json.loads(event_data)
                except Exception:
                    pass
        except Exception as e:
            print(f"[ChzzkSession] ⚠️ 소켓 이벤트 파싱 예외: {e} (원본: {payload_str[:120]})")
            return

        if event_name == "SYSTEM":
            # SYSTEM messages: e.g. {"type": "connected", "data": {"sessionKey": "..."}}
            # or {"type": "subscribed", "data": {...}}
            ev_type = event_data.get("type") if isinstance(event_data, dict) else None
            data = event_data.get("data", {}) if isinstance(event_data, dict) else {}

            if ev_type == "connected":
                self.session_key = data.get("sessionKey")
                self.is_connected = True
                print(f"[ChzzkSession] 🔑 치지직 세션키 획득: {self.session_key}")
                # Immediately subscribe to donation events
                await self.subscribe_donation_event()

            elif ev_type == "subscribed":
                self.subscribed_donation = True
                print(f"[ChzzkSession] ✅ 치지직 서버 구독 확인 응답 (type: subscribed): {event_data}")

            elif ev_type == "unsubscribed":
                self.subscribed_donation = False
                print(f"[ChzzkSession] ⚠️ 치지직 이벤트 구독 해제됨: {event_data}")

            elif ev_type == "revoked":
                self.subscribed_donation = False
                self.last_error = f"이벤트 권한 취소: {event_data}"
                print(f"[ChzzkSession] ❌ 치지직 이벤트 권한 취소: {event_data}")

        elif event_name == "DONATION":
            print(f"[ChzzkSession] 🎁 [공식 후원 수신] {event_data}")
            self.last_donation = event_data if isinstance(event_data, dict) else {"raw": event_data}
            if self.on_donation and isinstance(event_data, dict):
                try:
                    res = self.on_donation(event_data)
                    if asyncio.iscoroutine(res):
                        await res
                except Exception as e:
                    print(f"[ChzzkSession] ❌ 후원 콜백 실행 에러: {e}")

        else:
            # Other events like CHAT, SUBSCRIPTION, etc.
            pass

    async def connect_and_listen(self):
        """Creates session URL, connects websocket, and listens for events."""
        ok, session_url, mode_or_err = await chzzk_api.create_session_url()
        if not ok or not session_url:
            self.last_error = f"세션 URL 발급 불가: {mode_or_err}"
            print(f"[ChzzkSession] ⚠️ {self.last_error}")
            return False

        self.session_mode = mode_or_err
        parsed = urllib.parse.urlparse(session_url)
        qs = urllib.parse.parse_qs(parsed.query)
        auth_token = qs.get("auth", [""])[0]

        ws_url = f"wss://{parsed.netloc}/socket.io/?EIO=3&transport=websocket&auth={auth_token}"
        print(f"[ChzzkSession] 🔌 치지직 공식 세션 소켓 연결 중 ({self.session_mode} 모드): {parsed.netloc}")

        async with websockets.connect(ws_url, ping_interval=None) as ws:
            self.ws = ws
            self.is_connected = True
            self.last_error = None
            self.reconnect_delay = 5  # Reset backoff upon successful connect
            print("[ChzzkSession] 🔗 치지직 공식 세션 소켓 연결 수립 완료")

            async for raw_msg in ws:
                if isinstance(raw_msg, bytes):
                    raw_msg = raw_msg.decode("utf-8", errors="ignore")

                # Engine.IO Heartbeat Ping: server sends '2', client replies '3' (Pong)
                if raw_msg == "2":
                    await ws.send("3")
                    continue

                # Engine.IO Handshake response (0{...})
                if raw_msg.startswith("0"):
                    continue

                # Socket.IO connected (40)
                if raw_msg == "40":
                    continue

                # Socket.IO Event message (42[...])
                if raw_msg.startswith("42"):
                    await self.handle_socket_event(raw_msg[2:])

    async def run(self):
        """Continuous background runner with auto-reconnection and exponential backoff."""
        self.is_running = True
        while self.is_running:
            try:
                await self.connect_and_listen()
            except asyncio.CancelledError:
                print("[ChzzkSession] ⏹️ 세션 워커 작업 종료")
                break
            except Exception as e:
                self.is_connected = False
                self.subscribed_donation = False
                self.last_error = f"연결 끊김 또는 에러: {e}"
                print(f"[ChzzkSession] ⚠️ {self.last_error}. {self.reconnect_delay}초 후 재접속합니다...")

            self.is_connected = False
            self.subscribed_donation = False
            await asyncio.sleep(self.reconnect_delay)
            self.reconnect_delay = min(self.reconnect_delay * 1.5, 30.0)

    async def reconnect(self):
        """Force close active session socket to trigger immediate reconnect and event subscription."""
        print("[ChzzkSession] 🔄 새 토큰 적용을 위해 세션 소켓 즉시 재연결...")
        self.reconnect_delay = 1
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass

    def stop(self):
        self.is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
