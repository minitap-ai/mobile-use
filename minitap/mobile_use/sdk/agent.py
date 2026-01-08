import asyncio
import sys
import tempfile
import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from shutil import which
from types import NoneType
from typing import Any, TypeVar, overload

from adbutils import AdbClient
from dotenv import load_dotenv
from langchain_core.messages import AIMessage
from PIL import Image
from pydantic import BaseModel

from minitap.mobile_use.agents.outputter.outputter import outputter
from minitap.mobile_use.agents.planner.types import Subgoal
from minitap.mobile_use.clients.browserstack_client import BrowserStackClientWrapper
from minitap.mobile_use.clients.idb_client import IdbClientWrapper
from minitap.mobile_use.clients.ios_client import DeviceType, IosClientWrapper, get_ios_client
from minitap.mobile_use.clients.ui_automator_client import UIAutomatorClient
from minitap.mobile_use.clients.wda_client import WdaClientWrapper
from minitap.mobile_use.config import AgentNode, OutputConfig, record_events, settings
from minitap.mobile_use.context import (
    DeviceContext,
    DevicePlatform,
    ExecutionSetup,
    IsReplan,
    MobileUseContext,
)
from minitap.mobile_use.controllers.platform_specific_commands_controller import get_first_device
from minitap.mobile_use.graph.graph import get_graph
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.sdk.builders.agent_config_builder import get_default_agent_config
from minitap.mobile_use.sdk.builders.task_request_builder import TaskRequestBuilder
from minitap.mobile_use.sdk.constants import DEFAULT_PROFILE_NAME
from minitap.mobile_use.sdk.services.cloud_mobile import CloudMobileService
from minitap.mobile_use.sdk.services.platform import PlatformService
from minitap.mobile_use.sdk.types.agent import AgentConfig
from minitap.mobile_use.sdk.types.exceptions import (
    AgentError,
    AgentNotInitializedError,
    AgentProfileNotFoundError,
    AgentTaskRequestError,
    CloudMobileServiceUninitializedError,
    DeviceNotFoundError,
    ExecutableNotFoundError,
    PlatformServiceUninitializedError,
    ServerStartupError,
)
from minitap.mobile_use.sdk.types.platform import TaskRunPlanResponse, TaskRunStatus
from minitap.mobile_use.sdk.types.task import (
    AgentProfile,
    CloudDevicePlatformTaskRequest,
    PlatformTaskInfo,
    PlatformTaskRequest,
    Task,
    TaskRequest,
)
from minitap.mobile_use.services.telemetry import telemetry
from minitap.mobile_use.utils.app_launch_utils import _handle_initial_app_launch
from minitap.mobile_use.utils.logger import get_logger
from minitap.mobile_use.utils.media import (
    create_gif_from_trace_folder,
    create_steps_json_from_trace_folder,
    remove_images_from_trace_folder,
    remove_steps_json_from_trace_folder,
)
from minitap.mobile_use.utils.recorder import log_agent_thought

logger = get_logger(__name__)

TOutput = TypeVar("TOutput", bound=BaseModel | None)

load_dotenv()


