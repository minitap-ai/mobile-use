from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.mobile_command_controller import SelectorRequest
from minitap.mobile_use.controllers.mobile_command_controller import (
    long_press_on as long_press_on_controller,
)
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.tools.tool_wrapper import ToolWrapper
from typing import Annotated


def get_long_press_on_tool(ctx: MobileUseContext):
    @tool
    def long_press_on(
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
        agent_thought: str,
        selector_request: SelectorRequest,
        index: int | None = None,
    ):
        """
        Long press on a UI element identified by the given selector.
        An index can be specified to select a specific element if multiple are found.
        """
        output = long_press_on_controller(ctx=ctx, selector_request=selector_request, index=index)
        has_failed = output is not None
        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=long_press_on_wrapper.on_failure_fn()
            if has_failed
            else long_press_on_wrapper.on_success_fn(),
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

    return long_press_on


long_press_on_wrapper = ToolWrapper(
    tool_fn_getter=get_long_press_on_tool,
    on_success_fn=lambda: "Long press on is successful.",
    on_failure_fn=lambda: "Failed to long press on.",
)
