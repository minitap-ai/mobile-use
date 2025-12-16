import asyncio
from concurrent.futures.thread import ThreadPoolExecutor
from datetime import date
from shutil import which

from adbutils import AdbDevice

from minitap.mobile_use.clients.ios_client import (
    DeviceType,
    get_all_ios_devices_detailed,
    get_device_type,
)
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
        udid = ctx.device.device_id
        device_type = get_device_type(udid)

        if device_type == DeviceType.SIMULATOR:
            cmd = ["xcrun", "simctl", "listapps", udid, "|", "grep", "CFBundleIdentifier"]
            return run_shell_command_on_host(" ".join(cmd))

        # Physical device: try ios-deploy first (common with React Native/Cordova)
        if which("ios-deploy"):
            cmd = ["ios-deploy", "--id", udid, "--list_bundle_id"]
            try:
                output = run_shell_command_on_host(" ".join(cmd))
                packages = [line.strip() for line in output.strip().split("\n") if line.strip()]
                return "\n".join(sorted(packages))
            except Exception as e:
                logger.debug(f"ios-deploy failed: {e}")

        # Fallback: ideviceinstaller (libimobiledevice)
        if which("ideviceinstaller"):
            cmd = ["ideviceinstaller", "-l", "-u", udid]
            try:
                output = run_shell_command_on_host(" ".join(cmd))
                # Parse output: "CFBundleIdentifier, CFBundleVersion, CFBundleDisplayName"
                lines = output.strip().split("\n")
                packages = []
                for line in lines:
                    if ", " in line:
                        bundle_id = line.split(", ")[0].strip()
                        if bundle_id and not bundle_id.startswith("CFBundle"):
                            packages.append(bundle_id)
                return "\n".join(sorted(packages))
            except Exception as e:
                logger.debug(f"ideviceinstaller failed: {e}")

        logger.warning(
            "Cannot list apps on physical iOS device. Install ios-deploy "
            "(npm install -g ios-deploy) or ideviceinstaller (brew install ideviceinstaller)"
        )
        return ""
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
            return _get_ios_foreground_package(ctx)

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


def _get_ios_foreground_package(ctx: MobileUseContext) -> str | None:
    """Get foreground package for iOS devices (simulator or physical)."""

    ios_client = ctx.ios_client

    if not ios_client:
        return None

    try:
        # Handle both running and non-running event loops
        try:
            asyncio.get_running_loop()
            # Already in async context - run in separate thread
            with ThreadPoolExecutor() as pool:
                app_info = pool.submit(asyncio.run, ios_client.app_current()).result(timeout=10)
        except RuntimeError:
            # No running loop - use asyncio.run()
            app_info = asyncio.run(ios_client.app_current())
        if app_info and app_info.bundle_id:
            return app_info.bundle_id
    except Exception as e:
        logger.debug(f"Failed to get foreground app: {e}")
    return None
