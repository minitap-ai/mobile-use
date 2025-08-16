from langchain_core.messages import (
    ToolMessage,
)

from minitap.constants import (
    EXPIRED_TOOL_MESSAGE,
    SCREENSHOT_LIFETIME,
)
from minitap.graph.state import State


def history_cleanup(state: State):
    messages = list(state.messages)

    expired_screenshot_tool_messages: list[ToolMessage] = []
    for message in messages[:-SCREENSHOT_LIFETIME]:
        if isinstance(message, ToolMessage):
            if message.name == "take_screenshot":
                message.content = EXPIRED_TOOL_MESSAGE
                expired_screenshot_tool_messages.append(message)

    return {
        "messages": messages + expired_screenshot_tool_messages,
    }
