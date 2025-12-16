import sys

from adbutils import AdbClient
from rich.console import Console

from minitap.mobile_use.clients.ios_client import format_device_info, get_all_ios_devices_detailed


def display_device_status(console: Console, adb_client: AdbClient | None = None):
    """Checks for connected devices and displays the status."""
    console.print("\n[bold]📱 Device Status[/bold]")
    devices = None
    if adb_client is not None:
        devices = adb_client.device_list()
    if devices:
        console.print("✅ [bold green]Android device(s) connected:[/bold green]")
        for device in devices:
            console.print(f"  - {device.serial}")
    else:
        console.print("❌ [bold red]No Android device found.[/bold red]")
        command = "emulator -avd <avd_name>"
        if sys.platform not in ["win32", "darwin"]:
            command = f"./{command}"
            console.print(
                f"You can start an emulator using a command like: [bold]'{command}'[/bold]"
            )

    ios_devices = get_all_ios_devices_detailed()
    if ios_devices:
        console.print("✅ [bold green]iOS device(s) connected:[/bold green]")
        for device in ios_devices:
            console.print(f"  - [green]{format_device_info(device)}[/green]")
    else:
        console.print("❌ [bold red]No iOS device found.[/bold red]")
        console.print(
            "[iOS] Please make sure your emulator is running or a device is connected via USB."
        )
