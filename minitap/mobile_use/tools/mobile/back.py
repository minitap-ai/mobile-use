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


def get_back_tool(ctx: MobileUseContext):
    @tool
    async def back(
        agent_thought: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
    ) -> Command:
        """Navigates to the previous screen. (Only works on Android for the moment)"""
        controller = UnifiedMobileController(ctx)
        success = await controller.go_back()
        has_failed = not success
        output = "Failed to go back" if has_failed else None
        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=back_wrapper.on_failure_fn() if has_failed else back_wrapper.on_success_fn(),
            additional_kwargs={"error": output} if has_failed else {},
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

    return back


back_wrapper = ToolWrapper(
    tool_fn_getter=get_back_tool,
    on_success_fn=lambda: "Navigated to the previous screen.",
    on_failure_fn=lambda: "Failed to navigate to the previous screen.",
)
