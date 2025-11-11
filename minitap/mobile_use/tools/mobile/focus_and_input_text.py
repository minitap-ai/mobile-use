from __future__ import annotations

from typing import Annotated, Literal

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel

from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.mobile_command_controller import get_screen_data
from minitap.mobile_use.controllers.mobile_command_controller import (
    input_text as input_text_controller,
)
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.tools.tool_wrapper import ToolWrapper
from minitap.mobile_use.tools.types import Target
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


def get_focus_and_input_text_tool(ctx: MobileUseContext) -> BaseTool:
    @tool
    async def focus_and_input_text(
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
        agent_thought: str,
        text: str,
        target: Target,
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
            target: The target of the text input (if available).
        """
        focus_method = focus_element_if_needed(ctx=ctx, target=target)
        if not focus_method:
            error_message = "Failed to focus the text input element before typing."
            tool_message = ToolMessage(
                tool_call_id=tool_call_id,
                content=focus_and_input_text_wrapper.on_failure_fn(text, error_message),
                additional_kwargs={"error": error_message},
                status="error",
            )
            return Command(
                update=await state.asanitize_update(
                    ctx=ctx,
                    update={
                        "agents_thoughts": [agent_thought, error_message],
                        EXECUTOR_MESSAGES_KEY: [tool_message],
                    },
                    agent="executor",
                ),
            )

        move_cursor_to_end_if_bounds(ctx=ctx, state=state, target=target)

        result = _controller_input_text(ctx=ctx, text=text)
        status: Literal["success", "error"] = "success" if result.ok else "error"

        text_input_content = ""
        if status == "success" and target.resource_id:
            screen_data = get_screen_data(screen_api_client=ctx.screen_api_client)
            state.latest_ui_hierarchy = screen_data.elements
            element = find_element_by_resource_id(
                ui_hierarchy=state.latest_ui_hierarchy,
                resource_id=target.resource_id,
                index=target.resource_id_index,
            )
            if element:
                text_input_content = get_element_text(element)

        agent_outcome = (
            focus_and_input_text_wrapper.on_success_fn(
                text_to_type=text,
                text_from_resource_id=text_input_content,
                target_resource_id=target.resource_id,
                focus_method=focus_method,
            )
            if result.ok
            else focus_and_input_text_wrapper.on_failure_fn(text_to_type=text, error=result.error)
        )

        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=agent_outcome,
            additional_kwargs={"error": result.error} if not result.ok else {},
            status=status,
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

    return focus_and_input_text


def _on_input_success(text_to_type, text_from_resource_id, target_resource_id, focus_method):
    """Success message handler for input text operations."""
    if focus_method == "resource_id":
        return (
            f"Typed {repr(text_to_type)}\n"
            f"Here is the whole content of input with id {repr(target_resource_id)}: "
            f"{repr(text_from_resource_id)}"
        )
    else:
        return (
            f"Typed {repr(text_to_type)} using {focus_method}."
            + " Should now verify before moving forward."
        )


focus_and_input_text_wrapper = ToolWrapper(
    tool_fn_getter=get_focus_and_input_text_tool,
    on_success_fn=_on_input_success,
    on_failure_fn=lambda text, error: f"Failed to input text {repr(text)}. Reason: {error}",
)
