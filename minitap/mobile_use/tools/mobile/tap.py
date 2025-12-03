from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import BaseTool, InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.unified_controller import UnifiedMobileController
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.tools.tool_wrapper import ToolWrapper
from minitap.mobile_use.tools.types import Target
from minitap.mobile_use.tools.utils import has_valid_selectors, validate_coordinates_bounds
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


def get_tap_tool(ctx: MobileUseContext) -> BaseTool:
    @tool
    async def tap(
        agent_thought: str,
        target: Target,
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
    ):
        """
        Taps on a UI element identified by the 'target' object.

        The 'target' object allows specifying an element by its resource_id
        (with an optional index), its coordinates, or its text content (with an optional index).
        The tool uses a fallback strategy, trying the locators in that order.
        """
        # Track all attempts for better error reporting
        attempts: list[dict] = []
        success = False
        successful_selector: str | None = None

        # Validate target has at least one selector
        if not has_valid_selectors(target):
            attempts.append(
                {
                    "selector": "none",
                    "error": "No valid selector provided (need coordinates, resource_id, or text)",
                }
            )

        controller = UnifiedMobileController(ctx)

        # 1. Try with COORDINATES FIRST (visual approach)
        if not success and target.coordinates:
            center = target.coordinates.get_center()
            selector_info = f"coordinates ({center.x}, {center.y})"

            # Validate bounds before attempting
            bounds_error = validate_coordinates_bounds(
                target, ctx.device.device_width, ctx.device.device_height
            )
            if bounds_error:
                logger.warning(f"Coordinates out of bounds: {bounds_error}")
                attempts.append(
                    {"selector": selector_info, "error": f"Out of bounds: {bounds_error}"}
                )
            else:
                try:
                    center_point = target.coordinates.get_center()
                    logger.info(f"Attempting tap with {selector_info}")
                    result = await controller.tap_at(x=center_point.x, y=center_point.y)
                    if result.error is None:
                        success = True
                        successful_selector = selector_info
                    else:
                        error_msg = result.error
                        logger.warning(f"Tap with {selector_info} failed: {error_msg}")
                        attempts.append({"selector": selector_info, "error": error_msg})
                except Exception as e:
                    logger.warning(f"Exception during tap with {selector_info}: {e}")
                    attempts.append({"selector": selector_info, "error": str(e)})

        # 2. If coordinates failed or weren't provided, try with resource_id
        if not success and target.resource_id:
            selector_info = f"resource_id='{target.resource_id}' (index={target.resource_id_index})"
            try:
                logger.info(f"Attempting tap with {selector_info}")
                result = await controller.tap_element(
                    resource_id=target.resource_id,
                    index=target.resource_id_index or 0,
                )
                if result.error is None:
                    success = True
                    successful_selector = selector_info
                else:
                    error_msg = result.error
                    logger.warning(f"Tap with {selector_info} failed: {error_msg}")
                    attempts.append({"selector": selector_info, "error": error_msg})
            except Exception as e:
                logger.warning(f"Exception during tap with {selector_info}: {e}")
                attempts.append({"selector": selector_info, "error": str(e)})

        # 3. If resource_id failed or wasn't provided, try with text (last resort)
        if not success and target.text:
            selector_info = f"text='{target.text}' (index={target.text_index})"
            try:
                logger.info(f"Attempting tap with {selector_info}")
                result = await controller.tap_element(
                    text=target.text,
                    index=target.text_index or 0,
                )
                if result.error is None:
                    success = True
                    successful_selector = selector_info
                else:
                    error_msg = result.error
                    logger.warning(f"Tap with {selector_info} failed: {error_msg}")
                    attempts.append({"selector": selector_info, "error": error_msg})
            except Exception as e:
                logger.warning(f"Exception during tap with {selector_info}: {e}")
                attempts.append({"selector": selector_info, "error": str(e)})

        # Build result message
        if success:
            agent_outcome = tap_wrapper.on_success_fn(successful_selector)
        else:
            # Build detailed failure message with all attempts
            failure_details = "; ".join([f"{a['selector']}: {a['error']}" for a in attempts])
            agent_outcome = tap_wrapper.on_failure_fn(failure_details)

        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=agent_outcome,
            additional_kwargs={"attempts": attempts} if not success else {},
            status="success" if success else "error",
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

    return tap


tap_wrapper = ToolWrapper(
    tool_fn_getter=get_tap_tool,
    on_success_fn=lambda selector_info: f"Tap on element with {selector_info} was successful.",
    on_failure_fn=lambda failure_details: f"Failed to tap on element. Attempts: {failure_details}",
)
