from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.mobile_command_controller import get_screen_data
from minitap.mobile_use.controllers.platform_specific_commands_controller import (
    get_current_foreground_package,
    get_device_date,
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
    async def __call__(self, state: State):
        device_data = get_screen_data(self.ctx.screen_api_client)
        focused_app_info = get_current_foreground_package(self.ctx)
        device_date = get_device_date(self.ctx)

        return await state.asanitize_update(
            ctx=self.ctx,
            update={
                "latest_ui_hierarchy": device_data.elements,
                "focused_app_info": focused_app_info,
                "screen_size": (device_data.width, device_data.height),
                "device_date": device_date,
            },
        )
