from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.unified_controller import UnifiedMobileController
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.tools.tool_wrapper import ToolWrapper
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


def get_dismiss_keyboard_tool(ctx: MobileUseContext):
    @tool
    async def dismiss_keyboard(
        agent_thought: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
    ) -> Command:
        """Safely dismiss/hide the on-screen keyboard if it is currently visible.

        This tool checks whether the keyboard is actually shown before taking action.
        On Android, it uses UI Automator 2 to detect keyboard visibility and only
        presses back if the keyboard is visible, preventing accidental navigation.

        Use this tool instead of 'back' when the intent is to close the keyboard,
        not to navigate to a previous screen.
        """
        controller = UnifiedMobileController(ctx)
        logger.info("dismiss_keyboard tool called")
        success = await controller.dismiss_keyboard()
        has_failed = not success

        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=(
                dismiss_keyboard_wrapper.on_failure_fn()
                if has_failed
                else dismiss_keyboard_wrapper.on_success_fn()
            ),
            additional_kwargs={"error": "Failed to dismiss keyboard"} if has_failed else {},
            status="error" if has_failed else "success",
        )
        return Command(
            update=await state.asanitize_update(
                ctx=ctx,
                update={
                    "agents_thoughts": [agent_thought],
                    EXECUTOR_MESSAGES_KEY: [tool_message],
                },
                agent="executor",
            ),
        )

    return dismiss_keyboard


dismiss_keyboard_wrapper = ToolWrapper(
    tool_fn_getter=get_dismiss_keyboard_tool,
    on_success_fn=lambda: "Keyboard dismissed successfully (or was already hidden).",
    on_failure_fn=lambda: "Failed to dismiss keyboard.",
)
