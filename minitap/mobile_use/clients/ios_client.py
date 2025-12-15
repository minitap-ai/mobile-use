import json
import platform
import subprocess
from typing import Literal

from minitap.mobile_use.clients.idb_client import IdbClientWrapper
from minitap.mobile_use.clients.wda_client import WdaClientWrapper
from minitap.mobile_use.utils.shell_utils import run_shell_command_on_host

# Type alias for the union of both client wrappers
IosClientWrapper = IdbClientWrapper | WdaClientWrapper

# Device type literals
DeviceType = Literal["simulator", "physical", "unknown"]


class DeviceNotFoundError(Exception):
    """Raised when the specified device cannot be found."""

    pass


class UnsupportedDeviceError(Exception):
    """Raised when the device type is not supported."""

    pass


def get_device_type(udid: str) -> DeviceType:
    """Detect whether a device is a simulator or physical device.

    Args:
        udid: The device UDID to check

    Returns:
        "simulator" if the device is a simulator,
        "physical" if it's a physical device,
        "unknown" if detection fails
    """
    if platform.system() != "Darwin":
        return "unknown"

    # Check if it's a booted simulator
    try:
        cmd = ["xcrun", "simctl", "list", "devices", "--json"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            for _runtime, devices in data.get("devices", {}).items():
                for device in devices:
                    if device.get("udid") == udid:
                        return "simulator"
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception):
        pass

    # Check if it's a physical device using idevice_id
    try:
        cmd = ["idevice_id", "-l"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            physical_udids = result.stdout.strip().split("\n")
            if udid in physical_udids:
                return "physical"
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        pass

    # Fallback: try system_profiler for USB devices
    try:
        cmd = ["system_profiler", "SPUSBDataType", "-json"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and udid in result.stdout:
            return "physical"
    except (subprocess.TimeoutExpired, Exception):
        pass

    return "unknown"


def get_physical_devices() -> list[str]:
    """Get UDIDs of connected physical iOS devices.

    Returns:
        List of physical device UDIDs
    """
    if platform.system() != "Darwin":
        return []

    try:
        cmd = ["idevice_id", "-l"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            udids = result.stdout.strip().split("\n")
            return [u for u in udids if u]  # Filter empty strings
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        pass

    return []


def get_all_ios_devices() -> dict[str, DeviceType]:
    """Get all connected iOS devices (simulators and physical).

    Returns:
        Dictionary mapping UDID to device type
    """
    devices: dict[str, DeviceType] = {}

    # Get simulators
    success, simulator_udids, _ = get_ios_devices()
    if success:
        for udid in simulator_udids:
            devices[udid] = "simulator"

    # Get physical devices
    for udid in get_physical_devices():
        devices[udid] = "physical"

    return devices


def get_ios_client(
    udid: str,
    wda_url: str = "http://localhost:8100",
    wda_timeout: float = 30.0,
    idb_host: str | None = None,
    idb_port: int | None = None,
) -> IosClientWrapper:
    """Factory function to get the appropriate iOS client based on device type.

    Automatically detects whether the device is a simulator or physical device
    and returns the appropriate client wrapper.

    Args:
        udid: The device UDID
        wda_url: WebDriverAgent URL for physical devices (default: http://localhost:8100)
        wda_timeout: Timeout for WDA operations in seconds (default: 30.0)
        idb_host: Optional IDB companion host for simulators (None = manage locally)
        idb_port: Optional IDB companion port for simulators

    Returns:
        IdbClientWrapper for simulators, WdaClientWrapper for physical devices

    Raises:
        DeviceNotFoundError: If the device cannot be found
        UnsupportedDeviceError: If the device type cannot be determined

    Example:
        # Auto-detect and get appropriate client
        client = get_ios_client("device-udid")

        async with client:
            await client.tap(100, 200)
            screenshot = await client.screenshot()
    """
    device_type = get_device_type(udid)

    if device_type == "simulator":
        return IdbClientWrapper(udid=udid, host=idb_host, port=idb_port)

    if device_type == "physical":
        return WdaClientWrapper(wda_url=wda_url, timeout=wda_timeout)

    # Device type is unknown - try to provide helpful error
    all_devices = get_all_ios_devices()

    if not all_devices:
        raise DeviceNotFoundError(
            f"Device '{udid}' not found. No iOS devices detected.\n"
            "For simulators: Boot a simulator using Xcode or `xcrun simctl boot <udid>`\n"
            "For physical devices: Connect via USB and trust the computer on the device"
        )

    available = ", ".join(f"{u} ({t})" for u, t in all_devices.items())
    raise DeviceNotFoundError(f"Device '{udid}' not found.\nAvailable devices: {available}")


def get_ios_devices() -> tuple[bool, list[str], str]:
    """
    Get UDIDs of iOS simulator devices only.

    Returns:
        A tuple containing:
        - bool: True if xcrun is available, False otherwise.
        - list[str]: A list of iOS device UDIDs.
        - str: An error message if any.
    """
    if platform.system() != "Darwin":
        return False, [], "xcrun is only available on macOS."

    try:
        cmd = ["xcrun", "simctl", "list", "devices", "--json"]
        output = run_shell_command_on_host(" ".join(cmd))
        data = json.loads(output)

        serials = []
        devices_dict = data.get("devices", {})

        for runtime, devices in devices_dict.items():
            if "ios" in runtime.lower():  # e.g. "com.apple.CoreSimulator.SimRuntime.iOS-17-0"
                for device in devices:
                    if device.get("state") != "Booted":
                        continue
                    device_udid = device.get("udid")
                    if not device_udid:
                        continue
                    serials.append(device_udid)

        return True, serials, ""

    except FileNotFoundError:
        error_message = (
            "'xcrun' command not found. Please ensure Xcode Command Line Tools are installed."
        )
        return False, [], error_message
    except json.JSONDecodeError as e:
        return True, [], f"Failed to parse xcrun output as JSON: {e}"
    except Exception as e:
        return True, [], f"Failed to get iOS devices: {e}"
