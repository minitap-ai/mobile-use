from __future__ import annotations

from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.mobile_command_controller import (
    CoordinatesSelectorRequest,
    IdSelectorRequest,
    SelectorRequestWithCoordinates,
    tap,
)
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.utils.logger import get_logger
from minitap.mobile_use.utils.ui_hierarchy import (
    Point,
    find_element_by_resource_id,
    get_bounds_for_element,
    is_element_focused,
)

logger = get_logger(__name__)


def move_cursor_to_end_if_bounds(
    ctx: MobileUseContext,
    state: State,
    resource_id: str,
    elt: dict | None = None,
) -> dict | None:
    """
    Best-effort move of the text cursor near the end of the input by tapping the
    bottom-right area of the focused element (if bounds are available).
    """
    if not elt:
        elt = find_element_by_resource_id(
            ui_hierarchy=state.latest_ui_hierarchy or [],
            resource_id=resource_id,
        )
    if not elt:
        return

    bounds = get_bounds_for_element(elt)
    if not bounds:
        return elt

    logger.debug("Tapping near the end of the input to move the cursor")
    bottom_right: Point = bounds.get_relative_point(x_percent=0.99, y_percent=0.99)
    tap(
        ctx=ctx,
        selector_request=SelectorRequestWithCoordinates(
            coordinates=CoordinatesSelectorRequest(
                x=bottom_right.x,
                y=bottom_right.y,
            ),
        ),
    )
    logger.debug(f"Tapped end of input {resource_id} at ({bottom_right.x}, {bottom_right.y})")
    return elt


def focus_element_if_needed(
    ctx: MobileUseContext,
    resource_id: str,
) -> bool:
    """
    Ensures the element identified by `resource_id` is focused.
    """
    rich_hierarchy: list[dict] = ctx.hw_bridge_client.get_rich_hierarchy()
    rich_elt = find_element_by_resource_id(
        ui_hierarchy=rich_hierarchy,
        resource_id=resource_id,
        is_rich_hierarchy=True,
    )
    if rich_elt and not is_element_focused(rich_elt):
        tap(ctx=ctx, selector_request=IdSelectorRequest(id=resource_id))
        logger.debug(f"Focused (tap) on resource_id={resource_id}")
        rich_hierarchy = ctx.hw_bridge_client.get_rich_hierarchy()
        rich_elt = find_element_by_resource_id(
            ui_hierarchy=rich_hierarchy,
            resource_id=resource_id,
            is_rich_hierarchy=True,
        )
    if rich_elt and is_element_focused(rich_elt):
        logger.debug(f"Text input is focused: {resource_id}")
        return True

    logger.warning(f"Failed to focus resource_id={resource_id}")
    return False
