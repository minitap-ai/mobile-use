import asyncio
import json
import socket
import subprocess
from functools import wraps
from pathlib import Path
from typing import Any

from idb.common.types import HIDButtonType, InstalledAppInfo, InstalledArtifact, TCPAddress
from idb.grpc.client import Client
from pydantic import BaseModel

from minitap.mobile_use.utils.logger import get_logger


class IOSAppInfo(BaseModel):
    name: str | None
    bundle_id: str | None


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
    """Decorator to ensure idb client is initialized before method call.

    Note: Function must have None or bool in return type.
    """

    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        method_name = func.__name__
        try:
            if self._client is None:
                raise RuntimeError(
                    "IDB client not initialized. "
                    "Use 'async with' context manager or call init_companion() first."
                )
            logger.debug(f"Calling {method_name}...")
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
        self._client: Client | None = None
        self._client_generator: Any = None

    @property
    def client(self) -> Client:
        """Get the initialized IDB client. Raises if not initialized."""
        if self._client is None:
            raise RuntimeError(
                "IDB client not initialized. "
                "Use 'async with' context manager or call init_companion() first."
            )
        return self._client

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
            # Still need to build the client connection
            logger.debug("Building IDB client connection...")
            self._client_generator = Client.build(address=self.address, logger=logger.logger)
            self._client = await self._client_generator.__aenter__()
            logger.debug("IDB client connected")
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

            # Wait longer for gRPC server to be fully ready
            logger.debug("Waiting for idb_companion gRPC server to be ready...")
            await asyncio.sleep(5)

            if self.companion_process.poll() is not None:
                stdout, stderr = self.companion_process.communicate()
                logger.error(f"idb_companion failed to start: {stderr}")
                self.companion_process = None
                return False

            logger.info(
                f"idb_companion started successfully for {self.udid} on port {self.address.port}"
            )

            # Build and store the client connection
            logger.debug("Building IDB client connection...")
            self._client_generator = Client.build(address=self.address, logger=logger.logger)
            self._client = await self._client_generator.__aenter__()
            logger.debug("IDB client connected")

            return True

        except FileNotFoundError:
            logger.error(
                "idb_companion not found. Please install fb-idb to use iOS devices.\n"
                "Installation guide: https://fbidb.io/docs/installation/\n"
                "On macOS with Homebrew: brew install idb-companion"
            )
            self.companion_process = None
            return False
        except Exception as e:
            logger.error(f"Failed to start idb_companion: {e}")
            self.companion_process = None
            return False

    async def cleanup(self) -> None:
        # Always close the client context manager if it exists
        if self._client_generator is not None:
            try:
                logger.debug("Closing IDB client connection...")
                await self._client_generator.__aexit__(None, None, None)
                logger.debug("IDB client closed")
            except Exception as e:
                logger.error(f"Error closing IDB client: {e}")
            finally:
                self._client = None
                self._client_generator = None

        if not self._manage_companion:
            logger.debug(f"Not managing companion for {self.udid}, skipping companion cleanup")
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
        if not await self.init_companion():
            raise RuntimeError(f"Failed to initialize idb_companion for device {self.udid}")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()
        return False

    @with_idb_client
    async def tap(self, x: int, y: int, duration: float | None = None) -> bool:
        await self.client.tap(x=x, y=y, duration=duration)
        return True

    @with_idb_client
    async def swipe(
        self,
        x_start: int,
        y_start: int,
        x_end: int,
        y_end: int,
        duration: float | None = None,
    ) -> bool:
        await self.client.swipe(p_start=(x_start, y_start), p_end=(x_end, y_end), duration=duration)
        return True

    @with_idb_client
    async def screenshot(self, output_path: str | None = None) -> bytes | None:
        """
        Take a screenshot and return raw image data.

        Returns:
            Raw image data (PNG bytes not base64 encoded)
        """
        screenshot_data = await self.client.screenshot()
        if output_path:
            with open(output_path, "wb") as f:
                f.write(screenshot_data)
        return screenshot_data

    @with_idb_client
    async def launch(
        self,
        bundle_id: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> bool:
        await self.client.launch(
            bundle_id=bundle_id, args=args or [], env=env or {}, foreground_if_running=True
        )
        return True

    @with_idb_client
    async def terminate(self, bundle_id: str) -> bool:
        await self.client.terminate(bundle_id)
        return True

    @with_idb_client
    async def install(self, app_path: str) -> list[InstalledArtifact] | None:
        bundle_path = Path(app_path)
        artifacts = []
        with open(bundle_path, "rb") as f:
            async for artifact in self.client.install(bundle=f):
                artifacts.append(artifact)
        return artifacts

    @with_idb_client
    async def uninstall(self, bundle_id: str) -> bool:
        await self.client.uninstall(bundle_id)
        return True

    @with_idb_client
    async def list_apps(self) -> list[InstalledAppInfo] | None:
        apps = await self.client.list_apps()
        return apps

    @with_idb_client
    async def text(self, text: str) -> bool:
        await self.client.text(text)
        return True

    @with_idb_client
    async def key(self, key_code: int) -> bool:
        await self.client.key(key_code)
        return True

    @with_idb_client
    async def button(self, button_type: HIDButtonType) -> bool:
        await self.client.button(button_type=button_type)
        return True

    @with_idb_client
    async def clear_keychain(self) -> bool:
        await self.client.clear_keychain()
        return True

    @with_idb_client
    async def open_url(self, url: str) -> bool:
        await self.client.open_url(url)
        return True

    async def app_current(self) -> IOSAppInfo | None:
        """Get information about the currently active app on simulator.

        Uses idb ui describe-all to find the app name from the UI hierarchy,
        then looks up the bundle ID from simctl listapps.
        Returns dict with bundleId or None.
        """
        try:
            # Get the accessibility hierarchy to find the foreground app name
            elements = await self.describe_all()
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

            # Get installed apps from simctl and find bundle ID by display name
            cmd = ["xcrun", "simctl", "listapps", self.udid]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()

            if process.returncode != 0:
                return IOSAppInfo(name=app_name, bundle_id=None)

            # Parse plist-style output
            # Format: "com.apple.MobileAddressBook" = { ... CFBundleDisplayName = Contacts; ...}
            import re

            output = stdout.decode()
            current_bundle_id = None

            for line in output.split("\n"):
                line = line.strip()
                # Match app entry: "com.bundle.id" = {
                bundle_match = re.match(r'"([^"]+)"\s*=\s*\{', line)
                if bundle_match:
                    current_bundle_id = bundle_match.group(1)
                    continue

                # Match display name: CFBundleDisplayName = AppName; (no quotes)
                # or CFBundleName = AppName;
                if current_bundle_id:
                    name_match = re.match(r"CFBundle(?:Display)?Name\s*=\s*([^;]+);", line)
                    if name_match:
                        display_name = name_match.group(1).strip()
                        if display_name == app_name:
                            return IOSAppInfo(name=app_name, bundle_id=current_bundle_id)

                # Reset on closing brace
                if line == "};":
                    current_bundle_id = None

            return IOSAppInfo(name=app_name, bundle_id=None)
        except Exception as e:
            logger.debug(f"Failed to get current app: {e}")
            return None

    async def describe_all(self) -> list[dict[str, Any]] | None:
        try:
            cmd = ["idb", "ui", "describe-all", "--udid", self.udid, "--json"]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                logger.error(f"idb describe-all failed: {stderr.decode()}")
                return None

            parsed = json.loads(stdout.decode())
            return parsed if isinstance(parsed, list) else [parsed]
        except Exception as e:
            logger.error(f"Failed to describe_all: {e}")
            return None

    @with_idb_client
    async def describe_point(self, x: int, y: int) -> dict[str, Any] | None:
        accessibility_info = await self.client.accessibility_info(point=(x, y), nested=True)
        return json.loads(accessibility_info.json)
