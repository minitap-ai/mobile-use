from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.mobile_command_controller import Key
from minitap.mobile_use.controllers.mobile_command_controller import (
    press_key as press_key_controller,
)
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.tools.tool_wrapper import ToolWrapper


def get_press_key_tool(ctx: MobileUseContext):
    @tool
    async def press_key(
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
        agent_thought: str,
        key: Key,
    ) -> Command:
        """Press a key on the device."""
        output = press_key_controller(ctx=ctx, key=key)
        has_failed = output is not None

        agent_outcome = (
            press_key_wrapper.on_failure_fn(key)
            if has_failed
            else press_key_wrapper.on_success_fn(key)
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

    return press_key


press_key_wrapper = ToolWrapper(
    tool_fn_getter=get_press_key_tool,
    on_success_fn=lambda key: f"Key {key.value} pressed successfully.",
    on_failure_fn=lambda key: f"Failed to press key {key.value}.",
)
