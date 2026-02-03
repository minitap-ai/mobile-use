"""
Limrun device controller implementation.

Supports both Android (via ADB forwarding with SDK-based WebSocket tunnel) and iOS (via WebSocket).
"""

import asyncio
import base64
import re
import shlex
from io import BytesIO

from adbutils import AdbClient
from idb.common.types import HIDButtonType
from PIL import Image

from minitap.mobile_use.clients.adb_tunnel import AdbTunnel
from minitap.mobile_use.clients.idb_client import IOSAppInfo
from minitap.mobile_use.clients.limrun_client import LimrunIosClient
from minitap.mobile_use.clients.ui_automator_client import UIAutomatorClient
from minitap.mobile_use.controllers.device_controller import (
    MobileDeviceController,
    ScreenDataResponse,
)
from minitap.mobile_use.controllers.types import Bounds, CoordinatesSelectorRequest, TapOutput
from minitap.mobile_use.utils.logger import get_logger
from minitap.mobile_use.utils.video import DEFAULT_MAX_DURATION_SECONDS, VideoRecordingResult

logger = get_logger(__name__)


class LimrunAndroidController(MobileDeviceController):
    """
    Limrun Android controller using ADB forwarding via SDK-based WebSocket tunnel.

    Uses the Python SDK's AdbTunnel to establish ADB tunnel, then uses standard
    ADB/UIAutomator2 for device interaction.
    """

    def __init__(
        self,
        instance_id: str,
        adb_ws_url: str,
        endpoint_ws_url: str,
        token: str,
    ):
        self.instance_id = instance_id
        self.adb_ws_url = adb_ws_url
        self.endpoint_ws_url = endpoint_ws_url
        self.token = token
        self.device_width: int = 0
        self.device_height: int = 0

        self._adb_client: AdbClient | None = None
        self._ui_client: UIAutomatorClient | None = None
        self._tunnel: AdbTunnel | None = None
        self._adb_serial: str | None = None

    async def connect(self) -> None:
        """Establish ADB tunnel using SDK and connect."""
        logger.info(f"Connecting to Limrun Android instance {self.instance_id}")

        try:
            self._tunnel = AdbTunnel(
                remote_url=self.adb_ws_url,
                token=self.token,
            )

            tunnel_addr = await self._tunnel.start()
            logger.info(f"ADB tunnel started on {tunnel_addr}")

            # Give the tunnel thread a moment to be fully ready
            await asyncio.sleep(0.5)

            # Now connect to the tunnel
            logger.info(f"Running: adb connect {tunnel_addr}")
            proc = await asyncio.create_subprocess_exec(
                "adb",
                "connect",
                tunnel_addr,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            stdout_str = stdout.decode().strip()
            stderr_str = stderr.decode().strip()
            logger.info(f"ADB connect stdout: {stdout_str}")
            if stderr_str:
                logger.info(f"ADB connect stderr: {stderr_str}")

            # Wait a moment for the connection to establish
            await asyncio.sleep(2.0)

            # Now create the adbutils client
            self._adb_client = AdbClient(host="127.0.0.1", port=5037)

            max_retries = 15
            for attempt in range(max_retries):
                devices = await asyncio.to_thread(self._adb_client.device_list)
                tunnel_device = next(
                    (d for d in devices if d.serial and tunnel_addr in d.serial),
                    None,
                )
                if tunnel_device:
                    self._adb_serial = tunnel_device.serial
                    logger.info(f"Connected to Limrun Android device: {self._adb_serial}")
                    break

                logger.info(f"Waiting for ADB device (attempt {attempt + 1}/{max_retries})...")
                await asyncio.sleep(2)
            else:
                raise RuntimeError(
                    f"No ADB devices found after {max_retries * 2}s. "
                    "Tunnel may still be initializing."
                )

            if self._adb_serial is not None:
                self._ui_client = UIAutomatorClient(device_id=self._adb_serial)
                # Enable fast input IME keyboard
                device = await asyncio.to_thread(self._ui_client._ensure_connected)
                await asyncio.to_thread(device.set_fastinput_ime, True)

                # Fetch actual screen dimensions
                screen_data = await self.get_screen_data()
                self.device_width = screen_data.width
                self.device_height = screen_data.height
                logger.info(
                    f"Limrun Android screen dimensions: {self.device_width}x{self.device_height}"
                )

        except Exception as e:
            logger.error(f"Failed to connect to Limrun Android: {e}")
            await self.cleanup()
            raise

    @property
    def device(self):
        """Get the ADB device."""
        if self._adb_client is None or self._adb_serial is None:
            raise RuntimeError("Not connected to device")
        return self._adb_client.device(serial=self._adb_serial)

    async def tap(
        self,
        coords: CoordinatesSelectorRequest,
        long_press: bool = False,
        long_press_duration: int = 1000,
    ) -> TapOutput:
        """Tap at specific coordinates."""
        try:
            if long_press:
                cmd = (
                    f"input swipe {coords.x} {coords.y} {coords.x} {coords.y} {long_press_duration}"
                )
            else:
                cmd = f"input tap {coords.x} {coords.y}"

            self.device.shell(cmd)
            return TapOutput(error=None)
        except Exception as e:
            return TapOutput(error=f"Limrun Android tap failed: {str(e)}")

    async def swipe(
        self,
        start: CoordinatesSelectorRequest,
        end: CoordinatesSelectorRequest,
        duration: int = 400,
    ) -> str | None:
        """Swipe from start to end coordinates."""
        try:
            cmd = f"input touchscreen swipe {start.x} {start.y} {end.x} {end.y} {duration}"
            self.device.shell(cmd)
            return None
        except Exception as e:
            return f"Limrun Android swipe failed: {str(e)}"

    async def get_screen_data(self) -> ScreenDataResponse:
        """Get screen data using UIAutomator2."""
        if self._ui_client is None:
            raise RuntimeError("UIAutomator client not initialized")

        try:
            ui_data = self._ui_client.get_screen_data()
            return ScreenDataResponse(
                base64=ui_data.base64,
                elements=ui_data.elements,
                width=ui_data.width,
                height=ui_data.height,
                platform="android",
            )
        except Exception as e:
            logger.error(f"Failed to get screen data: {e}")
            raise

    async def screenshot(self) -> str:
        """Take a screenshot and return base64 encoded string."""
        return (await self.get_screen_data()).base64

    async def input_text(self, text: str) -> bool:
        """Input text at the currently focused field."""
        try:
            if self._ui_client:
                self._ui_client.send_text(text)
                return True
        except Exception as e:
            logger.warning(f"UIAutomator2 send_text failed: {e}, falling back to ADB")

        return self._input_text_adb_fallback(text)

    def _input_text_adb_fallback(self, text: str) -> bool:
        """Fallback method using ADB shell input text command."""
        try:
            parts = text.split("%s")
            for i, part in enumerate(parts):
                # Split on spaces and send each word separately with keyevent 62 for spaces
                words = part.split(" ")
                for j, word in enumerate(words):
                    if word:
                        quoted = shlex.quote(word)
                        self.device.shell(f"input text {quoted}")
                    if j < len(words) - 1:
                        self.device.shell("input keyevent 62")

                if i < len(parts) - 1:
                    self.device.shell("input keyevent 62")

            return True
        except Exception as e:
            logger.error(f"Failed to input text via ADB fallback: {e}")
            return False

    async def launch_app(self, package_or_bundle_id: str) -> bool:
        """Launch an application."""
        try:
            self.device.shell(
                [
                    "monkey",
                    "-p",
                    package_or_bundle_id,
                    "-c",
                    "android.intent.category.LAUNCHER",
                    "--pct-syskeys",  # Disable system key events not supported by Limrun mobiles
                    "0",
                    "1",
                ]
            )
            return True
        except Exception as e:
            logger.error(f"Failed to launch app {package_or_bundle_id}: {e}")
            return False

    async def terminate_app(self, package_or_bundle_id: str | None) -> bool:
        """Terminate an application."""
        try:
            if package_or_bundle_id is None:
                current_app = self._get_current_foreground_package()
                if current_app:
                    self.device.app_stop(current_app)
                else:
                    return False
            else:
                self.device.app_stop(package_or_bundle_id)
            return True
        except Exception as e:
            logger.error(f"Failed to terminate app: {e}")
            return False

    async def open_url(self, url: str) -> bool:
        """Open a URL."""
        try:
            self.device.shell(f"am start -a android.intent.action.VIEW -d {url}")
            return True
        except Exception as e:
            logger.error(f"Failed to open URL {url}: {e}")
            return False

    async def press_back(self) -> bool:
        """Press the back button."""
        try:
            self.device.shell("input keyevent 4")
            return True
        except Exception as e:
            logger.error(f"Failed to press back: {e}")
            return False

    async def press_home(self) -> bool:
        """Press the home button."""
        try:
            self.device.shell("input keyevent 3")
            return True
        except Exception as e:
            logger.error(f"Failed to press home: {e}")
            return False

    async def press_enter(self) -> bool:
        """Press the enter key."""
        try:
            self.device.shell("input keyevent 66")
            return True
        except Exception as e:
            logger.error(f"Failed to press enter: {e}")
            return False

    async def get_ui_hierarchy(self) -> list[dict]:
        """Get the UI element hierarchy."""
        try:
            device_data = await self.get_screen_data()
            return device_data.elements
        except Exception as e:
            logger.error(f"Failed to get UI hierarchy: {e}")
            return []

    def find_element(
        self,
        ui_hierarchy: list[dict],
        resource_id: str | None = None,
        text: str | None = None,
        index: int = 0,
    ) -> tuple[dict | None, Bounds | None, str | None]:
        """Find a UI element in the hierarchy."""
        if not resource_id and not text:
            return None, None, "No resource_id or text provided"

        matches = []
        for element in ui_hierarchy:
            if resource_id and element.get("resource-id") == resource_id:
                matches.append(element)
            elif text and (element.get("text") == text or element.get("accessibilityText") == text):
                matches.append(element)

        if not matches:
            criteria = f"resource_id='{resource_id}'" if resource_id else f"text='{text}'"
            return None, None, f"No element found with {criteria}"

        if index >= len(matches):
            return None, None, f"Index {index} out of range (found {len(matches)} matches)"

        element = matches[index]
        bounds = self._extract_bounds(element)
        return element, bounds, None

    def _get_current_foreground_package(self) -> str | None:
        """Get the current foreground app package."""
        try:
            result = self.device.shell("dumpsys window | grep mCurrentFocus")
            if isinstance(result, bytes):
                result = result.decode("utf-8")
            if isinstance(result, str) and "=" in result:
                parts = result.split("/")
                if len(parts) > 0:
                    package = parts[0].split()[-1]
                    return package if package else None
            return None
        except Exception as e:
            logger.error(f"Failed to get foreground package: {e}")
            return None

    def _extract_bounds(self, element: dict) -> Bounds | None:
        """Extract bounds from a UI element."""
        bounds_str = element.get("bounds")
        if not bounds_str or not isinstance(bounds_str, str):
            return None

        try:
            match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_str)
            if match:
                return Bounds(
                    x1=int(match.group(1)),
                    y1=int(match.group(2)),
                    x2=int(match.group(3)),
                    y2=int(match.group(4)),
                )
        except (ValueError, IndexError):
            return None
        return None

    async def erase_text(self, nb_chars: int | None = None) -> bool:
        """Erase text by sending delete key presses."""
        try:
            chars_to_delete = nb_chars if nb_chars is not None else 50
            for _ in range(chars_to_delete):
                self.device.shell("input keyevent KEYCODE_DEL")
            return True
        except Exception as e:
            logger.error(f"Failed to erase text: {e}")
            return False

    async def cleanup(self) -> None:
        """Cleanup resources."""
        if self._tunnel:
            await self._tunnel.stop()
            self._tunnel = None

        self._adb_client = None
        self._ui_client = None
        self._adb_serial = None
        logger.debug("Limrun Android controller cleanup complete")

    def get_compressed_b64_screenshot(self, image_base64: str, quality: int = 50) -> str:
        """Compress a base64 image."""
        if image_base64.startswith("data:image"):
            image_base64 = image_base64.split(",")[1]

        image_data = base64.b64decode(image_base64)
        image = Image.open(BytesIO(image_data))

        compressed_io = BytesIO()
        image.save(compressed_io, format="JPEG", quality=quality, optimize=True)

        return base64.b64encode(compressed_io.getvalue()).decode("utf-8")

    async def start_video_recording(
        self,
        max_duration_seconds: int = DEFAULT_MAX_DURATION_SECONDS,
    ) -> VideoRecordingResult:
        """Start screen recording."""
        return VideoRecordingResult(
            success=False,
            message="Video recording not yet supported for Limrun Android",
        )

    async def stop_video_recording(self) -> VideoRecordingResult:
        """Stop screen recording."""
        return VideoRecordingResult(
            success=False,
            message="Video recording not yet supported for Limrun Android",
        )


