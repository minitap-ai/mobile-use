from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.types import Command
from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.controllers.mobile_command_controller import (
    launch_app as launch_app_controller,
)
from minitap.mobile_use.tools.tool_wrapper import ToolWrapper
from typing import Annotated
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.graph.state import State
from langgraph.prebuilt import InjectedState


def get_launch_app_tool(ctx: MobileUseContext):
    @tool
    def launch_app(
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
        agent_thought: str,
        package_name: str,
    ):
        """
        Launch an application on the device using the package name on Android, bundle id on iOS.
        """
        output = launch_app_controller(ctx=ctx, package_name=package_name)
        has_failed = output is not None
        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=launch_app_wrapper.on_failure_fn(package_name)
            if has_failed
            else launch_app_wrapper.on_success_fn(package_name),
            additional_kwargs={"error": output} if has_failed else {},
            status="error" if has_failed else "success",
        )
        return Command(
            update=state.sanitize_update(
                ctx=ctx,
                update={
                    "agents_thoughts": [agent_thought],
                    EXECUTOR_MESSAGES_KEY: [tool_message],
                },
                agent="executor",
            ),
        )

    return launch_app


launch_app_wrapper = ToolWrapper(
    tool_fn_getter=get_launch_app_tool,
    on_success_fn=lambda package_name: f"App {package_name} launched successfully.",
    on_failure_fn=lambda package_name: f"Failed to launch app {package_name}.",
)
