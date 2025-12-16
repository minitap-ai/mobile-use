import asyncio
import re
import shutil
import subprocess

import httpx

from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)

# WDA bundle ID (default for Appium's WDA)
WDA_BUNDLE_ID = "com.facebook.WebDriverAgentRunner.xctrunner"
WDA_BUNDLE_ID_ALT = "com.apple.test.WebDriverAgentRunner-Runner"

# Default ports
DEFAULT_WDA_PORT = 8100
DEFAULT_DEVICE_WDA_PORT = 8100


async def check_wda_running(port: int = DEFAULT_WDA_PORT, timeout: float = 5.0) -> bool:
    """Check if WDA server is running and responding.

    Args:
        port: WDA port to check (default: 8100)
        timeout: Request timeout in seconds

    Returns:
        True if WDA is running and responding, False otherwise
    """
    url = f"http://localhost:{port}/status"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                # WDA returns a status object with sessionId
                if "value" in data or "sessionId" in data:
                    logger.debug(f"WDA is running on port {port}")
                    return True
            return False
    except httpx.ConnectError:
        logger.debug(f"WDA not responding on port {port} (connection refused)")
        return False
    except httpx.TimeoutException:
        logger.debug(f"WDA not responding on port {port} (timeout)")
        return False
    except Exception as e:
        logger.debug(f"Error checking WDA status: {e}")
        return False


