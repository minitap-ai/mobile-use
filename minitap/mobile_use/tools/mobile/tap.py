from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.mobile_command_controller import SelectorRequest
from minitap.mobile_use.controllers.mobile_command_controller import tap as tap_controller
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.tools.tool_wrapper import ToolWrapper
from typing import Annotated


def get_tap_tool(ctx: MobileUseContext):
    @tool
    def tap(
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
        agent_thought: str,
        selector_request: SelectorRequest,
        index: int | None = None,
    ):
        """
        Taps on a selector.
        Index is optional and is used when you have multiple views matching the same selector.
        """
        output = tap_controller(ctx=ctx, selector_request=selector_request, index=index)
        has_failed = output is not None
        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=tap_wrapper.on_failure_fn(selector_request, index)
            if has_failed
            else tap_wrapper.on_success_fn(selector_request, index),
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

    return tap


tap_wrapper = ToolWrapper(
    tool_fn_getter=get_tap_tool,
    on_success_fn=(
        lambda selector_request,
        index: f"Tap on {selector_request} {'at index {index}' if index else ''} is successful."
    ),
    on_failure_fn=(
        lambda selector_request,
        index: f"Failed to tap on {selector_request} {'at index {index}' if index else ''}."
    ),
)
