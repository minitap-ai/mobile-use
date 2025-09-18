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
    ElementBounds,
    Point,
    find_element_by_resource_id,
    get_bounds_for_element,
    get_element_text,
    is_element_focused,
)

logger = get_logger(__name__)


def find_element_by_text(ui_hierarchy: list[dict], text: str) -> dict | None:
    """
    Find a UI element by its text content in the rich hierarchy.

    Args:
        ui_hierarchy: List of UI element dictionaries (rich hierarchy format)
        text: The text content to search for

    Returns:
        The complete UI element dictionary if found, None otherwise
    """

    def search_recursive(elements: list[dict]) -> dict | None:
        for element in elements:
            if isinstance(element, dict):
                attrs = element.get("attributes", {})
                element_text = attrs.get("text", "")

                if text and text.lower() in element_text.lower():
                    return attrs

                children = element.get("children", [])
                if children:
                    result = search_recursive(children)
                    if result:
                        return result
        return None

    return search_recursive(ui_hierarchy)


def tap_bottom_right_of_element(bounds: ElementBounds, ctx: MobileUseContext):
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


def move_cursor_to_end_if_bounds(
    ctx: MobileUseContext,
    state: State,
    text_input_resource_id: str | None,
    text_input_coordinates: ElementBounds | None,
    text_input_text: str | None,
    elt: dict | None = None,
) -> dict | None:
    """
    Best-effort move of the text cursor near the end of the input by tapping the
    bottom-right area of the focused element (if bounds are available).
    """
    if text_input_resource_id:
        if not elt:
            elt = find_element_by_resource_id(
                ui_hierarchy=state.latest_ui_hierarchy or [],
                resource_id=text_input_resource_id,
            )
        if not elt:
            return

        bounds = get_bounds_for_element(elt)
        if not bounds:
            return elt

        logger.debug("Tapping near the end of the input to move the cursor")
        tap_bottom_right_of_element(bounds=bounds, ctx=ctx)
        logger.debug(f"Tapped end of input {text_input_resource_id}")
        return elt

    if text_input_coordinates:
        tap_bottom_right_of_element(text_input_coordinates, ctx=ctx)
        logger.debug("Tapped end of input by coordinates")
        return elt

    if text_input_text:
        text_elt = find_element_by_text(state.latest_ui_hierarchy or [], text_input_text)
        if text_elt:
            bounds = get_bounds_for_element(text_elt)
            if bounds:
                tap_bottom_right_of_element(bounds=bounds, ctx=ctx)
                logger.debug(f"Tapped end of input that had text'{text_input_text}'")
                return text_elt
        return None

    return None


def focus_element_if_needed(
    ctx: MobileUseContext,
    text_input_resource_id: str | None,
    text_input_coordinates: ElementBounds | None,
    text_input_text: str | None,
) -> bool:
    """
    Ensures the element is focused, with a sanity check to prevent trusting misleading IDs.
    """
    rich_hierarchy = ctx.hw_bridge_client.get_rich_hierarchy()

    if text_input_resource_id and text_input_text:
        elt_from_id = find_element_by_resource_id(
            ui_hierarchy=rich_hierarchy, resource_id=text_input_resource_id, is_rich_hierarchy=True
        )
        if elt_from_id:
            text_from_id_elt = get_element_text(elt_from_id)
            if not text_from_id_elt or text_input_text.lower() not in text_from_id_elt.lower():
                logger.warning(
                    f"ID '{text_input_resource_id}' and text '{text_input_text}'"
                    + "seem to be on different elements. "
                    "Ignoring the resource_id and falling back to other locators."
                )
                text_input_resource_id = None

    if text_input_resource_id:
        rich_elt = find_element_by_resource_id(
            ui_hierarchy=rich_hierarchy,
            resource_id=text_input_resource_id,
            is_rich_hierarchy=True,
        )
        if rich_elt and not is_element_focused(rich_elt):
            tap(ctx=ctx, selector_request=IdSelectorRequest(id=text_input_resource_id))
            logger.debug(f"Focused (tap) on resource_id={text_input_resource_id}")
            rich_hierarchy = ctx.hw_bridge_client.get_rich_hierarchy()
            rich_elt = find_element_by_resource_id(
                ui_hierarchy=rich_hierarchy,
                resource_id=text_input_resource_id,
                is_rich_hierarchy=True,
            )
        if rich_elt and is_element_focused(rich_elt):
            logger.debug(f"Text input is focused: {text_input_resource_id}")
            return True

        logger.warning(f"Failed to focus using resource_id='{text_input_resource_id}'. Fallback...")

    if text_input_coordinates:
        relative_point = text_input_coordinates.get_relative_point(x_percent=0.95, y_percent=0.95)
        tap(
            ctx=ctx,
            selector_request=SelectorRequestWithCoordinates(
                coordinates=CoordinatesSelectorRequest(
                    x=relative_point.x,
                    y=relative_point.y,
                ),
            ),
        )
        logger.debug(f"Tapped on coordinates ({relative_point.x}, {relative_point.y}) to focus.")
        return True

    if text_input_text:
        text_elt = find_element_by_text(rich_hierarchy, text_input_text)
        if text_elt:
            bounds = get_bounds_for_element(text_elt)
            if bounds:
                relative_point = bounds.get_relative_point(x_percent=0.95, y_percent=0.95)
                tap(
                    ctx=ctx,
                    selector_request=SelectorRequestWithCoordinates(
                        coordinates=CoordinatesSelectorRequest(
                            x=relative_point.x,
                            y=relative_point.y,
                        ),
                    ),
                )
                logger.debug(f"Tapped on text element '{text_input_text}' to focus.")
                return True

    logger.error("Failed to focus element. No valid locator (ID, coordinates, or text) succeeded.")
    return False
