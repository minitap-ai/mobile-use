from langchain_core.messages import BaseMessage

from minitap.mobile_use.utils.conversations import is_tool_message


def is_last_tool_message_take_screenshot(messages: list[BaseMessage]) -> bool:
    if not messages:
        return False
    for msg in messages[::-1]:
        if is_tool_message(msg):
            return msg.name == "glimpse_screen"
    return False
