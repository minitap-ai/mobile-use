from __future__ import annotations

from typing import Annotated, Literal

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel

from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.mobile_command_controller import (
    get_screen_data,
)
from minitap.mobile_use.controllers.mobile_command_controller import (
    input_text as input_text_controller,
)
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.tools.tool_wrapper import ToolWrapper
from minitap.mobile_use.tools.utils import focus_element_if_needed, move_cursor_to_end_if_bounds
from minitap.mobile_use.utils.logger import get_logger
from minitap.mobile_use.utils.ui_hierarchy import find_element_by_resource_id, get_element_text

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

        text_input_content = ""
        if status == "success":
            screen_data = get_screen_data(screen_api_client=ctx.screen_api_client)
            state.latest_ui_hierarchy = screen_data.elements

            element = find_element_by_resource_id(
                ui_hierarchy=state.latest_ui_hierarchy, resource_id=text_input_resource_id
            )

            if not element:
                result = InputResult(ok=False, error="Element not found")

            if element:
                text_input_content = get_element_text(element)

        agent_outcome = (
            input_text_wrapper.on_success_fn(text, text_input_content, text_input_resource_id)
            if result.ok
            else input_text_wrapper.on_failure_fn(text, result.error)
        )

        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=agent_outcome,
            additional_kwargs={"error": result.error} if not result.ok else {},
            status=status,
        )

        return Command(
            update=state.sanitize_update(
                ctx=ctx,
                update={
                    "agents_thoughts": [agent_thought, agent_outcome],
                    EXECUTOR_MESSAGES_KEY: [tool_message],
                },
                agent="executor",
            ),
        )

    return input_text


input_text_wrapper = ToolWrapper(
    tool_fn_getter=get_input_text_tool,
    on_success_fn=lambda text, text_input_content, text_input_resource_id: f"Typed {repr(text)}.\n"
    + f"Here is the whole content of input with id {repr(text_input_resource_id)} :"
    + f" {repr(text_input_content)}",
    on_failure_fn=lambda text, error: f"Failed to input text {repr(text)}. Reason: {error}",
)
