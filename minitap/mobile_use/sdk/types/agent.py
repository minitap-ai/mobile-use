from enum import Enum
from typing import Literal
from urllib.parse import urlparse

from langchain_core.callbacks.base import Callbacks
from pydantic import BaseModel

from minitap.mobile_use.clients.ios_client_config import BrowserStackClientConfig, IosClientConfig
from minitap.mobile_use.context import DevicePlatform
from minitap.mobile_use.controllers.limrun_controller import (
    LimrunAndroidController,
    LimrunIosController,
)
from minitap.mobile_use.sdk.types.task import AgentProfile, TaskRequestCommon


class LimrunPlatform(str, Enum):
    """Limrun device platform."""

    ANDROID = "android"
    IOS = "ios"


class LimrunConfig(BaseModel):
    """
    Configuration for Limrun cloud device provisioning.

    When set, the SDK will automatically provision a Limrun device
    during agent initialization and clean it up when the agent is stopped.

    Attributes:
        platform: The device platform (android or ios).
        api_key: API key for Limrun. If not provided, uses MINITAP_API_KEY
                 or LIM_API_KEY environment variable.
        base_url: Base URL for Limrun API. Defaults to https://platform.minitap.ai.
        inactivity_timeout: Timeout for device inactivity (e.g., "10m").
        hard_timeout: Hard timeout for device lifetime.
        display_name: Optional display name for the device.
        labels: Optional labels for the device.
    """

    platform: LimrunPlatform
    api_key: str | None = None
    base_url: str | None = None
    inactivity_timeout: str = "10m"
    hard_timeout: str | None = None
    display_name: str | None = None
    labels: dict[str, str] | None = None


class ApiBaseUrl(BaseModel):
    """
    Defines an API base URL.
    """

    scheme: Literal["http", "https"]
    host: str
    port: int | None = None

    def __eq__(self, other):
        if not isinstance(other, ApiBaseUrl):
            return False
        return self.to_url() == other.to_url()

    def to_url(self):
        return (
            f"{self.scheme}://{self.host}:{self.port}"
            if self.port is not None
            else f"{self.scheme}://{self.host}"
        )

    @classmethod
    def from_url(cls, url: str) -> "ApiBaseUrl":
        parsed_url = urlparse(url)
        if parsed_url.scheme not in ["http", "https"]:
            raise ValueError(f"Invalid scheme: {parsed_url.scheme}")
        if parsed_url.hostname is None:
            raise ValueError("Invalid hostname")
        return cls(
            scheme=parsed_url.scheme,  # type: ignore
            host=parsed_url.hostname,
            port=parsed_url.port,
        )


class ServerConfig(BaseModel):
    """
    Configuration for the required servers.
    """

    adb_host: str
    adb_port: int


class AgentConfig(BaseModel):
    """
    Mobile-use agent configuration.

    Attributes:
        agent_profiles: Map an agent profile name to its configuration.
        task_config_defaults: Default task request configuration.
        default_profile: default profile to use for tasks
        device_id: Specific device to target (if None, first available is used).
        device_platform: Platform of the device to target.
        servers: Custom server configurations.
        cloud_mobile_id_or_ref: ID or reference name of cloud mobile (virtual mobile)
                                to use for remote execution.
        video_recording_enabled: Whether video recording tools are enabled.
        limrun_config: Configuration for Limrun cloud device provisioning.
            When set, the SDK will automatically provision a Limrun device.
        limrun_android_controller: Pre-configured Limrun Android controller.
        limrun_ios_controller: Pre-configured Limrun iOS controller.
    """

    agent_profiles: dict[str, AgentProfile]
    task_request_defaults: TaskRequestCommon
    default_profile: AgentProfile
    device_id: str | None = None
    device_platform: DevicePlatform | None = None
    servers: ServerConfig
    graph_config_callbacks: Callbacks = None
    cloud_mobile_id_or_ref: str | None = None
    ios_client_config: IosClientConfig | None = None
    browserstack_config: BrowserStackClientConfig | None = None
    video_recording_enabled: bool = False
    limrun_config: LimrunConfig | None = None
    limrun_android_controller: LimrunAndroidController | None = None
    limrun_ios_controller: LimrunIosController | None = None

    model_config = {"arbitrary_types_allowed": True}
