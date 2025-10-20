import asyncio
from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.mobile_command_controller import (
    wait_for_delay as wait_for_delay_controller,
)
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.tools.tool_wrapper import ToolWrapper

MAX_DELAY_MS = 60000


def get_wait_for_delay_tool(ctx: MobileUseContext):
    @tool
    async def wait_for_delay(
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
        agent_thought: str,
        time_in_ms: int,
    ) -> Command:
        """
        Wait for a delay in milliseconds.

        This tool pauses execution for a specified number of milliseconds.
        Use this when you need to introduce a controlled delay to allow the UI
        to update after an action, regardless of whether an animation is playing.

        Args:
            time_in_ms: The number of milliseconds to wait. (capped at 60 seconds)


        Example:
            - wait_for_delay with time_in_ms=1000 (waits 1 second)
            - wait_for_delay with time_in_ms=500 (waits 0.5 seconds)
        """
        if time_in_ms < 0:
            time_in_ms = 1000
        if time_in_ms > MAX_DELAY_MS:
            time_in_ms = MAX_DELAY_MS
        try:
            await asyncio.to_thread(wait_for_delay_controller, time_in_ms)
            output = None
            has_failed = False
        except Exception as e:
            output = str(e)
            has_failed = True
        agent_outcome = (
            wait_for_delay_wrapper.on_failure_fn()
            if has_failed
            else wait_for_delay_wrapper.on_success_fn(time_in_ms)
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

    return wait_for_delay


wait_for_delay_wrapper = ToolWrapper(
    tool_fn_getter=get_wait_for_delay_tool,
    on_success_fn=lambda delay: f"Successfully waited for {delay} milliseconds.",
    on_failure_fn=lambda: "Failed to wait for delay.",
)
