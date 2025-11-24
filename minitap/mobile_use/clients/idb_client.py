import asyncio
import json
import socket
import subprocess
from functools import wraps
from pathlib import Path
from typing import Any

from idb.common.types import HIDButtonType, InstalledAppInfo, TCPAddress
from idb.grpc.client import Client

from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


def _find_available_port(start_port: int = 10882, max_attempts: int = 100) -> int:
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("localhost", port))
                return port
            except OSError:
                continue
    raise RuntimeError(
        f"Could not find available port in range {start_port}-{start_port + max_attempts}"
    )


def with_idb_client(func):
    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        async with Client.build(address=self.address, logger=logger.logger) as client:
            return await func(self, client, *args, **kwargs)

    return wrapper


class IdbClientWrapper:
    """Wrapper around fb-idb client for iOS device automation with lifecycle management.

    This wrapper can either manage the idb_companion process lifecycle locally or connect
    to an external companion server.

    Lifecycle Management:
    - If host is None (default): Manages companion locally on localhost
      - Call init_companion() to start the idb_companion process
      - Call cleanup() to stop the companion process
      - Or use as async context manager for automatic lifecycle
    - If host is provided: Connects to external companion server
      - init_companion() and cleanup() become no-ops
      - You manage the external companion separately

    Example:
        # Managed companion (recommended for local development)
        async with IdbClientWrapper(udid="device-id") as wrapper:
            await wrapper.tap(100, 200)

        # External companion (for production/remote)
        wrapper = IdbClientWrapper(udid="device-id", host="remote-host", port=10882)
        await wrapper.tap(100, 200)  # No companion lifecycle management needed
    """

    def __init__(self, udid: str, host: str | None = None, port: int | None = None):
        self.udid = udid
        self._manage_companion = host is None

        if host is None:
            actual_port = port if port is not None else _find_available_port()
            self.address = TCPAddress(host="localhost", port=actual_port)
            logger.debug(f"Will manage companion for {udid} on port {actual_port}")
        else:
            actual_port = port if port is not None else 10882
            self.address = TCPAddress(host=host, port=actual_port)

        self.companion_process: subprocess.Popen | None = None

    async def init_companion(self, idb_companion_path: str = "idb_companion") -> bool:
        """
        Start the idb_companion process for this device.
        Only starts if managing companion locally (host was None in __init__).

        Args:
            idb_companion_path: Path to idb_companion binary (default: "idb_companion" from PATH)

        Returns:
            True if companion started successfully, False otherwise
        """
        if not self._manage_companion:
            logger.info(f"Using external idb_companion at {self.address.host}:{self.address.port}")
            return True

        if self.companion_process is not None:
            logger.warning(f"idb_companion already running for {self.udid}")
            return True

        try:
            cmd = [idb_companion_path, "--udid", self.udid, "--grpc-port", str(self.address.port)]

            logger.info(f"Starting idb_companion: {' '.join(cmd)}")
            self.companion_process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )

            await asyncio.sleep(2)

            if self.companion_process.poll() is not None:
                stdout, stderr = self.companion_process.communicate()
                logger.error(f"idb_companion failed to start: {stderr}")
                self.companion_process = None
                return False

            logger.info(
                f"idb_companion started successfully for {self.udid} on port {self.address.port}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to start idb_companion: {e}")
            self.companion_process = None
            return False

    async def cleanup(self) -> None:
        if not self._manage_companion:
            logger.debug(f"Not managing companion for {self.udid}, skipping cleanup")
            return

        if self.companion_process is None:
            return

        try:
            logger.info(f"Stopping idb_companion for {self.udid}")

            self.companion_process.terminate()

            try:
                await asyncio.wait_for(asyncio.to_thread(self.companion_process.wait), timeout=5.0)
                logger.info(f"idb_companion stopped gracefully for {self.udid}")
            except TimeoutError:
                logger.warning(f"Force killing idb_companion for {self.udid}")
                self.companion_process.kill()
                await asyncio.to_thread(self.companion_process.wait)

        except Exception as e:
            logger.error(f"Error stopping idb_companion: {e}")
        finally:
            self.companion_process = None

    def __del__(self):
        if self.companion_process is not None:
            try:
                self.companion_process.terminate()
                self.companion_process.wait(timeout=2)
            except Exception:
                try:
                    self.companion_process.kill()
                except Exception:
                    pass

    async def __aenter__(self):
        await self.init_companion()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()
        return False

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
