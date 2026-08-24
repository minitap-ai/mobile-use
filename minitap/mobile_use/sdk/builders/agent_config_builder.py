"""
Builder for AgentConfig objects using a fluent interface.
"""

import copy

from langchain_core.callbacks.base import Callbacks

from minitap.mobile_use.clients.ios_client_config import BrowserStackClientConfig, IosClientConfig
from minitap.mobile_use.config import get_default_llm_config, get_default_minitap_llm_config
from minitap.mobile_use.context import DevicePlatform
from minitap.mobile_use.controllers.cloud_device_controller import (
    CloudAndroidController,
    CloudIosController,
)
from minitap.mobile_use.sdk.constants import DEFAULT_PROFILE_NAME
from minitap.mobile_use.sdk.types.agent import (
    AgentConfig,
    AgentProfile,
    CloudDeviceConfig,
    CloudDevicePlatform,
    ServerConfig,
)
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
        self._ios_client_config: IosClientConfig | None = None
        self._browserstack_config: BrowserStackClientConfig | None = None
        self._video_recording_enabled: bool = False
        self._cloud_device_config: CloudDeviceConfig | None = None
        self._cloud_android_controller: CloudAndroidController | None = None
        self._cloud_ios_controller: CloudIosController | None = None

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
        if self._browserstack_config is not None:
            raise ValueError(
                "Device ID cannot be set when BrowserStack is already configured.\n"
                "> for_device() and for_browserstack() are mutually exclusive"
            )
        if (
            self._cloud_device_config is not None
            or self._cloud_android_controller is not None
            or self._cloud_ios_controller is not None
        ):
            raise ValueError(
                "Local device cannot be set when a cloud device is already configured.\n"
                "> for_device() and cloud device configuration are mutually exclusive"
            )
        self._device_id = device_id
        self._device_platform = platform
        return self

    def for_browserstack(self, config: BrowserStackClientConfig) -> "AgentConfigBuilder":
        """
        Configure the mobile-use agent to use BrowserStack cloud devices.

        When using BrowserStack, the agent connects to BrowserStack's cloud infrastructure
        for iOS device automation. This is mutually exclusive with for_device() and
        cloud device provisioning.

        Args:
            config: BrowserStack configuration with credentials and device settings
        """
        if self._device_id is not None:
            raise ValueError(
                "BrowserStack cannot be set when a device is already configured.\n"
                "> for_device() and for_browserstack() are mutually exclusive"
            )
        if (
            self._cloud_device_config is not None
            or self._cloud_android_controller is not None
            or self._cloud_ios_controller is not None
        ):
            raise ValueError(
                "BrowserStack cannot be set when a cloud device is already configured.\n"
                "> for_cloud_device() and for_browserstack() are mutually exclusive"
            )
        self._browserstack_config = config
        self._device_platform = DevicePlatform.IOS
        return self

    def for_cloud_device(
        self,
        platform: CloudDevicePlatform,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        inactivity_timeout: str = "10m",
        hard_timeout: str | None = None,
        display_name: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> "AgentConfigBuilder":
        """
        Configure the agent to use a Minitap cloud device.

        The SDK will automatically provision the device during agent initialization
        and clean it up when the agent is stopped.

        Args:
            platform: The cloud device operating system.
            api_key: Minitap API key. If omitted, uses MINITAP_API_KEY.
            base_url: Optional cloud device API base URL.
            inactivity_timeout: Timeout for device inactivity (e.g., "10m").
            hard_timeout: Hard timeout for device lifetime.
            display_name: Optional display name for the device.
            labels: Optional labels for the device.

        Example:
            >>> config = (Builders.AgentConfig
            ...     .for_cloud_device(CloudDevicePlatform.ANDROID)
            ...     .build())
            >>> agent = Agent(config=config)
            >>> await agent.init()
        """
        if self._device_id is not None:
            raise ValueError(
                "Cloud device cannot be set when a local device is already configured.\n"
                "> for_device() and for_cloud_device() are mutually exclusive"
            )
        if self._browserstack_config is not None:
            raise ValueError(
                "Cloud device cannot be set when BrowserStack is already configured.\n"
                "> for_browserstack() and for_cloud_device() are mutually exclusive"
            )
        if self._cloud_android_controller is not None or self._cloud_ios_controller is not None:
            raise ValueError(
                "Cloud device config cannot be set when a controller is already configured.\n"
                "> for_cloud_device() and with_cloud_*_controller() are mutually exclusive"
            )

        self._cloud_device_config = CloudDeviceConfig(
            platform=platform,
            api_key=api_key,
            base_url=base_url,
            inactivity_timeout=inactivity_timeout,
            hard_timeout=hard_timeout,
            display_name=display_name,
            labels=labels,
        )
        self._device_platform = (
            DevicePlatform.ANDROID
            if platform == CloudDevicePlatform.ANDROID
            else DevicePlatform.IOS
        )
        return self

    def with_default_task_config(self, config: TaskRequestCommon) -> "AgentConfigBuilder":
        """
        Set the default task configuration.

        Args:
            config: The task configuration to use as default
        """
        self._task_request_defaults = copy.deepcopy(config)
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

    def with_ios_client_config(self, config: IosClientConfig) -> "AgentConfigBuilder":
        self._ios_client_config = copy.deepcopy(config)
        return self

    def with_cloud_android_controller(
        self, controller: "CloudAndroidController"
    ) -> "AgentConfigBuilder":
        """
        Configure the agent to use a pre-provisioned cloud Android controller.

        Args:
            controller: A connected cloud Android controller
        """
        if self._device_id is not None:
            raise ValueError(
                "Cloud controller cannot be set when a local device is already configured.\n"
                "> for_device() and with_cloud_android_controller() are mutually exclusive"
            )
        if self._browserstack_config is not None:
            raise ValueError(
                "Cloud controller cannot be set when BrowserStack is already configured.\n"
                "> for_browserstack() and with_cloud_android_controller() are mutually exclusive"
            )
        if self._cloud_device_config is not None:
            raise ValueError(
                "Cloud controller cannot be set when cloud config is already configured.\n"
                "> for_cloud_device() and with_cloud_android_controller() are mutually exclusive"
            )
        if self._cloud_ios_controller is not None:
            raise ValueError("Only one cloud device controller can be configured")
        self._cloud_android_controller = controller
        self._device_platform = DevicePlatform.ANDROID
        return self

    def with_cloud_ios_controller(self, controller: "CloudIosController") -> "AgentConfigBuilder":
        """
        Configure the agent to use a pre-provisioned cloud iOS controller.

        Args:
            controller: A connected cloud iOS controller
        """
        if self._device_id is not None:
            raise ValueError(
                "Cloud controller cannot be set when a local device is already configured.\n"
                "> for_device() and with_cloud_ios_controller() are mutually exclusive"
            )
        if self._browserstack_config is not None:
            raise ValueError(
                "Cloud controller cannot be set when BrowserStack is already configured.\n"
                "> for_browserstack() and with_cloud_ios_controller() are mutually exclusive"
            )
        if self._cloud_device_config is not None:
            raise ValueError(
                "Cloud controller cannot be set when cloud config is already configured.\n"
                "> for_cloud_device() and with_cloud_ios_controller() are mutually exclusive"
            )
        if self._cloud_android_controller is not None:
            raise ValueError("Only one cloud device controller can be configured")
        self._cloud_ios_controller = controller
        self._device_platform = DevicePlatform.IOS
        return self

    def with_video_recording_tools(self) -> "AgentConfigBuilder":
        """
        Enable video recording tools (start_video_recording, stop_video_recording).

        When enabled, the agent will have access to tools for recording the device
        screen and analyzing the video content using Gemini models.

        IMPORTANT: This requires:
        1. ffmpeg to be installed on the system (for video compression)
        2. A video-capable model configured in utils.video_analyzer

        Supported models for video_analyzer:
        - gemini-3-flash-preview (recommended)
        - gemini-3-pro-preview
        - gemini-2.5-flash
        - gemini-2.5-pro
        - gemini-2.0-flash

        Returns:
            Self for method chaining

        Raises:
            FFmpegNotInstalledError: If ffmpeg is not installed
            ValueError: When the agent is initialized if any profile lacks video_analyzer config
        """
        from minitap.mobile_use.utils.video import check_ffmpeg_available

        check_ffmpeg_available()
        self._video_recording_enabled = True
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
            ios_client_config=self._ios_client_config,
            browserstack_config=self._browserstack_config,
            video_recording_enabled=self._video_recording_enabled,
            cloud_device_config=self._cloud_device_config,
            cloud_android_controller=self._cloud_android_controller,
            cloud_ios_controller=self._cloud_ios_controller,
        )


def get_default_agent_config():
    return AgentConfigBuilder().build()


def get_default_servers():
    return ServerConfig(
        adb_host="localhost",
        adb_port=5037,
    )
