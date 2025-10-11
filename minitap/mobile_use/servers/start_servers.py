import multiprocessing
import os
import signal
import sys
import time
from enum import Enum
from typing import Annotated

import requests
import typer
from minitap.mobile_use.context import DevicePlatform
from minitap.mobile_use.servers.config import server_settings
from minitap.mobile_use.servers.device_hardware_bridge import DeviceHardwareBridge
from minitap.mobile_use.servers.device_screen_api import start as _start_device_screen_api
from minitap.mobile_use.servers.stop_servers import stop_servers
from minitap.mobile_use.utils.logger import get_server_logger

logger = get_server_logger()

running_processes = []
bridge_instance = None
shutdown_requested = False


def check_device_screen_api_health(base_url: str | None = None, max_retries=30, delay=1):
    base_url = base_url or f"http://localhost:{server_settings.DEVICE_SCREEN_API_PORT}"
    health_url = f"{base_url}/health"

    max_retries = int(os.getenv("MOBILE_USE_HEALTH_RETRIES", max_retries))
    delay = int(os.getenv("MOBILE_USE_HEALTH_DELAY", delay))

    for attempt in range(max_retries):
        try:
            response = requests.get(health_url, timeout=3)
            if response.status_code == 200:
                logger.success(
                    f"Device Screen API is healthy on port {server_settings.DEVICE_SCREEN_API_PORT}"
                )
                return True
        except requests.exceptions.RequestException:
            pass

        if attempt == 0:
            logger.info(f"Waiting for Device Screen API to become healthy on {base_url}...")

        time.sleep(delay)

    logger.error(f"Device Screen API failed to become healthy after {max_retries} attempts")
    return False


def _start_device_screen_api_process() -> multiprocessing.Process | None:
    try:
        process = multiprocessing.Process(target=start_device_screen_api, daemon=True)
        process.start()
        return process
    except Exception as e:
        logger.error(f"Failed to start Device Screen API process: {e}")
        return None


def start_device_hardware_bridge(
    device_id: str, platform: DevicePlatform, adb_host: str | None = None
) -> DeviceHardwareBridge | None:
    logger.info("Starting Device Hardware Bridge...")

    try:
        bridge = DeviceHardwareBridge(
            device_id=device_id,
            platform=platform,
            adb_host=adb_host or server_settings.ADB_HOST,
        )
        success = bridge.start()

        if success:
            logger.info("Device Hardware Bridge started successfully")
            return bridge
        else:
            logger.error("Failed to start Device Hardware Bridge. Exiting.")
            return None

    except Exception as e:
        logger.error(f"Error starting Device Hardware Bridge: {e}")
        return None


def start_device_screen_api(use_process: bool = False):
    logger.info("Starting Device Screen API...")
    if use_process:
        api_process = _start_device_screen_api_process()
        if not api_process:
            logger.error("Failed to start Device Screen API. Exiting.")
            return False
        logger.info("Device Screen API started successfully")
        return api_process
    else:
        return _start_device_screen_api()


cli = typer.Typer(add_completion=False, pretty_exceptions_enable=False)


class SupportedServers(str, Enum):
    DEVICE_HARDWARE_BRIDGE = "hardware_bridge"
    DEVICE_SCREEN_API = "screen_api"
    ALL = "all"


@cli.command()
def start(
    device_id: Annotated[str, typer.Option("--device", help="Device ID")],
    platform: Annotated[DevicePlatform, typer.Option("--platform", help="Device platform")],
    only: Annotated[
        SupportedServers, typer.Option("--only", help="Start only one server")
    ] = SupportedServers.ALL,
):
    servers_to_stop = {"device_screen_api": False, "device_hardware_bridge": False}

    def signal_handler(signum, frame):
        logger.info("Signal received, stopping servers...")
        if any(servers_to_stop.values()):
            stop_servers(**servers_to_stop)
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        if only == SupportedServers.ALL:
            hardware_bridge = start_device_hardware_bridge(device_id=device_id, platform=platform)
            if hardware_bridge:
                servers_to_stop["device_hardware_bridge"] = True
            start_device_screen_api(use_process=False)

        elif only == SupportedServers.DEVICE_HARDWARE_BRIDGE:
            hardware_bridge = start_device_hardware_bridge(device_id=device_id, platform=platform)
            if hardware_bridge:
                servers_to_stop["device_hardware_bridge"] = True
                hardware_bridge.wait()

        elif only == SupportedServers.DEVICE_SCREEN_API:
            start_device_screen_api(use_process=False)

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Shutting down...")
    finally:
        signal_handler(signal.SIGINT, None)


if __name__ == "__main__":
    cli()
