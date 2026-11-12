"""Unit tests of the deterministic P2 helpers (no device, no LLM)."""

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from minitap.mobile_use.agents.planner.types import Subgoal, SubgoalStatus
from minitap.mobile_use.robustness.calculator import calculate, convert, hms, seconds
from minitap.mobile_use.robustness.calendar_context import calendar_context, parse_device_date
from minitap.mobile_use.robustness.device_state import parse_ime_shown
from minitap.mobile_use.robustness.failure_streak import update_streak
from minitap.mobile_use.robustness.list_reader import Device, read_full_list
from minitap.mobile_use.robustness.planning import keep_completed_subgoals
from minitap.mobile_use.robustness.target_resolution import resolve_target_bounds
from minitap.mobile_use.utils.ui_hierarchy import ElementBounds

# ---------------------------------------------------------------- list reader (fake device)


class FakeList:
    """A RecyclerView of `items` rows (row height 100) in a container y=200..1000 (8 rows)."""

    def __init__(self, items, row_h=100, top=200, bottom=1000, fling_px=None):
        self.items, self.row_h, self.top, self.bottom = items, row_h, top, bottom
        self.offset = 0
        self.max_offset = max(0, len(items) * row_h - (bottom - top))
        self.swipes = 0

    def dump_xml(self):
        rows = []
        for i, text in enumerate(self.items):
            y1 = self.top + i * self.row_h - self.offset
            y2 = y1 + self.row_h
            if y2 <= self.top or y1 >= self.bottom:
                continue
            cy1, cy2 = max(y1, self.top), min(y2, self.bottom)
            rows.append(
                f'<node class="android.widget.LinearLayout" bounds="[0,{cy1}][720,{cy2}]">'
                f'<node class="android.widget.TextView" text="{text}" bounds="[10,{cy1}][700,{cy2}]"/>'
                f'</node>'
            )
        return (
            '<hierarchy><node class="android.widget.FrameLayout" bounds="[0,0][720,1280]">'
            '<node class="androidx.recyclerview.widget.RecyclerView" scrollable="true" '
            f'resource-id="app:id/list" bounds="[0,{self.top}][720,{self.bottom}]">'
            + "".join(rows)
            + "</node></node></hierarchy>"
        )

    def swipe(self, x1, y1, x2, y2, ms):
        self.swipes += 1
        self.offset = min(self.max_offset, max(0, self.offset + (y1 - y2)))

    def device(self):
        return Device(self.dump_xml, self.swipe, 720, 1280, settle_s=0)


@pytest.mark.parametrize("n", [3, 8, 9, 25, 61])
def test_reads_every_row_once_in_order(n):
    items = [f"Item {i:02d}" for i in range(n)]
    fake = FakeList(items)
    fake.offset = fake.max_offset // 2  # starts in the middle: must go to the top first
    res = read_full_list(fake.device())
    assert res.rows == items and res.reached_end
    assert fake.offset == 0  # back to the top


def test_true_duplicates_are_kept():
    items = ["A", "B", "Dup", "Dup", "C", "D", "E", "F", "Dup", "G", "H", "I", "J", "Dup", "Dup", "K"]
    res = read_full_list(FakeList(items).device())
    assert res.rows == items


def test_all_identical_rows_fall_back_without_losing_the_end():
    items = ["Same"] * 5 + [f"x{i}" for i in range(12)]
    res = read_full_list(FakeList(items).device())
    assert res.reached_end and res.rows[-12:] == items[-12:]


def test_no_scrollable_container():
    dev = Device(lambda: '<hierarchy><node class="a" bounds="[0,0][720,1280]"/></hierarchy>',
                 lambda *a: None, 720, 1280, settle_s=0)
    res = read_full_list(dev)
    assert res.error and "no scrollable" in res.render()


# ---------------------------------------------------------------- calculator / calendar


def test_calculator():
    assert calculate("10*9*5*5*3") == 6750
    assert calculate('round(convert(1.24, "mi", "m"))') == 1996
    assert calculate('hms(sum([seconds("3:45"), seconds("4:10"), seconds("1:02:03")]))') == "1:09:58"
    assert seconds("47:30") == 2850 and hms(2850) == "0:47:30"
    assert abs(convert(1, "km", "mi") - 0.621371) < 1e-5
    for bad in ("__import__('os')", "open('x')", "(1).__class__", "2**1000"):
        with pytest.raises(Exception):
            calculate(bad)


