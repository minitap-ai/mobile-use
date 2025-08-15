from typing import Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.types import Command
from typing_extensions import Annotated

from minitap.tools.tool_wrapper import ExecutorMetadata, ToolWrapper


@tool
def take_screenshot(
    tool_call_id: Annotated[str, InjectedToolCallId],
    agent_thought: str,
    executor_metadata: Optional[ExecutorMetadata],
):
    """
    Take a screenshot of the device.
    """
    has_failed = False

    tool_message = ToolMessage(tool_call_id=tool_call_id, content="Successfully took screenshot")
    updates = {
        "agents_thoughts": [agent_thought],
        "messages": [tool_message],
    }
    return Command(
        update=take_screenshot_wrapper.handle_executor_state_fields(
            executor_metadata=executor_metadata,
            tool_message=tool_message,
            is_failure=has_failed,
            updates=updates,
        ),
    )


take_screenshot_wrapper = ToolWrapper(
    tool_fn=take_screenshot,
    on_success_fn=lambda: "Screenshot taken successfully.",
    on_failure_fn=lambda: "Failed to take screenshot.",
)
