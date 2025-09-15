import re

from pydantic import BaseModel

from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


def text_input_is_empty(text: str | None, hint_text: str | None) -> bool:
    return not text or text == hint_text


def is_element_focused(element: dict) -> bool:
    attributes = element.get("attributes", {})
    return attributes.get("focused") == "true"


def get_element_text(element: dict, hint_text: bool = False) -> str | None:
    """
    Extracts the text or hint text from a UI element, handling both rich and flat hierarchies.
    """
    source = element.get("attributes", element)

    if hint_text:
        return source.get("hintText")

    text = source.get("text")
    if text is not None and text != "":
        return text

    return source.get("accessibilityText")


class Point(BaseModel):
    x: int
    y: int


class ElementBounds(BaseModel):
    x: int
    y: int
    width: int
    height: int

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


def get_bounds_for_element(element: dict) -> ElementBounds | None:
    """
    Extracts and parses bounds from a UI element, handling both rich (string) and flat (dict) hierarchy formats.
    """
    attributes = element.get("attributes", {})
    bounds_data = attributes.get("bounds", element.get("bounds"))

    if not bounds_data:
        return None

    if isinstance(bounds_data, dict):
        try:
            return ElementBounds(**bounds_data)
        except Exception as e:
            logger.error(f"Failed to validate bounds dictionary: {e}")
            return None

    if isinstance(bounds_data, str):
        match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_data)
        if match:
            x1, y1, x2, y2 = map(int, match.groups())
            return ElementBounds(
                x=x1,
                y=y1,
                width=x2 - x1,
                height=y2 - y1,
            )

    logger.warning(f"Could not parse bounds data: {bounds_data}")
    return None


def find_element_by_resource_id(ui_hierarchy: list[dict], resource_id: str) -> dict | None:
    """
    Find a UI element by its resource-id in the flat UI hierarchy.
    """
    for element in ui_hierarchy:
        if isinstance(element, dict) and element.get("resourceId") == resource_id:
            return element
    return None


def find_element_recursive(node: dict, resource_id: str) -> dict | None:
    """
    Recursively searches for an element with a specific resource-id in the rich hierarchy.
    """
    attributes = node.get("attributes", {})
    if attributes.get("resource-id") == resource_id:
        return node

    for child in node.get("children", []):
        found = find_element_recursive(child, resource_id)
        if found:
            return found
    return None


def find_child_element_by_class(parent_node: dict, class_name: str) -> dict | None:
    """
    Recursively searches the children of a given node for the first element
    with a specific class name (e.g., 'android.widget.EditText').
    """
    if parent_node.get("attributes", {}).get("class") == class_name:
        return parent_node

    for child in parent_node.get("children", []):
        found = find_child_element_by_class(child, class_name)
        if found:
            return found
    return None


def get_text_from_nested_input(hierarchy: list[dict], container_resource_id: str) -> str | None:
    """
    Finds a container in the rich hierarchy and returns the text of its first EditText child.
    This is primarily used for verification after a text input action.
    """
    parent_element = None

    for root_node in hierarchy:
        parent_element = find_element_recursive(root_node, container_resource_id)
        if parent_element:
            break

    if not parent_element:
        logger.warning(f"Verification failed: Could not find container '{container_resource_id}'")
        return None

    text_input_element = find_child_element_by_class(parent_element, "android.widget.EditText")

    if not text_input_element:
        logger.warning(
            f"Verification failed: Could not find EditText child in '{container_resource_id}'"
        )
        return None

    return get_element_text(text_input_element)
