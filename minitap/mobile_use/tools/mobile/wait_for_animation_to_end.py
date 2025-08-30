from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.mobile_command_controller import WaitTimeout
from minitap.mobile_use.controllers.mobile_command_controller import (
    wait_for_animation_to_end as wait_for_animation_to_end_controller,
)
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.tools.tool_wrapper import ToolWrapper
from typing import Annotated


def get_wait_for_animation_to_end_tool(ctx: MobileUseContext):
    @tool
    def wait_for_animation_to_end(
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
        agent_thought: str,
        timeout: WaitTimeout | None,
    ):
        """
        Waits for ongoing animations or videos to finish before continuing.

        If a `timeout` (in milliseconds) is set, the command proceeds after the timeout even if
        the animation hasn't ended.
        The flow continues immediately once the animation is detected as complete.

        Example:
            - waitForAnimationToEnd
            - waitForAnimationToEnd: { timeout: 5000 }
        """
        output = wait_for_animation_to_end_controller(ctx=ctx, timeout=timeout)
        has_failed = output is not None
        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=wait_for_animation_to_end_wrapper.on_failure_fn()
            if has_failed
            else wait_for_animation_to_end_wrapper.on_success_fn(timeout),
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

    return wait_for_animation_to_end


wait_for_animation_to_end_wrapper = ToolWrapper(
    tool_fn_getter=get_wait_for_animation_to_end_tool,
    on_success_fn=lambda: "Animation ended successfully.",
    on_failure_fn=lambda: "Failed to end animation.",
)