class LimrunIosController:
    """
    Limrun iOS controller using WebSocket communication.

    Implements IosClientWrapper interface for use with iOSDeviceController.
    """

    def __init__(
        self,
        instance_id: str,
        api_url: str,
        token: str,
    ):
        self.instance_id = instance_id
        self.api_url = api_url
        self.token = token
        self.device_width: int = 0
        self.device_height: int = 0

        self._client: LimrunIosClient | None = None

    async def connect(self) -> None:
        """Connect to the Limrun iOS instance."""
        logger.info(f"Connecting to Limrun iOS instance {self.instance_id}")

        self._client = LimrunIosClient(
            api_url=self.api_url,
            token=self.token,
        )
        await self._client.connect()

        device_info = self._client.device_info
        self.device_width = int(device_info.screen_width)
        self.device_height = int(device_info.screen_height)

        logger.info(
            f"Connected to Limrun iOS: {device_info.model} "
            f"({self.device_width}x{self.device_height})"
        )

    @property
    def client(self) -> LimrunIosClient:
        """Get the Limrun iOS client."""
        if self._client is None:
            raise RuntimeError("Not connected to Limrun iOS instance")
        return self._client

    async def cleanup(self) -> None:
        """Cleanup resources."""
        if self._client:
            await self._client.cleanup()
            self._client = None
        logger.debug("Limrun iOS controller cleanup complete")

    # IosClientWrapper interface methods (matching IdbClientWrapper)

    async def tap(self, x: int, y: int, duration: float | None = None) -> bool:
        """Tap at coordinates."""
        try:
            await self.client.tap(x=x, y=y, duration=duration)
            return True
        except Exception as e:
            logger.error(f"Limrun iOS tap failed: {e}")
            return False

    async def swipe(
        self,
        x_start: int,
        y_start: int,
        x_end: int,
        y_end: int,
        duration: float = 0.4,
    ) -> bool:
        """Swipe from start to end coordinates."""
        try:
            await self.client.swipe(
                x_start=x_start,
                y_start=y_start,
                x_end=x_end,
                y_end=y_end,
                duration=duration,
            )
            return True
        except Exception as e:
            logger.error(f"Limrun iOS swipe failed: {e}")
            return False

    async def screenshot(self, output_path: str | None = None) -> bytes | None:
        """Take a screenshot and return raw image bytes."""
        try:
            screenshot_data = await self.client.screenshot()
            if output_path:
                with open(output_path, "wb") as f:
                    f.write(screenshot_data)
            return screenshot_data
        except Exception as e:
            logger.error(f"Failed to take screenshot: {e}")
            return None

    async def describe_all(self) -> list[dict]:
        """Get accessibility info for all elements."""
        return await self.client.describe_all()

    async def text(self, text: str) -> bool:
        """Input text at the currently focused field."""
        return await self.client.text(text)

    async def launch(self, bundle_id: str) -> bool:
        """Launch an application."""
        return await self.client.launch(bundle_id=bundle_id)

    async def terminate(self, bundle_id: str) -> bool:
        """Terminate an application."""
        return await self.client.terminate(bundle_id=bundle_id)

    async def open_url(self, url: str) -> bool:
        """Open a URL."""
        return await self.client.open_url(url)

    async def key(self, key_code: int) -> bool:
        """Press a key by code."""
        try:
            await self.client.key(key_code)
            return True
        except Exception as e:
            logger.error(f"Failed to press key {key_code}: {e}")
            return False

    async def button(self, button_type: HIDButtonType) -> bool:
        """Press a hardware button."""
        try:
            if button_type == HIDButtonType.HOME:
                await self.client.press_key("home")
            elif button_type == HIDButtonType.LOCK:
                await self.client.press_key("lock")
            else:
                logger.warning(f"Unsupported button type: {button_type}")
                return False
            return True
        except Exception as e:
            logger.error(f"Failed to press button {button_type}: {e}")
            return False

    async def home(self) -> bool:
        """Press the home button."""
        try:
            await self.client.press_key("home")
            return True
        except Exception as e:
            logger.error(f"Failed to press home: {e}")
            return False

    async def app_current(self) -> IOSAppInfo | None:
        """Get information about the currently active app.

        Uses describe_all to find the app name from the Application element,
        then looks up the bundle ID from list_apps.
        """
        try:
            elements = await self.client.describe_all()
            if not elements:
                return None

            # Find the Application element - it contains the app name in AXLabel
            app_name = None
            for elem in elements:
                if elem.get("type") == "Application":
                    app_name = elem.get("AXLabel") or elem.get("label")
                    break

            if not app_name:
                return None

            # Get installed apps and find bundle ID by display name
            installed_apps = await self.client.list_apps()
            for app in installed_apps:
                if app.name == app_name:
                    return IOSAppInfo(name=app_name, bundle_id=app.bundle_id)

            return IOSAppInfo(name=app_name, bundle_id=None)

        except Exception as e:
            logger.error(f"Failed to get current app: {e}")
            return None
