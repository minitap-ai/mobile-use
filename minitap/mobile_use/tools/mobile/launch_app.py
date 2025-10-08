from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from minitap.mobile_use.agents.hopper.hopper import HopperOutput, hopper
from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.mobile_command_controller import (
    launch_app as launch_app_controller,
)
from minitap.mobile_use.controllers.platform_specific_commands_controller import list_packages
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.tools.tool_wrapper import ToolWrapper


async def find_package(ctx: MobileUseContext, app_name: str) -> str | None:
    """
    Finds the package name for a given application name.
    """
    all_packages = list_packages(ctx=ctx)
    try:
        hopper_output: HopperOutput = await hopper(
            ctx=ctx,
            request=f"I'm looking for the package name of the following app: '{app_name}'",
            data=all_packages,
        )
        # Assuming hopper_output.output directly contains the package name
        return hopper_output.output
    except Exception as e:
        print(f"Failed to find package for '{app_name}': {e}")
        return None


def get_launch_app_tool(ctx: MobileUseContext):
    @tool
    async def launch_app(
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
        app_name: str,
        agent_thought: str,
    ) -> Command:
        """
        Finds and launches an application on the device using its natural language name.
        """
        package_name = await find_package(ctx=ctx, app_name=app_name)

        if not package_name:
            tool_message = ToolMessage(
                tool_call_id=tool_call_id,
                content=launch_app_wrapper.on_failure_fn(app_name, "Package not found."),
                status="error",
            )
        else:
            output = launch_app_controller(ctx=ctx, package_name=package_name)
            has_failed = output is not None
            tool_message = ToolMessage(
                tool_call_id=tool_call_id,
                content=launch_app_wrapper.on_failure_fn(app_name, output)
                if has_failed
                else launch_app_wrapper.on_success_fn(app_name),
                additional_kwargs={"error": output} if has_failed else {},
                status="error" if has_failed else "success",
            )

        return Command(
            update=await state.asanitize_update(
                ctx=ctx,
                update={
                    "agents_thoughts": [agent_thought, tool_message.content],
                    EXECUTOR_MESSAGES_KEY: [tool_message],
                },
                agent="executor",
            ),
        )

    return launch_app


launch_app_wrapper = ToolWrapper(
    tool_fn_getter=get_launch_app_tool,
    on_success_fn=lambda app_name: f"App '{app_name}' launched successfully.",
    on_failure_fn=lambda app_name, error: f"Failed to launch app '{app_name}': {error}",
)
