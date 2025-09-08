from minitap.mobile_use.agents.executor.utils import is_last_tool_message_take_screenshot
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.mobile_command_controller import get_screen_data
from minitap.mobile_use.controllers.platform_specific_commands_controller import (
    get_device_date,
    get_focused_app_info,
)
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.utils.decorators import wrap_with_callbacks
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


class ContextorNode:
    def __init__(self, ctx: MobileUseContext):
        self.ctx = ctx

    @wrap_with_callbacks(
        before=lambda: logger.info("Starting Contextor Agent"),
        on_success=lambda _: logger.success("Contextor Agent"),
        on_failure=lambda _: logger.error("Contextor Agent"),
    )
    def __call__(self, state: State):
        device_data = get_screen_data(self.ctx.screen_api_client)
        focused_app_info = get_focused_app_info(self.ctx)
        device_date = get_device_date(self.ctx)

        should_add_screenshot_context = is_last_tool_message_take_screenshot(
            list(state.executor_messages)
        )

        return state.sanitize_update(
            ctx=self.ctx,
            update={
                "latest_screenshot_base64": device_data.base64
                if should_add_screenshot_context
                else None,
                "latest_ui_hierarchy": device_data.elements,
                "focused_app_info": focused_app_info,
                "screen_size": (device_data.width, device_data.height),
                "device_date": device_date,
            },
        )
