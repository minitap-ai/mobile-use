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
    find_child_element_by_class,
    find_element_by_resource_id,
    find_element_recursive,
    get_bounds_for_element,
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


def find_and_focus_text_input(ctx: MobileUseContext, container_resource_id: str) -> str | None:
    """
    Finds a container by its ID in the rich hierarchy, then finds the actual EditText
    child element and focuses it.

    Returns the resource_id of the actual input field if found, otherwise None.
    """
    logger.info(
        f"Attempting to find and focus text input within container: {container_resource_id}"
    )
    rich_hierarchy_children: list[dict] = ctx.hw_bridge_client.get_rich_hierarchy()

    parent_element = None
    for root_node in rich_hierarchy_children:
        parent_element = find_element_recursive(root_node, container_resource_id)
        if parent_element:
            break

    if not parent_element:
        logger.warning(
            f"Could not find parent container '{container_resource_id}'"
            + "in rich hierarchy. Falling back."
        )
        tap(ctx=ctx, selector_request=IdSelectorRequest(id=container_resource_id))
        return container_resource_id

    text_input_element = find_child_element_by_class(parent_element, "android.widget.EditText")
    # TODO: IOS support

    if not text_input_element:
        logger.warning(
            f"Could not find an EditText child in '{container_resource_id}'."
            + "Tapping container as fallback."
        )
        tap(ctx=ctx, selector_request=IdSelectorRequest(id=container_resource_id))
        return container_resource_id

    attributes = text_input_element.get("attributes", {})
    input_resource_id = attributes.get("resource-id")

    if input_resource_id and input_resource_id != "":
        logger.info(f"Found specific input field with ID: {input_resource_id}. Tapping to focus.")
        tap(ctx=ctx, selector_request=IdSelectorRequest(id=input_resource_id))
        return input_resource_id
    else:
        logger.info("Found input field with no ID. Tapping its coordinates to focus.")
        bounds = get_bounds_for_element(text_input_element)
        if bounds:
            center_point: Point = bounds.get_center()
            tap(
                ctx=ctx,
                selector_request=SelectorRequestWithCoordinates(
                    coordinates=CoordinatesSelectorRequest(x=center_point.x, y=center_point.y)
                ),
            )
            return container_resource_id
        else:
            logger.warning("Could not get bounds for the child input field. Tapping container.")
            tap(ctx=ctx, selector_request=IdSelectorRequest(id=container_resource_id))
            return container_resource_id