class Agent:
    _config: AgentConfig
    _tasks: list[Task] = []
    _tmp_traces_dir: Path
    _initialized: bool = False
    _device_context: DeviceContext
    _adb_client: AdbClient | None
    _ui_adb_client: UIAutomatorClient | None
    _ios_client: IosClientWrapper | None
    _ios_device_type: DeviceType | None
    _current_task: asyncio.Task | None = None
    _task_lock: asyncio.Lock
    _cloud_mobile_id: str | None = None

    def __init__(self, *, config: AgentConfig | None = None):
        self._config = config or get_default_agent_config()
        self._tasks = []
        self._tmp_traces_dir = Path(tempfile.gettempdir()) / "mobile-use-traces"
        self._initialized = False
        self._task_lock = asyncio.Lock()

        # Initialize platform service if API key is available in environment
        # Note: Can also be initialized later with API key at agent .init()
        if settings.MINITAP_API_KEY:
            self._platform_service = PlatformService()
            self._cloud_mobile_service = CloudMobileService()
        else:
            self._platform_service = None
            self._cloud_mobile_service = None

    async def init(
        self,
        api_key: str | None = None,
        server_restart_attempts: int = 3,
        retry_count: int = 5,
        retry_wait_seconds: int = 5,
    ):
        # Start telemetry session for SDK usage (if not already started by CLI)
        if not telemetry._session_id:
            telemetry.start_session({"source": "sdk"})

        try:
            return await self._init_internal(
                api_key=api_key,
                server_restart_attempts=server_restart_attempts,
                retry_count=retry_count,
                retry_wait_seconds=retry_wait_seconds,
            )
        except Exception as e:
            session_id = telemetry._session_id
            telemetry.capture_exception(e, {"phase": "agent_init"})
            telemetry.end_session(success=False, error=str(e))
            if session_id:
                logger.info(f"If you need support, please include this session ID: {session_id}")
            raise

    async def _init_internal(
        self,
        api_key: str | None = None,
        server_restart_attempts: int = 3,
        retry_count: int = 5,
        retry_wait_seconds: int = 5,
    ):
        if api_key:
            self._platform_service = PlatformService(api_key=api_key)
            self._cloud_mobile_service = CloudMobileService(api_key=api_key)

        # Skip initialization for cloud devices - no local setup required
        if self._config.cloud_mobile_id_or_ref:
            if not self._cloud_mobile_service:
                raise CloudMobileServiceUninitializedError()
            self._cloud_mobile_id = await self._cloud_mobile_service.resolve_cloud_mobile_id(
                cloud_mobile_id_or_ref=self._config.cloud_mobile_id_or_ref,
            )
            logger.info("Cloud device configured - skipping local initialization")
            self._initialized = True
            return True

        # Handle BrowserStack initialization
        if self._config.browserstack_config:
            logger.info("Initializing BrowserStack session...")
            self._ios_client = BrowserStackClientWrapper(config=self._config.browserstack_config)
            session_started = await self._ios_client.init_client()
            if not session_started:
                raise ServerStartupError(
                    message="Failed to create BrowserStack session. "
                    "Please check your credentials and device configuration."
                )
            self._ios_device_type = DeviceType.BROWSERSTACK
            self._adb_client = None
            self._ui_adb_client = None
            logger.success("BrowserStack session created successfully")

            self._device_context = await self._get_device_context(
                device_id="browserstack", platform=DevicePlatform.IOS
            )
            logger.info(self._device_context.to_str())
            logger.info("✅ Mobile-use agent initialized with BrowserStack.")
            self._initialized = True
            telemetry.capture_agent_initialized(
                platform=DevicePlatform.IOS.value,
                device_id="browserstack",
            )
            return True

        if not which("adb") and not which("xcrun"):
            raise ExecutableNotFoundError("cli_tools")

        if self._initialized:
            logger.warning("Agent is already initialized. Skipping...")
            return True

        # Get first available device ID
        if not self._config.device_id or not self._config.device_platform:
            device_id, platform, ios_device_type = get_first_device(logger=logger)
        else:
            device_id, platform = self._config.device_id, self._config.device_platform
            ios_device_type = None  # Will be auto-detected in _init_clients

        if not device_id or not platform:
            error_msg = "No device found. Exiting."
            logger.error(error_msg)
            raise DeviceNotFoundError(error_msg)

        # Initialize clients
        self._init_clients(
            device_id=device_id,
            platform=platform,
            ios_device_type=ios_device_type,
            retry_count=retry_count,
            retry_wait_seconds=retry_wait_seconds,
        )

        # Initialize iOS client (IDB companion for simulators, WDA already running for physical)
        if self._ios_client:
            if isinstance(self._ios_client, IdbClientWrapper):
                logger.info("Starting IDB companion for iOS simulator...")
                companion_started = await self._ios_client.init_companion()
                if not companion_started:
                    raise ServerStartupError(
                        message="Failed to start IDB companion for iOS simulator. "
                        "Please ensure fb-idb is installed: https://fbidb.io/docs/installation/"
                    )
                logger.success("IDB companion started successfully")
            elif isinstance(self._ios_client, WdaClientWrapper):
                logger.info("Connecting to WebDriverAgent for physical iOS device...")
                wda_connected = await self._ios_client.init_client()
                if not wda_connected:
                    raise ServerStartupError(
                        message="Failed to connect to WebDriverAgent. "
                        "Please ensure WDA is running on your device. "
                        "See the setup instructions above."
                    )
                logger.success("WDA client connected for physical device")

        # Start necessary servers
        restart_attempt = 0
        while restart_attempt < server_restart_attempts:
            success = self._run_servers(
                device_id=device_id,
                platform=platform,
            )
            if success:
                break

            restart_attempt += 1
            if restart_attempt < server_restart_attempts:
                logger.warning(
                    f"Server start failed, attempting restart "
                    f"{restart_attempt}/{server_restart_attempts}"
                )
            else:
                error_msg = "Mobile-use servers failed to start after all restart attempts."
                logger.error(error_msg)
                raise ServerStartupError(message=error_msg)

        self._device_context = await self._get_device_context(
            device_id=device_id, platform=platform
        )
        logger.info(self._device_context.to_str())
        logger.info("✅ Mobile-use agent initialized.")
        self._initialized = True
        telemetry.capture_agent_initialized(
            platform=platform.value,
            device_id=device_id,
        )
        return True

    async def install_apk(self, apk_path: str | Path) -> None:
        """
        Install an APK on the connected device.
        For cloud mobiles, the APK must be x86_64 compatible.

        Args:
            apk_path: Path to the local APK file to install

        Raises:
            AgentNotInitializedError: If the agent is not initialized
            AgentError: If attempting to install on non-Android device or ADB operations fail
            FileNotFoundError: If the APK file doesn't exist
            CloudMobileServiceUninitializedError: If cloud service is unavailable
        """
        try:
            await self._install_apk_internal(apk_path)
        except Exception as e:
            telemetry.capture_exception(e, {"phase": "install_apk"})
            raise

    async def _install_apk_internal(self, apk_path: str | Path) -> None:
        if isinstance(apk_path, str):
            apk_path = Path(apk_path)

        if not apk_path.exists():
            raise FileNotFoundError(f"APK file not found: {apk_path}")

        if self._config.cloud_mobile_id_or_ref:
            await self._install_apk_on_cloud_mobile(apk_path)
        else:
            if not self._initialized:
                raise AgentNotInitializedError()

            if self._device_context.mobile_platform != DevicePlatform.ANDROID:
                raise AgentError(
                    "APK can only be installed on Android devices but got "
                    f"'{self._device_context.mobile_platform.value}'"
                )

            device_id = self._device_context.device_id
            logger.info(f"Installing APK on Android device '{device_id}'")
            if not self._adb_client:
                raise AgentError("ADB client not initialized")

            device = self._adb_client.device(serial=device_id)
            await asyncio.to_thread(device.install, apk_path)
            logger.info(f"APK installed successfully on Android device '{device_id}'")

    async def _install_apk_on_cloud_mobile(self, apk_path: Path) -> None:
        """
        Install an APK on a cloud mobile device.

        This method starts the cloud mobile if needed, then uploads and installs the APK.
        """
        if not self._cloud_mobile_id:
            raise AgentTaskRequestError("Cloud mobile ID is not configured")

        if not self._cloud_mobile_service:
            raise CloudMobileServiceUninitializedError()

        # Check platform before starting - fail early if not Android
        vm_info = await self._cloud_mobile_service._get_virtual_mobile_status(self._cloud_mobile_id)
        if vm_info.platform and vm_info.platform != "android":
            raise AgentError(
                f"APK can only be installed on Android cloud mobiles but got '{vm_info.platform}'"
            )

        # Start cloud mobile if not already started
        logger.info(f"Starting cloud mobile '{self._cloud_mobile_id}' for APK installation...")
        await self._cloud_mobile_service.start_and_wait_for_ready(
            cloud_mobile_id=self._cloud_mobile_id,
        )

        # Install APK
        logger.info(f"Installing APK '{apk_path.name}' on cloud mobile '{self._cloud_mobile_id}'")
        await self._cloud_mobile_service.install_apk(
            cloud_mobile_id=self._cloud_mobile_id,
            apk_path=apk_path,
        )
        logger.success(f"APK '{apk_path.name}' installed successfully")

    def new_task(self, goal: str):
        """
        Create a new task request builder.

        Args:
            goal: Natural language description of what to accomplish

        Returns:
            TaskRequestBuilder that can be configured with:
            - .with_output_format() for structured output
            - .with_output_description() for output description
            - .with_locked_app_package() to restrict execution to a specific app
            - .using_profile() to specify an LLM profile
            - .with_max_steps() to set maximum execution steps
            - .with_trace_recording() to enable trace recording
            - .with_name() to set a custom task name
        """
        return TaskRequestBuilder[None].from_common(
            goal=goal,
            common=self._config.task_request_defaults,
        )

    @overload
    async def run_task(
        self,
        *,
        goal: str,
        output: type[TOutput],
        profile: str | AgentProfile | None = None,
        name: str | None = None,
        locked_app_package: str | None = None,
    ) -> TOutput | None: ...

    @overload
    async def run_task(
        self,
        *,
        goal: str,
        output: str,
        profile: str | AgentProfile | None = None,
        name: str | None = None,
        locked_app_package: str | None = None,
    ) -> str | dict | None: ...

    @overload
    async def run_task(
        self,
        *,
        goal: str,
        output=None,
        profile: str | AgentProfile | None = None,
        name: str | None = None,
        locked_app_package: str | None = None,
    ) -> str | None: ...

    @overload
    async def run_task(
        self,
        *,
        request: TaskRequest[None],
        locked_app_package: str | None = None,
    ) -> str | dict | None: ...

    @overload
    async def run_task(
        self,
        *,
        request: TaskRequest[TOutput],
        locked_app_package: str | None = None,
    ) -> TOutput | None: ...

    @overload
    async def run_task(
        self,
        *,
        request: PlatformTaskRequest[None],
        locked_app_package: str | None = None,
    ) -> str | dict | None: ...

    @overload
    async def run_task(
        self,
        *,
        request: PlatformTaskRequest[TOutput],
        locked_app_package: str | None = None,
    ) -> TOutput | None: ...

    async def run_task(
        self,
        *,
        goal: str | None = None,
        output: type[TOutput] | str | None = None,
        profile: str | AgentProfile | None = None,
        locked_app_package: str | None = None,
        name: str | None = None,
        request: TaskRequest[TOutput] | PlatformTaskRequest[TOutput] | None = None,
    ) -> str | dict | TOutput | None:
        # Check if cloud mobile is configured
        if self._config.cloud_mobile_id_or_ref:
            if request is None or not isinstance(request, PlatformTaskRequest):
                raise AgentTaskRequestError(
                    "When using a cloud mobile, only PlatformTaskRequest is supported. "
                    "Use AgentConfigBuilder.for_cloud_mobile() only with PlatformTaskRequest."
                )
            # Use cloud mobile execution path
            return await self._run_cloud_mobile_task(
                request=request, locked_app_package=locked_app_package
            )

        # Normal local execution path
        if request is not None:
            task_info = None
            if isinstance(request, PlatformTaskRequest):
                if not self._platform_service:
                    raise PlatformServiceUninitializedError()
                task_info = await self._platform_service.create_task_run(
                    request=request,
                    locked_app_package=locked_app_package,
                    enable_video_tools=self._config.video_recording_enabled,
                )
                if isinstance(request, CloudDevicePlatformTaskRequest):
                    request.task_run_id = task_info.task_run.id
                    request.task_run_id_available_event.set()
                self._config.agent_profiles[task_info.llm_profile.name] = task_info.llm_profile
                request = task_info.task_request
            elif locked_app_package is not None:
                if request.locked_app_package:
                    logger.warning(
                        "Locked app package specified both in the request and as a parameter. "
                        "Using the parameter value."
                    )
                request.locked_app_package = locked_app_package
            return await self._run_task(
                request=request, task_info=task_info, platform_service=self._platform_service
            )
        if goal is None:
            raise AgentTaskRequestError("Goal is required")
        task_request = self.new_task(goal=goal)
        if output is not None:
            if isinstance(output, str):
                task_request.with_output_description(description=output)
            elif output is not NoneType:
                task_request.with_output_format(output_format=output)
        if profile is not None:
            task_request.using_profile(profile=profile)
        if name is not None:
            task_request.with_name(name=name)
        if locked_app_package is not None:
            task_request.with_locked_app_package(package_name=locked_app_package)
        return await self._run_task(task_request.build())

    async def _run_cloud_mobile_task(
        self,
        request: PlatformTaskRequest[TOutput],
        locked_app_package: str | None = None,
    ) -> str | dict | TOutput | None:
        """
        Execute a task on a cloud mobile.

        This method triggers the task execution on the Platform and polls
        for completion without running any agentic logic locally.
        """
        if not self._cloud_mobile_id:
            raise AgentTaskRequestError("Cloud mobile ID is not configured")

        if not self._cloud_mobile_service:
            raise CloudMobileServiceUninitializedError()

        if not self._platform_service:
            raise PlatformServiceUninitializedError()

        if self._config.video_recording_enabled:
            profile_name = request.profile or DEFAULT_PROFILE_NAME
            _, profile = await self._platform_service.get_profile(profile_name)
            if not profile.llm_config.utils.video_analyzer:
                raise AgentTaskRequestError(
                    f"video_recording_enabled: profile '{profile_name}' "
                    "must have a video_analyzer agent configured"
                )

        # Start cloud mobile if not already started
        logger.info(f"Starting cloud mobile '{self._cloud_mobile_id}'...")
        await self._cloud_mobile_service.start_and_wait_for_ready(
            cloud_mobile_id=self._cloud_mobile_id,
        )
        logger.info(
            f"Starting cloud mobile task execution '{self._cloud_mobile_id}'",
        )

        def log_callback(message: str):
            """Callback for logging timeline updates."""
            logger.info(message)

        def status_callback(
            status: TaskRunStatus,
            status_message: str | None,
        ):
            """Callback for status updates."""
            logger.info(f"Task status update: [{status}] {status_message}")

        async def _execute_cloud(cloud_mobile_service: CloudMobileService, cloud_mobile_id: str):
            try:
                # Execute task on cloud mobile and wait for completion
                final_status, error, output = await cloud_mobile_service.run_task_on_cloud_mobile(
                    cloud_mobile_id=cloud_mobile_id,
                    request=request,
                    on_status_update=status_callback,
                    on_log=log_callback,
                    locked_app_package=locked_app_package,
                    enable_video_tools=self._config.video_recording_enabled,
                )
                if final_status == "completed":
                    logger.success("Cloud mobile task completed successfully")
                    return output
                if final_status == "failed":
                    logger.error(f"Cloud mobile task failed: {error}")
                    raise AgentTaskRequestError(
                        f"Task execution failed on cloud mobile: {error}",
                    )
                if final_status == "cancelled":
                    logger.warning("Cloud mobile task was cancelled")
                    raise AgentTaskRequestError("Task execution was cancelled")
                logger.error(f"Unknown cloud mobile task status: {final_status}")
                raise AgentTaskRequestError(f"Unknown task status: {final_status}")
            except asyncio.CancelledError:
                # Propagate cancellation to parent coroutine.
                logger.info("Task cancelled during execution, re-raising CancelledError")
                raise
            except AgentTaskRequestError as e:
                # Capture and re-raise known exceptions
                telemetry.capture_exception(e, {"phase": "cloud_mobile_task"})
                raise
            except Exception as e:
                logger.error(f"Unexpected error during cloud mobile task execution: {e}")
                telemetry.capture_exception(e, {"phase": "cloud_mobile_task"})
                raise AgentTaskRequestError(f"Unexpected error: {e}") from e

        async with self._task_lock:
            if self._current_task and not self._current_task.done():
                logger.warning(
                    "Another cloud task is running; cancelling it before starting new one.",
                )
                self.stop_current_task()
                try:
                    await self._current_task
                except asyncio.CancelledError:
                    pass
            try:
                self._current_task = asyncio.create_task(
                    _execute_cloud(
                        cloud_mobile_service=self._cloud_mobile_service,
                        cloud_mobile_id=self._cloud_mobile_id,
                    ),
                )
                return await self._current_task
            finally:
                self._current_task = None

    async def _run_task(
        self,
        request: TaskRequest[TOutput],
        task_info: PlatformTaskInfo | None = None,
        platform_service: PlatformService | None = None,
    ) -> str | dict | TOutput | None:
        if not self._initialized:
            raise AgentNotInitializedError()

        if request.profile:
            agent_profile = self._config.agent_profiles.get(request.profile)
            if agent_profile is None:
                raise AgentProfileNotFoundError(request.profile)
        else:
            agent_profile = self._config.default_profile

        if (
            self._config.video_recording_enabled
            and agent_profile.llm_config.utils.video_analyzer is None
        ):
            raise ValueError(
                f"with_video_recording_tools() requires 'video_analyzer' in utils for "
                f"profile '{agent_profile.name}'. Add 'video_analyzer' with a "
                f"video-capable model (e.g., gemini-3-flash-preview)."
            )

        logger.info(str(agent_profile))

        on_status_changed = None
        on_agent_thought = None
        on_plan_changes = None
        task_id = str(uuid.uuid4())
        if task_info:
            on_status_changed = self._get_task_status_change_callback(
                task_info=task_info, platform_service=platform_service
            )
            on_agent_thought = self._get_new_agent_thought_callback(
                task_info=task_info, platform_service=platform_service
            )
            on_plan_changes = self._get_plan_changes_callback(
                task_info=task_info, platform_service=platform_service
            )
            task_id = task_info.task_run.id

        task = Task(
            id=task_id,
            device=self._device_context,
            status="pending",
            request=request,
            created_at=datetime.now(),
            on_status_changed=on_status_changed,
        )
        self._tasks.append(task)
        task_name = task.get_name()

        # Extract API key from platform service if available
        api_key = None
        if platform_service:
            api_key = platform_service._api_key

        context = MobileUseContext(
            trace_id=task.id,
            device=self._device_context,
            adb_client=self._adb_client,
            ui_adb_client=self._ui_adb_client,
            ios_client=self._ios_client,
            llm_config=agent_profile.llm_config,
            on_agent_thought=on_agent_thought,
            on_plan_changes=on_plan_changes,
            minitap_api_key=api_key,
            video_recording_enabled=(
                self._config.video_recording_enabled
                and agent_profile.llm_config.utils.video_analyzer is not None
            ),
        )

        self._prepare_tracing(task=task, context=context)
        await self._prepare_app_lock(task=task, context=context)
        self._prepare_output_files(task=task)

        output_config = None
        if request.output_description or request.output_format:
            output_config = OutputConfig(
                output_description=request.output_description,
                structured_output=request.output_format,  # type: ignore
            )
            logger.info(str(output_config))

        logger.info(f"[{task_name}] Starting graph with goal: `{request.goal}`")
        state = self._get_graph_state(task=task)
        graph_input = state.model_dump()
        task_start_time = datetime.now(UTC)

        telemetry.capture_task_started(
            task_id=task_id,
            platform=self._device_context.mobile_platform.value,
            has_locked_app=request.locked_app_package is not None,
        )

        async def _execute_task_logic():
            last_state: State | None = None
            last_state_snapshot: dict | None = None
            output = None
            try:
                logger.info(f"[{task_name}] Invoking graph with input: {graph_input}")
                await task.set_status(status="running", message="Invoking graph...")
                async for chunk in (await get_graph(context)).astream(
                    input=graph_input,
                    config={
                        "recursion_limit": task.request.max_steps,
                        "callbacks": self._config.graph_config_callbacks,
                    },
                    stream_mode=["messages", "custom", "updates", "values"],
                ):
                    stream_mode, payload = chunk
                    if stream_mode == "values":
                        last_state_snapshot = payload  # type: ignore
                        last_state = State(**last_state_snapshot)  # type: ignore
                        if task.request.thoughts_output_path:
                            record_events(
                                output_path=task.request.thoughts_output_path,
                                events=last_state.agents_thoughts,
                            )

                    if stream_mode == "updates":
                        for _, value in payload.items():  # type: ignore node name, node output
                            if value and "agents_thoughts" in value:
                                new_thoughts = value["agents_thoughts"]
                                last_item = new_thoughts[-1] if new_thoughts else None
                                if last_item:
                                    log_agent_thought(
                                        agent_thought=last_item,
                                    )

                if not last_state:
                    err = f"[{task_name}] No result received from graph"
                    logger.warning(err)
                    await task.finalize(content=output, state=last_state_snapshot, error=err)
                    return None

                print_ai_response_to_stderr(graph_result=last_state)
                output = await self._extract_output(
                    task_name=task_name,
                    ctx=context,
                    request=request,
                    output_config=output_config,
                    state=last_state,
                )
                logger.info(f"✅ Automation '{task_name}' is success ✅")
                await task.finalize(content=output, state=last_state_snapshot)
                duration = (datetime.now(UTC) - task_start_time).total_seconds()
                steps_count = len(last_state.agents_thoughts) if last_state else 0
                telemetry.capture_task_completed(
                    task_id=task_id,
                    success=True,
                    steps_count=steps_count,
                    duration_seconds=duration,
                )
                return output
            except asyncio.CancelledError:
                err = f"[{task_name}] Task cancelled"
                logger.warning(err)
                await task.finalize(
                    content=output,
                    state=last_state_snapshot,
                    error=err,
                    cancelled=True,
                )
                duration = (datetime.now(UTC) - task_start_time).total_seconds()
                steps_count = len(last_state.agents_thoughts) if last_state else 0
                telemetry.capture_task_completed(
                    task_id=task_id,
                    success=False,
                    steps_count=steps_count,
                    duration_seconds=duration,
                    cancelled=True,
                )
                raise
            except Exception as e:
                err = f"[{task_name}] Error running automation: {e}"
                logger.error(err)
                await task.finalize(
                    content=output,
                    state=last_state_snapshot,
                    error=err,
                )
                duration = (datetime.now(UTC) - task_start_time).total_seconds()
                steps_count = len(last_state.agents_thoughts) if last_state else 0
                telemetry.capture_task_completed(
                    task_id=task_id,
                    success=False,
                    steps_count=steps_count,
                    duration_seconds=duration,
                )
                telemetry.capture_exception(e, {"task_id": task_id})
                if telemetry._session_id:
                    logger.info(
                        "If you need support, please include this session ID: "
                        f"{telemetry._session_id}"
                    )
                raise
            finally:
                await self._finalize_tracing(task=task, context=context)

        async with self._task_lock:
            if self._current_task and not self._current_task.done():
                logger.warning(
                    "Another automation task is already running. "
                    "Stopping it before starting the new one."
                )
                self.stop_current_task()
                try:
                    await self._current_task
                except asyncio.CancelledError:
                    pass

            try:
                self._current_task = asyncio.create_task(_execute_task_logic())
                return await self._current_task
            finally:
                self._current_task = None

    def stop_current_task(self):
        """Requests cancellation of the currently running automation task."""
        if self._current_task and not self._current_task.done():
            logger.info("Requesting to stop the current automation task...")
            was_cancelled = self._current_task.cancel()
            if was_cancelled:
                logger.success("Cancellation request for the current task was sent.")
            else:
                logger.warning(
                    "Could not send cancellation request for the current task "
                    "(it may already be completing)."
                )
        else:
            logger.info("No active automation task to stop.")

    async def get_screenshot(self) -> Image.Image:
        """
        Capture a screenshot from the mobile device.

        For cloud mobiles, this method calls the mobile-manager endpoint.
        For local mobiles, it uses ADB (Android) or xcrun (iOS) directly.

        Returns:
            Screenshot as PIL Image

        Raises:
            AgentNotInitializedError: If the agent is not initialized
            PlatformServiceUninitializedError: If cloud mobile service is not available
            Exception: If screenshot capture fails
        """
        # Check if cloud mobile is configured
        if self._cloud_mobile_id:
            if not self._cloud_mobile_service:
                raise CloudMobileServiceUninitializedError()
            screenshot = await self._cloud_mobile_service.get_screenshot(
                cloud_mobile_id=self._cloud_mobile_id,
            )
            return screenshot

        # Local device - use ADB or xcrun directly
        if not self._initialized:
            raise AgentNotInitializedError()

        if self._device_context.mobile_platform == DevicePlatform.ANDROID:
            # Use ADB to capture screenshot
            logger.info("Capturing screenshot from local Android device")
            if not self._adb_client:
                raise Exception("ADB client not initialized")

            device = self._adb_client.device(serial=self._device_context.device_id)
            screenshot = await asyncio.to_thread(device.screenshot)
            logger.info("Screenshot captured from local Android device")
            return screenshot

        elif self._device_context.mobile_platform == DevicePlatform.IOS:
            # Use xcrun to capture screenshot
            import functools
            import subprocess
            from io import BytesIO

            logger.info("Capturing screenshot from local iOS device")
            try:
                # xcrun simctl io <device> screenshot --type=png -
                result = await asyncio.to_thread(
                    functools.partial(
                        subprocess.run,
                        [
                            "xcrun",
                            "simctl",
                            "io",
                            self._device_context.device_id,
                            "screenshot",
                            "--type=png",
                            "-",
                        ],
                        capture_output=True,
                        check=True,
                    )
                )
                # Convert bytes to PIL Image
                screenshot = Image.open(BytesIO(result.stdout))
                logger.info("Screenshot captured from local iOS device")
                return screenshot
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to capture screenshot: {e}")
                raise Exception(f"Failed to capture screenshot from iOS device: {e}")

        else:
            raise Exception(f"Unsupported platform: {self._device_context.mobile_platform}")

    async def clean(self, force: bool = False):
        if self._cloud_mobile_id:
            self._initialized = False
            logger.info("✅ Cloud-mode agent stopped.")
            # End telemetry session if started by SDK (not CLI)
            if telemetry._session_id and telemetry._session_context.get("source") == "sdk":
                telemetry.end_session(success=True)
            return
        if not self._initialized and not force:
            return

        if self._ios_client:
            await self._ios_client.cleanup()
            self._ios_client = None

        self._initialized = False
        logger.info("✅ Mobile-use agent stopped.")

        # End telemetry session if started by SDK (not CLI)
        if telemetry._session_id and telemetry._session_context.get("source") == "sdk":
            telemetry.end_session(success=True)

    async def _prepare_app_lock(self, task: Task, context: MobileUseContext):
        """Prepare app lock by launching the locked app if specified."""
        if not task.request.locked_app_package:
            return

        task_name = task.get_name()
        logger.info(f"[{task_name}] Preparing app lock for: {task.request.locked_app_package}")

        app_lock_status = await _handle_initial_app_launch(
            ctx=context, locked_app_package=task.request.locked_app_package
        )

        if context.execution_setup is None:
            context.execution_setup = ExecutionSetup(app_lock_status=app_lock_status)
        else:
            context.execution_setup.app_lock_status = app_lock_status

        if app_lock_status.locked_app_initial_launch_success is False:
            error = app_lock_status.locked_app_initial_launch_error
            logger.warning(f"[{task_name}] Failed to launch locked app: {error}")

    def _prepare_tracing(self, task: Task, context: MobileUseContext):
        """Prepare tracing setup if record_trace is enabled."""
        if not task.request.record_trace:
            return

        task_name = task.get_name()
        temp_trace_path = Path(self._tmp_traces_dir / task_name).resolve()
        traces_output_path = Path(task.request.trace_path).resolve()
        logger.info(f"[{task_name}] 📂 Traces output path: {traces_output_path}")
        logger.info(f"[{task_name}] 📄📂 Traces temp path: {temp_trace_path}")
        traces_output_path.mkdir(parents=True, exist_ok=True)
        temp_trace_path.mkdir(parents=True, exist_ok=True)

        context.execution_setup = ExecutionSetup(
            traces_path=self._tmp_traces_dir,
            trace_name=task_name,
            enable_remote_tracing=task.request.enable_remote_tracing,
        )

    async def _finalize_tracing(self, task: Task, context: MobileUseContext):
        exec_setup_ctx = context.execution_setup
        if not exec_setup_ctx:
            return

        if exec_setup_ctx.traces_path is None or exec_setup_ctx.trace_name is None:
            return

        task_name = task.get_name()
        status = "_PASS" if task.status == "completed" else "_FAIL"
        ts = task.created_at.strftime("%Y-%m-%dT%H-%M-%S")
        new_name = f"{exec_setup_ctx.trace_name}{status}_{ts}"

        temp_trace_path = (self._tmp_traces_dir / exec_setup_ctx.trace_name).resolve()
        traces_output_path = Path(task.request.trace_path).resolve()

        logger.info(f"[{task_name}] Compiling trace FROM FOLDER: " + str(temp_trace_path))
        create_gif_from_trace_folder(temp_trace_path)
        create_steps_json_from_trace_folder(temp_trace_path)

        if exec_setup_ctx.enable_remote_tracing:
            gif_path = temp_trace_path / "trace.gif"
            if gif_path.exists() and self._platform_service:
                try:
                    task_run_id = await self._platform_service.upload_trace_gif(
                        task_run_id=task.id, gif_path=gif_path
                    )
                    if task_run_id:
                        platform_url = f"{settings.MINITAP_BASE_URL}/task-runs/{task_run_id}"
                        logger.info(f"[{task_name}] 🌐 View on platform: {platform_url}")
                except Exception as e:
                    logger.warning(f"[{task_name}] Failed to upload trace GIF: {e}")

        logger.info(f"[{task_name}] Video created, removing dust...")
        remove_images_from_trace_folder(temp_trace_path)
        remove_steps_json_from_trace_folder(temp_trace_path)
        logger.info(f"[{task_name}] 📽️ Trace compiled, moving to output path 📽️")

        output_folder_path = temp_trace_path.rename(traces_output_path / new_name).resolve()
        logger.info(f"[{task_name}] 📂✅ Traces located in: {output_folder_path}")

    def _prepare_output_files(self, task: Task):
        if task.request.llm_output_path:
            _validate_and_prepare_file(file_path=task.request.llm_output_path)
        if task.request.thoughts_output_path:
            _validate_and_prepare_file(file_path=task.request.thoughts_output_path)

    async def _extract_output(
        self,
        task_name: str,
        ctx: MobileUseContext,
        request: TaskRequest[TOutput],
        output_config: OutputConfig | None,
        state: State,
    ) -> str | dict | TOutput | None:
        if output_config and output_config.needs_structured_format():
            logger.info(f"[{task_name}] Generating structured output...")
            try:
                structured_output = await outputter(
                    ctx=ctx,
                    output_config=output_config,
                    graph_output=state,
                )
                logger.info(f"[{task_name}] Structured output: {structured_output}")
                record_events(output_path=request.llm_output_path, events=structured_output)
                if request.output_format is not None and request.output_format is not NoneType:
                    return request.output_format.model_validate(structured_output)
                return structured_output
            except Exception as e:
                logger.error(f"[{task_name}] Failed to generate structured output: {e}")
                return None
        if state and state.agents_thoughts:
            last_msg = state.agents_thoughts[-1]
            logger.info(str(last_msg))
            record_events(output_path=request.llm_output_path, events=last_msg)
            return last_msg
        return None

    def _get_graph_state(self, task: Task):
        return State(
            messages=[],
            initial_goal=task.request.goal,
            subgoal_plan=[],
            latest_ui_hierarchy=None,
            latest_screenshot=None,
            focused_app_info=None,
            device_date=None,
            structured_decisions=None,
            complete_subgoals_by_ids=[],
            agents_thoughts=[],
            remaining_steps=task.request.max_steps,
            executor_messages=[],
            cortex_last_thought=None,
            scratchpad={},
        )

    def _init_clients(
        self,
        device_id: str,
        platform: DevicePlatform,
        ios_device_type: DeviceType | None,
        retry_count: int,
        retry_wait_seconds: int,
    ):
        self._adb_client = (
            AdbClient(host=self._config.servers.adb_host, port=self._config.servers.adb_port)
            if platform == DevicePlatform.ANDROID
            else None
        )
        self._ui_adb_client = (
            UIAutomatorClient(device_id=device_id) if platform == DevicePlatform.ANDROID else None
        )

        # Initialize iOS client using factory (auto-detects device type if not provided)
        if platform == DevicePlatform.IOS:
            self._ios_client = get_ios_client(
                udid=device_id,
                config=self._config.ios_client_config,
            )
            self._ios_device_type = ios_device_type or (
                DeviceType.PHYSICAL
                if isinstance(self._ios_client, WdaClientWrapper)
                else DeviceType.SIMULATOR
            )
        else:
            self._ios_client = None
            self._ios_device_type = None

    def _run_servers(self, device_id: str, platform: DevicePlatform) -> bool:
        if platform == DevicePlatform.ANDROID:
            if not self._ui_adb_client:
                error_msg = (
                    "UIAutomator client is required for Android but not available. "
                    "Please ensure UIAutomator2 is properly installed and configured."
                )
                logger.error(error_msg)
                raise ValueError(error_msg)
            logger.info("✓ UIAutomator client available for Android")
        elif platform == DevicePlatform.IOS:
            if not self._ios_client:
                error_msg = (
                    "iOS client is required but not available. "
                    "Ensure idb (simulators) or WDA (physical) is available."
                )
                logger.error(error_msg)
                raise ValueError(error_msg)
            if isinstance(self._ios_client, WdaClientWrapper):
                client_type = "WDA"
            elif isinstance(self._ios_client, BrowserStackClientWrapper):
                client_type = "BrowserStack"
            else:
                client_type = "IDB"
            logger.info(f"✓ iOS client available ({client_type})")

        return True

    async def _get_device_context(
        self,
        device_id: str,
        platform: DevicePlatform,
    ) -> DeviceContext:
        from platform import system

        host_platform = system()

        # Get real device dimensions from the device
        if platform == DevicePlatform.ANDROID:
            if self._ui_adb_client:
                try:
                    # Use UIAutomator to get actual screen dimensions
                    screen_data = self._ui_adb_client.get_screen_data()
                    device_width = screen_data.width
                    device_height = screen_data.height
                    logger.info(
                        f"Retrieved Android screen dimensions: {device_width}x{device_height}"
                    )
                except Exception as e:
                    logger.warning(f"Failed to get Android screen dimensions: {e}, using defaults")
                    device_width, device_height = 1080, 2340
            else:
                logger.warning("UIAutomator client not available, using default dimensions")
                device_width, device_height = 1080, 2340
        else:  # iOS
            if self._ios_client:
                try:
                    # Use iOS client to take a screenshot and get dimensions
                    screenshot_data = await self._ios_client.screenshot()  # type: ignore[call-arg]
                    if screenshot_data:
                        img = Image.open(BytesIO(screenshot_data))
                        device_width = img.width
                        device_height = img.height
                        logger.info(
                            f"Retrieved iOS screen dimensions: {device_width}x{device_height}"
                        )
                    else:
                        logger.warning("IDB screenshot returned None, using default dimensions")
                        device_width, device_height = 375, 812
                except Exception as e:
                    logger.warning(f"Failed to get iOS screen dimensions: {e}, using defaults")
                    device_width, device_height = 375, 812
            else:
                logger.warning("IDB client not available, using default dimensions")
                device_width, device_height = 375, 812

        return DeviceContext(
            host_platform="WINDOWS" if host_platform == "Windows" else "LINUX",
            mobile_platform=platform,
            device_id=device_id,
            device_width=device_width,
            device_height=device_height,
        )

    def _get_task_status_change_callback(
        self,
        task_info: PlatformTaskInfo,
        platform_service: PlatformService | None = None,
    ) -> Callable[[TaskRunStatus, str | None, Any | None], Coroutine]:
        service = platform_service or self._platform_service

        async def change_status(
            status: TaskRunStatus,
            message: str | None = None,
            output: Any | None = None,
        ):
            if not service:
                raise PlatformServiceUninitializedError()
            try:
                await service.update_task_run_status(
                    task_run_id=task_info.task_run.id,
                    status=status,
                    message=message,
                    output=output,
                )
            except Exception as e:
                logger.error(f"Failed to update task run status: {e}")

        return change_status

    def _get_plan_changes_callback(
        self,
        task_info: PlatformTaskInfo,
        platform_service: PlatformService | None = None,
    ) -> Callable[[list[Subgoal], IsReplan], Coroutine]:
        service = platform_service or self._platform_service
        current_plan: TaskRunPlanResponse | None = None

        async def update_plan(plan: list[Subgoal], is_replan: IsReplan):
            nonlocal current_plan

            if not service:
                raise PlatformServiceUninitializedError()
            try:
                if is_replan and current_plan:
                    # End previous plan
                    await service.upsert_task_run_plan(
                        task_run_id=task_info.task_run.id,
                        started_at=current_plan.started_at,
                        plan=plan,
                        ended_at=datetime.now(UTC),
                        plan_id=current_plan.id,
                    )
                    current_plan = None

                current_plan = await service.upsert_task_run_plan(
                    task_run_id=task_info.task_run.id,
                    started_at=current_plan.started_at if current_plan else datetime.now(UTC),
                    plan=plan,
                    ended_at=current_plan.ended_at if current_plan else None,
                    plan_id=current_plan.id if current_plan else None,
                )
            except Exception as e:
                logger.error(f"Failed to update plan: {e}")

        return update_plan

    def _get_new_agent_thought_callback(
        self,
        task_info: PlatformTaskInfo,
        platform_service: PlatformService | None = None,
    ) -> Callable[[AgentNode, str], Coroutine]:
        service = platform_service or self._platform_service

        async def add_agent_thought(agent: AgentNode, thought: str):
            if not service:
                raise PlatformServiceUninitializedError()
            try:
                await service.add_agent_thought(
                    task_run_id=task_info.task_run.id,
                    agent=agent,
                    thought=thought,
                )
            except Exception as e:
                logger.error(f"Failed to add agent thought: {e}")

        return add_agent_thought


def _validate_and_prepare_file(file_path: Path):
    path_obj = Path(file_path)
    if path_obj.exists() and path_obj.is_dir():
        raise AgentTaskRequestError(f"Error: Path '{file_path}' is a directory, not a file.")
    try:
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        path_obj.touch(exist_ok=True)
    except OSError as e:
        raise AgentTaskRequestError(f"Error creating file '{file_path}': {e}")


def print_ai_response_to_stderr(graph_result: State):
    for msg in reversed(graph_result.messages):
        if isinstance(msg, AIMessage):
            print(msg.content, file=sys.stderr)
            return
