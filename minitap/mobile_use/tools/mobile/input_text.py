from __future__ import annotations

from typing import Literal

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel
from typing_extensions import Annotated

from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.mobile_command_controller import (
    input_text as input_text_controller,
)
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.tools.tool_wrapper import ToolWrapper
from minitap.mobile_use.tools.utils import focus_element_if_needed, move_cursor_to_end_if_bounds
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


class InputResult(BaseModel):
    """Result of an input operation from the controller layer."""

    ok: bool
    error: str | None = None


def _controller_input_text(ctx: MobileUseContext, text: str) -> InputResult:
    """
    Thin wrapper to normalize the controller result.
    """
    controller_out = input_text_controller(ctx=ctx, text=text)
    if controller_out is None:
        return InputResult(ok=True)
    return InputResult(ok=False, error=str(controller_out))


def get_input_text_tool(ctx: MobileUseContext):
    @tool
    def input_text(
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
        agent_thought: str,
        text: str,
        text_input_resource_id: str,
    ):
        """
        Focus a text field and type text into it.

        - Ensure the corresponding element is focused (tap if necessary).
        - If bounds are available, tap near the end to place the cursor at the end.
        - Type the provided `text` using the controller.
        """
        focused = focus_element_if_needed(ctx=ctx, resource_id=text_input_resource_id)
        if focused:
            move_cursor_to_end_if_bounds(ctx=ctx, state=state, resource_id=text_input_resource_id)

        result = _controller_input_text(ctx=ctx, text=text)

        status: Literal["success", "error"] = "success" if result.ok else "error"
        content_msg = (
            input_text_wrapper.on_success_fn(text)
            if result.ok
            else input_text_wrapper.on_failure_fn(text)
        )

        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=content_msg,
            additional_kwargs={"error": result.error} if not result.ok else {},
            status=status,
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

    return input_text


input_text_wrapper = ToolWrapper(
    tool_fn_getter=get_input_text_tool,
    on_success_fn=lambda text: f"Successfully typed {text}",
    on_failure_fn=lambda text: f"Failed to input text {text}",
)
