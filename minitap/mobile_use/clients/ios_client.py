import json
import platform
import re
from enum import Enum
from typing import TypedDict

from minitap.mobile_use.clients.browserstack_client import BrowserStackClientWrapper
from minitap.mobile_use.clients.idb_client import IdbClientWrapper
from minitap.mobile_use.clients.ios_client_config import IosClientConfig
from minitap.mobile_use.clients.wda_client import WdaClientWrapper
from minitap.mobile_use.utils.logger import get_logger
from minitap.mobile_use.utils.shell_utils import run_shell_command_on_host

logger = get_logger(__name__)


def _run_host_cmd(cmd: list[str]) -> str:
    return run_shell_command_on_host(" ".join(cmd))


# Type alias for the union of all client wrappers
IosClientWrapper = IdbClientWrapper | WdaClientWrapper | BrowserStackClientWrapper


class DeviceType(str, Enum):
    """Type of iOS device."""

    SIMULATOR = "SIMULATOR"
    PHYSICAL = "PHYSICAL"
    BROWSERSTACK = "BROWSERSTACK"
    UNKNOWN = "UNKNOWN"


class DeviceInfo(TypedDict):
    """Information about an iOS device."""

    udid: str
    type: DeviceType
    name: str


def format_device_info(device: DeviceInfo) -> str:
    return f"{device['name']} ({device['type'].value}) - {device['udid']}"


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
        DeviceType.SIMULATOR if the device is a simulator,
        DeviceType.PHYSICAL if it's a physical device,
        DeviceType.UNKNOWN if detection fails
    """
    if platform.system() != "Darwin":
        return DeviceType.UNKNOWN

    # Check if it's a booted simulator
    try:
        cmd = ["xcrun", "simctl", "list", "devices", "--json"]
        output = _run_host_cmd(cmd)
        data = json.loads(output)
        for _runtime, devices in data.get("devices", {}).items():
            for device in devices:
                if device.get("udid") == udid and device.get("state") == "Booted":
                    return DeviceType.SIMULATOR
    except (RuntimeError, json.JSONDecodeError, Exception):
        logger.debug("Failed to detect simulator device type")
        pass

    # Check if it's a physical device using idevice_id
    try:
        cmd = ["idevice_id", "-l"]
        output = _run_host_cmd(cmd)
        physical_udids = output.strip().split("\n") if output else []
        if udid in physical_udids:
            return DeviceType.PHYSICAL
    except (RuntimeError, Exception) as e:
        logger.debug(f"Failed to detect physical device type using idevice_id: {e}")
        pass

    # Fallback: try system_profiler for USB devices
    try:
        cmd = ["system_profiler", "SPUSBDataType", "-json"]
        output = _run_host_cmd(cmd)
        if udid in output:
            return DeviceType.PHYSICAL
    except (RuntimeError, Exception) as e:
        logger.debug(f"Failed to detect physical device type using system_profiler: {e}")
        pass

    return DeviceType.UNKNOWN


def get_physical_devices() -> list[str]:
    """Get UDIDs of connected physical iOS devices.

    Returns:
        List of physical device UDIDs
    """
    if platform.system() != "Darwin":
        return []

    # Try idevice_id first (libimobiledevice) - most reliable
    try:
        cmd = ["idevice_id", "-l"]
        output = _run_host_cmd(cmd)
        udids = output.strip().split("\n") if output else []
        return [u for u in udids if u]
    except (RuntimeError, Exception):
        pass

    # Fallback to xcrun xctrace - filter out simulators by checking name
    try:
        cmd = ["xcrun", "xctrace", "list", "devices"]
        output = _run_host_cmd(cmd)
        udids: list[str] = []
        for line in output.strip().split("\n") if output else []:
            if "Simulator" in line:
                continue
            match = re.search(r"\(([A-Fa-f0-9-]{36})\)$", line)
            if match:
                udids.append(match.group(1))
        return udids
    except (RuntimeError, Exception):
        pass

    return []


def get_physical_ios_devices() -> list[DeviceInfo]:
    """Get detailed info about connected physical iOS devices.

    Returns:
        List of DeviceInfo dicts with udid, type, and name
    """
    if platform.system() != "Darwin":
        return []

    devices: list[DeviceInfo] = []

    # Primary: idevice_id + ideviceinfo for names (most reliable)
    try:
        cmd = ["idevice_id", "-l"]
        output = _run_host_cmd(cmd)
        for udid in output.strip().split("\n") if output else []:
            if not udid:
                continue
            name = _get_device_name(udid)
            devices.append(
                DeviceInfo(udid=udid, type=DeviceType.PHYSICAL, name=name or "Unknown Device")
            )
        if devices:
            return devices
    except (RuntimeError, Exception):
        pass

    # Fallback: xcrun xctrace - filter out simulators by name
    try:
        cmd = ["xcrun", "xctrace", "list", "devices"]
        output = _run_host_cmd(cmd)
        for line in output.strip().split("\n") if output else []:
            if "Simulator" in line:
                continue
            match = re.search(r"^(.+?)\s+\([^)]+\)\s+\(([A-Fa-f0-9-]{36})\)$", line)
            if match:
                devices.append(
                    DeviceInfo(
                        udid=match.group(2),
                        type=DeviceType.PHYSICAL,
                        name=match.group(1).strip(),
                    )
                )
    except (RuntimeError, Exception):
        pass

    return devices


def _get_device_name(udid: str) -> str | None:
    """Get device name using ideviceinfo."""
    try:
        cmd = ["ideviceinfo", "-u", udid, "-k", "DeviceName"]
        output = _run_host_cmd(cmd)
        return output.strip() if output else None
    except (RuntimeError, Exception):
        return None


def get_simulator_devices() -> list[DeviceInfo]:
    """Get detailed info about booted iOS simulators.

    Returns:
        List of DeviceInfo dicts with udid, type, and name
    """
    if platform.system() != "Darwin":
        return []

    devices: list[DeviceInfo] = []

    try:
        cmd = ["xcrun", "simctl", "list", "devices", "--json"]
        output = _run_host_cmd(cmd)
        data = json.loads(output)
        for runtime, runtime_devices in data.get("devices", {}).items():
            if "ios" not in runtime.lower():
                continue
            for device in runtime_devices:
                if device.get("state") != "Booted":
                    continue
                udid = device.get("udid")
                name = device.get("name")
                if not udid:
                    continue
                devices.append(
                    DeviceInfo(
                        udid=udid,
                        type=DeviceType.SIMULATOR,
                        name=name or "Unknown Simulator",
                    )
                )
    except (RuntimeError, json.JSONDecodeError, Exception):
        pass

    return devices


def get_all_ios_devices() -> dict[str, DeviceType]:
    """Get all connected iOS devices (simulators and physical).

    Returns:
        Dictionary mapping UDID to device type
    """
    devices: dict[str, DeviceType] = {}

    # Get simulators
    for device in get_simulator_devices():
        devices[device["udid"]] = DeviceType.SIMULATOR

    # Get physical devices
    for device in get_physical_ios_devices():
        devices[device["udid"]] = DeviceType.PHYSICAL

    return devices


def get_all_ios_devices_detailed() -> list[DeviceInfo]:
    """Get detailed info about all connected iOS devices.

    Returns:
        List of DeviceInfo dicts with udid, type, and name
    """
    devices: list[DeviceInfo] = []
    devices.extend(get_simulator_devices())
    devices.extend(get_physical_ios_devices())
    return devices


def get_ios_client(
    udid: str | None = None,
    config: IosClientConfig | None = None,
) -> IosClientWrapper:
    """Factory function to get the appropriate iOS client based on device type.

    Automatically detects whether the device is a simulator or physical device
    and returns the appropriate client wrapper.

    Args:
        udid: Optional device UDID
        config: Optional iOS client configuration (WDA/IDB settings). Defaults are used when None.

    Returns:
        IdbClientWrapper for simulators, WdaClientWrapper for physical devices

    Raises:
        DeviceNotFoundError: If the device cannot be found

    Example:
        # Auto-detect and get appropriate client
        client = get_ios_client("device-udid")

        async with client:
            await client.tap(100, 200)
            screenshot = await client.screenshot()
    """
    if not udid:
        if config and config.browserstack:
            return BrowserStackClientWrapper(config=config.browserstack)
        raise DeviceNotFoundError("No device UDID provided")

    device_type = get_device_type(udid)
    resolved_config = config or IosClientConfig()

    if device_type == DeviceType.SIMULATOR:
        return IdbClientWrapper(
            udid=udid,
            host=resolved_config.idb.host,
            port=resolved_config.idb.port,
        )

    if device_type == DeviceType.PHYSICAL:
        return WdaClientWrapper(
            udid=udid,
            config=resolved_config.wda,
        )

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
