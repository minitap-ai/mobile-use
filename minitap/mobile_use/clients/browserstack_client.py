import asyncio
from functools import wraps
from typing import Any

from appium.options.common.base import AppiumOptions
from appium.webdriver.webdriver import WebDriver
from selenium.webdriver.common.actions import interaction
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput

from minitap.mobile_use.clients.idb_client import IOSAppInfo
from minitap.mobile_use.clients.ios_client_config import BrowserStackClientConfig
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)

BROWSERSTACK_HUB_URL = "https://hub-cloud.browserstack.com/wd/hub"


def with_browserstack_client(func):
    """Decorator to handle BrowserStack client error handling.

    Note: Function must have None or bool in return type for error fallback.
    """

    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        method_name = func.__name__
        try:
            logger.debug(f"Executing BrowserStack operation: {method_name}...")
            result = await func(self, *args, **kwargs)
            logger.debug(f"{method_name} completed successfully")
            return result
        except Exception as e:
            logger.error(f"Failed to {method_name}: {e}")
            import traceback

            logger.debug(f"Traceback: {traceback.format_exc()}")

            return_type = func.__annotations__.get("return")
            if return_type is bool:
                return False
            return None

    return wrapper


class BrowserStackClientWrapper:
    """Wrapper around Appium WebDriver for BrowserStack iOS device automation.

    This wrapper provides an interface similar to IdbClientWrapper and WdaClientWrapper
    but uses BrowserStack's cloud infrastructure for physical iOS device automation.

    BrowserStack is used for:
    - Cloud-based physical iOS devices
    - CI/CD pipelines requiring real device testing
    - Cross-device testing without local hardware

    Prerequisites:
        1. BrowserStack account with App Automate access
        2. Valid username and access_key
        3. App uploaded to BrowserStack (app_url)

    Example:
        config = BrowserStackClientConfig(
            username="your_username",
            access_key="your_access_key",
            device_name="iPhone 14",
            platform_version="16",
            app_url="bs://your_app_hash",
        )
        wrapper = BrowserStackClientWrapper(config=config)
        await wrapper.init_client()
        await wrapper.tap(100, 200)
        await wrapper.cleanup()

        # Using context manager
        async with BrowserStackClientWrapper(config=config) as wrapper:
            await wrapper.tap(100, 200)
            screenshot = await wrapper.screenshot()
    """

    def __init__(self, config: BrowserStackClientConfig):
        """Initialize the BrowserStack client wrapper.

        Args:
            config: BrowserStack configuration with credentials and device settings
        """
        self.config = config
        self._driver: WebDriver | None = None

    async def init_client(self) -> bool:
        """Initialize the Appium WebDriver session on BrowserStack.

        Returns:
            True if session created successfully, False otherwise
        """
        try:
            logger.info(
                f"Creating BrowserStack session for {self.config.device_name} "
                f"(iOS {self.config.platform_version})"
            )

            options = AppiumOptions()

            options.set_capability("platformName", "iOS")
            options.set_capability("appium:deviceName", self.config.device_name)
            options.set_capability("appium:platformVersion", self.config.platform_version)
            options.set_capability("appium:automationName", "XCUITest")
            options.set_capability("appium:app", self.config.app_url)

            bstack_options: dict[str, Any] = {
                "userName": self.config.username,
                "accessKey": self.config.access_key.get_secret_value(),
                "buildName": self.config.build_name or "mobile-use-session",
                "sessionName": self.config.session_name or "BrowserStack Session",
                "debug": True,
            }

            if self.config.project_name:
                bstack_options["projectName"] = self.config.project_name

            options.set_capability("bstack:options", bstack_options)

            hub_url = self.config.hub_url or BROWSERSTACK_HUB_URL

            self._driver = await asyncio.to_thread(
                WebDriver,
                command_executor=hub_url,
                options=options,
            )

            if self._driver:
                session_id = self._driver.session_id
                logger.info(f"BrowserStack session created successfully. Session ID: {session_id}")
                logger.info(
                    f"View session: https://app-automate.browserstack.com/dashboard/v2/sessions/{session_id}"
                )

            return True

        except Exception as e:
            logger.error(f"Failed to create BrowserStack session: {e}")
            self._driver = None
            return False

    async def cleanup(self) -> None:
        """Clean up BrowserStack session and quit the driver."""
        if self._driver is not None:
            try:
                logger.info("Ending BrowserStack session")
                await asyncio.to_thread(self._driver.quit)
            except Exception as e:
                logger.debug(f"Error ending BrowserStack session: {e}")
            finally:
                self._driver = None

        logger.debug("BrowserStack client cleanup completed")

    async def __aenter__(self):
        """Async context manager entry."""
        if not await self.init_client():
            raise RuntimeError("Failed to create BrowserStack session")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.cleanup()
        return False

    def _ensure_driver(self) -> WebDriver:
        """Ensure a valid WebDriver session exists.

        Returns:
            The WebDriver instance

        Raises:
            RuntimeError: If no driver is available
        """
        if self._driver is None:
            raise RuntimeError(
                "BrowserStack session not initialized. "
                "Call init_client() first or use as context manager."
            )
        return self._driver

    @with_browserstack_client
    async def tap(self, x: int, y: int, duration: float | None = None) -> bool:
        """Tap at the specified coordinates.

        Args:
            x: X coordinate
            y: Y coordinate
            duration: Optional tap duration in seconds (for long press)

        Returns:
            True if tap succeeded, False otherwise
        """
        driver = self._ensure_driver()

        def perform_tap():
            finger = PointerInput(interaction.POINTER_TOUCH, "finger")
            actions = ActionBuilder(driver, mouse=finger)
            actions.pointer_action.move_to_location(x, y)
            actions.pointer_action.pointer_down()
            if duration:
                actions.pointer_action.pause(duration)
            actions.pointer_action.pointer_up()
            actions.perform()

        await asyncio.to_thread(perform_tap)
        return True

    @with_browserstack_client
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
        driver = self._ensure_driver()

        swipe_duration = duration or 0.5

        def perform_swipe():
            finger = PointerInput(interaction.POINTER_TOUCH, "finger")
            actions = ActionBuilder(driver, mouse=finger)
            actions.pointer_action.move_to_location(x_start, y_start)
            actions.pointer_action.pointer_down()
            actions.pointer_action.pause(swipe_duration)
            actions.pointer_action.move_to_location(x_end, y_end)
            actions.pointer_action.pointer_up()
            actions.perform()

        await asyncio.to_thread(perform_swipe)
        return True

    @with_browserstack_client
    async def screenshot(self, output_path: str | None = None) -> bytes | None:
        """Take a screenshot and return raw image data.

        Args:
            output_path: Optional path to save the screenshot

        Returns:
            Raw image data (PNG bytes) or None on failure
        """
        driver = self._ensure_driver()

        screenshot_base64 = await asyncio.to_thread(driver.get_screenshot_as_base64)

        import base64

        screenshot_data = base64.b64decode(screenshot_base64)

        if output_path:
            with open(output_path, "wb") as f:
                f.write(screenshot_data)

        return screenshot_data

    @with_browserstack_client
    async def launch(
        self,
        bundle_id: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> bool:
        """Launch an application by bundle ID.

        Args:
            bundle_id: The bundle identifier of the app to launch
            args: Optional list of arguments to pass to the app (not supported on BrowserStack)
            env: Optional environment variables for the app (not supported on BrowserStack)

        Returns:
            True if launch succeeded, False otherwise
        """
        driver = self._ensure_driver()

        if args or env:
            logger.warning(
                "BrowserStack does not support app launch arguments or environment variables"
            )

        script = "mobile: launchApp"
        params = {"bundleId": bundle_id}

        await asyncio.to_thread(driver.execute_script, script, params)
        return True

    @with_browserstack_client
    async def terminate(self, bundle_id: str) -> bool:
        """Terminate an application by bundle ID.

        Args:
            bundle_id: The bundle identifier of the app to terminate

        Returns:
            True if termination succeeded, False otherwise
        """
        driver = self._ensure_driver()

        script = "mobile: terminateApp"
        params = {"bundleId": bundle_id}

        await asyncio.to_thread(driver.execute_script, script, params)
        return True

    @with_browserstack_client
    async def text(self, text: str) -> bool:
        """Type text using the keyboard.

        Args:
            text: The text to type

        Returns:
            True if text input succeeded, False otherwise
        """
        driver = self._ensure_driver()

        active_element = await asyncio.to_thread(lambda: driver.switch_to.active_element)
        await asyncio.to_thread(active_element.send_keys, text)
        return True

    @with_browserstack_client
    async def open_url(self, url: str) -> bool:
        """Open a URL on the device.

        Args:
            url: The URL to open

        Returns:
            True if URL opened successfully, False otherwise
        """
        driver = self._ensure_driver()

        await asyncio.to_thread(driver.get, url)
        return True

    @with_browserstack_client
    async def key(self, key_code: int) -> bool:
        """Send a key press.

        Note: Limited key support on BrowserStack/Appium.
        For delete (key_code=42), we send a backspace.

        Args:
            key_code: HID key code (42 = delete/backspace)

        Returns:
            True if key press succeeded, False otherwise
        """
        driver = self._ensure_driver()

        if key_code == 42:  # Delete/backspace
            active_element = await asyncio.to_thread(lambda: driver.switch_to.active_element)
            current_text = await asyncio.to_thread(lambda: active_element.text)
            if current_text:
                await asyncio.to_thread(active_element.clear)
                await asyncio.to_thread(active_element.send_keys, current_text[:-1])
        return True

    @with_browserstack_client
    async def button(self, button_type: Any) -> bool:
        """Press a hardware button (compatible with IDB's HIDButtonType).

        Args:
            button_type: Button type (HIDButtonType.HOME, etc.)

        Returns:
            True if button press succeeded, False otherwise
        """
        driver = self._ensure_driver()

        button_name = getattr(button_type, "name", str(button_type)).lower()

        if button_name == "home":
            script = "mobile: pressButton"
            params = {"name": "home"}
            await asyncio.to_thread(driver.execute_script, script, params)
        elif button_name in ("volume_up", "volumeup"):
            script = "mobile: pressButton"
            params = {"name": "volumeUp"}
            await asyncio.to_thread(driver.execute_script, script, params)
        elif button_name in ("volume_down", "volumedown"):
            script = "mobile: pressButton"
            params = {"name": "volumeDown"}
            await asyncio.to_thread(driver.execute_script, script, params)

        return True

    async def describe_all(self) -> list[dict[str, Any]] | None:
        """Get UI hierarchy as a flat list (compatible with IDB's describe_all).

        Returns:
            List of UI elements or None on error
        """
        try:
            driver = self._ensure_driver()
            page_source = await asyncio.to_thread(lambda: driver.page_source)
            if page_source is None:
                return None
            return self._parse_xml_to_elements(page_source)
        except Exception as e:
            logger.error(f"Failed to describe_all: {e}")
            return None

    def _parse_xml_to_elements(self, xml_source: str) -> list[dict[str, Any]]:
        """Parse Appium XML source into flat element list matching IDB format."""
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

    async def app_current(self) -> IOSAppInfo | None:
        """Get information about the currently active app.

        Note: BrowserStack doesn't support activeAppInfo script directly.
        Returns None as this feature is not available on BrowserStack.

        Returns:
            None (not supported on BrowserStack)
        """
        logger.debug("app_current is not supported on BrowserStack")
        return None

    async def install(self, app_path: str) -> list[Any]:
        """Install an app (not supported on BrowserStack - apps must be pre-uploaded).

        Args:
            app_path: Path to the app (ignored)

        Returns:
            Empty list with warning
        """
        logger.warning(
            "App installation not supported on BrowserStack. "
            "Please upload your app to BrowserStack first and use the app_url in config."
        )
        return []
