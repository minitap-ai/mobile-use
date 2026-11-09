import re
from pydantic import BaseModel, Field

from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


def __find_element_by_ressource_id_in_rich_hierarchy(
    hierarchy: list[dict], resource_id: str
) -> dict | None:
    """
    Retrieves all the sibling elements for a given resource ID from a nested dictionary.

    Args:
      hierarchy (dict): The nested dictionary representing the UI hierarchy.
      resource_id (str): The resource-id to find.

    Returns:
      list: A list of the sibling elements, or None if the resource_id is not found.
    """
    if not hierarchy:
        return None

    for child in hierarchy:
        if child.get("attributes", {}).get("resource-id") == resource_id:
            return child.get("attributes", {})

    for child in hierarchy:
        result = __find_element_by_ressource_id_in_rich_hierarchy(
            child.get("children", []), resource_id
        )
        if result is not None:
            return result

    return None


def text_input_is_empty(text: str | None, hint_text: str | None) -> bool:
    return not text or text == hint_text


def find_element_by_resource_id(
    ui_hierarchy: list[dict],
    resource_id: str,
    index: int | None = None,
    is_rich_hierarchy: bool = False,
    legacy_v1: bool = False,
) -> dict | None:
    """
    Find a UI element by its resource-id in the UI hierarchy.

    Args:
        ui_hierarchy: List of UI element dictionaries
        resource_id: The resource-id to search for
            (e.g., "com.google.android.settings.intelligence:id/open_search_view_edit_text")

    Returns:
        The complete UI element dictionary if found, None otherwise
    """
    if is_rich_hierarchy:
        return __find_element_by_ressource_id_in_rich_hierarchy(ui_hierarchy, resource_id)

    if legacy_v1:
        return _find_element_by_resource_id_v1(ui_hierarchy, resource_id, index)

    # Matches still to skip before returning one. paper/androidworld-rework, audit A10: this
    # counter used to be re-initialised at every match, so any index >= 1 never matched.
    remaining = [index or 0]

    def search_recursive(elements: list[dict]) -> dict | None:
        for element in elements:
            if isinstance(element, dict):
                # paper/androidworld-rework, audit A10: the UIAutomator2 client (Android) emits
                # "resource-id"; only the Maestro key "resourceId" used to be matched, so this
                # lookup never matched on Android (focus by id + post-validation read-back inert).
                element_id = element.get("resourceId", element.get("resource-id"))
                if element_id == resource_id:
                    if remaining[0] == 0:
                        return element
                    remaining[0] -= 1
                    continue

                children = element.get("children", [])
                if children:
                    result = search_recursive(children)
                    if result:
                        return result
        return None

    return search_recursive(ui_hierarchy)


def _find_element_by_resource_id_v1(
    ui_hierarchy: list[dict], resource_id: str, index: int | None = None
) -> dict | None:
    """v1 (January 2026) lookup, kept verbatim for `legacy_v1_android_bugs`: Maestro key only,
    index counter reset at every match."""

    def search_recursive(elements: list[dict]) -> dict | None:
        for element in elements:
            if isinstance(element, dict):
                if element.get("resourceId") == resource_id:
                    idx = index or 0
                    if idx == 0:
                        return element
                    idx -= 1
                    continue

                children = element.get("children", [])
                if children:
                    result = search_recursive(children)
                    if result:
                        return result
        return None

    return search_recursive(ui_hierarchy)


def is_element_focused(element: dict) -> bool:
    return element.get("focused", None) == "true"


def get_element_text(element: dict, hint_text: bool = False) -> str | None:
    if hint_text:
        return element.get("hintText", None)
    return element.get("text", None)


class Point(BaseModel):
    x: int
    y: int


class ElementBounds(BaseModel):
    x: int = Field(description="The x coordinate of the top-left corner of the element.")
    y: int = Field(description="The y coordinate of the top-left corner of the element.")
    width: int = Field(description="The width of the element.")
    height: int = Field(description="The height of the element.")

    def get_center(self) -> Point:
        return Point(x=self.x + self.width // 2, y=self.y + self.height // 2)

    def get_relative_point(self, x_percent: float, y_percent: float) -> Point:
        """
        Returns the coordinates of the point at x_percent of the width and y_percent
        of the height of the element.

        Ex if x_percent = 0.95 and y_percent = 0.95,
        the point is at the bottom right of the element:
        <------>
        |      |
        |     x|
        <------>
        """
        return Point(
            x=int(self.x + self.width * x_percent),
            y=int(self.y + self.height * y_percent),
        )


_BOUNDS_STR_RE = re.compile(r"^\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]$")


def get_bounds_for_element(element: dict, legacy_v1: bool = False) -> ElementBounds | None:
    bounds = element.get("bounds", None)
    if isinstance(bounds, str):
        if legacy_v1:
            # v1 behaviour (`legacy_v1_android_bugs`): ElementBounds(**"<str>") raised and the
            # error was logged, so UIAutomator2 bounds were never usable.
            logger.error(f"Failed to validate bounds: {bounds!r} is not a mapping")
            return None
        # paper/androidworld-rework, audit A10: UIAutomator2 gives "[x1,y1][x2,y2]"; only the
        # Maestro dict format {x, y, width, height} used to be parsed.
        match = _BOUNDS_STR_RE.match(bounds.strip())
        if not match:
            logger.error(f"Failed to parse bounds string: {bounds!r}")
            return None
        x1, y1, x2, y2 = (int(v) for v in match.groups())
        return ElementBounds(x=x1, y=y1, width=x2 - x1, height=y2 - y1)
    if bounds:
        try:
            return ElementBounds(**bounds)
        except Exception as e:
            logger.error(f"Failed to validate bounds: {e}")
            return None
    return None
