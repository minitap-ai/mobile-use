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


def get_open_link_tool(ctx: MobileUseContext):
    @tool
    async def open_link(
        agent_thought: str,
        url: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
    ) -> Command:
        """
        Open a link on a device (i.e. a deep link).
        """
        controller = UnifiedMobileController(ctx)
        success = await controller.open_url(url)
        has_failed = not success
        output = "Failed to open URL" if has_failed else None

        agent_outcome = (
            open_link_wrapper.on_failure_fn()
            if has_failed
            else open_link_wrapper.on_success_fn(url)
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

    return open_link


open_link_wrapper = ToolWrapper(
    tool_fn_getter=get_open_link_tool,
    on_success_fn=lambda url: f"Link {url} opened successfully.",
    on_failure_fn=lambda: "Failed to open link.",
)
