import asyncio
from functools import wraps
from typing import Any

import wda
from wda.exceptions import WDAError, WDARequestError

from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


def with_wda_client(func):
    """Decorator to handle WDA client lifecycle and error handling.

    This decorator ensures that WDA operations are properly wrapped with
    error handling and logging. Unlike IDB which requires building a new
    client connection for each operation, WDA maintains a persistent session.

    Note: Function must have None or bool in return type for error fallback.
    """

    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        method_name = func.__name__
        try:
            logger.debug(f"Executing WDA operation: {method_name}...")
            result = await func(self, *args, **kwargs)
            logger.debug(f"{method_name} completed successfully")
            return result
        except WDARequestError as e:
            logger.error(f"WDA request error in {method_name}: {e}")
            return_type = func.__annotations__.get("return")
            if return_type is bool:
                return False
            return None
        except WDAError as e:
            logger.error(f"WDA error in {method_name}: {e}")
            return_type = func.__annotations__.get("return")
            if return_type is bool:
                return False
            return None
        except Exception as e:
            logger.error(f"Failed to {method_name}: {e}")
            import traceback

            logger.debug(f"Traceback: {traceback.format_exc()}")

            return_type = func.__annotations__.get("return")
            if return_type is bool:
                return False
            return None

    return wrapper


