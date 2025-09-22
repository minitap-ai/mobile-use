import sys
import time

import psutil
import requests

from minitap.mobile_use.servers.config import server_settings
from minitap.mobile_use.servers.device_hardware_bridge import DEVICE_HARDWARE_BRIDGE_PORT
from minitap.mobile_use.utils.logger import get_server_logger

logger = get_server_logger()


def find_processes_by_name(name: str) -> list[psutil.Process]:
    """Find all processes with the given name."""
    processes = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if name.lower() in proc.info["name"].lower():
                processes.append(proc)
            elif proc.info["cmdline"] and any(name in cmd for cmd in proc.info["cmdline"]):
                processes.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return processes


def find_processes_by_port(port: int) -> list[psutil.Process]:
    processes = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            for conn in proc.net_connections():
                if conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
                    processes.append(proc)
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return processes


def stop_process_gracefully(process: psutil.Process, timeout: int = 5) -> bool:
    try:
        if not process.is_running():
            logger.success(f"Process {process.pid} ({process.name()}) already terminated")
            return True

        logger.debug(f"Stopping process {process.pid} ({process.name()})")

        process.terminate()

        try:
            process.wait(timeout=timeout)
            return True
        except psutil.TimeoutExpired:
            logger.warning(f"Process {process.pid} didn't terminate gracefully, force killing...")
            try:
                process.kill()
                process.wait(timeout=2)
                return True
            except psutil.NoSuchProcess:
                return True

    except psutil.NoSuchProcess:
        return True
    except (psutil.AccessDenied, psutil.ZombieProcess) as e:
        logger.warning(f"Cannot stop process {process.pid}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error stopping process {process.pid}: {e}")
        return False


def check_service_running(port: int, service_name: str) -> bool:
    try:
        if port == server_settings.DEVICE_SCREEN_API_PORT:
            requests.get(f"http://localhost:{port}/health", timeout=2)
        elif port == DEVICE_HARDWARE_BRIDGE_PORT:
            requests.get(f"http://localhost:{port}/api/banner-message", timeout=2)
        else:
            return False

        logger.debug(f"{service_name} is still responding on port {port}")
        return True
    except requests.exceptions.RequestException:
        pass

    return False


def stop_device_screen_api() -> bool:
    logger.info("Stopping Device Screen API...")
    api_port = server_settings.DEVICE_SCREEN_API_PORT

    if not check_service_running(api_port, "Device Screen API"):
        logger.success("Device Screen API is not running")
        return True

    # Find processes by port
    processes = find_processes_by_port(api_port)

    # Also find by process name/command
    uvicorn_processes = find_processes_by_name("uvicorn")
    python_processes = find_processes_by_name("device_screen_api.py")

    all_processes = list(set(processes + uvicorn_processes + python_processes))

    if not all_processes:
        logger.warning("No Device Screen API processes found, but service is still responding")
        # Still try to verify if service actually stops
        time.sleep(1)
        if not check_service_running(api_port, "Device Screen API"):
            logger.success("Device Screen API stopped successfully (was orphaned)")
            return True
        return False

    # Stop all processes
    for proc in all_processes:
        stop_process_gracefully(proc)

    # Verify service is stopped
    time.sleep(1)
    if check_service_running(api_port, "Device Screen API"):
        logger.error("Device Screen API is still running after stop attempt")
        return False

    logger.success("Device Screen API stopped successfully")
    return True


def stop_device_hardware_bridge() -> bool:
    logger.info("Stopping Device Hardware Bridge...")

    if not check_service_running(DEVICE_HARDWARE_BRIDGE_PORT, "Maestro Studio"):
        logger.success("Device Hardware Bridge is not running")
        return True

    processes = find_processes_by_port(DEVICE_HARDWARE_BRIDGE_PORT)

    maestro_processes = find_processes_by_name("maestro")

    all_processes = list(set(processes + maestro_processes))

    if not all_processes:
        logger.warning("No Device Hardware Bridge processes found, but service is still responding")
        # Still try to verify if service actually stops
        time.sleep(1)
        if not check_service_running(DEVICE_HARDWARE_BRIDGE_PORT, "Maestro Studio"):
            logger.success("Device Hardware Bridge stopped successfully (was orphaned)")
            return True
        return False

    for proc in all_processes:
        stop_process_gracefully(proc)

    time.sleep(1)
    if check_service_running(DEVICE_HARDWARE_BRIDGE_PORT, "Maestro Studio"):
        logger.error("Device Hardware Bridge is still running after stop attempt")
        return False

    logger.success("Device Hardware Bridge stopped successfully")
    return True


def stop_servers(
    should_stop_screen_api: bool = False, should_stop_hw_bridge: bool = False
) -> tuple[bool, bool]:
    """Stop the servers and return whether they stopped successfully (api_success, bridge_success).

    Returns:
        Tuple of (api_stopped, bridge_stopped) booleans
    """
    api_success = stop_device_screen_api() if should_stop_screen_api else True
    bridge_success = stop_device_hardware_bridge() if should_stop_hw_bridge else True

    if api_success and bridge_success:
        logger.success("All servers stopped successfully")
    elif api_success:
        logger.warning("Device Screen API stopped, but Device Hardware Bridge had issues")
    elif bridge_success:
        logger.warning("Device Hardware Bridge stopped, but Device Screen API had issues")
    else:
        logger.error("Failed to stop both servers")

    return api_success, bridge_success


def main():
    """Main function to stop all servers."""
    api_success, bridge_success = stop_servers(
        should_stop_screen_api=True, should_stop_hw_bridge=True
    )
    if api_success and bridge_success:
        return 0
    elif api_success or bridge_success:
        return 1
    else:
        return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logger.warning("\nStop operation interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)