def test_calendar_context_weeks():
    assert parse_device_date("Sun Oct 15 15:34:21 UTC 2023").day == 15
    assert parse_device_date("Sun Oct 15 15:34:21 CEST 2023").year == 2023
    text = calendar_context("Sun Oct 15 15:34:21 UTC 2023")
    assert "Today: Sunday 2023-10-15" in text
    assert "Next week (Mon-Sun): Mon 2023-10-16 to Sun 2023-10-22" in text
    assert "This week (Mon-Sun): Mon 2023-10-09 to Sun 2023-10-15" in text
    assert "Next week (Sun-Sat): Sun 2023-10-22 to Sat 2023-10-28" in text
    assert "Last month: Fri 2023-09-01 to Sat 2023-09-30" in text
    assert calendar_context("garbage") is None and calendar_context(None) is None


# ---------------------------------------------------------------- target resolution


def _el(rid, text, x1, y1, x2, y2):
    return {"resource-id": rid, "text": text, "bounds": f"[{x1},{y1}][{x2},{y2}]"}


def test_center_written_as_top_left_is_corrected():
    live = [_el("app:id/fab", "", 311, 1448, 409, 1546)]
    given = ElementBounds(x=360, y=1497, width=98, height=98)  # centre as top-left
    res = resolve_target_bounds(live, given, "app:id/fab", 0, None, None)
    assert res.corrected and res.bounds.get_center().x == 360 and res.bounds.get_center().y == 1497


def test_correct_bounds_are_trusted_even_with_another_index():
    live = [_el("app:id/title", "Row A", 0, 100, 720, 200), _el("app:id/title", "Row B", 0, 200, 720, 300)]
    given = ElementBounds(x=0, y=200, width=720, height=100)  # row B, while index says 0
    res = resolve_target_bounds(live, given, "app:id/title", 0, None, None)
    assert not res.corrected and res.bounds == given


def test_nearest_live_match_when_index_is_ambiguous():
    live = [_el("r", "", 0, 100, 100, 200), _el("r", "", 0, 500, 100, 600)]
    given = ElementBounds(x=50, y=550, width=100, height=100)  # centre (100,600): just outside #2
    res = resolve_target_bounds(live, given, "r", 0, None, None)
    assert res.corrected and res.bounds.y == 500


def test_no_selector_or_no_match_keeps_bounds():
    given = ElementBounds(x=1, y=2, width=3, height=4)
    assert resolve_target_bounds([], given, None, None, None, None).bounds == given
    assert resolve_target_bounds([_el("a", "", 0, 0, 9, 9)], given, "zzz", 0, None, None).bounds == given


# ---------------------------------------------------------------- IME / replan / streak


def test_parse_ime_shown():
    assert parse_ime_shown("  mInputShown=true mDisplayId=0") is True
    assert parse_ime_shown("mInputShown=false") is False
    assert parse_ime_shown("nothing here") is None


def _sg(desc, status):
    return Subgoal(id=desc[:4], description=desc, status=status)


def test_replan_keeps_completed_and_drops_restatements():
    prev = [_sg("Open the app", SubgoalStatus.SUCCESS), _sg("Add item A", SubgoalStatus.SUCCESS),
            _sg("Add item B", SubgoalStatus.FAILURE)]
    new = [_sg("open the app.", SubgoalStatus.NOT_STARTED), _sg("Add item B", SubgoalStatus.NOT_STARTED),
           _sg("Verify the list", SubgoalStatus.NOT_STARTED)]
    out = keep_completed_subgoals(prev, new)
    assert [s.description for s in out] == ["Open the app", "Add item A", "Add item B", "Verify the list"]
    assert [s.status for s in out][:2] == [SubgoalStatus.SUCCESS] * 2


def _state_with_failure(tool, err):
    ai = AIMessage(content="", tool_calls=[{"name": tool, "args": {}, "id": "c1"}])
    tm = ToolMessage(content=err, tool_call_id="c1", status="error")
    return SimpleNamespace(executor_messages=[ai, tm])


def test_failure_streak_fires_on_second_identical_failure():
    ctx = SimpleNamespace(p2_failure_streak=None)
    assert update_streak(ctx, _state_with_failure("stop_video_recording", "too large 14.1 MB")) is None
    note = update_streak(ctx, _state_with_failure("stop_video_recording", "too large 14.3 MB"))
    assert note and "STRATEGY SWITCH" in note
    assert update_streak(ctx, SimpleNamespace(executor_messages=[])) is None
    assert ctx.p2_failure_streak is None


