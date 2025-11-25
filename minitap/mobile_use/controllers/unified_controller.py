from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.controller_factory import get_controller
from minitap.mobile_use.controllers.device_controller import MobileDeviceController
from minitap.mobile_use.controllers.types import (
    CoordinatesSelectorRequest,
    PercentagesSelectorRequest,
    SwipeRequest,
    SwipeStartEndCoordinatesRequest,
    SwipeStartEndPercentagesRequest,
    TapOutput,
)
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


class UnifiedMobileController:
    def __init__(self, ctx: MobileUseContext):
        self.ctx = ctx
        self._controller: MobileDeviceController = get_controller(ctx)

    @property
    def controller(self) -> MobileDeviceController:
        return self._controller

    async def tap_at(
        self,
        x: int,
        y: int,
        long_press: bool = False,
        long_press_duration: int = 1000,
    ) -> TapOutput:
        coords = CoordinatesSelectorRequest(x=x, y=y)
        return await self._controller.tap(coords, long_press, long_press_duration)

    async def tap_percentage(
        self,
        x_percent: int,
        y_percent: int,
        long_press: bool = False,
        long_press_duration: int = 1000,
    ) -> TapOutput:
        """Tap at percentage-based coordinates (0 to 100)."""
        coords = PercentagesSelectorRequest(x_percent=x_percent, y_percent=y_percent).to_coords(
            width=self.ctx.device.device_width,
            height=self.ctx.device.device_height,
        )
        return await self._controller.tap(coords, long_press, long_press_duration)

    async def tap_element(
        self,
        resource_id: str | None = None,
        text: str | None = None,
        index: int = 0,
        long_press: bool = False,
        long_press_duration: int = 1000,
    ) -> TapOutput:
        """
        Tap on a UI element by finding it in the hierarchy.

        Args:
            resource_id: Android resource ID or iOS element type
            text: Element text/label/value to match
            index: Which match to tap if multiple elements match
            long_press: Whether to perform long press
            long_press_duration: Duration of long press in milliseconds

        Returns:
            TapOutput with error field set on failure
        """
        # Get UI hierarchy
        ui_hierarchy = await self._controller.get_ui_hierarchy()

        # Find element
        element, bounds, error = self._controller.find_element(
            ui_hierarchy=ui_hierarchy,
            resource_id=resource_id,
            text=text,
            index=index,
        )

        if error or not bounds:
            return TapOutput(error=error or "Could not extract bounds for element")

        # Tap at element center
        center = bounds.get_center()
        return await self._controller.tap(center, long_press, long_press_duration)

    async def swipe_coords(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: int = 400,
    ) -> str | None:
        """Swipe between two coordinate points."""
        start = CoordinatesSelectorRequest(x=start_x, y=start_y)
        end = CoordinatesSelectorRequest(x=end_x, y=end_y)
        return await self._controller.swipe(start, end, duration)

    async def swipe_percentage(
        self,
        start_x_percent: int,
        start_y_percent: int,
        end_x_percent: int,
        end_y_percent: int,
        duration: int = 400,
    ) -> str | None:
        """Swipe using percentage-based coordinates (0 to 100)."""
        start = PercentagesSelectorRequest(
            x_percent=start_x_percent, y_percent=start_y_percent
        ).to_coords(
            width=self.ctx.device.device_width,
            height=self.ctx.device.device_height,
        )
        end = PercentagesSelectorRequest(
            x_percent=end_x_percent, y_percent=end_y_percent
        ).to_coords(
            width=self.ctx.device.device_width,
            height=self.ctx.device.device_height,
        )
        return await self._controller.swipe(start, end, duration)

    async def swipe_request(self, request: SwipeRequest) -> str | None:
        mode = request.swipe_mode

        if isinstance(mode, SwipeStartEndCoordinatesRequest):
            return await self._controller.swipe(
                start=mode.start,
                end=mode.end,
                duration=request.duration or 400,
            )
        elif isinstance(mode, SwipeStartEndPercentagesRequest):
            coords = mode.to_coords(
                width=self.ctx.device.device_width,
                height=self.ctx.device.device_height,
            )
            return await self._controller.swipe(
                start=coords.start,
                end=coords.end,
                duration=request.duration or 400,
            )
        else:
            return "Unsupported swipe mode"

    async def type_text(self, text: str) -> bool:
        return await self._controller.input_text(text)

    async def take_screenshot(self) -> str:
        return await self._controller.screenshot()

    async def launch_app(self, package_or_bundle_id: str) -> bool:
        return await self._controller.launch_app(package_or_bundle_id)

    async def terminate_app(self, package_or_bundle_id: str | None) -> bool:
        return await self._controller.terminate_app(package_or_bundle_id)

    async def open_url(self, url: str) -> bool:
        return await self._controller.open_url(url)

    async def go_back(self) -> bool:
        return await self._controller.press_back()

    async def go_home(self) -> bool:
        return await self._controller.press_home()

    async def erase_text(self, nb_chars: int | None = None) -> bool:
        return await self._controller.erase_text(nb_chars)

    async def get_ui_elements(self) -> list[dict]:
        return await self._controller.get_ui_hierarchy()

    async def find_element(
        self,
        resource_id: str | None = None,
        text: str | None = None,
        index: int = 0,
    ) -> tuple[dict | None, str | None]:
        ui_hierarchy = await self._controller.get_ui_hierarchy()
        element, bounds, error = self._controller.find_element(
            ui_hierarchy=ui_hierarchy,
            resource_id=resource_id,
            text=text,
            index=index,
        )
        return element, error

    async def cleanup(self) -> None:
        await self._controller.cleanup()
