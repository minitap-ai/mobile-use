"""Regression tests for the paper-era bugs fixed on paper/androidworld-rework (A10, A11)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from minitap.mobile_use.tools.types import Target
from minitap.mobile_use.utils.ui_hierarchy import (
    find_element_by_resource_id,
    get_bounds_for_element,
)

# Shape produced by clients/ui_automator_client.py (Android).
U2_FIELD = {
    "resource-id": "android:id/search_src_text",
    "class": "android.widget.AutoCompleteTextView",
    "text": "battery saver",
    "focused": "false",
    "bounds": "[126,118][537,181]",
}


def test_a10_resource_id_lookup_matches_uiautomator2_elements():
    ui = [{"resource-id": "x", "text": "other"}, U2_FIELD, {**U2_FIELD, "text": "second"}]
    assert find_element_by_resource_id(ui, "android:id/search_src_text")["text"] == "battery saver"
    assert find_element_by_resource_id(ui, "android:id/search_src_text", 1)["text"] == "second"
    # Maestro format still works
    assert find_element_by_resource_id([{"resourceId": "m", "text": "t"}], "m")["text"] == "t"
    assert find_element_by_resource_id(ui, "missing") is None


def test_a10_bounds_string_is_parsed():
    b = get_bounds_for_element(U2_FIELD)
    assert (b.x, b.y, b.width, b.height) == (126, 118, 411, 63)
    assert get_bounds_for_element({"bounds": {"x": 1, "y": 2, "width": 3, "height": 4}}).width == 3
    assert get_bounds_for_element({"bounds": "garbage"}) is None
    assert get_bounds_for_element({}) is None


@pytest.mark.asyncio
async def test_a10_focus_by_resource_id_awaits_the_tap():
    from minitap.mobile_use.tools import utils as tool_utils

    unfocused = {**U2_FIELD, "text": "", "focused": "false"}
    focused = {**U2_FIELD, "text": "", "focused": "true"}
    controller = MagicMock()
    controller.get_ui_elements = AsyncMock(side_effect=[[unfocused], [focused]])
    tap = AsyncMock(return_value=None)
    with (
        patch.object(tool_utils, "UnifiedMobileController", return_value=controller),
        patch.object(tool_utils, "tap", tap),
    ):
        method = await tool_utils.focus_element_if_needed(
            ctx=MagicMock(), target=Target(resource_id="android:id/search_src_text")
        )
    assert method == "resource_id"
    tap.assert_awaited_once()


@pytest.mark.asyncio
async def test_a11_swipe_default_duration_is_an_int():
    from minitap.mobile_use.tools.mobile import swipe as swipe_mod

    controller = MagicMock()
    controller.swipe_request = AsyncMock(return_value=None)
    state = MagicMock()
    state.asanitize_update = AsyncMock(side_effect=lambda ctx, update, agent: update)
    with patch.object(swipe_mod, "UnifiedMobileController", return_value=controller):
        tools = {t.name: t for t in swipe_mod.get_composite_swipe_tools(MagicMock())}
        await tools["swipe_percentages"].coroutine(
            agent_thought="scroll",
            start_x_percent=50,
            start_y_percent=80,
            end_x_percent=50,
            end_y_percent=20,
            tool_call_id="1",
            state=state,
        )
        await tools["swipe_coordinates"].coroutine(
            agent_thought="scroll",
            start_x=1,
            start_y=2,
            end_x=3,
            end_y=4,
            tool_call_id="2",
            state=state,
        )
    durations = [c.args[0].duration for c in controller.swipe_request.await_args_list]
    assert durations == [400, 400]
    schema = tools["swipe_percentages"].tool_call_schema.model_json_schema()
    assert "duration" not in schema.get("required", [])


# ---------------------------------------------------------------- legacy_v1_android_bugs


def _ctx(legacy: bool):
    from minitap.mobile_use.config import AblationConfig

    ctx = MagicMock()
    ctx.get_ablation_config.return_value = AblationConfig(legacy_v1_android_bugs=legacy)
    return ctx


def test_legacy_flag_restores_v1_lookup_and_bounds():
    ui = [U2_FIELD, {**U2_FIELD, "text": "second"}]
    assert find_element_by_resource_id(ui, "android:id/search_src_text", legacy_v1=True) is None
    assert get_bounds_for_element(U2_FIELD, legacy_v1=True) is None
    # v1 index bug on Maestro-format elements: index >= 1 never matches
    maestro = [{"resourceId": "m", "text": "a"}, {"resourceId": "m", "text": "b"}]
    assert find_element_by_resource_id(maestro, "m", 0, legacy_v1=True)["text"] == "a"
    assert find_element_by_resource_id(maestro, "m", 1, legacy_v1=True) is None
    assert find_element_by_resource_id(maestro, "m", 1)["text"] == "b"


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy,expected", [(False, "resource_id"), (True, "coordinates")])
async def test_legacy_flag_focus_falls_back_to_coordinates(legacy, expected):
    from minitap.mobile_use.tools import utils as tool_utils
    from minitap.mobile_use.utils.ui_hierarchy import ElementBounds

    unfocused = {**U2_FIELD, "text": "", "focused": "false"}
    focused = {**U2_FIELD, "text": "", "focused": "true"}
    controller = MagicMock()
    controller.get_ui_elements = AsyncMock(side_effect=[[unfocused], [focused]])
    tap = AsyncMock(return_value=None)
    target = Target(
        resource_id="android:id/search_src_text",
        bounds=ElementBounds(x=126, y=118, width=411, height=63),
    )
    with (
        patch.object(tool_utils, "UnifiedMobileController", return_value=controller),
        patch.object(tool_utils, "tap", tap),
    ):
        method = await tool_utils.focus_element_if_needed(ctx=_ctx(legacy), target=target)
    assert method == expected
    selectors = [type(c.kwargs["selector_request"]).__name__ for c in tap.await_args_list]
    assert selectors == (["SelectorRequestWithCoordinates"] if legacy else ["IdSelectorRequest"])


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_legacy_flag_restores_v1_swipe_failure_only_when_duration_omitted(legacy):
    from pydantic import ValidationError

    from minitap.mobile_use.tools.mobile import swipe as swipe_mod

    controller = MagicMock()
    controller.swipe_request = AsyncMock(return_value=None)
    state = MagicMock()
    state.asanitize_update = AsyncMock(side_effect=lambda ctx, update, agent: update)
    args = dict(
        agent_thought="scroll",
        start_x_percent=50,
        start_y_percent=80,
        end_x_percent=50,
        end_y_percent=20,
        tool_call_id="1",
        state=state,
    )
    with patch.object(swipe_mod, "UnifiedMobileController", return_value=controller):
        tool = {t.name: t for t in swipe_mod.get_composite_swipe_tools(_ctx(legacy))}[
            "swipe_percentages"
        ]
        # explicit duration works in both modes
        await tool.coroutine(**args, duration=300)
        if legacy:
            with pytest.raises(ValidationError, match="valid integer"):
                await tool.coroutine(**args)
        else:
            await tool.coroutine(**args)
    durations = [c.args[0].duration for c in controller.swipe_request.await_args_list]
    assert durations == ([300] if legacy else [300, 400])


@pytest.mark.asyncio
async def test_langchain_passes_the_marked_default_when_duration_is_omitted():
    """The legacy switch relies on LangChain calling the tool without the omitted argument, so the
    function sees the marked default object (and a plain int when the model sends 400)."""
    from typing import Annotated

    from langchain_core.tools import tool
    from pydantic import Field

    from minitap.mobile_use.tools.mobile.swipe import DEFAULT_SWIPE_DURATION_MS

    @tool
    async def probe(
        x: int, duration: Annotated[int, Field(ge=1)] = DEFAULT_SWIPE_DURATION_MS
    ) -> str:
        """probe"""
        return type(duration).__name__

    assert await probe.ainvoke({"x": 1}) == "_DefaultDuration"
    assert await probe.ainvoke({"x": 1, "duration": 400}) == "int"
