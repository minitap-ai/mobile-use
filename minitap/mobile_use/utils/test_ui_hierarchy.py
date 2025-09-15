from unittest.mock import patch

from minitap.mobile_use.utils.ui_hierarchy import (
    ElementBounds,
    Point,
    find_element_by_resource_id,
    get_bounds_for_element,
    get_element_text,
    is_element_focused,
    text_input_is_empty,
)


def test_text_input_is_empty():
    assert text_input_is_empty(text=None, hint_text=None)
    assert text_input_is_empty(text="", hint_text=None)
    assert text_input_is_empty(text="", hint_text="")
    assert text_input_is_empty(text="text", hint_text="text")

    assert not text_input_is_empty(text="text", hint_text=None)
    assert not text_input_is_empty(text="text", hint_text="")


def test_find_element_by_resource_id():
    ui_hierarchy = [
        {"resourceId": "com.example:id/button1", "text": "Button 1", "children": []},
        {
            "resourceId": "com.example:id/container",
            "children": [
                {
                    "resourceId": "com.example:id/nested_button",
                    "text": "Nested Button",
                    "children": [],
                }
            ],
        },
    ]

    result = find_element_by_resource_id(ui_hierarchy, "com.example:id/button1")
    assert result is not None
    assert result["resourceId"] == "com.example:id/button1"
    assert result["text"] == "Button 1"

    result = find_element_by_resource_id(ui_hierarchy, "com.example:id/nested_button")
    assert result is not None
    assert result["resourceId"] == "com.example:id/nested_button"
    assert result["text"] == "Nested Button"

    result = find_element_by_resource_id(ui_hierarchy, "com.example:id/nonexistent")
    assert result is None

    result = find_element_by_resource_id([], "com.example:id/button1")
    assert result is None


def test_find_element_by_resource_id_rich_hierarchy():
    rich_hierarchy = [
        {"attributes": {"resource-id": "com.example:id/button1"}, "children": []},
        {
            "attributes": {"resource-id": "com.example:id/container"},
            "children": [
                {"attributes": {"resource-id": "com.example:id/nested_button"}, "children": []}
            ],
        },
    ]

    result = find_element_by_resource_id(
        rich_hierarchy, "com.example:id/button1", is_rich_hierarchy=True
    )
    assert result is not None
    assert result["resource-id"] == "com.example:id/button1"

    result = find_element_by_resource_id(
        rich_hierarchy, "com.example:id/nested_button", is_rich_hierarchy=True
    )
    assert result is not None
    assert result["resource-id"] == "com.example:id/nested_button"

    result = find_element_by_resource_id(
        rich_hierarchy, "com.example:id/nonexistent", is_rich_hierarchy=True
    )
    assert result is None


def test_is_element_focused():
    focused_element = {"focused": "true"}
    assert is_element_focused(focused_element)

    non_focused_element = {"focused": "false"}
    assert not is_element_focused(non_focused_element)

    no_focused_element = {"text": "some text"}
    assert not is_element_focused(no_focused_element)

    none_focused_element = {"focused": None}
    assert not is_element_focused(none_focused_element)


def test_get_element_text():
    element = {"text": "Button Text", "hintText": "Hint Text"}
    assert get_element_text(element) == "Button Text"
    assert get_element_text(element, hint_text=False) == "Button Text"
    assert get_element_text(element, hint_text=True) == "Hint Text"

    element_no_text = {"hintText": "Hint Text"}
    assert get_element_text(element_no_text) is None
    assert get_element_text(element_no_text, hint_text=True) == "Hint Text"
    element_no_hint = {"text": "Button Text"}
    assert get_element_text(element_no_hint) == "Button Text"
    assert get_element_text(element_no_hint, hint_text=True) is None

    empty_element = {}
    assert get_element_text(empty_element) is None
    assert get_element_text(empty_element, hint_text=True) is None


def test_get_bounds_for_element():
    element_with_bounds = {"bounds": {"x": 10, "y": 20, "width": 100, "height": 50}}
    bounds = get_bounds_for_element(element_with_bounds)
    assert bounds is not None
    assert isinstance(bounds, ElementBounds)
    assert bounds.x == 10
    assert bounds.y == 20
    assert bounds.width == 100
    assert bounds.height == 50

    element_no_bounds = {"text": "Button"}
    bounds = get_bounds_for_element(element_no_bounds)
    assert bounds is None

    # Suppress logger output for the invalid bounds test case
    with patch("minitap.mobile_use.utils.ui_hierarchy.logger.error"):
        element_invalid_bounds = {
            "bounds": {
                "x": "invalid",  # Should be int
                "y": 20,
                "width": 100,
                "height": 50,
            }
        }
        bounds = get_bounds_for_element(element_invalid_bounds)
        assert bounds is None


def test_element_bounds():
    bounds = ElementBounds(x=10, y=20, width=100, height=50)

    center = bounds.get_center()
    assert isinstance(center, Point)
    assert center.x == 60
    assert center.y == 45

    center_point = bounds.get_relative_point(0.5, 0.5)
    assert isinstance(center_point, Point)
    assert center_point.x == 60
    assert center_point.y == 45

    top_left = bounds.get_relative_point(0.0, 0.0)
    assert top_left.x == 10
    assert top_left.y == 20

    bottom_right = bounds.get_relative_point(1.0, 1.0)
    assert bottom_right.x == 110
    assert bottom_right.y == 70
    custom_point = bounds.get_relative_point(0.95, 0.95)
    assert custom_point.x == 105
    assert custom_point.y == 67


if __name__ == "__main__":
    test_text_input_is_empty()
    test_find_element_by_resource_id()
    test_find_element_by_resource_id_rich_hierarchy()
    test_is_element_focused()
    test_get_element_text()
    test_get_bounds_for_element()
    test_element_bounds()
    print("All tests passed")
