from typing import Literal
from urllib.parse import urlparse

from langchain_core.callbacks.base import Callbacks
from pydantic import BaseModel

from minitap.mobile_use.context import DevicePlatform
from minitap.mobile_use.sdk.types.task import AgentProfile, TaskRequestCommon


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

    hw_bridge_base_url: ApiBaseUrl
    screen_api_base_url: ApiBaseUrl
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
    """

    agent_profiles: dict[str, AgentProfile]
    task_request_defaults: TaskRequestCommon
    default_profile: AgentProfile
    device_id: str | None = None
    device_platform: DevicePlatform | None = None
    servers: ServerConfig
    graph_config_callbacks: Callbacks = None
    cloud_mobile_id_or_ref: str | None = None

    model_config = {"arbitrary_types_allowed": True}
