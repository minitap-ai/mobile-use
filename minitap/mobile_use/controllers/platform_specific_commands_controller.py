import json
from datetime import date
from shutil import which

from adbutils import AdbDevice

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
) -> tuple[str | None, DevicePlatform | None]:
    """Gets the first available device."""
    if which("adb"):
        try:
            android_output = run_shell_command_on_host("adb devices")
            lines = android_output.strip().split("\n")
            for line in lines:
                if "device" in line and not line.startswith("List of devices"):
                    return line.split()[0], DevicePlatform.ANDROID
        except RuntimeError as e:
            if logger:
                logger.error(f"ADB command failed: {e}")

    if which("xcrun"):
        try:
            ios_output = run_shell_command_on_host("xcrun simctl list devices booted -j")
            data = json.loads(ios_output)
            for runtime, devices in data.get("devices", {}).items():
                if "iOS" not in runtime:
                    continue
                for device in devices:
                    if device.get("state") == "Booted":
                        return device["udid"], DevicePlatform.IOS
        except RuntimeError as e:
            if logger:
                logger.error(f"xcrun command failed: {e}")

    return None, None


def get_focused_app_info(ctx: MobileUseContext) -> str | None:
    if ctx.device.mobile_platform == DevicePlatform.IOS:
        return None
    device = get_adb_device(ctx)
    return str(device.shell("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'"))


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

    For Android: Extracts from 'adb shell dumpsys window | grep mCurrentFocus'
    For iOS: Uses native xcrun command first, falls back to maestro query if available

    Returns:
        The package/bundle name (e.g., 'com.whatsapp'), or None if unable to determine
    """
    try:
        if ctx.device.mobile_platform == DevicePlatform.IOS:
            try:
                cmd = (
                    "xcrun simctl spawn booted launchctl print "
                    "system/com.apple.SpringBoard.services | grep FrontmostApplication"
                )
                output = run_shell_command_on_host(cmd)
                if output and "bundleIdentifier" in output:
                    for line in output.split("\n"):
                        if "bundleIdentifier" in line:
                            parts = line.split('"')
                            if len(parts) >= 4:
                                bundle_id = parts[-2].strip()
                                is_valid = (
                                    bundle_id
                                    and "." in bundle_id
                                    and bundle_id.replace(".", "").replace("-", "").isalnum()
                                )
                                if is_valid:
                                    return bundle_id
                return None
            except Exception as e:
                logger.debug(f"Native iOS foreground detection failed: {e}")
                try:
                    output = run_shell_command_on_host("maestro status")
                    if output and "current_app" in output.lower():
                        for line in output.split("\n"):
                            if "current_app" in line.lower() or "app" in line.lower():
                                parts = line.split(":")
                                if len(parts) >= 2:
                                    app_id = parts[-1].strip().strip('"')
                                    is_valid = (
                                        app_id
                                        and "." in app_id
                                        and app_id.replace(".", "").replace("-", "").isalnum()
                                    )
                                    if is_valid:
                                        return app_id
                except Exception as e:
                    logger.debug(f"Maestro fallback for iOS foreground detection failed: {e}")
                return None
        else:
            device = get_adb_device(ctx)
            output = str(device.shell("dumpsys window | grep mCurrentFocus"))
            if output and "mCurrentFocus=" in output:
                window_info = output.split("mCurrentFocus=")[-1]
                if "/" in window_info:
                    package_name = window_info.split("/")[0]
                    package_name = package_name.lstrip("Window{").strip()
                    if package_name and "." in package_name:
                        return package_name
            return None
    except Exception:
        return None