class WdaClientWrapper:
    """Wrapper around facebook-wda client for physical iOS device automation.

    This wrapper provides an interface similar to IdbClientWrapper but uses
    WebDriverAgent (WDA) for physical iOS device automation instead of fb-idb.

    WDA is typically used for:
    - Physical iOS devices connected via USB
    - Devices where fb-idb is not available or preferred

    Prerequisites:
        1. WebDriverAgent must be running on the target device
        2. Port forwarding must be set up (e.g., iproxy 8100 8100)

    Example:
        # Basic usage
        async with WdaClientWrapper(wda_url="http://localhost:8100") as wrapper:
            await wrapper.tap(100, 200)
            screenshot = await wrapper.screenshot()

        # With custom timeout
        wrapper = WdaClientWrapper(
            wda_url="http://localhost:8100",
            timeout=60.0
        )
        await wrapper.init_client()
        await wrapper.tap(100, 200)
        await wrapper.cleanup()
    """

    def __init__(
        self,
        wda_url: str = "http://localhost:8100",
        timeout: float = 30.0,
    ):
        """Initialize the WDA client wrapper.

        Args:
            wda_url: URL of the WebDriverAgent server (default: http://localhost:8100)
            timeout: Default timeout for WDA operations in seconds (default: 30.0)
        """
        self.wda_url = wda_url
        self.timeout = timeout
        self._client: wda.Client | None = None
        self._session: wda.Session | None = None

    async def init_client(self) -> bool:
        """Initialize the WDA client connection.

        Returns:
            True if client initialized successfully, False otherwise
        """
        try:
            logger.info(f"Connecting to WebDriverAgent at {self.wda_url}")

            # WDA client is synchronous, run in thread pool
            self._client = await asyncio.to_thread(wda.Client, self.wda_url)

            # Verify connection by getting status
            status = await asyncio.to_thread(self._client.status)
            logger.debug(f"WDA status: {status}")

            # Create a session for operations
            self._session = await asyncio.to_thread(self._client.session)

            logger.info(f"Successfully connected to WebDriverAgent at {self.wda_url}")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to WebDriverAgent: {e}")
            logger.error(
                "\nMake sure:\n"
                "1. WebDriverAgent is running on your device\n"
                "2. Port forwarding is active: iproxy 8100 8100\n"
                f"3. URL is correct: {self.wda_url}"
            )
            self._client = None
            self._session = None
            return False

    async def cleanup(self) -> None:
        """Clean up WDA client resources."""
        if self._session is not None:
            try:
                logger.debug("Closing WDA session")
                await asyncio.to_thread(self._session.close)
            except Exception as e:
                logger.debug(f"Error closing WDA session: {e}")
            finally:
                self._session = None

        self._client = None
        logger.debug("WDA client cleanup completed")

    async def __aenter__(self):
        """Async context manager entry."""
        if not await self.init_client():
            raise RuntimeError(f"Failed to connect to WebDriverAgent at {self.wda_url}")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.cleanup()
        return False

    def _ensure_session(self) -> wda.Session:
        """Ensure a valid WDA session exists.

        Returns:
            The WDA session

        Raises:
            RuntimeError: If no session is available
        """
        if self._session is None:
            raise RuntimeError(
                "WDA session not initialized. Call init_client() first or use as context manager."
            )
        return self._session

    @with_wda_client
    async def tap(self, x: int, y: int, duration: float | None = None) -> bool:
        """Tap at the specified coordinates.

        Args:
            x: X coordinate
            y: Y coordinate
            duration: Optional tap duration in seconds (for long press)

        Returns:
            True if tap succeeded, False otherwise
        """
        session = self._ensure_session()
        if duration:
            await asyncio.to_thread(session.tap_hold, x, y, duration)
        else:
            await asyncio.to_thread(session.tap, x, y)
        return True

    @with_wda_client
    async def swipe(
        self,
        x_start: int,
        y_start: int,
        x_end: int,
        y_end: int,
        duration: float | None = None,
    ) -> bool:
        """Swipe from start coordinates to end coordinates.

        Args:
            x_start: Starting X coordinate
            y_start: Starting Y coordinate
            x_end: Ending X coordinate
            y_end: Ending Y coordinate
            duration: Optional swipe duration in seconds

        Returns:
            True if swipe succeeded, False otherwise
        """
        session = self._ensure_session()
        await asyncio.to_thread(session.swipe, x_start, y_start, x_end, y_end, duration)  # type: ignore
        return True

    @with_wda_client
    async def screenshot(self, output_path: str | None = None) -> bytes | None:
        """Take a screenshot and return raw image data.

        Args:
            output_path: Optional path to save the screenshot

        Returns:
            Raw image data (PNG bytes) or None on failure
        """
        session = self._ensure_session()
        # Use format='raw' to get PNG bytes directly
        screenshot_data = await asyncio.to_thread(
            session.screenshot, png_filename=output_path, format="raw"
        )
        if isinstance(screenshot_data, bytes):
            return screenshot_data
        logger.warning(f"Expected bytes, got: {type(screenshot_data)}")
        return None

    @with_wda_client
    async def launch(
        self,
        bundle_id: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> bool:
        """Launch an application by bundle ID.

        Args:
            bundle_id: The bundle identifier of the app to launch
            args: Optional list of arguments to pass to the app
            env: Optional environment variables for the app

        Returns:
            True if launch succeeded, False otherwise
        """
        session = self._ensure_session()
        await asyncio.to_thread(
            session.app_launch,
            bundle_id,
            arguments=args or [],
            environment=env or {},
        )
        return True

    @with_wda_client
    async def terminate(self, bundle_id: str) -> bool:
        """Terminate an application by bundle ID.

        Args:
            bundle_id: The bundle identifier of the app to terminate

        Returns:
            True if termination succeeded, False otherwise
        """
        session = self._ensure_session()
        await asyncio.to_thread(session.app_terminate, bundle_id)
        return True

    @with_wda_client
    async def text(self, text: str) -> bool:
        """Type text using the keyboard.

        Args:
            text: The text to type

        Returns:
            True if text input succeeded, False otherwise
        """
        session = self._ensure_session()
        await asyncio.to_thread(session.send_keys, text)
        return True

    @with_wda_client
    async def open_url(self, url: str) -> bool:
        """Open a URL on the device.

        Args:
            url: The URL to open

        Returns:
            True if URL opened successfully, False otherwise
        """
        session = self._ensure_session()
        await asyncio.to_thread(session.open_url, url)
        return True

    @with_wda_client
    async def key(self, key_code: int) -> bool:
        """Send a key press.

        Note: WDA doesn't have direct key code support like IDB.
        For delete (key_code=42), we send a backspace character.

        Args:
            key_code: HID key code (42 = delete/backspace)

        Returns:
            True if key press succeeded, False otherwise
        """
        session = self._ensure_session()
        if key_code == 42:  # Delete/backspace
            await asyncio.to_thread(session.send_keys, "\b")
        return True

    @with_wda_client
    async def button(self, button_type: Any) -> bool:
        """Press a hardware button (compatible with IDB's HIDButtonType).

        Args:
            button_type: Button type (HIDButtonType.HOME, etc.)

        Returns:
            True if button press succeeded, False otherwise
        """
        client = self._client
        if client is None:
            raise RuntimeError("WDA client not initialized")
        button_name = getattr(button_type, "name", str(button_type)).lower()
        if button_name == "home":
            await asyncio.to_thread(client.home)
        elif button_name in ("volume_up", "volumeup"):
            session = self._ensure_session()
            await asyncio.to_thread(session.press, "volumeUp")
        elif button_name in ("volume_down", "volumedown"):
            session = self._ensure_session()
            await asyncio.to_thread(session.press, "volumeDown")
        return True

    async def describe_all(self) -> list[dict[str, Any]] | None:
        """Get UI hierarchy as a flat list (compatible with IDB's describe_all).

        Returns:
            List of UI elements or None on error
        """
        try:
            session = self._ensure_session()
            xml_source = await asyncio.to_thread(session.source, format="xml")
            if xml_source is None:
                return None
            return self._parse_xml_to_elements(xml_source)
        except Exception as e:
            logger.error(f"Failed to describe_all: {e}")
            return None

    def _parse_xml_to_elements(self, xml_source: str) -> list[dict[str, Any]]:
        """Parse WDA XML source into flat element list matching IDB format."""
        import xml.etree.ElementTree as ET

        elements = []
        try:
            root = ET.fromstring(xml_source)
            for elem in root.iter():
                if elem.tag == "AppiumAUT":
                    continue
                frame = {
                    "x": float(elem.get("x", 0)),
                    "y": float(elem.get("y", 0)),
                    "width": float(elem.get("width", 0)),
                    "height": float(elem.get("height", 0)),
                }
                element = {
                    "type": elem.get("type", elem.tag),
                    "value": elem.get("value", ""),
                    "label": elem.get("label", elem.get("name", "")),
                    "frame": frame,
                    "enabled": elem.get("enabled", "false").lower() == "true",
                    "visible": elem.get("visible", "true").lower() == "true",
                }
                elements.append(element)
        except ET.ParseError as e:
            logger.error(f"Failed to parse XML: {e}")
        return elements
