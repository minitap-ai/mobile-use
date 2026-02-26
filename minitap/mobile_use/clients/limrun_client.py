"""
Limrun client wrapper for iOS WebSocket communication.

This module ports the TypeScript SDK's iOS client functionality to Python,
providing WebSocket-based communication with Limrun iOS instances.
"""

import asyncio
import base64
import json
import time
from collections.abc import Callable
from enum import StrEnum

import websockets
from pydantic import BaseModel, Field
from websockets.asyncio.client import ClientConnection

from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


class ConnectionState(StrEnum):
    """Connection state of the instance client."""

    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"


class ScreenshotData(BaseModel):
    """Screenshot response data."""

    base64: str
    width: int
    height: int


class DeviceInfo(BaseModel):
    """Device information fetched during client initialization."""

    udid: str
    screen_width: float = Field(alias="screenWidth")
    screen_height: float = Field(alias="screenHeight")
    model: str

    class Config:
        populate_by_name = True


class InstalledApp(BaseModel):
    """Information about an installed app."""

    bundle_id: str = Field(alias="bundleId")
    name: str
    install_type: str = Field(alias="installType")

    class Config:
        populate_by_name = True


class AccessibilitySelector(BaseModel):
    """Selector criteria for finding accessibility elements."""

    accessibility_id: str | None = Field(default=None, alias="accessibilityId")
    label: str | None = None
    label_contains: str | None = Field(default=None, alias="labelContains")
    element_type: str | None = Field(default=None, alias="elementType")
    title: str | None = None
    title_contains: str | None = Field(default=None, alias="titleContains")
    value: str | None = None

    class Config:
        populate_by_name = True


class TapElementResult(BaseModel):
    """Result from tapping an element."""

    element_label: str | None = Field(default=None, alias="elementLabel")
    element_type: str | None = Field(default=None, alias="elementType")

    class Config:
        populate_by_name = True


