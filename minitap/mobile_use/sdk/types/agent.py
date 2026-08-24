from enum import StrEnum
from typing import Literal
from urllib.parse import urlparse

from langchain_core.callbacks.base import Callbacks
from pydantic import BaseModel

from minitap.mobile_use.clients.ios_client_config import BrowserStackClientConfig, IosClientConfig
from minitap.mobile_use.context import DevicePlatform
from minitap.mobile_use.controllers.cloud_device_controller import (
    CloudAndroidController,
    CloudIosController,
)
from minitap.mobile_use.sdk.types.task import AgentProfile, TaskRequestCommon


class CloudDevicePlatform(StrEnum):
    """Cloud device operating system."""

    ANDROID = "android"
    IOS = "ios"


class CloudDeviceConfig(BaseModel):
    """
    Configuration for cloud device provisioning.

    When set, the SDK will automatically provision a cloud device
    during agent initialization and clean it up when the agent is stopped.

    Attributes:
        platform: The device platform (android or ios).
        api_key: API key for the cloud device API. If omitted, uses MINITAP_API_KEY.
        base_url: Optional cloud device API base URL.
        inactivity_timeout: Timeout for device inactivity (e.g., "10m").
        hard_timeout: Hard timeout for device lifetime.
        display_name: Optional display name for the device.
        labels: Optional labels for the device.
    """

    platform: CloudDevicePlatform
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
        video_recording_enabled: Whether video recording tools are enabled.
        cloud_device_config: Configuration for cloud device provisioning.
        cloud_android_controller: Pre-configured cloud Android controller.
        cloud_ios_controller: Pre-configured cloud iOS controller.
    """

    agent_profiles: dict[str, AgentProfile]
    task_request_defaults: TaskRequestCommon
    default_profile: AgentProfile
    device_id: str | None = None
    device_platform: DevicePlatform | None = None
    servers: ServerConfig
    graph_config_callbacks: Callbacks = None
    ios_client_config: IosClientConfig | None = None
    browserstack_config: BrowserStackClientConfig | None = None
    video_recording_enabled: bool = False
    cloud_device_config: CloudDeviceConfig | None = None
    cloud_android_controller: CloudAndroidController | None = None
    cloud_ios_controller: CloudIosController | None = None

    model_config = {"arbitrary_types_allowed": True}