def test_text_restored_from_cortex_decision():
    import json

    from minitap.mobile_use.robustness.text_copy import restore_from_decision

    good = "Pulse cauliflower until it resembles rice. Sauté with vegetables and soy sauce."
    bad = "Pulse cauliflower until it resembles rice. Sã© with vegetables and soy sauce."
    dec = json.dumps([{"action": "focus_and_input_text", "text": good, "target": {"text": "Directions"}},
                      {"action": "focus_and_input_text", "text": "Fried Rice", "target": {}}])
    assert restore_from_decision(bad, dec) == good
    assert restore_from_decision(good, dec) is None  # exact copy: unchanged
    assert restore_from_decision("Something unrelated entirely", dec) is None
    assert restore_from_decision("Fried Rice", dec) is None
    assert restore_from_decision(bad, None) is None


def test_screenrecord_is_stopped_before_the_local_client():
    import asyncio

    from minitap.mobile_use.controllers.android_controller import p2_stop_screenrecord

    calls = []

    class Dev:
        alive = 2

        def shell(self, cmd):
            calls.append(cmd)
            if cmd.startswith("pidof"):
                Dev.alive -= 1
                return "1234" if Dev.alive > 0 else ""
            return ""

    class Proc:
        async def wait(self):
            calls.append("local_wait")

        def kill(self):
            calls.append("kill")

    asyncio.run(p2_stop_screenrecord(Dev(), Proc(), timeout_s=5))
    assert calls[0].startswith("pkill -2 screenrecord")
    assert calls.index("local_wait") > max(i for i, c in enumerate(calls) if c.startswith("pidof"))
    assert "kill" not in calls


def test_screen_log_keeps_recent_distinct_screens():
    from minitap.mobile_use.robustness.screen_log import MAX_SCREENS, record_screen, render_screen_log

    ctx = SimpleNamespace(p2_screen_log=None)
    for i in range(MAX_SCREENS + 5):
        els = [{"text": f"Item {i}", "children": [{"content-desc": "Category Others"}]}]
        record_screen(ctx, i, "app", els)
        record_screen(ctx, i, "app", els)  # identical consecutive screen: not duplicated
    assert len(ctx.p2_screen_log) == MAX_SCREENS
    text = render_screen_log(ctx.p2_screen_log)
    assert "Item 18 | Category Others" in text and "Item 0 " not in text


def test_geometry_only_centre_as_top_left():
    from minitap.mobile_use.robustness.target_resolution import snap_centre_written_as_top_left

    live = [_el("", "", 576, 1426, 720, 1536)]  # a 144x110 button at the right edge
    given = ElementBounds(x=648, y=1481, width=144, height=110)  # its centre as top-left
    r = snap_centre_written_as_top_left(live, given, 720, 1600)
    assert r.corrected and r.bounds.get_center().x == 648 and r.bounds.get_center().y == 1481
    # no matching live element, box off-screen, x/y on screen -> x/y used as the centre
    r = snap_centre_written_as_top_left([], given, 720, 1600)
    assert r.corrected and r.bounds.x == 576
    # consistent geometry: unchanged
    ok = ElementBounds(x=100, y=100, width=50, height=50)
    assert not snap_centre_written_as_top_left([], ok, 720, 1600).corrected


def test_replan_never_ends_with_an_all_done_plan():
    prev = [_sg("Draw with the three colours", SubgoalStatus.SUCCESS),
            _sg("Submit the drawing", SubgoalStatus.SUCCESS),
            _sg("Satisfy the remaining goal requirement: tap Submit", SubgoalStatus.FAILURE)]
    out = keep_completed_subgoals(prev, [_sg("Submit the drawing", SubgoalStatus.NOT_STARTED)])
    assert [s.status for s in out].count(SubgoalStatus.NOT_STARTED) == 1
    out = keep_completed_subgoals(prev, [])
    assert out[-1].status == SubgoalStatus.NOT_STARTED and "tap Submit" in out[-1].description


def test_screen_log_keeps_the_last_screen_of_an_app_that_left_the_window():
    from minitap.mobile_use.robustness.screen_log import MAX_SCREENS, record_screen

    ctx = SimpleNamespace(p2_screen_log=None)
    record_screen(ctx, 0, "source.app", [{"text": "Row 1 | Row 2 | Row 3"}])
    for i in range(1, MAX_SCREENS + 3):
        record_screen(ctx, i, "target.app", [{"text": f"form {i}"}])
    apps = [e["app"] for e in ctx.p2_screen_log]
    assert apps[0] == "source.app" and len(ctx.p2_screen_log) == MAX_SCREENS + 1
