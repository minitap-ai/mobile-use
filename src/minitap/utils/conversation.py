from langchain_core.messages import HumanMessage


def message_is_screenshot(message: HumanMessage) -> bool:
    first_content = message.content[0]
    return isinstance(first_content, dict) and first_content.get("type") == "image_url"