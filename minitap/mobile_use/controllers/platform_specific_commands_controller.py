import re
from datetime import date
from shutil import which

from adbutils import AdbDevice

from minitap.mobile_use.clients.ios_client import DeviceType, get_all_ios_devices_detailed
from minitap.mobile_use.context import DevicePlatform, MobileUseContext
from minitap.mobile_use.utils.logger import MobileUseLogger, get_logger
from minitap.mobile_use.utils.shell_utils import run_shell_command_on_host

logger = get_logger(__name__)


def get_adb_device(ctx: MobileUseContext) -> AdbDevice:
    if ctx.device.mobile_platform != DevicePlatform.ANDROID:
        raise ValueError("Device is not an Android device")
    adb = ctx.get_adb_client()
    device = adb.device(serial=ctx.device.device_id)
    if not device:
        raise ConnectionError(f"Device {ctx.device.device_id} not found.")
    return device


def get_first_device(
    logger: MobileUseLogger | None = None,
    prefer_physical: bool = True,
) -> tuple[str | None, DevicePlatform | None, DeviceType | None]:
    """Gets the first available device.

    Args:
        logger: Optional logger for error messages
        prefer_physical: If True, prefer physical iOS devices over simulators

    Returns:
        Tuple of (device_id, platform, device_type) or (None, None, None) if no device found.
        device_type is only set for iOS devices (SIMULATOR or PHYSICAL).
    """
    # Check for Android devices first
    if which("adb"):
        try:
            android_output = run_shell_command_on_host("adb devices")
            lines = android_output.strip().split("\n")
            for line in lines:
                if "device" in line and not line.startswith("List of devices"):
                    return line.split()[0], DevicePlatform.ANDROID, None
        except RuntimeError as e:
            if logger:
                logger.error(f"ADB command failed: {e}")

    # Check for iOS devices (both simulators and physical)
    ios_devices = get_all_ios_devices_detailed()
    if ios_devices:
        if prefer_physical:
            # Sort to prefer physical devices
            ios_devices.sort(key=lambda d: d["type"] != DeviceType.PHYSICAL)

        device = ios_devices[0]
        if logger:
            logger.info(
                f"Selected iOS device: {device['name']} ({device['type'].value}) - {device['udid']}"
            )
        return device["udid"], DevicePlatform.IOS, device["type"]

    return None, None, None


def get_device_date(ctx: MobileUseContext) -> str:
    if ctx.device.mobile_platform == DevicePlatform.IOS:
        return date.today().strftime("%a %b %d %H:%M:%S %Z %Y")
    device = get_adb_device(ctx)
    return str(device.shell("date"))


def list_packages(ctx: MobileUseContext) -> str:
    if ctx.device.mobile_platform == DevicePlatform.IOS:
        cmd = ["xcrun", "simctl", "listapps", "booted", "|", "grep", "CFBundleIdentifier"]
        return run_shell_command_on_host(" ".join(cmd))
    else:
        device = get_adb_device(ctx)
        # Get full package list with paths
        cmd = ["pm", "list", "packages", "-f"]
        raw_output = str(device.shell(" ".join(cmd)))

        # Extract only package names (remove paths and "package:" prefix)
        # Format: "package:/path/to/app.apk=com.example.app" -> "com.example.app"
        lines = raw_output.strip().split("\n")
        packages = []
        for line in lines:
            if "=" in line:
                package_name = line.split("=")[-1].strip()
                packages.append(package_name)

        return "\n".join(sorted(packages))


def get_current_foreground_package(ctx: MobileUseContext) -> str | None:
    """
    Get the package name of the currently focused/foreground app.

    Returns only the clean package/bundle name (e.g., 'com.whatsapp'),
    without any metadata or window information.

    Returns:
        The package/bundle name, or None if unable to determine
    """
    try:
        if ctx.device.mobile_platform == DevicePlatform.IOS:
            output = run_shell_command_on_host(
                "xcrun simctl spawn booted launchctl print "
                "system/com.apple.SpringBoard.services | grep bundleIdentifier"
            )
            match = re.search(r'"bundleIdentifier"\s*=\s*"([^"]+)"', output)
            if match:
                bundle_id = match.group(1)
                if "." in bundle_id:
                    return bundle_id
            return None

        device = get_adb_device(ctx)
        output = str(device.shell("dumpsys window | grep mCurrentFocus"))

        if "mCurrentFocus=" not in output:
            return None

        segment = output.split("mCurrentFocus=")[-1]

        if "/" in segment:
            tokens = segment.split()
            for token in tokens:
                if "." in token and not token.startswith("Window"):
                    package = token.split("/")[0]
                    package = package.rstrip("}")
                    if package and "." in package:
                        return package

        return None

    except Exception as e:
        logger.debug(f"Failed to get current foreground package: {e}")
        return None
