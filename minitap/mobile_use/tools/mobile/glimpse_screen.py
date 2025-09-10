from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.mobile_command_controller import (
    take_screenshot as take_screenshot_controller,
)
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.tools.tool_wrapper import ToolWrapper
from minitap.mobile_use.utils.media import compress_base64_jpeg


def get_glimpse_screen_tool(ctx: MobileUseContext):
    @tool
    def glimpse_screen(
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
        agent_thought: str,
    ):
        """
        Your primary tool for visual perception. Call this to get an up-to-date
        image of the screen for immediate analysis. It is the most reliable way
        to confirm what is actually displayed, especially for visual elements like
        icons, images, or when the UI hierarchy seems ambiguous. The captured
        visual context is ephemeral and must be analyzed in the very next step.
        """
        compressed_image_base64 = None
        has_failed = False

        try:
            output = take_screenshot_controller(ctx=ctx)
            compressed_image_base64 = compress_base64_jpeg(output)
        except Exception as e:
            output = str(e)
            has_failed = True

        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=glimpse_screen_wrapper.on_failure_fn()
            if has_failed
            else glimpse_screen_wrapper.on_success_fn(),
            additional_kwargs={"error": output} if has_failed else {},
            status="error" if has_failed else "success",
        )
        updates = {
            "agents_thoughts": [agent_thought],
            EXECUTOR_MESSAGES_KEY: [tool_message],
        }
        if compressed_image_base64:
            updates["latest_screenshot_base64"] = compressed_image_base64
        return Command(
            update=state.sanitize_update(
                ctx=ctx,
                update=updates,
                agent="executor",
            ),
        )

    return glimpse_screen


glimpse_screen_wrapper = ToolWrapper(
    tool_fn_getter=get_glimpse_screen_tool,
    on_success_fn=lambda: (
        "Visual context captured successfully." + "It is now available for immediate analysis."
    ),
    on_failure_fn=lambda: "Failed to capture visual context.",
)
