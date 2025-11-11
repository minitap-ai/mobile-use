import sys
from unittest.mock import Mock, patch

import pytest

# Mock the problematic langgraph import at module level
sys.modules["langgraph.prebuilt.chat_agent_executor"] = Mock()
sys.modules["minitap.mobile_use.graph.state"] = Mock()

from minitap.mobile_use.context import MobileUseContext  # noqa: E402
from minitap.mobile_use.controllers.mobile_command_controller import (  # noqa: E402
    IdSelectorRequest,
    SelectorRequestWithCoordinates,
)
from minitap.mobile_use.tools.types import Target  # noqa: E402
from minitap.mobile_use.tools.utils import (  # noqa: E402
    focus_element_if_needed,
    move_cursor_to_end_if_bounds,
)
from minitap.mobile_use.utils.ui_hierarchy import ElementBounds  # noqa: E402


@pytest.fixture
def mock_context():
    """Create a mock MobileUseContext for testing."""
    ctx = Mock(spec=MobileUseContext)
    ctx.hw_bridge_client = Mock()
    return ctx


@pytest.fixture
def mock_state():
    """Create a mock State for testing."""
    state = Mock()
    state.latest_ui_hierarchy = []
    return state


@pytest.fixture
def sample_element():
    """Create a sample UI element for testing."""
    return {
        "resourceId": "com.example:id/text_input",
        "text": "Sample text",
        "bounds": {"x": 100, "y": 200, "width": 300, "height": 50},
        "focused": "false",
    }


@pytest.fixture
def sample_rich_element():
    """Create a sample rich UI element for testing."""
    return {
        "attributes": {
            "resource-id": "com.example:id/text_input",
            "focused": "false",
            "text": "Sample text",
            "bounds": {"x": 100, "y": 200, "width": 300, "height": 50},
        },
        "children": [],
    }


