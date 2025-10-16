import json
from datetime import date
from shutil import which

from adbutils import AdbDevice

from minitap.mobile_use.context import DevicePlatform, MobileUseContext
from minitap.mobile_use.utils.logger import MobileUseLogger
from minitap.mobile_use.utils.shell_utils import run_shell_command_on_host


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
