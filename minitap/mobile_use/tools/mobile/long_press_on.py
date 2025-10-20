from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import BaseTool, InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.mobile_command_controller import (
    CoordinatesSelectorRequest,
    IdSelectorRequest,
    SelectorRequestWithCoordinates,
    TextSelectorRequest,
)
from minitap.mobile_use.controllers.mobile_command_controller import (
    long_press_on as long_press_on_controller,
)
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.tools.tool_wrapper import ToolWrapper
from minitap.mobile_use.tools.types import Target
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


def get_long_press_on_tool(ctx: MobileUseContext) -> BaseTool:
    @tool
    async def long_press_on(
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
        agent_thought: str,
        target: Target,
        duration_ms: int = 1000,
    ):
        """
        Long presses on a UI element identified by the 'target' object.

        The 'target' object allows specifying an element by its resource_id
        (with an optional index), its coordinates, or its text content (with an optional index).
        The tool uses a fallback strategy, trying the locators in that order.

        Args:
            target: The UI element to long press on (coordinates, resource_id, or text).
            duration_ms: Duration of the long press in milliseconds. Choose based on interaction:
                        - 500-800ms: Quick long press (e.g., selecting text, haptic feedback)
                        - 1000ms (default): Standard long press (most common use case)
                        - 1500-2000ms: Extended long press (e.g., context menus, special actions)
                        - 2500ms+: Very long press (e.g., accessibility, advanced gestures)
        """
        error_obj: dict | None = {
            "error": "No valid selector provided or all selectors failed."
        }  # Default to failure
        latest_selector_info: str | None = None

        # 1. Try with COORDINATES FIRST (visual approach)
        if target.coordinates:
            try:
                center_point = target.coordinates.get_center()
                selector = SelectorRequestWithCoordinates(
                    coordinates=CoordinatesSelectorRequest(x=center_point.x, y=center_point.y)
                )
                logger.info(
                    f"Attempting to long press using coordinates: {center_point.x},{center_point.y}"
                )
                latest_selector_info = f"coordinates='{target.coordinates}'"
                result = long_press_on_controller(
                    ctx=ctx,
                    selector_request=selector,
                    ui_hierarchy=state.latest_ui_hierarchy,
                    long_press_duration=duration_ms,
                )
                if result is None:  # Success
                    error_obj = None
                else:
                    logger.warning(
                        f"Long press with coordinates '{target.coordinates}' failed. "
                        f"Error: {result}"
                    )
                    error_obj = {"error": result} if isinstance(result, str) else result
            except Exception as e:
                logger.warning(
                    f"Exception during long press with coordinates '{target.coordinates}': {e}"
                )
                error_obj = {"error": str(e)}

        # 2. If coordinates failed or weren't provided, try with resource_id
        if error_obj is not None and target.resource_id:
            try:
                selector = IdSelectorRequest(id=target.resource_id)
                logger.info(
                    f"Attempting to long press using resource_id: '{target.resource_id}' "
                    f"at index {target.resource_id_index}"
                )
                latest_selector_info = (
                    f"resource_id='{target.resource_id}' (index={target.resource_id_index})"
                )
                result = long_press_on_controller(
                    ctx=ctx,
                    selector_request=selector,
                    index=target.resource_id_index,
                    ui_hierarchy=state.latest_ui_hierarchy,
                    long_press_duration=duration_ms,
                )
                if result is None:  # Success
                    error_obj = None
                else:
                    logger.warning(
                        f"Long press with resource_id '{target.resource_id}' failed. "
                        f"Error: {result}"
                    )
                    error_obj = {"error": result} if isinstance(result, str) else result
            except Exception as e:
                logger.warning(
                    f"Exception during long press with resource_id '{target.resource_id}': {e}"
                )
                error_obj = {"error": str(e)}

        # 3. If resource_id failed or wasn't provided, try with text (last resort)
        if error_obj is not None and target.text:
            try:
                selector = TextSelectorRequest(text=target.text)
                logger.info(
                    f"Attempting to long press using text: '{target.text}' "
                    f"at index {target.text_index}"
                )
                latest_selector_info = f"text='{target.text}' (index={target.text_index})"
                result = long_press_on_controller(
                    ctx=ctx,
                    selector_request=selector,
                    index=target.text_index,
                    ui_hierarchy=state.latest_ui_hierarchy,
                    long_press_duration=duration_ms,
                )
                if result is None:  # Success
                    error_obj = None
                else:
                    logger.warning(f"Long press with text '{target.text}' failed. Error: {result}")
                    error_obj = {"error": result} if isinstance(result, str) else result
            except Exception as e:
                logger.warning(f"Exception during long press with text '{target.text}': {e}")
                error_obj = {"error": str(e)}

        has_failed = error_obj is not None
        final_selector_info = latest_selector_info if latest_selector_info else "N/A"
        agent_outcome = (
            long_press_on_wrapper.on_failure_fn(final_selector_info)
            if has_failed
            else long_press_on_wrapper.on_success_fn(final_selector_info)
        )

        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=agent_outcome,
            additional_kwargs=error_obj if has_failed else {},
            status="error" if has_failed else "success",
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

    return long_press_on


long_press_on_wrapper = ToolWrapper(
    tool_fn_getter=get_long_press_on_tool,
    on_success_fn=lambda selector_info: (
        f"Long press on element with {selector_info} was successful."
    ),
    on_failure_fn=lambda selector_info: "Failed to long press on element. "
    + f"Last attempt was with {selector_info}.",
)
