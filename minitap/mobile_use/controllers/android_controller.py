import base64
import re
from io import BytesIO

from adbutils import AdbClient, AdbDevice
from PIL import Image

from minitap.mobile_use.clients.ui_automator_client import UIAutomatorClient
from minitap.mobile_use.controllers.device_controller import (
    MobileDeviceController,
    ScreenDataResponse,
)
from minitap.mobile_use.controllers.types import Bounds, CoordinatesSelectorRequest, TapOutput
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


class AndroidDeviceController(MobileDeviceController):
    def __init__(
        self,
        device_id: str,
        adb_client: AdbClient,
        ui_adb_client: UIAutomatorClient,
        device_width: int,
        device_height: int,
    ):
        self.device_id = device_id
        self.adb_client = adb_client
        self.ui_adb_client = ui_adb_client
        self.device_width = device_width
        self.device_height = device_height
        self._device: AdbDevice | None = None

    @property
    def device(self) -> AdbDevice:
        if self._device is None:
            self._device = self.adb_client.device(serial=self.device_id)
        return self._device

    async def tap(
        self,
        coords: CoordinatesSelectorRequest,
        long_press: bool = False,
        long_press_duration: int = 1000,
    ) -> TapOutput:
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
            return TapOutput(error=f"ADB tap failed: {str(e)}")

    async def swipe(
        self,
        start: CoordinatesSelectorRequest,
        end: CoordinatesSelectorRequest,
        duration: int = 400,
    ) -> str | None:
        try:
            cmd = f"input touchscreen swipe {start.x} {start.y} {end.x} {end.y} {duration}"
            self.device.shell(cmd)
            return None
        except Exception as e:
            return f"ADB swipe failed: {str(e)}"

    async def get_screen_data(self) -> ScreenDataResponse:
        """Get screen data using the UIAutomator2 client"""
        try:
            logger.info("Using UIAutomator2 for screen data retrieval")
            ui_data = self.ui_adb_client.get_screen_data()
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
        try:
            return (await self.get_screen_data()).base64
        except Exception as e:
            logger.error(f"Failed to take screenshot: {e}")
            raise

    async def input_text(self, text: str) -> bool:
        try:
            parts = text.split("%s")
            for i, part in enumerate(parts):
                to_write = ""
                for char in part:
                    if char == " ":
                        to_write += "%s"
                    elif char in ["&", "<", ">", "|", ";", "(", ")", "$", "`", "\\", '"', "'"]:
                        to_write += f"\\{char}"
                    else:
                        to_write += char

                if to_write:
                    self.device.shell(f"input text '{to_write}'")

                if i < len(parts) - 1:
                    self.device.shell("input keyevent 62")

            return True
        except Exception as e:
            logger.error(f"Failed to input text: {e}")
            return False

    async def launch_app(self, package_or_bundle_id: str) -> bool:
        try:
            self.device.app_start(package_or_bundle_id)
            return True
        except Exception as e:
            logger.error(f"Failed to launch app {package_or_bundle_id}: {e}")
            return False

    async def terminate_app(self, package_or_bundle_id: str | None) -> bool:
        try:
            if package_or_bundle_id is None:
                current_app = self._get_current_foreground_package()
                if current_app:
                    logger.info(f"Stopping currently running app: {current_app}")
                    self.device.app_stop(current_app)
                else:
                    logger.warning("No foreground app detected")
                    return False
            else:
                self.device.app_stop(package_or_bundle_id)
            return True
        except Exception as e:
            logger.error(f"Failed to terminate app {package_or_bundle_id}: {e}")
            return False

    async def open_url(self, url: str) -> bool:
        try:
            self.device.shell(f"am start -a android.intent.action.VIEW -d {url}")
            return True
        except Exception as e:
            logger.error(f"Failed to open URL {url}: {e}")
            return False

    async def press_back(self) -> bool:
        try:
            self.device.shell("input keyevent 4")
            return True
        except Exception as e:
            logger.error(f"Failed to press back: {e}")
            return False

    async def press_home(self) -> bool:
        try:
            self.device.shell("input keyevent 3")
            return True
        except Exception as e:
            logger.error(f"Failed to press home: {e}")
            return False

    async def get_ui_hierarchy(self) -> list[dict]:
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
            criteria = f"resource_id='{resource_id}'" if resource_id else f"text='{text}'"
            return (
                None,
                None,
                f"Index {index} out of range for {criteria} (found {len(matches)} matches)",
            )

        element = matches[index]
        bounds = self._extract_bounds(element)

        return element, bounds, None

    def _get_current_foreground_package(self) -> str | None:
        try:
            result = self.device.shell("dumpsys window | grep mCurrentFocus")

            # Convert to string if bytes
            if isinstance(result, bytes):
                result_str = result.decode("utf-8")
            elif isinstance(result, str):
                result_str = result
            else:
                return None

            if result_str and "=" in result_str:
                parts = result_str.split("/")
                if len(parts) > 0:
                    package = parts[0].split()[-1]
                    return package if package else None
            return None
        except Exception as e:
            logger.error(f"Failed to get current foreground package: {e}")
            return None

    def _extract_bounds(self, element: dict) -> Bounds | None:
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
        try:
            chars_to_delete = nb_chars if nb_chars is not None else 50
            for _ in range(chars_to_delete):
                self.device.shell("input keyevent KEYCODE_DEL")
            return True
        except Exception as e:
            logger.error(f"Failed to erase text: {e}")
            return False

    async def cleanup(self) -> None:
        pass

    def get_compressed_b64_screenshot(self, image_base64: str, quality: int = 50) -> str:
        if image_base64.startswith("data:image"):
            image_base64 = image_base64.split(",")[1]

        image_data = base64.b64decode(image_base64)
        image = Image.open(BytesIO(image_data))

        compressed_io = BytesIO()
        image.save(compressed_io, format="JPEG", quality=quality, optimize=True)

        compressed_base64 = base64.b64encode(compressed_io.getvalue()).decode("utf-8")
        return compressed_base64
