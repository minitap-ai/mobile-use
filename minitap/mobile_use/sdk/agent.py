import asyncio
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from shutil import which
from types import NoneType
from typing import TypeVar, overload

from adbutils import AdbClient
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from minitap.mobile_use.agents.outputter.outputter import outputter
from minitap.mobile_use.clients.device_hardware_client import DeviceHardwareClient
from minitap.mobile_use.clients.screen_api_client import ScreenApiClient
from minitap.mobile_use.config import OutputConfig, record_events
from minitap.mobile_use.context import (
    DeviceContext,
    DevicePlatform,
    ExecutionSetup,
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
from minitap.mobile_use.sdk.constants import (
    DEFAULT_HW_BRIDGE_BASE_URL,
    DEFAULT_SCREEN_API_BASE_URL,
)
from minitap.mobile_use.sdk.types.agent import AgentConfig
from minitap.mobile_use.sdk.types.exceptions import (
    AgentNotInitializedError,
    AgentProfileNotFoundError,
    AgentTaskRequestError,
    DeviceNotFoundError,
    ExecutableNotFoundError,
    ServerStartupError,
)
from minitap.mobile_use.sdk.types.task import AgentProfile, Task, TaskRequest, TaskStatus
from minitap.mobile_use.servers.device_hardware_bridge import BridgeStatus
from minitap.mobile_use.servers.start_servers import (
    start_device_hardware_bridge,
    start_device_screen_api,
)
from minitap.mobile_use.servers.stop_servers import stop_servers
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

    def __init__(self, config: AgentConfig | None = None):
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

    def init(
        self,
        server_restart_attempts: int = 3,
        retry_count: int = 5,
        retry_wait_seconds: int = 5,
    ):
        if not which("adb") and not which("xcrun"):
            raise ExecutableNotFoundError("cli_tools")
        if self._is_default_hw_bridge and not which("maestro"):
            raise ExecutableNotFoundError("maestro")

        if self._initialized:
            logger.warning("Agent is already initialized. Skipping...")
            return True

        # Get first available device ID
        if not self._config.device_id or not self._config.device_platform:
            device_id, platform = get_first_device()
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
    ) -> TOutput | None: ...

    @overload
    async def run_task(
        self,
        *,
        goal: str,
        output: str,
        profile: str | AgentProfile | None = None,
        name: str | None = None,
    ) -> str | dict | None: ...

    @overload
    async def run_task(
        self,
        *,
        goal: str,
        output=None,
        profile: str | AgentProfile | None = None,
        name: str | None = None,
    ) -> str | None: ...

    @overload
    async def run_task(self, *, request: TaskRequest[None]) -> str | dict | None: ...

    @overload
    async def run_task(self, *, request: TaskRequest[TOutput]) -> TOutput | None: ...

    async def run_task(
        self,
        *,
        goal: str | None = None,
        output: type[TOutput] | str | None = None,
        profile: str | AgentProfile | None = None,
        name: str | None = None,
        request: TaskRequest[TOutput] | None = None,
    ) -> str | dict | TOutput | None:
        if request is not None:
            return await self._run_task(request)
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
        return await self._run_task(task_request.build())

    async def _run_task(self, request: TaskRequest[TOutput]) -> str | dict | TOutput | None:
        if not self._initialized:
            raise AgentNotInitializedError()

        if request.profile:
            agent_profile = self._config.agent_profiles.get(request.profile)
            if agent_profile is None:
                raise AgentProfileNotFoundError(request.profile)
        else:
            agent_profile = self._config.default_profile
        logger.info(str(agent_profile))

        task = Task(
            id=str(uuid.uuid4()),
            device=self._device_context,
            status=TaskStatus.PENDING,
            request=request,
            created_at=datetime.now(),
        )
        self._tasks.append(task)
        task_name = task.get_name()

        context = MobileUseContext(
            device=self._device_context,
            hw_bridge_client=self._hw_bridge_client,
            screen_api_client=self._screen_api_client,
            adb_client=self._adb_client,
            llm_config=agent_profile.llm_config,
        )

        self._prepare_tracing(task=task, context=context)
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

        last_state: State | None = None
        last_state_snapshot: dict | None = None
        output = None
        try:
            logger.info(f"[{task_name}] Invoking graph with input: {graph_input}")
            task.status = TaskStatus.RUNNING
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
                task.finalize(content=output, state=last_state_snapshot, error=err)
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
            task.finalize(content=output, state=last_state_snapshot)
        except asyncio.CancelledError:
            err = f"[{task_name}] Task cancelled"
            logger.warning(err)
            task.finalize(content=output, state=last_state_snapshot, error=err, cancelled=True)
            raise
        except Exception as e:
            err = f"[{task_name}] Error running automation: {e}"
            logger.error(err)
            task.finalize(content=output, state=last_state_snapshot, error=err)
            raise
        finally:
            self._finalize_tracing(task=task, context=context)
        return output

    def clean(self, force: bool = False):
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

    def _prepare_tracing(self, task: Task, context: MobileUseContext):
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
            traces_path=self._tmp_traces_dir, trace_id=task_name
        )

    def _finalize_tracing(self, task: Task, context: MobileUseContext):
        exec_setup_ctx = context.execution_setup
        if not exec_setup_ctx:
            return

        task_name = task.get_name()
        status = "_PASS" if task.status == TaskStatus.COMPLETED else "_FAIL"
        ts = task.created_at.strftime("%Y-%m-%dT%H-%M-%S")
        new_name = f"{exec_setup_ctx.trace_id}{status}_{ts}"

        temp_trace_path = (self._tmp_traces_dir / exec_setup_ctx.trace_id).resolve()
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
            latest_screenshot_base64=None,
            focused_app_info=None,
            device_date=None,
            structured_decisions=None,
            complete_subgoals_by_ids=[],
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
            bridge_instance = start_device_hardware_bridge(device_id=device_id, platform=platform)
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
