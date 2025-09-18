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
from minitap.mobile_use.tools.utils import (  # noqa: E402
    focus_element_if_needed,
    move_cursor_to_end_if_bounds,
)


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
        },
        "children": [],
    }


class TestMoveCursorToEndIfBounds:
    """Test cases for move_cursor_to_end_if_bounds function."""

    @patch("minitap.mobile_use.tools.utils.tap")
    @patch("minitap.mobile_use.tools.utils.find_element_by_resource_id")
    def test_move_cursor_with_element_and_bounds(
        self, mock_find_element, mock_tap, mock_context, mock_state, sample_element
    ):
        """Test moving cursor when element has bounds."""
        mock_state.latest_ui_hierarchy = [sample_element]
        mock_find_element.return_value = sample_element

        result = move_cursor_to_end_if_bounds(
            ctx=mock_context,
            state=mock_state,
            text_input_resource_id="com.example:id/text_input",
            text_input_coordinates=sample_element["bounds"],
            text_input_text=sample_element["text"],
        )

        # Verify element was found
        mock_find_element.assert_called_once_with(
            ui_hierarchy=[sample_element], resource_id="com.example:id/text_input"
        )

        # Verify tap was called with correct coordinates
        mock_tap.assert_called_once()
        call_args = mock_tap.call_args[1]
        assert call_args["ctx"] == mock_context

        # Check that coordinates are calculated correctly (99% of width and height)
        selector_request = call_args["selector_request"]
        assert isinstance(selector_request, SelectorRequestWithCoordinates)
        coords = selector_request.coordinates
        assert coords.x == 397  # 100 + 300 * 0.99 = 397
        assert coords.y == 249  # 200 + 50 * 0.99 = 249

        # Verify return value
        assert result == sample_element

    @patch("minitap.mobile_use.tools.utils.find_element_by_resource_id")
    def test_move_cursor_with_provided_element(
        self, mock_find_element, mock_context, mock_state, sample_element
    ):
        """Test moving cursor when element is provided directly."""
        with patch("minitap.mobile_use.tools.utils.tap") as mock_tap:
            result = move_cursor_to_end_if_bounds(
                ctx=mock_context,
                state=mock_state,
                text_input_resource_id="com.example:id/text_input",
                text_input_coordinates=sample_element["bounds"],
                text_input_text=sample_element["text"],
                elt=sample_element,
            )

            # Should not search for element since it's provided
            mock_find_element.assert_not_called()

            # Should still tap
            mock_tap.assert_called_once()
            assert result == sample_element

    @patch("minitap.mobile_use.tools.utils.find_element_by_resource_id")
    def test_move_cursor_element_not_found(self, mock_find_element, mock_context, mock_state):
        """Test when element is not found."""
        mock_state.latest_ui_hierarchy = []
        mock_find_element.return_value = None

        result = move_cursor_to_end_if_bounds(
            ctx=mock_context,
            state=mock_state,
            text_input_resource_id="com.example:id/nonexistent",
            text_input_coordinates=None,
            text_input_text=None,
        )

        assert result is None

    @patch("minitap.mobile_use.tools.utils.tap")
    def test_move_cursor_element_without_bounds(self, mock_tap, mock_context, mock_state):
        """Test when element exists but has no bounds."""
        element_no_bounds = {
            "resourceId": "com.example:id/text_input",
            "text": "Sample text",
        }

        result = move_cursor_to_end_if_bounds(
            ctx=mock_context,
            state=mock_state,
            text_input_resource_id="com.example:id/text_input",
            text_input_coordinates=None,
            text_input_text=None,
            elt=element_no_bounds,
        )

        # Should not tap since no bounds
        mock_tap.assert_not_called()
        assert result == element_no_bounds

    @patch("minitap.mobile_use.tools.utils.find_element_by_resource_id")
    def test_move_cursor_empty_ui_hierarchy(self, mock_find_element, mock_context, mock_state):
        """Test when UI hierarchy is None."""
        mock_state.latest_ui_hierarchy = None
        mock_find_element.return_value = None

        result = move_cursor_to_end_if_bounds(
            ctx=mock_context,
            state=mock_state,
            text_input_resource_id="com.example:id/text_input",
            text_input_coordinates=None,
            text_input_text=None,
        )

        mock_find_element.assert_called_once_with(
            ui_hierarchy=[], resource_id="com.example:id/text_input"
        )
        assert result is None


