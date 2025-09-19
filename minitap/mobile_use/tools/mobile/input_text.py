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
from minitap.mobile_use.utils.ui_hierarchy import (
    ElementBounds,
    find_element_by_resource_id,
    get_element_text,
)

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
        text_input_resource_id: str | None,
        text_input_coordinates: ElementBounds | None,
        text_input_text: str | None,
    ):
        """
        Focus a text field and type text into it.

        - Ensure the corresponding element is focused (tap if necessary).
        - If bounds are available, tap near the end to place the cursor at the end.
        - Type the provided `text` using the controller.

        Args:
            tool_call_id: The ID of the tool call.
            state: The state of the agent.
            agent_thought: The thought of the agent.
            text: The text to type.
            text_input_resource_id: The resource ID of the text input (if available).
            text_input_coordinates: The bounds (ElementBounds) of the text input (if available).
            text_input_text: The current text content of the text input (if available).
        """

        focused = focus_element_if_needed(
            ctx=ctx,
            input_resource_id=text_input_resource_id,
            input_coordinates=text_input_coordinates,
            input_text=text_input_text,
        )
        if not focused:
            error_message = "Failed to focus the text input element before typing."
            tool_message = ToolMessage(
                tool_call_id=tool_call_id,
                content=input_text_wrapper.on_failure_fn(text, error_message),
                additional_kwargs={"error": error_message},
                status="error",
            )
            return Command(
                update=state.sanitize_update(
                    ctx=ctx,
                    update={
                        "agents_thoughts": [agent_thought, error_message],
                        EXECUTOR_MESSAGES_KEY: [tool_message],
                    },
                    agent="executor",
                ),
            )

        move_cursor_to_end_if_bounds(
            ctx=ctx,
            state=state,
            text_input_resource_id=text_input_resource_id,
            text_input_coordinates=text_input_coordinates,
            text_input_text=text_input_text,
        )

        result = _controller_input_text(ctx=ctx, text=text)

        status: Literal["success", "error"] = "success" if result.ok else "error"

        text_input_content = ""
        if status == "success":
            if text_input_resource_id is not None:
                # Verification phase for elements with resource_id
                screen_data = get_screen_data(screen_api_client=ctx.screen_api_client)
                state.latest_ui_hierarchy = screen_data.elements

                element = find_element_by_resource_id(
                    ui_hierarchy=state.latest_ui_hierarchy, resource_id=text_input_resource_id
                )

                if not element:
                    result = InputResult(ok=False, error="Element not found")

                if element:
                    text_input_content = get_element_text(element)
            else:
                # For elements without resource_id, skip verification and use direct message
                pass

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


def _on_input_success(text, text_input_content, text_input_resource_id):
    """Success message handler for input text operations."""
    if text_input_resource_id is not None:
        return (
            f"Typed {repr(text)}.\n"
            f"Here is the whole content of input with id {repr(text_input_resource_id)}: "
            f"{repr(text_input_content)}"
        )
    else:
        return "Typed text, should now verify before moving forward"


input_text_wrapper = ToolWrapper(
    tool_fn_getter=get_input_text_tool,
    on_success_fn=_on_input_success,
    on_failure_fn=lambda text, error: f"Failed to input text {repr(text)}. Reason: {error}",
)