class LimrunIosClient:
    """
    A client for interacting with a Limrun iOS instance via WebSocket.

    This is a Python port of the TypeScript SDK's iOS client functionality.
    """

    def __init__(
        self,
        api_url: str,
        token: str,
    ):
        self.api_url = api_url
        self.token = token

        self._ws: ClientConnection | None = None
        self._connection_state = ConnectionState.DISCONNECTED
        self._intentional_disconnect = False
        self._pending_requests: dict[str, asyncio.Future] = {}
        self._state_change_callbacks: list[Callable[[ConnectionState], None]] = []
        self._device_info: DeviceInfo | None = None
        self._ping_task: asyncio.Task | None = None
        self._receive_task: asyncio.Task | None = None
        self._request_counter = 0

    @property
    def device_info(self) -> DeviceInfo:
        """Get cached device info."""
        if self._device_info is None:
            raise RuntimeError("Device info not available. Call connect() first.")
        return self._device_info

    @property
    def connection_state(self) -> ConnectionState:
        """Get current connection state."""
        return self._connection_state

    def _generate_id(self) -> str:
        """Generate a unique request ID."""
        self._request_counter += 1
        return f"py-client-{int(time.time() * 1000)}-{self._request_counter}"

    def _get_ws_url(self) -> str:
        """Get the WebSocket URL for signaling."""
        url = self.api_url.replace("https://", "wss://").replace("http://", "ws://")
        return f"{url}/signaling?token={self.token}"

    def _update_connection_state(self, new_state: ConnectionState) -> None:
        """Update connection state and notify callbacks."""
        if self._connection_state != new_state:
            self._connection_state = new_state
            logger.debug(f"Connection state changed to: {new_state}")
            for callback in self._state_change_callbacks:
                try:
                    callback(new_state)
                except Exception as e:
                    logger.error(f"Error in connection state callback: {e}")

    async def connect(self) -> None:
        """Connect to the Limrun iOS instance."""
        self._intentional_disconnect = False
        self._update_connection_state(ConnectionState.CONNECTING)

        ws_url = self._get_ws_url()
        logger.debug(f"Connecting to {ws_url}")

        try:
            self._ws = await websockets.connect(ws_url)
            self._update_connection_state(ConnectionState.CONNECTED)
            self._reconnect_attempts = 0

            self._receive_task = asyncio.create_task(self._receive_loop())
            self._ping_task = asyncio.create_task(self._ping_loop())

            self._device_info = await self._fetch_device_info()
            logger.info(f"Connected to Limrun iOS instance: {self._device_info.model}")

        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            self._update_connection_state(ConnectionState.DISCONNECTED)
            raise

    async def disconnect(self) -> None:
        """Disconnect from the Limrun iOS instance."""
        self._intentional_disconnect = True

        if self._ping_task:
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass
            self._ping_task = None

        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        if self._ws:
            await self._ws.close()
            self._ws = None

        self._fail_pending_requests("Intentional disconnect")
        self._update_connection_state(ConnectionState.DISCONNECTED)
        logger.debug("Disconnected from Limrun iOS instance")

    async def cleanup(self) -> None:
        """Cleanup resources."""
        await self.disconnect()

    async def _ping_loop(self) -> None:
        """Send periodic pings to keep connection alive."""
        while True:
            try:
                await asyncio.sleep(30)
                if self._ws:
                    await self._ws.ping()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Ping error: {e}")

    async def _receive_loop(self) -> None:
        """Receive and process messages from WebSocket."""
        try:
            while self._ws:
                try:
                    message = await self._ws.recv()
                    await self._handle_message(message)
                except websockets.ConnectionClosed:
                    logger.debug("WebSocket connection closed")
                    break
                except Exception as e:
                    logger.error(f"Error receiving message: {e}")
                    break
        except asyncio.CancelledError:
            pass
        finally:
            if not self._intentional_disconnect:
                self._update_connection_state(ConnectionState.DISCONNECTED)
                self._fail_pending_requests("Connection closed")

    async def _handle_message(self, raw_message: str | bytes) -> None:
        """Handle incoming WebSocket message."""
        try:
            if isinstance(raw_message, bytes):
                raw_message = raw_message.decode("utf-8")
            message = json.loads(raw_message)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse message: {e}")
            return

        msg_type = message.get("type", "")
        msg_id = message.get("id", "")

        if msg_id in self._pending_requests:
            future = self._pending_requests.pop(msg_id)

            if message.get("error"):
                future.set_exception(RuntimeError(message["error"]))
            else:
                future.set_result(message)
        else:
            logger.debug(f"Received message without pending request: {msg_type}")

    def _fail_pending_requests(self, reason: str) -> None:
        """Fail all pending requests with an error."""
        for future in self._pending_requests.values():
            if not future.done():
                future.set_exception(RuntimeError(reason))
        self._pending_requests.clear()

    async def _send_request(
        self,
        msg_type: str,
        params: dict | None = None,
        timeout: float | None = None,
    ) -> dict:
        """Send a request and wait for response."""
        if not self._ws:
            raise RuntimeError("WebSocket is not connected")

        request_id = self._generate_id()
        request = {"type": msg_type, "id": request_id, **(params or {})}

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = future

        try:
            await self._ws.send(json.dumps(request))
            result = await asyncio.wait_for(future, timeout=timeout or 30.0)
            return result
        except TimeoutError:
            self._pending_requests.pop(request_id, None)
            raise RuntimeError(f"Request {msg_type} timed out")
        except Exception:
            self._pending_requests.pop(request_id, None)
            raise

    async def _fetch_device_info(self) -> DeviceInfo:
        """Fetch device info from the instance."""
        response = await self._send_request("deviceInfo")
        return DeviceInfo(
            udid=response["udid"],
            screenWidth=response["screenWidth"],
            screenHeight=response["screenHeight"],
            model=response["model"],
        )

    async def screenshot(self) -> bytes:
        """Take a screenshot and return raw image bytes."""
        response = await self._send_request("screenshot")
        base64_data = response.get("base64", "")
        return base64.b64decode(base64_data)

    async def screenshot_data(self) -> ScreenshotData:
        """Take a screenshot and return structured data."""
        response = await self._send_request("screenshot")
        return ScreenshotData(
            base64=response["base64"],
            width=response["width"],
            height=response["height"],
        )

    async def element_tree(self, point: tuple[float, float] | None = None) -> str:
        """Get the element tree (accessibility hierarchy) as JSON string."""
        params = {"point": {"x": point[0], "y": point[1]}} if point else {}
        response = await self._send_request("elementTree", params, timeout=60.0)
        return response.get("json", "")

    async def tap(self, x: float, y: float, duration: float | None = None) -> None:
        """Tap at the specified coordinates."""
        params = {
            "x": x,
            "y": y,
            "screenWidth": self.device_info.screen_width,
            "screenHeight": self.device_info.screen_height,
        }
        if duration is not None:
            params["duration"] = duration
        await self._send_request("tap", params)

    async def tap_element(self, selector: AccessibilitySelector) -> TapElementResult:
        """Tap an accessibility element by selector."""
        response = await self._send_request(
            "tapElement", {"selector": selector.model_dump(by_alias=True, exclude_none=True)}
        )
        return TapElementResult(
            elementLabel=response.get("elementLabel"),
            elementType=response.get("elementType"),
        )

    async def text(self, text: str, press_enter: bool = False) -> bool:
        """Type text into the currently focused input field."""
        try:
            await self._send_request("typeText", {"text": text, "pressEnter": press_enter})
            return True
        except Exception as e:
            logger.error(f"Failed to type text: {e}")
            return False

    async def key(self, key_code: int) -> None:
        """Press a key by key code."""
        await self._send_request("pressKey", {"key": str(key_code)})

    async def press_key(self, key: str, modifiers: list[str] | None = None) -> None:
        """Press a key with optional modifiers."""
        params: dict = {"key": key}
        if modifiers:
            params["modifiers"] = modifiers
        await self._send_request("pressKey", params)

    async def launch(self, bundle_id: str) -> bool:
        """Launch an app by bundle ID."""
        try:
            await self._send_request("launchApp", {"bundleId": bundle_id})
            return True
        except Exception as e:
            logger.error(f"Failed to launch app: {e}")
            return False

    async def terminate(self, bundle_id: str) -> bool:
        """Terminate an app by bundle ID."""
        try:
            await self._send_request("terminateApp", {"bundleId": bundle_id})
            return True
        except Exception as e:
            logger.error(f"Failed to terminate app: {e}")
            return False

    async def open_url(self, url: str) -> bool:
        """Open a URL."""
        try:
            await self._send_request("openUrl", {"url": url})
            return True
        except Exception as e:
            logger.error(f"Failed to open URL: {e}")
            return False

    async def list_apps(self) -> list[InstalledApp]:
        """List installed apps."""
        response = await self._send_request("listApps")
        apps_json = response.get("apps", "[]")
        apps_data = json.loads(apps_json) if isinstance(apps_json, str) else apps_json
        return [InstalledApp(**app) for app in apps_data]

    async def swipe(
        self,
        x_start: float,
        y_start: float,
        x_end: float,
        y_end: float,
        duration: float = 0.4,
    ) -> None:
        """Swipe from start to end coordinates."""
        direction = self._calculate_swipe_direction(x_start, y_start, x_end, y_end)
        pixels = self._calculate_swipe_distance(x_start, y_start, x_end, y_end)

        await self._send_request(
            "scroll",
            {
                "direction": direction,
                "pixels": int(pixels),
                "coordinate": [x_start, y_start],
                "momentum": min(1.0, duration),
            },
        )

    def _calculate_swipe_direction(
        self, x_start: float, y_start: float, x_end: float, y_end: float
    ) -> str:
        """Calculate scroll direction from swipe coordinates.

        Limrun uses scroll semantics: "down" scrolls content down (reveals content below).
        A swipe from bottom to top (y_start > y_end) should scroll "down".
        """
        dx = x_end - x_start
        dy = y_end - y_start

        if abs(dx) > abs(dy):
            return "left" if dx > 0 else "right"
        else:
            # Invert: swipe up (dy < 0) = scroll down, swipe down (dy > 0) = scroll up
            return "down" if dy < 0 else "up"

    def _calculate_swipe_distance(
        self, x_start: float, y_start: float, x_end: float, y_end: float
    ) -> float:
        """Calculate swipe distance."""
        dx = x_end - x_start
        dy = y_end - y_start
        return (dx**2 + dy**2) ** 0.5

    async def describe_all(self) -> list[dict]:
        """Get accessibility info for all elements (flat list)."""
        element_tree_json = await self.element_tree()
        if not element_tree_json:
            return []
        try:
            return json.loads(element_tree_json)
        except json.JSONDecodeError:
            return []

    async def set_orientation(self, orientation: str) -> None:
        """Set device orientation ('Portrait' or 'Landscape')."""
        await self._send_request("setOrientation", {"orientation": orientation})

    async def scroll(
        self,
        direction: str,
        pixels: int,
        coordinate: tuple[float, float] | None = None,
        momentum: float = 0.0,
    ) -> None:
        """Scroll in a direction."""
        params: dict = {"direction": direction, "pixels": pixels}
        if coordinate:
            params["coordinate"] = list(coordinate)
        if momentum:
            params["momentum"] = momentum
        await self._send_request("scroll", params)

    async def install_app(self, url: str, md5: str | None = None) -> dict:
        """Install an app from a URL."""
        params: dict = {"url": url}
        if md5:
            params["md5"] = md5
        response = await self._send_request("appInstallation", params, timeout=120.0)
        return {
            "url": response.get("url", ""),
            "bundleId": response.get("bundleId", ""),
        }

    def on_connection_state_change(
        self, callback: Callable[[ConnectionState], None]
    ) -> Callable[[], None]:
        """Register a callback for connection state changes."""
        self._state_change_callbacks.append(callback)
        return lambda: self._state_change_callbacks.remove(callback)
