from langchain_core.tools import BaseTool

from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.tools.mobile.back import back_wrapper
from minitap.mobile_use.tools.mobile.erase_one_char import erase_one_char_wrapper
from minitap.mobile_use.tools.mobile.focus_and_clear_text import focus_and_clear_text_wrapper
from minitap.mobile_use.tools.mobile.focus_and_input_text import focus_and_input_text_wrapper
from minitap.mobile_use.tools.mobile.launch_app import launch_app_wrapper
from minitap.mobile_use.tools.mobile.long_press_on import long_press_on_wrapper
from minitap.mobile_use.tools.mobile.open_link import open_link_wrapper
from minitap.mobile_use.tools.mobile.press_key import press_key_wrapper
from minitap.mobile_use.tools.mobile.stop_app import stop_app_wrapper
from minitap.mobile_use.tools.mobile.swipe import swipe_wrapper
from minitap.mobile_use.tools.mobile.tap import tap_wrapper
from minitap.mobile_use.tools.mobile.wait_for_delay import (
    wait_for_delay_wrapper,
)
from minitap.mobile_use.tools.tool_wrapper import CompositeToolWrapper, ToolWrapper

EXECUTOR_WRAPPERS_TOOLS = [
    back_wrapper,
    open_link_wrapper,
    tap_wrapper,
    long_press_on_wrapper,
    swipe_wrapper,
    focus_and_input_text_wrapper,
    erase_one_char_wrapper,
    launch_app_wrapper,
    stop_app_wrapper,
    focus_and_clear_text_wrapper,
    press_key_wrapper,
    wait_for_delay_wrapper,
]


def get_tools_from_wrappers(
    ctx: "MobileUseContext",
    wrappers: list[ToolWrapper],
) -> list[BaseTool]:
    tools: list[BaseTool] = []
    for wrapper in wrappers:
        if ctx.llm_config.get_agent("executor").provider == "vertexai":
            # The main swipe tool argument structure is not supported by vertexai, we need to split
            # this tool into multiple tools
            if wrapper.tool_fn_getter == swipe_wrapper.tool_fn_getter and isinstance(
                wrapper, CompositeToolWrapper
            ):
                tools.extend(wrapper.composite_tools_fn_getter(ctx))
                continue

        tools.append(wrapper.tool_fn_getter(ctx))
    return tools


def format_tools_list(ctx: MobileUseContext, wrappers: list[ToolWrapper]) -> str:
    return ", ".join([tool.name for tool in get_tools_from_wrappers(ctx, wrappers)])
