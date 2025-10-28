"""
Builder for AgentConfig objects using a fluent interface.
"""

import copy

from langchain_core.callbacks.base import Callbacks

from minitap.mobile_use.config import get_default_llm_config, get_default_minitap_llm_config
from minitap.mobile_use.context import DevicePlatform
from minitap.mobile_use.sdk.constants import (
    DEFAULT_HW_BRIDGE_BASE_URL,
    DEFAULT_PROFILE_NAME,
    DEFAULT_SCREEN_API_BASE_URL,
)
from minitap.mobile_use.sdk.types.agent import AgentConfig, AgentProfile, ApiBaseUrl, ServerConfig
from minitap.mobile_use.sdk.types.task import TaskRequestCommon


class AgentConfigBuilder:
    """
    Builder class providing a fluent interface for creating AgentConfig objects.

    This builder allows for step-by-step construction of an AgentConfig with
    clear methods that make the configuration process intuitive and type-safe.

    Examples:
        >>> builder = AgentConfigBuilder()
        >>> config = (builder
        ...     .add_profile(AgentProfile(name="HighReasoning", llm_config=LLMConfig(...)))
        ...     .add_profile(AgentProfile(name="LowReasoning", llm_config=LLMConfig(...)))
        ...     .for_device(DevicePlatform.ANDROID, "device123")
        ...     .with_default_task_config(TaskRequestCommon(max_steps=30))
        ...     .with_default_profile("HighReasoning")
        ...     .build()
        ... )
    """

    def __init__(self):
        """Initialize an empty AgentConfigBuilder."""
        self._agent_profiles: dict[str, AgentProfile] = {}
        self._task_request_defaults: TaskRequestCommon | None = None
        self._default_profile: str | AgentProfile | None = None
        self._device_id: str | None = None
        self._device_platform: DevicePlatform | None = None
        self._servers: ServerConfig = get_default_servers()
        self._graph_config_callbacks: Callbacks = None
        self._cloud_mobile_id_or_ref: str | None = None

    def add_profile(self, profile: AgentProfile, validate: bool = True) -> "AgentConfigBuilder":
        """
        Add an agent profile to the mobile-use agent.

        Args:
            profile: The agent profile to add
        """
        self._agent_profiles[profile.name] = profile
        if validate:
            profile.llm_config.validate_providers()
        return self

    def add_profiles(
        self,
        profiles: list[AgentProfile],
        validate: bool = True,
    ) -> "AgentConfigBuilder":
        """
        Add multiple agent profiles to the mobile-use agent.

        Args:
            profiles: List of agent profiles to add
        """
        for profile in profiles:
            self.add_profile(profile=profile, validate=validate)
        return self

    def with_default_profile(self, profile: str | AgentProfile) -> "AgentConfigBuilder":
        """
        Set the default agent profile used for tasks.

        Args:
            profile: The name or instance of the default agent profile
        """
        self._default_profile = profile
        return self

    def for_device(
        self,
        platform: DevicePlatform,
        device_id: str,
    ) -> "AgentConfigBuilder":
        """
        Configure the mobile-use agent for a specific device.

        Args:
            platform: The device platform (ANDROID or IOS)
            device_id: The unique identifier for the device
        """
        if self._cloud_mobile_id_or_ref is not None:
            raise ValueError(
                "Device ID cannot be set when a cloud mobile is already configured.\n"
                "> for_device() and for_cloud_mobile() are mutually exclusive"
            )
        self._device_id = device_id
        self._device_platform = platform
        return self

    def for_cloud_mobile(self, cloud_mobile_id_or_ref: str) -> "AgentConfigBuilder":
        """
        Configure the mobile-use agent to use a cloud mobile.

        When using a cloud mobile, tasks are executed remotely via the Platform API,
        and only PlatformTaskRequest can be used.

        Args:
            cloud_mobile_id_or_ref: The unique identifier or reference name for the cloud mobile.
                Can be either a UUID (e.g., '550e8400-e29b-41d4-a716-446655440000')
                or a reference name (e.g., 'my-test-device')
        """
        if self._device_id is not None:
            raise ValueError(
                "Cloud mobile device ID cannot be set when a device is already configured.\n"
                "> for_device() and for_cloud_mobile() are mutually exclusive"
            )
        self._cloud_mobile_id_or_ref = cloud_mobile_id_or_ref
        return self

    def with_default_task_config(self, config: TaskRequestCommon) -> "AgentConfigBuilder":
        """
        Set the default task configuration.

        Args:
            config: The task configuration to use as default
        """
        self._task_request_defaults = copy.deepcopy(config)
        return self

    def with_hw_bridge(self, url: str | ApiBaseUrl) -> "AgentConfigBuilder":
        """
        Set the base URL for the device HW bridge API.

        Args:
            url: The base URL for the HW bridge API
        """
        if isinstance(url, str):
            url = ApiBaseUrl.from_url(url)
        self._servers.hw_bridge_base_url = url
        return self

    def with_screen_api(self, url: str | ApiBaseUrl) -> "AgentConfigBuilder":
        """
        Set the base URL for the device screen API.

        Args:
            url: The base URL for the screen API
        """
        if isinstance(url, str):
            url = ApiBaseUrl.from_url(url)
        self._servers.screen_api_base_url = url
        return self

    def with_adb_server(self, host: str, port: int | None = None) -> "AgentConfigBuilder":
        """
        Set the ADB server host and port.

        Args:
            host: The ADB server host
            port: The ADB server port
        """
        self._servers.adb_host = host
        if port is not None:
            self._servers.adb_port = port
        return self

    def with_servers(self, servers: ServerConfig) -> "AgentConfigBuilder":
        """
        Set the server settings.

        Args:
            servers: The server settings to use
        """
        self._servers = copy.deepcopy(servers)
        return self

    def with_graph_config_callbacks(self, callbacks: Callbacks) -> "AgentConfigBuilder":
        """
        Set the graph config callbacks.

        Args:
            callbacks: The graph config callbacks to use
        """
        self._graph_config_callbacks = callbacks
        return self

    def build(self, validate_profiles: bool = True) -> AgentConfig:
        """
        Build the mobile-use AgentConfig object.

        Args:
            default_profile: Name of the default agent profile to use

        Returns:
            A configured AgentConfig object

        Raises:
            ValueError: If default_profile is specified but not found in configured profiles
        """
        nb_profiles = len(self._agent_profiles)

        if isinstance(self._default_profile, str):
            profile_name = self._default_profile
            default_profile = self._agent_profiles.get(profile_name, None)
            if default_profile is None:
                raise ValueError(f"Profile '{profile_name}' not found in configured agents")
        elif isinstance(self._default_profile, AgentProfile):
            default_profile = self._default_profile
            if default_profile.name not in self._agent_profiles:
                self.add_profile(default_profile, validate=validate_profiles)
        elif nb_profiles <= 0:
            llm_config = (
                get_default_minitap_llm_config(validate=validate_profiles)
                or get_default_llm_config()
            )
            default_profile = AgentProfile(
                name=DEFAULT_PROFILE_NAME,
                llm_config=llm_config,
            )
            self.add_profile(default_profile, validate=validate_profiles)
        elif nb_profiles == 1:
            # Select the only one available
            default_profile = next(iter(self._agent_profiles.values()))
        else:
            available_profiles = ", ".join(self._agent_profiles.keys())
            raise ValueError(
                f"You must call with_default_profile() to select one among: {available_profiles}"
            )

        return AgentConfig(
            agent_profiles=self._agent_profiles,
            task_request_defaults=self._task_request_defaults or TaskRequestCommon(),
            default_profile=default_profile,
            device_id=self._device_id,
            device_platform=self._device_platform,
            servers=self._servers,
            graph_config_callbacks=self._graph_config_callbacks,
            cloud_mobile_id_or_ref=self._cloud_mobile_id_or_ref,
        )


def get_default_agent_config():
    return AgentConfigBuilder().build()


def get_default_servers():
    return ServerConfig(
        hw_bridge_base_url=copy.deepcopy(DEFAULT_HW_BRIDGE_BASE_URL),
        screen_api_base_url=copy.deepcopy(DEFAULT_SCREEN_API_BASE_URL),
        adb_host="localhost",
        adb_port=5037,
    )
