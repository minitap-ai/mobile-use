from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.unified_controller import UnifiedMobileController
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.tools.tool_wrapper import ToolWrapper


def get_stop_app_tool(ctx: MobileUseContext):
    @tool
    async def stop_app(
        agent_thought: str,
        package_name: str | None = None,
        tool_call_id: Annotated[str, InjectedToolCallId] = None,  # type: ignore
        state: Annotated[State, InjectedState] = None,  # type: ignore
    ) -> Command:
        """
        Stops current application if it is running.
        You can also specify the package name of the app to be stopped.
        """
        controller = UnifiedMobileController(ctx)
        success = await controller.terminate_app(package_name)
        has_failed = not success
        output = "Failed to terminate app" if has_failed else None

        agent_outcome = (
            stop_app_wrapper.on_failure_fn(package_name)
            if has_failed
            else stop_app_wrapper.on_success_fn(package_name)
        )
        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=agent_outcome,
            additional_kwargs={"error": output} if has_failed else {},
            status="error" if has_failed else "success",
        )
        return Command(
            update=await state.asanitize_update(
                ctx=ctx,
                update={
                    "agents_thoughts": [agent_thought, agent_outcome],
                    EXECUTOR_MESSAGES_KEY: [tool_message],
                },
                agent="executor",
            ),
        )

    return stop_app


stop_app_wrapper = ToolWrapper(
    tool_fn_getter=get_stop_app_tool,
    on_success_fn=lambda package_name: f"App {package_name or 'current'} stopped successfully.",
    on_failure_fn=lambda package_name: f"Failed to stop app {package_name or 'current'}.",
)
