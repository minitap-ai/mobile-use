"""
Context variables for global state management.

Uses ContextVar to avoid prop drilling and maintain clean function signatures.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from adbutils import AdbClient
from pydantic import BaseModel, ConfigDict

from minitap.mobile_use.clients.ios_client import IosClientWrapper
from minitap.mobile_use.clients.ui_automator_client import UIAutomatorClient
from minitap.mobile_use.controllers.limrun_controller import LimrunAndroidController


class AppLaunchResult(BaseModel):
    """Result of initial app launch attempt."""

    locked_app_package: str
    locked_app_initial_launch_success: bool | None
    locked_app_initial_launch_error: str | None


class DevicePlatform(StrEnum):
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

    traces_path: Path | None = None
    trace_name: str | None = None
    enable_remote_tracing: bool = False
    app_lock_status: AppLaunchResult | None = None

    def get_locked_app_package(self) -> str | None:
        """
        Get the locked app package name if app locking is enabled.

        Returns:
            The locked app package name, or None if app locking is not enabled.
        """
        if self.app_lock_status:
            return self.app_lock_status.locked_app_package
        return None


IsReplan = bool

# Agent-only callback type aliases (for documentation).
# At runtime these are Any since the agent types may not be installed.
# When running with [agent] extras, callers pass typed callables.
AgentThoughtCallback = Any  # Callable[[AgentNode, str], Coroutine]
PlanChangesCallback = Any  # Callable[[list[Subgoal], IsReplan], Coroutine]


class MobileUseContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    trace_id: str
    device: DeviceContext
    llm_config: Any = None  # LLMConfig (from config.py) — only set when running the agent
    adb_client: AdbClient | None = None
    ui_adb_client: UIAutomatorClient | None = None
    ios_client: IosClientWrapper | None = None
    limrun_android_controller: LimrunAndroidController | None = None
    execution_setup: ExecutionSetup | None = None
    on_agent_thought: AgentThoughtCallback = None
    on_plan_changes: PlanChangesCallback = None
    minitap_api_key: str | None = None
    video_recording_enabled: bool = False

    def get_adb_client(self) -> AdbClient:
        if self.adb_client is None:
            raise ValueError("No ADB client in context.")
        return self.adb_client  # type: ignore

    def get_ui_adb_client(self) -> UIAutomatorClient:
        if self.ui_adb_client is None:
            raise ValueError("No UIAutomator client in context.")
        return self.ui_adb_client

    def get_ios_client(self) -> IosClientWrapper:
        """Get the iOS client (IDB for simulators, WDA for physical devices)."""
        if self.ios_client is None:
            raise ValueError("No iOS client in context.")
        return self.ios_client
