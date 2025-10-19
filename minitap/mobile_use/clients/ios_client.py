import json
import platform

from minitap.mobile_use.utils.shell_utils import run_shell_command_on_host


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
