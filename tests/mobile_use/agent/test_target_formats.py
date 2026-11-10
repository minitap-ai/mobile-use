"""Fix round 6: unambiguous target/bounds formats written by the model are accepted."""

import pytest

from minitap.mobile_use.tools.types import Target
from minitap.mobile_use.utils.ui_hierarchy import ElementBounds


@pytest.mark.parametrize(
    "raw,expected",
    [
        ({"x": 10, "y": 20, "width": 30, "height": 40}, (10, 20, 30, 40)),
        ({"left": 10, "top": 20, "right": 40, "bottom": 60}, (10, 20, 30, 40)),
        ("[10,20][40,60]", (10, 20, 30, 40)),
        ({"x": 350, "y": 100}, (350, 100, 0, 0)),
    ],
)
def test_bounds_formats(raw, expected):
    b = ElementBounds.model_validate(raw)
    assert (b.x, b.y, b.width, b.height) == expected


def test_point_bounds_tap_at_the_point():
    assert ElementBounds.model_validate({"x": 350, "y": 100}).get_center().model_dump() == {
        "x": 350,
        "y": 100,
    }


def test_target_as_json_string():
    t = Target.model_validate(
        '{"resource_id": "id/field", "bounds": {"x": 1, "y": 2, "width": 3, "height": 4}}'
    )
    assert t.resource_id == "id/field" and t.bounds.width == 3


def test_invalid_inputs_still_fail():
    with pytest.raises(Exception):
        Target.model_validate("not json")
    with pytest.raises(Exception):
        ElementBounds.model_validate({"left": 1, "top": 2})


def test_tool_schema_unchanged():
    props = ElementBounds.model_json_schema()["properties"]
    assert set(props) == {"x", "y", "width", "height"}
