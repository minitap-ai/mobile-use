from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from minitap.mobile_use.agents.hopper.hopper import HopperOutput, hopper
from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.platform_specific_commands_controller import list_packages
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.tools.tool_wrapper import ToolWrapper
from typing import Annotated


def get_find_packages_tool(ctx: MobileUseContext):
    @tool
    async def find_packages(
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
        appNames: list[str],
        agent_thought: str,
    ) -> Command:
        """
        Finds relevant applications.
        Outputs the full package names list (android) or bundle ids list (IOS).
        """
        output: str = list_packages(ctx=ctx)

        try:
            hopper_output: HopperOutput = await hopper(
                ctx=ctx,
                request=f"I'm looking for the package names of the following apps: {appNames}",
                data=output,
            )
            tool_message = ToolMessage(
                tool_call_id=tool_call_id,
                content=find_packages_wrapper.on_success_fn(
                    hopper_output.step, hopper_output.output
                ),
                status="success",
            )
        except Exception as e:
            print("Failed to extract insights from data: " + str(e))
            tool_message = ToolMessage(
                tool_call_id=tool_call_id,
                content=find_packages_wrapper.on_failure_fn(),
                additional_kwargs={"output": output},
                status="error",
            )

        return Command(
            update=state.sanitize_update(
                ctx=ctx,
                update={
                    "agents_thoughts": [agent_thought, tool_message.content],
                    EXECUTOR_MESSAGES_KEY: [tool_message],
                },
                agent="executor",
            ),
        )

    return find_packages


find_packages_wrapper = ToolWrapper(
    tool_fn_getter=get_find_packages_tool,
    on_success_fn=lambda thought, output: f"Packages found successfully ({thought}): {output}",
    on_failure_fn=lambda: "Failed to find packages.",
)
