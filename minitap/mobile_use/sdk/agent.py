import asyncio
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
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
from minitap.mobile_use.clients.device_hardware_client import DeviceHardwareClient
from minitap.mobile_use.clients.screen_api_client import ScreenApiClient
from minitap.mobile_use.config import AgentNode, OutputConfig, record_events, settings
from minitap.mobile_use.context import (
    DeviceContext,
    DevicePlatform,
    ExecutionSetup,
    IsReplan,
    MobileUseContext,
)
from minitap.mobile_use.controllers.mobile_command_controller import (
    ScreenDataResponse,
    get_screen_data,
)
from minitap.mobile_use.controllers.platform_specific_commands_controller import get_first_device
from minitap.mobile_use.graph.graph import get_graph
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.sdk.builders.agent_config_builder import get_default_agent_config
from minitap.mobile_use.sdk.builders.task_request_builder import TaskRequestBuilder
from minitap.mobile_use.sdk.constants import DEFAULT_HW_BRIDGE_BASE_URL, DEFAULT_SCREEN_API_BASE_URL
from minitap.mobile_use.sdk.services.cloud_mobile import CloudMobileService
from minitap.mobile_use.sdk.services.platform import PlatformService
from minitap.mobile_use.sdk.types.agent import AgentConfig
from minitap.mobile_use.sdk.types.exceptions import (
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
from minitap.mobile_use.servers.device_hardware_bridge import BridgeStatus
from minitap.mobile_use.servers.start_servers import (
    start_device_hardware_bridge,
    start_device_screen_api,
)
from minitap.mobile_use.servers.stop_servers import stop_servers
from minitap.mobile_use.utils.app_lock_utils import _handle_initial_app_launch
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
    _is_default_screen_api: bool
    _is_default_hw_bridge: bool
    _device_context: DeviceContext
    _screen_api_client: ScreenApiClient
    _hw_bridge_client: DeviceHardwareClient
    _adb_client: AdbClient | None
    _current_task: asyncio.Task | None = None
    _task_lock: asyncio.Lock
    _cloud_mobile_id: str | None = None

    def __init__(self, *, config: AgentConfig | None = None):
        self._config = config or get_default_agent_config()
        self._tasks = []
        self._tmp_traces_dir = Path(tempfile.gettempdir()) / "mobile-use-traces"
        self._initialized = False
        self._is_default_hw_bridge = (
            self._config.servers.hw_bridge_base_url == DEFAULT_HW_BRIDGE_BASE_URL
        )
        self._is_default_screen_api = (
            self._config.servers.screen_api_base_url == DEFAULT_SCREEN_API_BASE_URL
        )
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

        if not which("adb") and not which("xcrun"):
            raise ExecutableNotFoundError("cli_tools")
        if self._is_default_hw_bridge and not which("maestro"):
            raise ExecutableNotFoundError("maestro")

        if self._initialized:
            logger.warning("Agent is already initialized. Skipping...")
            return True

        # Get first available device ID
        if not self._config.device_id or not self._config.device_platform:
            device_id, platform = get_first_device(logger=logger)
        else:
            device_id, platform = self._config.device_id, self._config.device_platform

        if not device_id or not platform:
            error_msg = "No device found. Exiting."
            logger.error(error_msg)
            raise DeviceNotFoundError(error_msg)

        # Initialize clients
        self._init_clients(
            platform=platform,
            retry_count=retry_count,
            retry_wait_seconds=retry_wait_seconds,
        )

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
                stop_servers(
                    should_stop_screen_api=self._is_default_screen_api,
                    should_stop_hw_bridge=self._is_default_hw_bridge,
                )
            else:
                error_msg = "Mobile-use servers failed to start after all restart attempts."
                logger.error(error_msg)
                raise ServerStartupError(message=error_msg)

        self._device_context = self._get_device_context(device_id=device_id, platform=platform)
        logger.info(self._device_context.to_str())
        logger.info("✅ Mobile-use agent initialized.")
        self._initialized = True
        return True

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
                    request=request, locked_app_package=locked_app_package
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
            except AgentTaskRequestError:
                # Re-raise known exceptions
                raise
            except Exception as e:
                logger.error(f"Unexpected error during cloud mobile task execution: {e}")
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
            hw_bridge_client=self._hw_bridge_client,
            screen_api_client=self._screen_api_client,
            adb_client=self._adb_client,
            llm_config=agent_profile.llm_config,
            on_agent_thought=on_agent_thought,
            on_plan_changes=on_plan_changes,
            minitap_api_key=api_key,
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
                raise
            except Exception as e:
                err = f"[{task_name}] Error running automation: {e}"
                logger.error(err)
                await task.finalize(
                    content=output,
                    state=last_state_snapshot,
                    error=err,
                )
                raise
            finally:
                self._finalize_tracing(task=task, context=context)

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

    def is_healthy(self):
        """
        Check if the agent is healthy by verifying the streaming connection status.
        Uses the configured Screen API base URL instead of hardcoding localhost.
        """
        try:
            # In cloud mode, local streaming health is irrelevant.
            if self._config.cloud_mobile_id_or_ref:
                return True
            response = self._screen_api_client.get_with_retry("/streaming-status", timeout=2)
            if response.status_code == 200:
                data = response.json()
                is_connected = data.get("is_streaming_connected", False)
                return is_connected
            return False
        except Exception:
            return False

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
            return
        if not self._initialized and not force:
            return
        screen_api_ok, hw_bridge_ok = stop_servers(
            should_stop_screen_api=self._is_default_screen_api,
            should_stop_hw_bridge=self._is_default_hw_bridge,
        )
        if not screen_api_ok:
            logger.warning("Failed to stop Device Screen API.")
        if not hw_bridge_ok:
            logger.warning("Failed to stop Device Hardware Bridge.")
        self._initialized = False
        logger.info("✅ Mobile-use agent stopped.")

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

    def _finalize_tracing(self, task: Task, context: MobileUseContext):
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
            focused_app_info=None,
            device_date=None,
            structured_decisions=None,
            complete_subgoals_by_ids=[],
            screen_analysis_prompt=None,
            agents_thoughts=[],
            remaining_steps=task.request.max_steps,
            executor_messages=[],
            cortex_last_thought=None,
        )

    def _init_clients(self, platform: DevicePlatform, retry_count: int, retry_wait_seconds: int):
        self._adb_client = (
            AdbClient(host=self._config.servers.adb_host, port=self._config.servers.adb_port)
            if platform == DevicePlatform.ANDROID
            else None
        )
        self._hw_bridge_client = DeviceHardwareClient(
            base_url=self._config.servers.hw_bridge_base_url.to_url(),
        )
        self._screen_api_client = ScreenApiClient(
            base_url=self._config.servers.screen_api_base_url.to_url(),
            retry_count=retry_count,
            retry_wait_seconds=retry_wait_seconds,
        )

    def _run_servers(self, device_id: str, platform: DevicePlatform) -> bool:
        if self._is_default_hw_bridge:
            bridge_instance = start_device_hardware_bridge(
                device_id=device_id,
                platform=platform,
                adb_host=self._config.servers.adb_host,
            )
            if not bridge_instance:
                logger.warning("Failed to start Device Hardware Bridge.")
                return False

            logger.info("Waiting for Device Hardware Bridge to connect to a device...")
            while True:
                status_info = bridge_instance.get_status()
                status = status_info.get("status")
                output = status_info.get("output")

                if status == BridgeStatus.RUNNING.value:
                    logger.success(
                        "Device Hardware Bridge is running. "
                        + f"Connected to device: {device_id} [{platform.value}]"
                    )
                    break

                failed_statuses = [
                    BridgeStatus.NO_DEVICE.value,
                    BridgeStatus.FAILED.value,
                    BridgeStatus.PORT_IN_USE.value,
                    BridgeStatus.STOPPED.value,
                ]
                if status in failed_statuses:
                    logger.error(
                        f"Device Hardware Bridge failed to connect. "
                        f"Status: {status} - Output: {output}"
                    )
                    return False

                time.sleep(1)

        # Start Device Screen API if not already running
        if self._is_default_screen_api:
            api_process = start_device_screen_api(use_process=True)
            if not api_process:
                logger.error("Failed to start Device Screen API. Exiting.")
                return False

        # Check API health
        if not self._check_device_screen_api_health():
            logger.error("Device Screen API health check failed. Stopping...")
            return False

        return True

    def _check_device_screen_api_health(self) -> bool:
        try:
            # Required to know if the Screen API is up
            self._screen_api_client.get_with_retry("/health", timeout=5)
            # Required to know if the Screen API actually receives screenshot from the HW Bridge API
            self._screen_api_client.get_with_retry("/screen-info", timeout=5)
            return True
        except Exception as e:
            logger.error(f"Device Screen API health check failed: {e}")
            return False

    def _get_device_context(
        self,
        device_id: str,
        platform: DevicePlatform,
    ) -> DeviceContext:
        from platform import system

        host_platform = system()
        screen_data: ScreenDataResponse = get_screen_data(self._screen_api_client)
        return DeviceContext(
            host_platform="WINDOWS" if host_platform == "Windows" else "LINUX",
            mobile_platform=platform,
            device_id=device_id,
            device_width=screen_data.width,
            device_height=screen_data.height,
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
