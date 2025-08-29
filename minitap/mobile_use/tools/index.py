from langchain_core.tools import BaseTool

from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.tools.mobile.back import back_wrapper
from minitap.mobile_use.tools.mobile.clear_text import clear_text_wrapper
from minitap.mobile_use.tools.mobile.copy_text_from import copy_text_from_wrapper
from minitap.mobile_use.tools.mobile.find_packages import find_packages_wrapper
from minitap.mobile_use.tools.mobile.input_text import input_text_wrapper
from minitap.mobile_use.tools.mobile.launch_app import launch_app_wrapper
from minitap.mobile_use.tools.mobile.long_press_on import long_press_on_wrapper
from minitap.mobile_use.tools.mobile.open_link import open_link_wrapper
from minitap.mobile_use.tools.mobile.paste_text import paste_text_wrapper
from minitap.mobile_use.tools.mobile.press_key import press_key_wrapper
from minitap.mobile_use.tools.mobile.stop_app import stop_app_wrapper
from minitap.mobile_use.tools.mobile.swipe import swipe_wrapper
from minitap.mobile_use.tools.mobile.take_screenshot import take_screenshot_wrapper
from minitap.mobile_use.tools.mobile.tap import tap_wrapper
from minitap.mobile_use.tools.mobile.wait_for_animation_to_end import (
    wait_for_animation_to_end_wrapper,
)
from minitap.mobile_use.tools.tool_wrapper import ToolWrapper

EXECUTOR_WRAPPERS_TOOLS = [
    back_wrapper,
    open_link_wrapper,
    tap_wrapper,
    long_press_on_wrapper,
    swipe_wrapper,
    take_screenshot_wrapper,
    copy_text_from_wrapper,
    input_text_wrapper,
    find_packages_wrapper,
    launch_app_wrapper,
    stop_app_wrapper,
    paste_text_wrapper,
    clear_text_wrapper,
    press_key_wrapper,
    wait_for_animation_to_end_wrapper,
]


def get_tools_from_wrappers(ctx: MobileUseContext, wrappers: list[ToolWrapper]) -> list[BaseTool]:
    """Get the tools from the wrappers."""
    return [wrapper.tool_fn_getter(ctx) for wrapper in wrappers]


def get_tool_wrapper_from_name(name: str) -> ToolWrapper | None:
    """Get the tool wrapper from the name."""
    for wrapper in EXECUTOR_WRAPPERS_TOOLS:
        if wrapper.tool_fn_getter.__name__ == f"get_{name}_tool":
            return wrapper
    return None
