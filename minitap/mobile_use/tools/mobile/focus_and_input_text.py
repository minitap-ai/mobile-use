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
from minitap.mobile_use.controllers.controller_factory import create_device_controller
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


async def _controller_input_text(ctx: MobileUseContext, text: str) -> InputResult:
    """
    Thin wrapper to normalize the controller result.
    """
    controller = create_device_controller(ctx)
    success = await controller.input_text(text)
    if success:
        return InputResult(ok=True)
    return InputResult(ok=False, error="Failed to type text")


def get_focus_and_input_text_tool(ctx: MobileUseContext) -> BaseTool:
    @tool
    async def focus_and_input_text(
        agent_thought: str,
        text: str,
        target: Target,
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
    ):
        """
        Focus a text field and type text into it.

        - Ensure the corresponding element is focused (tap if necessary).
        - If bounds are available, tap near the end to place the cursor at the end.
        - Type the provided `text` using the controller.

        Args:
            agent_thought: The thought of the agent.
            text: The text to type.
            target: The target of the text input (if available).
        """
        # Get ablation config to determine execution mode
        ablation_config = ctx.get_ablation_config()
        use_deterministic = ablation_config.use_deterministic_text
        use_validation = ablation_config.use_post_validation

        focus_method: str | None = None
        
        if use_deterministic:
            # PRODUCTION MODE: Deterministic state machine
            # Step 1: Focus the element
            focus_method = await focus_element_if_needed(ctx=ctx, target=target)
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

            # Step 2: Move cursor to end
            await move_cursor_to_end_if_bounds(ctx=ctx, state=state, target=target)
        else:
            # ABLATION BASELINE MODE: Simple direct input
            # Just tap on the target without sophisticated focus handling
            logger.warning("Using SIMPLE text input mode (ablation baseline)")
            if target.bounds:
                controller = create_device_controller(ctx)
                center = target.bounds.get_center()
                await controller.tap_at(center.x, center.y)
                focus_method = "simple_tap"
            elif target.resource_id:
                # Try a simple tap by resource_id without verification
                from minitap.mobile_use.controllers.unified_controller import UnifiedMobileController
                controller = UnifiedMobileController(ctx)
                await controller.tap_element(resource_id=target.resource_id, index=target.resource_id_index or 0)
                focus_method = "simple_tap"
            else:
                focus_method = "none"

        # Step 3: Type the text
        result = await _controller_input_text(ctx=ctx, text=text)
        status: Literal["success", "error"] = "success" if result.ok else "error"

        text_input_content = ""
        if use_validation and status == "success" and target.resource_id:
            # PRODUCTION MODE: Post-validation - verify text was entered
            controller = create_device_controller(ctx)
            screen_data = await controller.get_screen_data()
            state.latest_ui_hierarchy = screen_data.elements
            element = find_element_by_resource_id(
                ui_hierarchy=state.latest_ui_hierarchy,
                resource_id=target.resource_id,
                index=target.resource_id_index,
            )
            if element:
                text_input_content = get_element_text(element)
        elif not use_validation:
            # ABLATION BASELINE MODE: No validation, just report success
            logger.warning("Skipping post-input validation (ablation baseline)")
            text_input_content = f"(validation skipped) {text}"

        agent_outcome = (
            focus_and_input_text_wrapper.on_success_fn(
                text_to_type=text,
                text_from_resource_id=text_input_content,
                target_resource_id=target.resource_id,
                focus_method=focus_method or "unknown",
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
