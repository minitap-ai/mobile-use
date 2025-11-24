import json
from functools import wraps
from pathlib import Path
from typing import Any

from idb.common.types import HIDButtonType, InstalledAppInfo, TCPAddress
from idb.grpc.client import Client

from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


def with_idb_client(func):
    """Decorator that creates a Client.build context and injects it as 'client' parameter."""

    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        async with Client.build(address=self.address, logger=logger.logger) as client:
            return await func(self, client, *args, **kwargs)

    return wrapper


class IdbClientWrapper:
    """Wrapper around fb-idb client for iOS device automation.

    Each method uses the @with_idb_client decorator which:
    - Creates a fresh Client.build context per operation
    - Injects the client as the first parameter after self
    - Ensures proper cleanup after each operation completes
    """

    def __init__(self, udid: str, host: str = "localhost", port: int = 10882):
        """
        Initialize IDB Controller

        Args:
            udid: Device UDID
            host: IDB companion host (default: localhost)
            port: IDB companion port (default: 10882)
        """
        self.udid = udid
        self.address = TCPAddress(host=host, port=port)

    @with_idb_client
    async def tap(self, client: Client, x: int, y: int, duration: float | None = None):
        await client.tap(x=x, y=y, duration=duration)

    @with_idb_client
    async def swipe(
        self, client: Client, x_start: int, y_start: int, x_end: int, y_end: int, delta: int = 10
    ):
        await client.swipe(p_start=(x_start, y_start), p_end=(x_end, y_end), delta=delta)

    @with_idb_client
    async def screenshot(self, client: Client, output_path: str | None = None):
        screenshot_data = await client.screenshot()
        if output_path:
            with open(output_path, "wb") as f:
                f.write(screenshot_data)
        return screenshot_data

    @with_idb_client
    async def launch(
        self,
        client: Client,
        bundle_id: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> bool:
        try:
            await client.launch(
                bundle_id=bundle_id, args=args or [], env=env or {}, foreground_if_running=True
            )
            return True
        except Exception as e:
            logger.error(f"Failed to launch: {e}")
            return False

    @with_idb_client
    async def terminate(self, client: Client, bundle_id: str) -> bool:
        try:
            await client.terminate(bundle_id)
            return True
        except Exception as e:
            logger.error(f"Failed to terminate: {e}")
            return False

    @with_idb_client
    async def install(self, client: Client, app_path: str) -> bool:
        try:
            bundle_path = Path(app_path)
            with open(bundle_path, "rb") as f:
                async for _ in client.install(bundle=f):
                    pass  # Consume the async iterator
            return True
        except Exception as e:
            logger.error(f"Failed to install: {e}")
            return False

    @with_idb_client
    async def uninstall(self, client: Client, bundle_id: str) -> bool:
        try:
            await client.uninstall(bundle_id)
            return True
        except Exception as e:
            logger.error(f"Failed to uninstall: {e}")
            return False

    @with_idb_client
    async def list_apps(self, client: Client) -> list[InstalledAppInfo]:
        try:
            apps = await client.list_apps()
            return apps
        except Exception as e:
            logger.error(f"Failed to list apps: {e}")
            return []

    @with_idb_client
    async def text(self, client: Client, text: str) -> bool:
        try:
            await client.text(text)
            return True
        except Exception as e:
            logger.error(f"Failed to type: {e}")
            return False

    @with_idb_client
    async def key(self, client: Client, key_code: int) -> bool:
        try:
            await client.key(key_code)
            return True
        except Exception as e:
            logger.error(f"Failed to press key: {e}")
            return False

    @with_idb_client
    async def button(self, client: Client, button_type: str) -> bool:
        try:
            button_map = {
                "HOME": HIDButtonType.HOME,
                "LOCK": HIDButtonType.LOCK,
                "SIDE_BUTTON": HIDButtonType.SIDE_BUTTON,
                "APPLE_PAY": HIDButtonType.APPLE_PAY,
                "SIRI": HIDButtonType.SIRI,
            }
            button_enum = button_map.get(button_type.upper())
            if not button_enum:
                return False

            await client.button(button_type=button_enum)
            return True
        except Exception as e:
            logger.error(f"Failed to press button: {e}")
            return False

    @with_idb_client
    async def clear_keychain(self, client: Client) -> bool:
        try:
            await client.clear_keychain()
            return True
        except Exception as e:
            logger.error(f"Failed to clear keychain: {e}")
            return False

    @with_idb_client
    async def open_url(self, client: Client, url: str) -> bool:
        try:
            await client.open_url(url)
            return True
        except Exception as e:
            logger.error(f"Failed to open URL: {e}")
            return False

    @with_idb_client
    async def describe_all(self, client: Client) -> dict[str, Any]:
        try:
            accessibility_info = await client.accessibility_info(nested=True, point=None)
            return json.loads(accessibility_info.json)
        except Exception as e:
            logger.error(f"Failed to describe all: {e}")
            return {}

    @with_idb_client
    async def describe_point(self, client: Client, x: int, y: int) -> dict[str, Any]:
        try:
            accessibility_info = await client.accessibility_info(point=(x, y), nested=True)
            return json.loads(accessibility_info.json)
        except Exception as e:
            logger.error(f"Failed to describe point: {e}")
            return {}
