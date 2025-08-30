from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.types import Command
from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.mobile_command_controller import (
    paste_text as paste_text_controller,
)
from minitap.mobile_use.graph.state import State
from langgraph.prebuilt import InjectedState
from minitap.mobile_use.tools.tool_wrapper import ToolWrapper
from typing import Annotated


def get_paste_text_tool(ctx: MobileUseContext):
    @tool
    def paste_text(
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
        agent_thought: str,
    ):
        """
        Pastes text previously copied via `copyTextFrom` into the currently focused field.

        Note:
            The text field must be focused before using this command.

        Example:
            - copyTextFrom: { id: "someId" }
            - tapOn: { id: "searchFieldId" }
            - pasteText
        """
        output = paste_text_controller(ctx=ctx)
        has_failed = output is not None
        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=paste_text_wrapper.on_failure_fn()
            if has_failed
            else paste_text_wrapper.on_success_fn(),
            additional_kwargs={"error": output} if has_failed else {},
            status="error" if has_failed else "success",
        )
        return Command(
            update=state.sanitize_update(
                ctx=ctx,
                update={
                    "agents_thoughts": [agent_thought],
                    EXECUTOR_MESSAGES_KEY: [tool_message],
                },
                agent="executor",
            ),
        )

    return paste_text


paste_text_wrapper = ToolWrapper(
    tool_fn_getter=get_paste_text_tool,
    on_success_fn=lambda: "Text pasted successfully.",
    on_failure_fn=lambda: "Failed to paste text.",
)