class TestFocusElementIfNeeded:
    """Test cases for focus_element_if_needed function."""

    @patch("minitap.mobile_use.tools.utils.tap")
    @patch("minitap.mobile_use.tools.utils.find_element_by_resource_id")
    def test_focus_element_already_focused(
        self, mock_find_element, mock_tap, mock_context, sample_rich_element
    ):
        """Test when element is already focused."""
        # Element is already focused
        focused_element = sample_rich_element.copy()
        focused_element["attributes"]["focused"] = "true"

        mock_context.hw_bridge_client.get_rich_hierarchy.return_value = [focused_element]
        mock_find_element.return_value = focused_element["attributes"]

        result = focus_element_if_needed(
            ctx=mock_context,
            text_input_resource_id="com.example:id/text_input",
            text_input_coordinates=None,
            text_input_text=None,
        )

        # Should not tap since already focused
        mock_tap.assert_not_called()
        assert result is True

        # Should check hierarchy once
        mock_context.hw_bridge_client.get_rich_hierarchy.assert_called_once()

    @patch("minitap.mobile_use.tools.utils.tap")
    @patch("minitap.mobile_use.tools.utils.find_element_by_resource_id")
    def test_focus_element_needs_focus_success(
        self, mock_find_element, mock_tap, mock_context, sample_rich_element
    ):
        """Test when element needs focus and focusing succeeds."""
        # Create deep copies to avoid reference issues
        unfocused_element = {
            "attributes": {
                "resource-id": "com.example:id/text_input",
                "focused": "false",
            },
            "children": [],
        }

        focused_element = {
            "attributes": {
                "resource-id": "com.example:id/text_input",
                "focused": "true",
            },
            "children": [],
        }

        # Mock hierarchy calls - first unfocused, then focused
        mock_context.hw_bridge_client.get_rich_hierarchy.side_effect = [
            [unfocused_element],
            [focused_element],
        ]

        # Mock find_element calls - return attributes
        mock_find_element.side_effect = [
            unfocused_element["attributes"],
            focused_element["attributes"],
        ]

        result = focus_element_if_needed(
            ctx=mock_context,
            text_input_resource_id="com.example:id/text_input",
            text_input_coordinates=None,
            text_input_text=None,
        )

        # Should tap to focus
        mock_tap.assert_called_once_with(
            ctx=mock_context,
            selector_request=IdSelectorRequest(id="com.example:id/text_input"),
        )

        # Should get hierarchy twice (before and after tap)
        assert mock_context.hw_bridge_client.get_rich_hierarchy.call_count == 2

        assert result is True

    @patch("minitap.mobile_use.tools.utils.tap")
    @patch("minitap.mobile_use.tools.utils.find_element_by_resource_id")
    def test_focus_element_needs_focus_fails(
        self, mock_find_element, mock_tap, mock_context, sample_rich_element
    ):
        """Test when element needs focus but focusing fails."""
        # Remains unfocused even after tap
        unfocused_element = sample_rich_element.copy()
        unfocused_element["attributes"]["focused"] = "false"

        mock_context.hw_bridge_client.get_rich_hierarchy.return_value = [unfocused_element]
        mock_find_element.return_value = unfocused_element["attributes"]

        result = focus_element_if_needed(
            ctx=mock_context,
            text_input_resource_id="com.example:id/text_input",
            text_input_coordinates=None,
            text_input_text=None,
        )

        # Should tap to try to focus
        mock_tap.assert_called_once()

        # Should get hierarchy twice
        assert mock_context.hw_bridge_client.get_rich_hierarchy.call_count == 2

        assert result is False

    @patch("minitap.mobile_use.tools.utils.find_element_by_resource_id")
    def test_focus_element_not_found(self, mock_find_element, mock_context):
        """Test when element is not found in hierarchy."""
        mock_context.hw_bridge_client.get_rich_hierarchy.return_value = []
        mock_find_element.return_value = None

        result = focus_element_if_needed(
            ctx=mock_context,
            text_input_resource_id="com.example:id/nonexistent",
            text_input_coordinates=None,
            text_input_text=None,
        )

        assert result is False

    @patch("minitap.mobile_use.tools.utils.tap")
    @patch("minitap.mobile_use.tools.utils.find_element_by_resource_id")
    def test_focus_element_disappears_after_tap(
        self, mock_find_element, mock_tap, mock_context, sample_rich_element
    ):
        """Test when element disappears after tap."""
        unfocused_element = sample_rich_element.copy()
        unfocused_element["attributes"]["focused"] = "false"

        # First call returns element, second call returns None
        mock_context.hw_bridge_client.get_rich_hierarchy.side_effect = [
            [unfocused_element],
            [],
        ]

        mock_find_element.side_effect = [
            unfocused_element["attributes"],
            None,
        ]

        result = focus_element_if_needed(
            ctx=mock_context,
            text_input_resource_id="com.example:id/text_input",
            text_input_coordinates=None,
            text_input_text=None,
        )

        mock_tap.assert_called_once()
        assert result is False

    @patch("minitap.mobile_use.tools.utils.logger")
    @patch("minitap.mobile_use.tools.utils.tap")
    @patch("minitap.mobile_use.tools.utils.find_element_by_resource_id")
    def test_focus_element_logging(
        self, mock_find_element, mock_tap, mock_logger, mock_context, sample_rich_element
    ):
        """Test that appropriate log messages are generated."""
        focused_element = sample_rich_element.copy()
        focused_element["attributes"]["focused"] = "true"

        mock_context.hw_bridge_client.get_rich_hierarchy.return_value = [focused_element]
        mock_find_element.return_value = focused_element["attributes"]

        focus_element_if_needed(
            ctx=mock_context,
            text_input_resource_id="com.example:id/text_input",
            text_input_coordinates=None,
            text_input_text=None,
        )

        # Should log successful focus
        mock_logger.debug.assert_called_with("Text input is focused: com.example:id/text_input")


if __name__ == "__main__":
    pytest.main([__file__])
