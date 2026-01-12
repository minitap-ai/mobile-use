import asyncio
import base64
import re
import tempfile
import time
from io import BytesIO
from pathlib import Path

from adbutils import AdbClient, AdbDevice
from PIL import Image

from minitap.mobile_use.clients.ui_automator_client import UIAutomatorClient
from minitap.mobile_use.controllers.device_controller import (
    MobileDeviceController,
    ScreenDataResponse,
)
from minitap.mobile_use.controllers.types import Bounds, CoordinatesSelectorRequest, TapOutput
from minitap.mobile_use.utils.logger import get_logger
from minitap.mobile_use.utils.video import (
    ANDROID_MAX_RECORDING_DURATION_SECONDS,
    DEFAULT_MAX_DURATION_SECONDS,
    VIDEO_READY_DELAY_SECONDS,
    RecordingSession,
    VideoRecordingResult,
    cleanup_video_segments,
    concatenate_videos,
    get_active_session,
    has_active_session,
    remove_active_session,
    set_active_session,
)

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
            self.ui_adb_client.send_text(text)
            return True
        except Exception as e:
            logger.warning(f"UIAutomator2 send_text failed: {e}, falling back to ADB shell")
            return self._input_text_adb_fallback(text)

    def _input_text_adb_fallback(self, text: str) -> bool:
        """Fallback method using ADB shell input text command."""
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
            logger.error(f"Failed to input text via ADB fallback: {e}")
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

    async def press_enter(self) -> bool:
        try:
            self.device.shell("input keyevent 66")
            return True
        except Exception as e:
            logger.error(f"Failed to press enter: {e}")
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

    async def _start_android_segment(
        self, session: RecordingSession
    ) -> asyncio.subprocess.Process | None:
        """Start a single Android recording segment."""
        segment_path = f"/sdcard/screen_recording_{session.android_segment_index}.mp4"
        cmd = f"screenrecord --time-limit {ANDROID_MAX_RECORDING_DURATION_SECONDS} {segment_path}"

        process = await asyncio.create_subprocess_shell(
            f'adb -s {self.device_id} shell "{cmd}"',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        session.android_device_path = segment_path
        session.process = process
        return process

    async def _android_auto_restart_loop(
        self,
        session: RecordingSession,
        max_duration_seconds: int,
    ) -> None:
        """Background task that auto-restarts Android recording when segment ends."""
        total_elapsed = 0

        while total_elapsed < max_duration_seconds:
            process = session.process
            if process is None:
                break

            try:
                await asyncio.wait_for(
                    process.wait(),
                    timeout=ANDROID_MAX_RECORDING_DURATION_SECONDS + 5,
                )
            except TimeoutError:
                pass
            except asyncio.CancelledError:
                return

            if not has_active_session(self.device_id):
                return

            total_elapsed = time.time() - session.start_time
            if total_elapsed >= max_duration_seconds:
                break

            await asyncio.sleep(VIDEO_READY_DELAY_SECONDS)

            temp_dir = tempfile.mkdtemp(prefix="mobile_use_video_segment_")
            local_segment = Path(temp_dir) / f"segment_{session.android_segment_index}.mp4"

            try:
                self.device.sync.pull(session.android_device_path, str(local_segment))
                self.device.shell(f"rm -f {session.android_device_path}")
                session.android_video_segments.append(local_segment)
                logger.info(
                    f"Saved Android segment {session.android_segment_index} to {local_segment}"
                )
            except Exception as e:
                error_msg = f"Failed to pull segment {session.android_segment_index}: {e}"
                logger.warning(error_msg)
                session.errors.append(error_msg)

            session.android_segment_index += 1

            try:
                await self._start_android_segment(session)
                logger.info(
                    f"Auto-restarted Android recording (segment {session.android_segment_index})"
                )
            except Exception as e:
                error_msg = f"Failed to restart Android recording: {e}"
                logger.error(error_msg)
                session.errors.append(error_msg)
                break

    async def start_video_recording(
        self,
        max_duration_seconds: int = DEFAULT_MAX_DURATION_SECONDS,
    ) -> VideoRecordingResult:
        """Start screen recording on Android device using adb shell screenrecord."""
        if has_active_session(self.device_id):
            return VideoRecordingResult(
                success=False,
                message=f"Recording already in progress for device {self.device_id}",
            )

        try:
            session = RecordingSession(
                device_id=self.device_id,
                start_time=time.time(),
                android_video_segments=[],
                android_segment_index=0,
            )

            set_active_session(self.device_id, session)
            await self._start_android_segment(session)

            restart_task = asyncio.create_task(
                self._android_auto_restart_loop(session, max_duration_seconds)
            )
            session.android_restart_task = restart_task

            logger.info(f"Started Android screen recording on {self.device_id}")
            return VideoRecordingResult(
                success=True,
                message=(
                    f"Recording started (max {max_duration_seconds}s, "
                    f"auto-restarts every {ANDROID_MAX_RECORDING_DURATION_SECONDS}s)."
                ),
            )

        except Exception as e:
            logger.error(f"Failed to start Android recording: {e}")
            remove_active_session(self.device_id)
            return VideoRecordingResult(
                success=False,
                message=f"Failed to start recording: {e}",
            )

    async def stop_video_recording(self) -> VideoRecordingResult:
        """Stop Android recording, pull all segments, and concatenate them."""
        session = get_active_session(self.device_id)

        if not session:
            return VideoRecordingResult(
                success=False,
                message=f"No active recording for device {self.device_id}",
            )

        try:
            if session.android_restart_task:
                session.android_restart_task.cancel()
                try:
                    await session.android_restart_task
                except asyncio.CancelledError:
                    pass

            process = session.process
            if process is not None:
                try:
                    process.terminate()
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except TimeoutError:
                    process.kill()
                    await process.wait()

            self.device.shell("pkill -2 screenrecord || true")
            await asyncio.sleep(VIDEO_READY_DELAY_SECONDS)

            temp_dir = tempfile.mkdtemp(prefix="mobile_use_video_")
            final_segment = Path(temp_dir) / f"segment_{session.android_segment_index}.mp4"

            try:
                self.device.sync.pull(session.android_device_path, str(final_segment))
                self.device.shell(f"rm -f {session.android_device_path}")
                session.android_video_segments.append(final_segment)
            except Exception as e:
                logger.warning(f"Failed to pull final segment: {e}")

            for i in range(session.android_segment_index + 1):
                self.device.shell(f"rm -f /sdcard/screen_recording_{i}.mp4")

            all_segments = session.android_video_segments

            if not all_segments:
                remove_active_session(self.device_id)
                return VideoRecordingResult(
                    success=False,
                    message="No video segments were captured",
                )

            output_dir = tempfile.mkdtemp(prefix="mobile_use_video_final_")
            output_path = Path(output_dir) / "recording.mp4"

            if len(all_segments) == 1:
                all_segments[0].rename(output_path)
            else:
                success = await concatenate_videos(all_segments, output_path)
                if not success:
                    output_path = all_segments[-1]
                    logger.warning("Concatenation failed, using last segment only")

            cleanup_video_segments(all_segments, keep_path=output_path)

            errors = session.errors.copy()
            remove_active_session(self.device_id)

            duration = time.time() - session.start_time
            segment_count = len(all_segments)
            logger.info(
                f"Stopped Android recording after {duration:.1f}s, "
                f"{segment_count} segment(s), saved to {output_path}"
            )

            message = f"Recording stopped after {duration:.1f}s ({segment_count} segments)"
            if errors:
                message += f". Warnings during recording: {'; '.join(errors)}"

            return VideoRecordingResult(
                success=True,
                message=message,
                video_path=output_path,
            )

        except Exception as e:
            logger.error(f"Failed to stop Android recording: {e}")
            remove_active_session(self.device_id)
            return VideoRecordingResult(
                success=False,
                message=f"Failed to stop recording: {e}",
            )
