from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import BaseTool, InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.tools.tool_wrapper import ToolWrapper
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


def get_save_note_tool(ctx: MobileUseContext) -> BaseTool:
    @tool
    async def save_note(
        agent_thought: str,
        key: str,
        content: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
    ):
        """
        Saves a text note to persistent memory with the given key.
        If the key already exists, it will be overwritten.
        """
        updated_scratchpad = {**state.scratchpad, key: content}

        agent_outcome = save_note_wrapper.on_success_fn(key)

        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=agent_outcome,
            status="success",
        )
        return Command(
            update=await state.asanitize_update(
                ctx=ctx,
                update={
                    "agents_thoughts": [agent_thought, agent_outcome],
                    EXECUTOR_MESSAGES_KEY: [tool_message],
                    "scratchpad": updated_scratchpad,
                },
                agent="executor",
            ),
        )

    return save_note


def get_read_note_tool(ctx: MobileUseContext) -> BaseTool:
    @tool
    async def read_note(
        agent_thought: str,
        key: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
    ):
        """
        Reads a previously saved note from persistent memory by its key.
        """
        content = state.scratchpad.get(key)

        if content is not None:
            agent_outcome = read_note_wrapper.on_success_fn(key, content)
            status = "success"
        else:
            agent_outcome = read_note_wrapper.on_failure_fn(key)
            status = "error"

        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=agent_outcome,
            status=status,
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

    return read_note


def get_list_notes_tool(ctx: MobileUseContext) -> BaseTool:
    @tool
    async def list_notes(
        agent_thought: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
    ):
        """
        Lists all note keys currently stored in persistent memory.
        """
        keys = list(state.scratchpad.keys())

        agent_outcome = list_notes_wrapper.on_success_fn(keys)

        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=agent_outcome,
            status="success",
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

    return list_notes


save_note_wrapper = ToolWrapper(
    tool_fn_getter=get_save_note_tool,
    on_success_fn=lambda key: (f"Successfully saved note '{key}'."),
    on_failure_fn=lambda key: f"Failed to save note '{key}'.",
)

read_note_wrapper = ToolWrapper(
    tool_fn_getter=get_read_note_tool,
    on_success_fn=lambda key, content: (
        f"Successfully read note '{key}'. '{key}' note full content: {content}"
    ),
    on_failure_fn=lambda key: f"Note '{key}' not found in scratchpad.",
)

list_notes_wrapper = ToolWrapper(
    tool_fn_getter=get_list_notes_tool,
    on_success_fn=lambda keys: (
        f"Here are all the note keys: {keys}" if keys else "No notes saved yet."
    ),
    on_failure_fn=lambda: "Failed to list notes.",
)