class TestMoveCursorToEndIfBounds:
    """Test cases for move_cursor_to_end_if_bounds function."""

    @patch("minitap.mobile_use.tools.utils.tap")
    @patch("minitap.mobile_use.tools.utils.find_element_by_resource_id")
    def test_move_cursor_with_resource_id(
        self, mock_find_element, mock_tap, mock_context, mock_state, sample_element
    ):
        """Test moving cursor using resource_id (highest priority)."""
        mock_state.latest_ui_hierarchy = [sample_element]
        mock_find_element.return_value = sample_element

        target = Target(
            resource_id="com.example:id/text_input",
            resource_id_index=None,
            text=None,
            text_index=None,
            coordinates=None,
        )
        result = move_cursor_to_end_if_bounds(ctx=mock_context, state=mock_state, target=target)

        mock_find_element.assert_called_once_with(
            ui_hierarchy=[sample_element],
            resource_id="com.example:id/text_input",
            index=0,
        )
        mock_tap.assert_called_once()
        call_args = mock_tap.call_args[1]
        selector_request = call_args["selector_request"]
        assert isinstance(selector_request, SelectorRequestWithCoordinates)
        coords = selector_request.coordinates
        assert coords.x == 397  # 100 + 300 * 0.99
        assert coords.y == 249  # 200 + 50 * 0.99
        assert result == sample_element

    @patch("minitap.mobile_use.tools.utils.tap")
    @patch("minitap.mobile_use.tools.utils.find_element_by_resource_id")
    def test_move_cursor_with_coordinates_only(
        self, mock_find_element, mock_tap, mock_context, mock_state
    ):
        """Test moving cursor when only coordinates are provided."""
        bounds = ElementBounds(x=50, y=150, width=200, height=40)
        target = Target(
            resource_id=None,
            resource_id_index=None,
            text=None,
            text_index=None,
            coordinates=bounds,
        )

        result = move_cursor_to_end_if_bounds(ctx=mock_context, state=mock_state, target=target)

        mock_find_element.assert_not_called()
        mock_tap.assert_called_once()
        call_args = mock_tap.call_args[1]
        selector_request = call_args["selector_request"]
        coords = selector_request.coordinates
        assert coords.x == 248  # 50 + 200 * 0.99
        assert coords.y == 189  # 150 + 40 * 0.99
        assert result is None  # No element is returned when using coords directly

    @patch("minitap.mobile_use.tools.utils.tap")
    @patch("minitap.mobile_use.tools.utils.find_element_by_text")
    def test_move_cursor_with_text_only_success(
        self, mock_find_text, mock_tap, mock_context, mock_state, sample_element
    ):
        """Test moving cursor when only text is provided and succeeds."""
        mock_state.latest_ui_hierarchy = [sample_element]
        mock_find_text.return_value = sample_element

        target = Target(
            resource_id=None,
            resource_id_index=None,
            text="Sample text",
            text_index=0,
            coordinates=None,
        )
        result = move_cursor_to_end_if_bounds(ctx=mock_context, state=mock_state, target=target)

        mock_find_text.assert_called_once_with([sample_element], "Sample text", index=0)
        mock_tap.assert_called_once()
        assert result == sample_element

    @patch("minitap.mobile_use.tools.utils.tap")
    @patch("minitap.mobile_use.tools.utils.find_element_by_text")
    def test_move_cursor_with_text_only_element_not_found(
        self, mock_find_text, mock_tap, mock_context, mock_state
    ):
        """Test when searching by text finds no element."""
        mock_state.latest_ui_hierarchy = []
        mock_find_text.return_value = None

        target = Target(
            resource_id=None,
            resource_id_index=None,
            text="Nonexistent text",
            text_index=None,
            coordinates=None,
        )
        result = move_cursor_to_end_if_bounds(ctx=mock_context, state=mock_state, target=target)

        mock_tap.assert_not_called()
        assert result is None

    @patch("minitap.mobile_use.tools.utils.tap")
    @patch("minitap.mobile_use.tools.utils.find_element_by_text")
    def test_move_cursor_with_text_only_no_bounds(
        self, mock_find_text, mock_tap, mock_context, mock_state
    ):
        """Test when element is found by text but has no bounds."""
        element_no_bounds = {"text": "Text without bounds"}
        mock_state.latest_ui_hierarchy = [element_no_bounds]
        mock_find_text.return_value = element_no_bounds

        target = Target(
            resource_id=None,
            resource_id_index=None,
            text="Text without bounds",
            text_index=None,
            coordinates=None,
        )
        result = move_cursor_to_end_if_bounds(ctx=mock_context, state=mock_state, target=target)

        mock_tap.assert_not_called()
        assert result is None  # Should return None as no action was taken

    @patch("minitap.mobile_use.tools.utils.find_element_by_resource_id")
    def test_move_cursor_element_not_found_by_id(self, mock_find_element, mock_context, mock_state):
        """Test when element is not found by resource_id."""
        mock_find_element.return_value = None

        target = Target(
            resource_id="com.example:id/nonexistent",
            resource_id_index=None,
            text=None,
            text_index=None,
            coordinates=None,
        )
        result = move_cursor_to_end_if_bounds(ctx=mock_context, state=mock_state, target=target)

        assert result is None