def check_iproxy_running(port: int = DEFAULT_WDA_PORT) -> bool:
    """Check if iproxy is running for the specified port.

    Args:
        port: Local port to check (default: 8100)

    Returns:
        True if iproxy is running for this port, False otherwise
    """
    try:
        # Check for iproxy process listening on the port
        result = subprocess.run(
            ["pgrep", "-f", f"iproxy.*{port}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception as e:
        logger.debug(f"Error checking iproxy status: {e}")
        return False


def get_iproxy_pid(port: int = DEFAULT_WDA_PORT) -> int | None:
    """Get the PID of iproxy process for the specified port.

    Args:
        port: Local port to check

    Returns:
        PID if found, None otherwise
    """
    try:
        result = subprocess.run(
            ["pgrep", "-f", f"iproxy.*{port}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip().split()[0])
        return None
    except Exception:
        return None


async def start_iproxy(
    local_port: int = DEFAULT_WDA_PORT,
    device_port: int = DEFAULT_DEVICE_WDA_PORT,
    udid: str | None = None,
) -> subprocess.Popen | None:
    """Start iproxy for port forwarding.

    Args:
        local_port: Local port to forward to (default: 8100)
        device_port: Device port to forward from (default: 8100)
        udid: Optional device UDID (uses first device if not specified)

    Returns:
        Popen process object if started successfully, None otherwise
    """
    if not shutil.which("iproxy"):
        logger.error("iproxy not found. Install libimobiledevice:\n  brew install libimobiledevice")
        return None

    # Check if already running
    if check_iproxy_running(local_port):
        logger.info(f"iproxy already running on port {local_port}")
        return None

    try:
        cmd = ["iproxy", str(local_port), str(device_port)]
        if udid:
            cmd.extend(["-u", udid])

        logger.info(f"Starting iproxy: {' '.join(cmd)}")
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )

        # Give it a moment to start
        await asyncio.sleep(0.5)

        # Check if it's still running
        if process.poll() is not None:
            stderr = process.stderr.read().decode() if process.stderr else ""
            logger.error(f"iproxy failed to start: {stderr}")
            return None

        logger.info(f"iproxy started successfully (PID: {process.pid})")
        return process

    except Exception as e:
        logger.error(f"Failed to start iproxy: {e}")
        return None


def find_wda_project() -> str | None:
    """Find WebDriverAgent.xcodeproj in common locations.

    Returns:
        Path to WebDriverAgent.xcodeproj or None if not found
    """
    import os
    from pathlib import Path

    # Common locations to search
    search_paths = [
        # Current directory
        Path.cwd() / "WebDriverAgent" / "WebDriverAgent.xcodeproj",
        Path.cwd() / "WebDriverAgent.xcodeproj",
        # Home directory
        Path.home() / "WebDriverAgent" / "WebDriverAgent.xcodeproj",
        # Appium installation
        Path.home()
        / ".appium"
        / "node_modules"
        / "appium-xcuitest-driver"
        / "node_modules"
        / "appium-webdriveragent"
        / "WebDriverAgent.xcodeproj",
        # Common dev locations
        Path.home() / "Developer" / "WebDriverAgent" / "WebDriverAgent.xcodeproj",
        Path.home() / "Projects" / "WebDriverAgent" / "WebDriverAgent.xcodeproj",
        Path(
            "/usr/local/lib/node_modules/appium/node_modules/appium-webdriveragent"
            "/WebDriverAgent.xcodeproj"
        ),
    ]

    # Also check WDA_PROJECT_PATH environment variable
    env_path = os.environ.get("WDA_PROJECT_PATH")
    if env_path:
        search_paths.insert(0, Path(env_path))

    for path in search_paths:
        if path.exists():
            logger.debug(f"Found WDA project at: {path}")
            return str(path)

    return None


async def build_and_run_wda(
    udid: str,
    project_path: str | None = None,
    timeout: float = 120.0,
) -> subprocess.Popen | None:
    """Build and run WebDriverAgent on the device using xcodebuild.

    This starts xcodebuild test in the background, which builds WDA if needed
    and runs it on the device.

    Args:
        udid: Device UDID
        project_path: Path to WebDriverAgent.xcodeproj (auto-detected if None)
        timeout: Build timeout in seconds (default: 120)

    Returns:
        Popen process object if started successfully, None otherwise
    """
    if not shutil.which("xcodebuild"):
        logger.error("xcodebuild not found. Please install Xcode.")
        return None

    # Find WDA project
    if project_path is None:
        project_path = find_wda_project()

    if project_path is None:
        logger.error(
            "WebDriverAgent.xcodeproj not found.\n"
            "Please clone it first:\n"
            "  git clone https://github.com/appium/WebDriverAgent.git\n"
            "Or set WDA_PROJECT_PATH environment variable."
        )
        return None

    logger.info(f"Building and running WDA from: {project_path}")
    logger.info(f"Target device: {udid[:16]}...")
    logger.info("This may take a minute on first run...")

    try:
        # Build and test command
        cmd = [
            "xcodebuild",
            "test",
            "-project",
            project_path,
            "-scheme",
            "WebDriverAgentRunner",
            "-destination",
            f"id={udid}",
            "-allowProvisioningUpdates",
        ]

        # Start xcodebuild in background
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )

        # Wait for WDA to start (look for "ServerURLHere" in output)
        start_time = asyncio.get_event_loop().time()
        server_started = False

        while asyncio.get_event_loop().time() - start_time < timeout:
            if process.poll() is not None:
                # Process ended - check if it failed
                output = process.stdout.read() if process.stdout else ""
                if "BUILD FAILED" in output or "error:" in output.lower():
                    logger.error(f"WDA build failed:\n{output[-1000:]}")
                    return None
                break

            # Check output for server start indicator
            if process.stdout:
                line = process.stdout.readline()
                if line:
                    logger.debug(f"xcodebuild: {line.strip()}")
                    if "ServerURLHere" in line or "WebDriverAgent" in line:
                        server_started = True
                        logger.info("WDA server starting on device...")

            # If server started, give it a moment then return
            if server_started:
                await asyncio.sleep(3)
                if process.poll() is None:
                    logger.info("WDA build and run started successfully")
                    return process

            await asyncio.sleep(0.5)

        if process.poll() is None:
            # Still running after timeout - assume it's working
            logger.info("WDA process running (build may still be in progress)")
            return process

        return None

    except Exception as e:
        logger.error(f"Failed to start xcodebuild: {e}")
        return None


def get_wda_setup_instructions(udid: str) -> str:
    """Get WDA setup instructions (only manual steps not handled by code)."""
    return f"""WebDriverAgent Setup (device: {udid[:16]}...)

1. Clone WebDriverAgent:
   git clone https://github.com/appium/WebDriverAgent.git

2. Configure code signing in Xcode:
   - Open WebDriverAgent.xcodeproj
   - Select WebDriverAgentLib target → Signing & Capabilities
   - Set your Team and Bundle Identifier
   - Repeat for WebDriverAgentRunner target

Build and run are handled automatically after signing is configured.
"""


async def wait_for_wda(
    port: int = DEFAULT_WDA_PORT,
    timeout: float = 60.0,
    poll_interval: float = 2.0,
) -> bool:
    """Wait for WDA to become available.

    Args:
        port: WDA port to check
        timeout: Maximum time to wait in seconds
        poll_interval: Time between checks in seconds

    Returns:
        True if WDA became available, False if timeout
    """
    logger.info(
        f"Waiting for WDA on port {port} (unlock your device, password may be required) "
        f"(timeout: {timeout}s)..."
    )
    elapsed = 0.0

    while elapsed < timeout:
        if await check_wda_running(port):
            logger.info(f"WDA is ready on port {port}")
            return True

        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
        logger.debug(f"Waiting for WDA... ({elapsed:.0f}s/{timeout:.0f}s)")

    logger.error(f"Timeout waiting for WDA on port {port}")
    return False


def parse_wda_port_from_url(url: str) -> int:
    """Extract port number from WDA URL.

    Args:
        url: WDA URL (e.g., "http://localhost:8100")

    Returns:
        Port number (default: 8100 if not found)
    """
    match = re.search(r":(\d+)", url)
    if match:
        return int(match.group(1))
    return DEFAULT_WDA_PORT
