"""iOS-specific device controller implementation using IDB or WDA."""

import asyncio
import base64
import re
import tempfile
import time
from io import BytesIO
from pathlib import Path

from idb.common.types import HIDButtonType
from PIL import Image

from minitap.mobile_use.clients.idb_client import IdbClientWrapper
from minitap.mobile_use.clients.ios_client import IosClientWrapper
from minitap.mobile_use.controllers.device_controller import (
    MobileDeviceController,
    ScreenDataResponse,
)
from minitap.mobile_use.controllers.types import Bounds, CoordinatesSelectorRequest, TapOutput
from minitap.mobile_use.utils.logger import get_logger
from minitap.mobile_use.utils.video import (
    DEFAULT_MAX_DURATION_SECONDS,
    VIDEO_READY_DELAY_SECONDS,
    RecordingSession,
    VideoRecordingResult,
    get_active_session,
    has_active_session,
    remove_active_session,
    set_active_session,
)

logger = get_logger(__name__)


class iOSDeviceController(MobileDeviceController):
    """iOS device controller using IDB (simulators) or WDA (physical devices)."""

    def __init__(
        self,
        ios_client: IosClientWrapper,
        device_id: str,
        device_width: int,
        device_height: int,
    ):
        self.ios_client = ios_client
        self.device_id = device_id
        self.device_width = device_width
        self.device_height = device_height
        self._is_idb = isinstance(ios_client, IdbClientWrapper)

    async def tap(
        self,
        coords: CoordinatesSelectorRequest,
        long_press: bool = False,
        long_press_duration: int = 1000,
    ) -> TapOutput:
        """Tap at specific coordinates using IDB."""
        try:
            duration = long_press_duration / 1000.0 if long_press else None
            await self.ios_client.tap(x=coords.x, y=coords.y, duration=duration)  # type: ignore[call-arg]
            return TapOutput(error=None)
        except Exception as e:
            return TapOutput(error=f"IDB tap failed: {str(e)}")

    async def swipe(
        self,
        start: CoordinatesSelectorRequest,
        end: CoordinatesSelectorRequest,
        duration: int = 400,
    ) -> str | None:
        """Swipe from start to end coordinates using IDB."""
        try:
            # IDB delta is the number of steps, approximating from duration
            ms_duration_to_percentage = duration / 1000.0
            await self.ios_client.swipe(  # type: ignore[call-arg]
                x_start=start.x,
                y_start=start.y,
                x_end=end.x,
                y_end=end.y,
                duration=ms_duration_to_percentage,
            )
            return None
        except Exception as e:
            return f"IDB swipe failed: {str(e)}"

    async def get_screen_data(self) -> ScreenDataResponse:
        """Get screen data (screenshot and hierarchy in parallel)."""
        try:
            # Run screenshot and hierarchy fetch in parallel
            screenshot_bytes, accessibility_info = await asyncio.gather(
                self.ios_client.screenshot(),  # type: ignore[call-arg]
                self.ios_client.describe_all(),
            )

            if screenshot_bytes is None:
                raise RuntimeError("Screenshot returned None")

            elements = (
                self._process_flat_ios_hierarchy(accessibility_info) if accessibility_info else []
            )

            base64_screenshot = base64.b64encode(screenshot_bytes).decode("utf-8")

            return ScreenDataResponse(
                base64=base64_screenshot,
                elements=elements,
                width=self.device_width,
                height=self.device_height,
                platform="ios",
            )
        except Exception as e:
            logger.error(f"Failed to get screen data: {e}")
            raise

    async def screenshot(self) -> str:
        """Take a screenshot using IDB and return base64 encoded string."""
        try:
            screenshot_bytes = await self.ios_client.screenshot()  # type: ignore[call-arg]
            if screenshot_bytes is None:
                raise RuntimeError("Screenshot returned None")
            return base64.b64encode(screenshot_bytes).decode("utf-8")
        except Exception as e:
            logger.error(f"Failed to take screenshot: {e}")
            raise

    async def input_text(self, text: str) -> bool:
        """Input text using IDB."""
        try:
            return await self.ios_client.text(text)  # type: ignore[call-arg]
        except Exception as e:
            logger.error(f"Failed to input text: {e}")
            return False

    async def launch_app(self, package_or_bundle_id: str) -> bool:
        """Launch an iOS app using IDB."""
        try:
            return await self.ios_client.launch(bundle_id=package_or_bundle_id)  # type: ignore[call-arg]
        except Exception as e:
            logger.error(f"Failed to launch app {package_or_bundle_id}: {e}")
            return False

    async def terminate_app(self, package_or_bundle_id: str | None) -> bool:
        """Terminate an iOS app using IDB."""
        if package_or_bundle_id is None:
            logger.warning("Cannot terminate app: bundle_id is None")
            return False
        try:
            return await self.ios_client.terminate(bundle_id=package_or_bundle_id)  # type: ignore[call-arg]
        except Exception as e:
            logger.error(f"Failed to terminate app {package_or_bundle_id}: {e}")
            return False

    async def open_url(self, url: str) -> bool:
        """Open a URL using IDB."""
        try:
            return await self.ios_client.open_url(url)  # type: ignore[call-arg]
        except Exception as e:
            logger.error(f"Failed to open URL {url}: {e}")
            return False

    async def press_back(self) -> bool:
        """iOS doesn't have a back button - swipe from left edge."""
        try:
            # Simulate back gesture by swiping from left edge
            start = CoordinatesSelectorRequest(x=10, y=self.device_height // 4)
            end = CoordinatesSelectorRequest(x=300, y=self.device_height // 4)
            result = await self.swipe(start, end, duration=300)
            return result is None
        except Exception as e:
            logger.error(f"Failed to press back: {e}")
            return False

    async def press_home(self) -> bool:
        """Press the home button."""
        try:
            if self._is_idb:
                return await self.ios_client.button(button_type=HIDButtonType.HOME)  # type: ignore[call-arg, union-attr]
            else:
                return await self.ios_client.home()  # type: ignore[union-attr]
        except Exception as e:
            logger.error(f"Failed to press home: {e}")
            return False

    async def press_enter(self) -> bool:
        """Press the enter/return key."""
        try:
            await self.ios_client.key(40)  # type: ignore[call-arg]
            return True
        except Exception as e:
            logger.error(f"Failed to press enter: {e}")
            return False

    async def get_ui_hierarchy(self) -> list[dict]:
        """Get UI hierarchy using IDB accessibility info or WDA source."""
        try:
            accessibility_info = await asyncio.wait_for(
                self.ios_client.describe_all(), timeout=40.0
            )
            if accessibility_info is None:
                logger.warning("Accessibility info returned None")
                return []

            hierarchy = self._process_flat_ios_hierarchy(accessibility_info)
            return hierarchy
        except TimeoutError:
            logger.error("Timeout waiting for UI hierarchy (40s)")
            return []
        except Exception as e:
            logger.error(f"Failed to get UI hierarchy: {e}")
            return []

    def _process_flat_ios_hierarchy(self, accessibility_data: list[dict]) -> list[dict]:
        """
        Process flat iOS accessibility info into our standard format.

        IDB with nested=False returns a flat list of all elements.
        """
        elements = []

        for node in accessibility_data:
            if not isinstance(node, dict):
                continue

            # Extract element info
            element = {
                "type": node.get("type", ""),
                "value": node.get("AXValue", ""),
                "label": node.get("AXLabel", node.get("label", "")),
                "frame": node.get("frame", {}),
                "enabled": node.get("enabled", False),
                "visible": True,  # Elements in the list are generally visible
            }

            # Add bounds if frame is available
            if "frame" in node and isinstance(node["frame"], dict):
                frame = node["frame"]
                if all(k in frame for k in ["x", "y", "width", "height"]):
                    element["bounds"] = (
                        f"[{int(frame['x'])},{int(frame['y'])}]"
                        f"[{int(frame['x'] + frame['width'])},{int(frame['y'] + frame['height'])}]"
                    )

            elements.append(element)

        return elements

    def find_element(
        self,
        ui_hierarchy: list[dict],
        resource_id: str | None = None,
        text: str | None = None,
        index: int = 0,
    ) -> tuple[dict | None, Bounds | None, str | None]:
        """Find a UI element in the iOS hierarchy."""
        if not resource_id and not text:
            return None, None, "No resource_id or text provided"

        matches = []
        for element in ui_hierarchy:
            # iOS doesn't have resource-id, so we match on type if provided as resource_id
            if resource_id and element.get("type") == resource_id:
                matches.append(element)
            # Match on value or label for text
            elif text and (element.get("value") == text or element.get("label") == text):
                matches.append(element)

        if not matches:
            criteria = f"type='{resource_id}'" if resource_id else f"text='{text}'"
            return None, None, f"No element found with {criteria}"

        if index >= len(matches):
            criteria = f"type='{resource_id}'" if resource_id else f"text='{text}'"
            return (
                None,
                None,
                f"Index {index} out of range for {criteria} (found {len(matches)} matches)",
            )

        element = matches[index]
        bounds = self._extract_bounds(element)

        return element, bounds, None

    def _extract_bounds(self, element: dict) -> Bounds | None:
        """Extract bounds from an iOS UI element."""
        bounds_str = element.get("bounds")
        if not bounds_str or not isinstance(bounds_str, str):
            return None

        try:
            # Parse bounds string like "[x1,y1][x2,y2]"
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
            if nb_chars is None:
                nb_chars = 50  # Default to erasing 50 characters
            # iOS delete key code is 42 (HID keyboard delete)
            for _ in range(nb_chars):
                await self.ios_client.key(42)  # type: ignore[call-arg]
            return True
        except Exception as e:
            logger.error(f"Failed to erase text: {e}")
            return False

    async def cleanup(self) -> None:
        """Cleanup iOS controller resources."""
        logger.debug("iOS controller cleanup")
        await self.ios_client.cleanup()

    def get_compressed_b64_screenshot(self, image_base64: str, quality: int = 50) -> str:
        if image_base64.startswith("data:image"):
            image_base64 = image_base64.split(",")[1]

        image_data = base64.b64decode(image_base64)
        image = Image.open(BytesIO(image_data))

        # Convert RGBA to RGB if image has alpha channel (PNG transparency)
        if image.mode in ("RGBA", "LA", "P"):
            rgb_image = Image.new("RGB", image.size, (255, 255, 255))
            rgb_image.paste(image, mask=image.split()[-1] if image.mode == "RGBA" else None)
            image = rgb_image

        compressed_io = BytesIO()
        image.save(compressed_io, format="JPEG", quality=quality, optimize=True)

        compressed_base64 = base64.b64encode(compressed_io.getvalue()).decode("utf-8")
        return compressed_base64

    async def start_video_recording(
        self,
        max_duration_seconds: int = DEFAULT_MAX_DURATION_SECONDS,
    ) -> VideoRecordingResult:
        """Start screen recording on iOS device/simulator using idb record-video."""
        device_id = self.device_id

        if has_active_session(device_id):
            return VideoRecordingResult(
                success=False,
                message=f"Recording already in progress for device {device_id}",
            )

        try:
            temp_dir = tempfile.mkdtemp(prefix="mobile_use_video_")
            video_path = Path(temp_dir) / "recording.mp4"

            cmd = ["idb", "record-video", "--udid", device_id, str(video_path)]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            session = RecordingSession(
                device_id=device_id,
                start_time=time.time(),
                process=process,
                local_video_path=video_path,
            )
            set_active_session(device_id, session)

            logger.info(f"Started iOS screen recording on {device_id}")
            return VideoRecordingResult(
                success=True,
                message=f"Recording started (max {max_duration_seconds}s).",
            )

        except Exception as e:
            logger.error(f"Failed to start iOS recording: {e}")
            return VideoRecordingResult(
                success=False,
                message=f"Failed to start recording: {e}",
            )

    async def stop_video_recording(self) -> VideoRecordingResult:
        """Stop iOS recording and retrieve the video file."""
        device_id = self.device_id
        session = get_active_session(device_id)

        if not session:
            return VideoRecordingResult(
                success=False,
                message=f"No active recording for device {device_id}",
            )

        try:
            process = session.process
            if process is not None:
                try:
                    process.terminate()
                    await asyncio.wait_for(process.wait(), timeout=10.0)
                except TimeoutError:
                    process.kill()
                    await process.wait()

            await asyncio.sleep(VIDEO_READY_DELAY_SECONDS)

            local_path = session.local_video_path
            remove_active_session(device_id)

            duration = time.time() - session.start_time
            logger.info(f"Stopped iOS recording after {duration:.1f}s, saved to {local_path}")

            if local_path and local_path.exists():
                return VideoRecordingResult(
                    success=True,
                    message=f"Recording stopped after {duration:.1f}s",
                    video_path=local_path,
                )
            else:
                return VideoRecordingResult(
                    success=False,
                    message="Recording stopped but video file not found",
                )

        except Exception as e:
            logger.error(f"Failed to stop iOS recording: {e}")
            remove_active_session(device_id)
            return VideoRecordingResult(
                success=False,
                message=f"Failed to stop recording: {e}",
            )
