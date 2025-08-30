"""
Context variables for global state management.

Uses ContextVar to avoid prop drilling and maintain clean function signatures.
"""

from enum import Enum
from pathlib import Path

from adbutils import AdbClient
from openai import BaseModel
from pydantic import ConfigDict
from typing import Literal

from minitap.mobile_use.clients.device_hardware_client import DeviceHardwareClient
from minitap.mobile_use.clients.screen_api_client import ScreenApiClient
from minitap.mobile_use.config import LLMConfig


class DevicePlatform(str, Enum):
    """Mobile device platform enumeration."""

    ANDROID = "android"
    IOS = "ios"


class DeviceContext(BaseModel):
    host_platform: Literal["WINDOWS", "LINUX"]
    mobile_platform: DevicePlatform
    device_id: str
    device_width: int
    device_height: int

    def to_str(self):
        return (
            f"Host platform: {self.host_platform}\n"
            f"Mobile platform: {self.mobile_platform.value}\n"
            f"Device ID: {self.device_id}\n"
            f"Device width: {self.device_width}\n"
            f"Device height: {self.device_height}\n"
        )


class ExecutionSetup(BaseModel):
    """Execution setup for a task."""

    traces_path: Path
    trace_id: str


class MobileUseContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    device: DeviceContext
    hw_bridge_client: DeviceHardwareClient
    screen_api_client: ScreenApiClient
    llm_config: LLMConfig
    adb_client: AdbClient | None = None
    execution_setup: ExecutionSetup | None = None

    def get_adb_client(self) -> AdbClient:
        if self.adb_client is None:
            raise ValueError("No ADB client in context.")
        return self.adb_client  # type: ignore
