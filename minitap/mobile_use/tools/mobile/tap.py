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
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


def get_tap_tool(ctx: MobileUseContext) -> BaseTool:
    @tool
    async def tap(
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
        agent_thought: str,
        target: Target,
    ):
        """
        Taps on a UI element identified by the 'target' object.

        The 'target' object allows specifying an element by its resource_id
        (with an optional index), its coordinates, or its text content (with an optional index).
        The tool uses a fallback strategy, trying the locators in that order.
        """
        output = {
            "error": "No valid selector provided or all selectors failed."
        }  # Default to failure
        latest_selector_info: str | None = None

        controller = UnifiedMobileController(ctx)

        # 1. Try with COORDINATES FIRST (visual approach)
        if target.coordinates:
            try:
                center_point = target.coordinates.get_center()
                logger.info(
                    f"Attempting to tap using coordinates: {center_point.x},{center_point.y}"
                )
                latest_selector_info = f"coordinates='{target.coordinates}'"
                result = await controller.tap_at(x=center_point.x, y=center_point.y)
                if result.error is None:  # Success
                    output = None
                else:
                    logger.warning(
                        f"Tap with coordinates '{target.coordinates}' failed. Error: {result.error}"
                    )
                    output = {"error": result.error}
            except Exception as e:
                logger.warning(f"Exception during tap with coordinates '{target.coordinates}': {e}")
                output = {"error": str(e)}

        # 2. If coordinates failed or weren't provided, try with resource_id
        if output is not None and target.resource_id:
            try:
                logger.info(
                    f"Attempting to tap using resource_id: '{target.resource_id}' "
                    f"at index {target.resource_id_index}"
                )
                latest_selector_info = (
                    f"resource_id='{target.resource_id}' (index={target.resource_id_index})"
                )
                result = await controller.tap_element(
                    resource_id=target.resource_id,
                    index=target.resource_id_index or 0,
                )
                if result.error is None:  # Success
                    output = None
                else:
                    logger.warning(
                        f"Tap with resource_id '{target.resource_id}' failed. Error: {result.error}"
                    )
                    output = {"error": result.error}
            except Exception as e:
                logger.warning(f"Exception during tap with resource_id '{target.resource_id}': {e}")
                output = {"error": str(e)}

        # 3. If resource_id failed or wasn't provided, try with text (last resort)
        if output is not None and target.text:
            try:
                logger.info(
                    f"Attempting to tap using text: '{target.text}' at index {target.text_index}"
                )
                latest_selector_info = f"text='{target.text}' (index={target.text_index})"
                result = await controller.tap_element(
                    text=target.text,
                    index=target.text_index or 0,
                )
                if result.error is None:  # Success
                    output = None
                else:
                    logger.warning(f"Tap with text '{target.text}' failed. Error: {result.error}")
                    output = {"error": result.error}
            except Exception as e:
                logger.warning(f"Exception during tap with text '{target.text}': {e}")
                output = {"error": str(e)}

        has_failed = output is not None
        final_selector_info = latest_selector_info if latest_selector_info else "N/A"
        agent_outcome = (
            tap_wrapper.on_failure_fn(final_selector_info)
            if has_failed
            else tap_wrapper.on_success_fn(final_selector_info)
        )

        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=agent_outcome,
            additional_kwargs={"error": output} if has_failed else {},
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

    return tap


tap_wrapper = ToolWrapper(
    tool_fn_getter=get_tap_tool,
    on_success_fn=lambda selector_info: f"Tap on element with {selector_info} was successful.",
    on_failure_fn=lambda selector_info: "Failed to tap on element. "
    + f"Last attempt was with {selector_info}.",
)
