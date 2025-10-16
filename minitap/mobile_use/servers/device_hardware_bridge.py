import platform
import re
import subprocess
import threading
import time
from enum import Enum

import requests

from minitap.mobile_use.context import DevicePlatform
from minitap.mobile_use.servers.utils import is_port_in_use

MAESTRO_STUDIO_PORT = 9999
DEVICE_HARDWARE_BRIDGE_PORT = MAESTRO_STUDIO_PORT


class BridgeStatus(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    NO_DEVICE = "no_device"
    PORT_IN_USE = "port_in_use"
    FAILED = "failed"


class DeviceHardwareBridge:
    def __init__(self, device_id: str, platform: DevicePlatform, adb_host: str | None = None):
        self.process = None
        self.status = BridgeStatus.STOPPED
        self.thread = None
        self.output = []
        self.lock = threading.Lock()
        self.device_id: str = device_id
        self.platform: DevicePlatform = platform
        self.adb_host: str | None = adb_host

    def _run_maestro_studio(self):
        try:
            creation_flags = 0
            if hasattr(subprocess, "CREATE_NO_WINDOW"):
                creation_flags = subprocess.CREATE_NO_WINDOW  # pyright: ignore[reportAttributeAccessIssue]

            maestro_platform = "android" if self.platform == DevicePlatform.ANDROID else "ios"
            cmd = ["maestro", "--device", self.device_id, "--platform", maestro_platform]
            if self.adb_host is not None:
                cmd.append(f"--host={self.adb_host}")
            cmd.extend(["studio", "--no-window"])

            self.process = subprocess.Popen(
                args=cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creation_flags,
                shell=platform.system() == "Windows",
            )

            with self.lock:
                self.status = BridgeStatus.STARTING

            stdout_thread = threading.Thread(target=self._read_stdout, daemon=True)
            stdout_thread.start()

            stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
            stderr_thread.start()

            stdout_thread.join()
            stderr_thread.join()

            if self.process:
                self.process.wait()

        except FileNotFoundError:
            print("Error: 'maestro' command not found. Is Maestro installed and in your PATH?")
            with self.lock:
                self.status = BridgeStatus.FAILED
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            with self.lock:
                self.status = BridgeStatus.FAILED
        finally:
            with self.lock:
                if self.status not in [
                    BridgeStatus.RUNNING,
                    BridgeStatus.NO_DEVICE,
                    BridgeStatus.PORT_IN_USE,
                ]:
                    self.status = BridgeStatus.STOPPED
            print("Maestro Studio process has terminated.")

    def _read_stdout(self):
        if not self.process or not self.process.stdout:
            return
        for line in iter(self.process.stdout.readline, ""):
            if not line:
                break

            line = line.strip()
            print(f"[Maestro Studio]: {line}")
            self.output.append(line)

            if "No running devices found" in line:
                with self.lock:
                    self.status = BridgeStatus.NO_DEVICE
                if self.process:
                    self.process.kill()
                break

            connected_match = re.search(r"Running on (\S+)", line)
            if connected_match:
                with self.lock:
                    self.device_id = connected_match.group(1)

            if "Maestro Studio is running at" in line:
                if self._wait_for_health_check():
                    with self.lock:
                        self.status = BridgeStatus.RUNNING
                else:
                    with self.lock:
                        self.status = BridgeStatus.FAILED
                    if self.process:
                        self.process.kill()
                break

    def _read_stderr(self):
        if not self.process or not self.process.stderr:
            return
        for line in iter(self.process.stderr.readline, ""):
            if not line:
                break

            line = line.strip()
            print(f"[Maestro Studio ERROR]: {line}")
            self.output.append(line)

            lower_line = line.lower()

            # Ignore known benign warnings (common on macOS/JDK 21+)
            if line.startswith("WARNING:") or (
                "restricted method" in lower_line
                or "jansi" in lower_line
                or "enable-native-access" in lower_line
                or "java.lang.system::load" in lower_line
            ):
                continue

            if "device offline" in lower_line:
                with self.lock:
                    self.status = BridgeStatus.FAILED
                if self.process:
                    self.process.kill()
                break

            if "address already in use" in lower_line:
                with self.lock:
                    self.status = BridgeStatus.PORT_IN_USE
                if self.process:
                    self.process.kill()
                break

    def _wait_for_health_check(self, retries=5, delay=2):
        health_url = f"http://localhost:{DEVICE_HARDWARE_BRIDGE_PORT}/api/banner-message"
        for _ in range(retries):
            try:
                response = requests.get(health_url, timeout=3)
                if response.status_code == 200 and "level" in response.json():
                    print("Health check successful.")
                    return True
            except requests.exceptions.RequestException:
                pass
            time.sleep(delay)
        print("Health check failed after multiple retries.")
        return False

    def _should_start_maestro(self):
        return self.status in [
            BridgeStatus.STOPPED,
            BridgeStatus.FAILED,
            BridgeStatus.NO_DEVICE,
            BridgeStatus.PORT_IN_USE,
        ]

    def start(self):
        if is_port_in_use(port=DEVICE_HARDWARE_BRIDGE_PORT):
            print("Maestro port already in use - assuming Maestro is running.")
            self.status = BridgeStatus.RUNNING
            return True
        if self._should_start_maestro():
            self.status = BridgeStatus.STARTING
            self.output.clear()
            self.thread = threading.Thread(target=self._run_maestro_studio, daemon=True)
            self.thread.start()
            return True
        print(f"Cannot start, current status is {self.status.value}")
        return False

    def wait(self):
        if self.thread:
            self.thread.join()

    def stop(self):
        if self.process:
            self.process.kill()
            self.process = None
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)
        with self.lock:
            self.status = BridgeStatus.STOPPED
        print("Maestro Studio stopped.")

    def get_status(self):
        with self.lock:
            return {"status": self.status.value, "output": self.output[-10:]}

    def get_device_id(self) -> str | None:
        with self.lock:
            return self.device_id
