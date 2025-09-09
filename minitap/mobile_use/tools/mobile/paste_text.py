from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.mobile_command_controller import (
    get_screen_data,
)
from minitap.mobile_use.controllers.mobile_command_controller import (
    paste_text as paste_text_controller,
)
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.tools.tool_wrapper import ToolWrapper
from minitap.mobile_use.utils.ui_hierarchy import find_element_by_resource_id, get_element_text


def get_paste_text_tool(ctx: MobileUseContext):
    @tool
    def paste_text(
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
        agent_thought: str,
        focused_element_resource_id: str,
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

        text_input_content = ""
        screen_data = get_screen_data(screen_api_client=ctx.screen_api_client)
        state.latest_ui_hierarchy = screen_data.elements

        element = find_element_by_resource_id(
            ui_hierarchy=state.latest_ui_hierarchy, resource_id=focused_element_resource_id
        )

        if element:
            text_input_content = get_element_text(element)

        has_failed = output is not None

        agent_outcome = (
            paste_text_wrapper.on_success_fn(text_input_content)
            if not has_failed
            else paste_text_wrapper.on_failure_fn(text_input_content)
        )

        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=agent_outcome,
            additional_kwargs={"error": output} if has_failed else {},
            status="error" if has_failed else "success",
        )
        return Command(
            update=state.sanitize_update(
                ctx=ctx,
                update={
                    "agents_thoughts": [agent_thought, agent_outcome],
                    EXECUTOR_MESSAGES_KEY: [tool_message],
                },
                agent="executor",
            ),
        )

    return paste_text


paste_text_wrapper = ToolWrapper(
    tool_fn_getter=get_paste_text_tool,
    on_success_fn=lambda input_content: "Text pasted successfully. Here is the actual"
    + f"content of the text field : {repr(input_content)}",
    on_failure_fn=lambda input_content: "Failed to paste text."
    + f"Here is the actual content of the text field : {repr(input_content)}",
)