class TestFocusElementIfNeeded:
    """Test cases for focus_element_if_needed function."""

    @patch("minitap.mobile_use.tools.utils.tap")
    @patch("minitap.mobile_use.tools.utils.find_element_by_resource_id")
    def test_focus_element_already_focused(
        self, mock_find_element, mock_tap, mock_context, sample_rich_element
    ):
        """Test when element is already focused."""
        focused_element = sample_rich_element.copy()
        focused_element["attributes"]["focused"] = "true"

        mock_context.hw_bridge_client.get_rich_hierarchy.return_value = [focused_element]
        mock_find_element.return_value = focused_element["attributes"]

        target = Target(
            resource_id="com.example:id/text_input",
            resource_id_index=None,
            text=None,
            text_index=None,
            coordinates=None,
        )
        result = focus_element_if_needed(ctx=mock_context, target=target)

        mock_tap.assert_not_called()
        assert result == "resource_id"
        mock_context.hw_bridge_client.get_rich_hierarchy.assert_called_once()

    @patch("minitap.mobile_use.tools.utils.tap")
    @patch("minitap.mobile_use.tools.utils.find_element_by_resource_id")
    def test_focus_element_needs_focus_success(
        self, mock_find_element, mock_tap, mock_context, sample_rich_element
    ):
        """Test when element needs focus and focusing succeeds."""
        unfocused_element = sample_rich_element
        focused_element = {
            "attributes": {
                "resource-id": "com.example:id/text_input",
                "focused": "true",
            },
            "children": [],
        }

        mock_context.hw_bridge_client.get_rich_hierarchy.side_effect = [
            [unfocused_element],
            [focused_element],
        ]
        mock_find_element.side_effect = [
            unfocused_element["attributes"],
            focused_element["attributes"],
        ]

        target = Target(
            resource_id="com.example:id/text_input",
            resource_id_index=None,
            text=None,
            text_index=None,
            coordinates=None,
        )
        result = focus_element_if_needed(ctx=mock_context, target=target)

        mock_tap.assert_called_once_with(
            ctx=mock_context,
            selector_request=IdSelectorRequest(id="com.example:id/text_input"),
            index=0,
        )
        assert mock_context.hw_bridge_client.get_rich_hierarchy.call_count == 2
        assert result == "resource_id"

    @patch("minitap.mobile_use.tools.utils.tap")
    @patch("minitap.mobile_use.tools.utils.logger")
    @patch("minitap.mobile_use.tools.utils.find_element_by_resource_id")
    def test_focus_id_and_text_mismatch_fallback_to_text(
        self, mock_find_id, mock_logger, mock_tap, mock_context, sample_rich_element
    ):
        """Test fallback when resource_id and text point to different elements."""
        element_from_id = sample_rich_element["attributes"].copy()
        element_from_id["text"] = "Different text"

        element_from_text = sample_rich_element.copy()
        element_from_text["attributes"]["bounds"] = {
            "x": 10,
            "y": 20,
            "width": 100,
            "height": 30,
        }

        mock_context.hw_bridge_client.get_rich_hierarchy.return_value = [element_from_text]
        mock_find_id.return_value = element_from_id

        with patch("minitap.mobile_use.tools.utils.find_element_by_text") as mock_find_text:
            mock_find_text.return_value = element_from_text["attributes"]

            target = Target(
                resource_id="com.example:id/text_input",
                resource_id_index=None,
                text="Sample text",
                text_index=None,
                coordinates=None,
            )
            result = focus_element_if_needed(ctx=mock_context, target=target)

            mock_logger.warning.assert_called_once()
            mock_tap.assert_called_once()
            assert result == "text"

    @patch("minitap.mobile_use.tools.utils.tap")
    @patch("minitap.mobile_use.tools.utils.find_element_by_text")
    def test_focus_fallback_to_text(
        self, mock_find_text, mock_tap, mock_context, sample_rich_element
    ):
        """Test fallback to focusing using text."""
        element_with_bounds = sample_rich_element.copy()
        element_with_bounds["attributes"]["bounds"] = {
            "x": 10,
            "y": 20,
            "width": 100,
            "height": 30,
        }

        mock_context.hw_bridge_client.get_rich_hierarchy.return_value = [element_with_bounds]
        mock_find_text.return_value = element_with_bounds["attributes"]

        target = Target(
            resource_id=None,
            resource_id_index=None,
            text="Sample text",
            text_index=None,
            coordinates=None,
        )
        result = focus_element_if_needed(ctx=mock_context, target=target)

        mock_find_text.assert_called_once()
        mock_tap.assert_called_once()
        call_args = mock_tap.call_args[1]
        selector = call_args["selector_request"]
        assert isinstance(selector, SelectorRequestWithCoordinates)
        assert selector.coordinates.x == 60  # 10 + 100/2
        assert selector.coordinates.y == 35  # 20 + 30/2
        assert result == "text"

    @patch("minitap.mobile_use.tools.utils.logger")
    def test_focus_all_locators_fail(self, mock_logger, mock_context):
        """Test failure when no locator can find an element."""
        mock_context.hw_bridge_client.get_rich_hierarchy.return_value = []

        with (
            patch("minitap.mobile_use.tools.utils.find_element_by_resource_id") as mock_find_id,
            patch("minitap.mobile_use.tools.utils.find_element_by_text") as mock_find_text,
        ):
            mock_find_id.return_value = None
            mock_find_text.return_value = None

            target = Target(
                resource_id="nonexistent",
                resource_id_index=None,
                text="nonexistent",
                text_index=None,
                coordinates=None,
            )
            result = focus_element_if_needed(ctx=mock_context, target=target)

        mock_logger.error.assert_called_once_with(
            "Failed to focus element."
            + " No valid locator (resource_id, coordinates, or text) succeeded."
        )
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__])
