from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.mobile_command_controller import (
    erase_text as erase_text_controller,
)
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.tools.tool_wrapper import ToolWrapper


def get_erase_one_char_tool(ctx: MobileUseContext):
    @tool
    async def erase_one_char(
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
        agent_thought: str,
    ) -> Command:
        """
        Erase one character from a text area.
        It acts the same as pressing backspace a single time.
        """
        output = erase_text_controller(ctx=ctx, nb_chars=1)
        has_failed = output is not None
        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=erase_one_char_wrapper.on_failure_fn()
            if has_failed
            else erase_one_char_wrapper.on_success_fn(),
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

    return erase_one_char


erase_one_char_wrapper = ToolWrapper(
    tool_fn_getter=get_erase_one_char_tool,
    on_success_fn=lambda: "Erased one character successfully.",
    on_failure_fn=lambda: "Failed to erase one character.",
)
