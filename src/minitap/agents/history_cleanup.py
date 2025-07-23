from typing import Sequence

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
)
from minitap.constants import (
    EXPIRED_TOOL_MESSAGE,
    SCREENSHOT_LIFETIME,
)
from minitap.graph.state import State
from minitap.utils.conversation import message_is_screenshot


def history_cleanup(state: State, transformed_messages: Sequence[BaseMessage]):
    messages = state.messages

    expired_screenshot_tool_messages: list[HumanMessage] = []
    for message in messages[:-SCREENSHOT_LIFETIME]:
        if isinstance(message, HumanMessage) and message_is_screenshot(message):
            message.content = EXPIRED_TOOL_MESSAGE
            expired_screenshot_tool_messages.append(message)

    return {
        "messages": list(transformed_messages) + expired_screenshot_tool_messages,
    }
