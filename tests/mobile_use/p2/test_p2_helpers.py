"""Unit tests of the deterministic P2 helpers (no device, no LLM)."""

import asyncio
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
    assert "kill -2" in calls[0] and "pkill" not in calls[0]
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


def test_read_full_list_tool_end_to_end(monkeypatch):
    """Regression: the @tool function shadowed the imported helper (every call failed with
    "argument of type 'Device' is not iterable" in dev rounds 2-5)."""
    import asyncio

    from minitap.mobile_use.tools import p2_tools

    items = [f"Row {i}" for i in range(20)]
    fake = FakeList(items)
    monkeypatch.setattr(p2_tools, "android_device", lambda ctx: fake.device())

    class _State:
        async def asanitize_update(self, ctx, update, agent=None):
            return update

    ctx = SimpleNamespace(p2_tool_evidence=None)
    tool = p2_tools.get_read_full_list_tool(ctx)
    cmd = asyncio.run(
        tool.coroutine(agent_thought="read", tool_call_id="c1", state=_State(), container_resource_id=None)
    )
    msg = cmd.update["executor_messages"][0]
    assert msg.status == "success", msg.content
    assert "Read 20 rows" in msg.content and "END OF LIST REACHED" in msg.content
    assert ctx.p2_tool_evidence and "Row 19" in ctx.p2_tool_evidence[-1]


def test_sample_colors_exact_hex():
    from PIL import Image

    from minitap.mobile_use.tools.p2_tools import sample_colors_at

    img = Image.new("RGB", (40, 40), (255, 255, 255))
    for x in range(10, 20):
        for y in range(10, 20):
            img.putpixel((x, y), (0xFF, 0x8C, 0x00))  # dark orange, not orange (#ffa500)
    out = sample_colors_at(img, [{"x": 15, "y": 15, "label": "swatch"}, {"x": 99, "y": 1}])
    assert out[0].startswith("(15,15) swatch: #ff8c00") and "outside" in out[1]


def test_target_exists_checks_id_text_desc_and_hint():
    from minitap.mobile_use.robustness.target_resolution import target_exists

    live = [{"resource-id": "answer", "text": "", "hint": "Your answer", "children": [
        {"content-desc": "Go", "bounds": "[0,0][1,1]"}]}]
    assert target_exists(live, "answer", None)
    assert target_exists(live, None, "Your answer")
    assert target_exists(live, None, "Go")
    assert not target_exists(live, "com.example.calculate:id/field", "Enter expression")


def test_executor_completion_appends_missing_predictable_actions():
    import json

    from minitap.mobile_use.robustness.executor_completion import completion_calls
    from minitap.mobile_use.tools.p2_tools import get_calculate_tool

    class _Schema:
        @staticmethod
        def model_validate(args):
            if "target" not in args:
                raise ValueError("target missing")

    class _T:
        def __init__(self, name):
            self.name, self.tool_call_schema = name, _Schema

    tools = {n: _T(n) for n in ("focus_and_input_text", "tap", "back")}
    dec = json.dumps([
        {"action": "focus_and_input_text", "text": "a", "target": {"resource_id": "f1"}},
        {"action": "focus_and_input_text", "text": "b", "target": {"resource_id": "f2"}},
        {"action": "tap", "target": {"text": "Save"}},
        {"action": "back", "target": {}},
    ])
    emitted = [{"name": "focus_and_input_text", "args": {"text": "a"}, "id": "x"}]
    extra = completion_calls(dec, emitted, tools)
    # completes field 2, then the screen-changing tap, and stops before 'back'
    assert [c["name"] for c in extra] == ["focus_and_input_text", "tap"]
    assert extra[0]["args"]["text"] == "b" and extra[0]["args"]["agent_thought"]
    # nothing emitted at all: dispatch from the start
    assert [c["name"] for c in completion_calls(dec, [], tools)][:2] == ["focus_and_input_text"] * 2
    # the Executor already ended on a screen-changing action: append nothing
    assert completion_calls(dec, [{"name": "tap", "args": {}, "id": "y"}], tools) == []
    # an invalid decided action stops the completion
    bad = json.dumps([{"action": "focus_and_input_text", "text": "a"}])
    assert completion_calls(bad, [], tools) == []
    assert get_calculate_tool  # import sanity


def test_sample_colors_point_shapes():
    from minitap.mobile_use.tools.p2_tools import normalize_points

    assert normalize_points("[[250, 260], [300, 261]]") == [{"x": 250, "y": 260}, {"x": 300, "y": 261}]
    assert normalize_points([{"x": 1, "y": 2, "label": "ref"}]) == [{"x": 1, "y": 2, "label": "ref"}]
    assert normalize_points({"x": 3, "y": 4}) == [{"x": 3, "y": 4}]
    assert normalize_points("not json") == [] and normalize_points(None) == []


class FakeListWithDetails(FakeList):
    """Rows open a detail screen (all fields) on tap; BACK returns to the list, same offset."""

    def __init__(self, items, details, **kw):
        super().__init__(items, **kw)
        self.details, self.open = details, None
        self.taps = 0

    def dump_xml(self):
        if self.open is None:
            return super().dump_xml()
        fields = "".join(f'<node class="android.widget.TextView" text="{t}" bounds="[0,{200+i*60}][720,{250+i*60}]"/>'
                         for i, t in enumerate(self.details[self.open]))
        return f'<hierarchy><node class="android.widget.FrameLayout" bounds="[0,0][720,1280]">{fields}</node></hierarchy>'

    def tap(self, x, y):
        self.taps += 1
        idx = (y - self.top + self.offset) // self.row_h
        if self.open is None and 0 <= idx < len(self.items):
            self.open = idx

    def back(self):
        self.open = None

    def device(self):
        return Device(self.dump_xml, self.swipe, 720, 1280, settle_s=0, tap=self.tap, back=self.back)


def test_inspect_rows_reads_every_matching_row_including_identical_cards():
    from minitap.mobile_use.robustness.row_inspector import inspect_rows

    items = [f"Other {i}" for i in range(6)] + ["Soup | Warm"] * 3 + [f"Tail {i}" for i in range(8)] + ["Soup | Warm"]
    details = [[f"title {it}", f"servings {i}"] for i, it in enumerate(items)]
    fake = FakeListWithDetails(items, details)
    res = inspect_rows(fake.device(), "soup")
    assert res.error is None and res.stopped is None, res.render()
    assert [r["details"][1] for r in res.rows] == ["servings 6", "servings 7", "servings 8", "servings 17"]
    assert fake.open is None  # back on the list


def test_executor_completion_never_redispatches_an_emitted_action():
    import json

    from minitap.mobile_use.robustness.executor_completion import completion_calls

    class _Schema:
        @staticmethod
        def model_validate(args):
            return args

    class _T:
        def __init__(self, name):
            self.name, self.tool_call_schema = name, _Schema

    tools = {n: _T(n) for n in ("focus_and_input_text", "tap")}
    shutter = {"resource_id": "cam:id/shutter_button"}
    dec = json.dumps([
        {"action": "focus_and_input_text", "text": "a", "target": {"resource_id": "f1"}},
        {"action": "tap", "target": shutter},
    ])
    # the Executor emitted the shutter tap first (out of the decided order): it must not be re-dispatched
    emitted = [{"name": "tap", "args": {"target": shutter}, "id": "x"}]
    assert completion_calls(dec, emitted, tools) == []
    # the Executor emitted the typing (same target, JSON-string form) but not the tap: dispatch only the tap
    emitted = [{"name": "focus_and_input_text", "args": {"text": "a", "target": json.dumps({"resource_id": "f1"})}, "id": "y"}]
    assert [c["name"] for c in completion_calls(dec, emitted, tools)] == ["tap"]
    # nothing after a screen-changing action is ever dispatched
    dec2 = json.dumps([{"action": "tap", "target": shutter}, {"action": "tap", "target": shutter}])
    assert [c["name"] for c in completion_calls(dec2, [], tools)] == ["tap"]


def test_verified_final_answer_prefers_the_verifier():
    from minitap.mobile_use.benchmark.runner import verified_final_answer

    st = SimpleNamespace(agents_thoughts=["[cortex] Goal verification PASSED: ...", "[cortex] Final answer: 2",
                                          "[executor] something"])
    assert verified_final_answer(st) == "2"
    assert verified_final_answer(SimpleNamespace(agents_thoughts=["[orchestrator] Final answer: 9"])) is None
    assert verified_final_answer(None) is None


def test_custom_scrollable_views_are_never_scrolled_automatically():
    """A camera filmstrip (custom view, scrollable=true): a vertical swipe deletes the photo."""
    xml = ('<hierarchy><node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">'
           '<node class="com.android.camera.widget.FilmstripView" scrollable="true" '
           'resource-id="com.android.camera2:id/filmstrip_view" bounds="[0,0][1080,2400]">'
           '<node class="android.widget.ImageView" content-desc="Photo" bounds="[0,0][1080,2400]"/></node>'
           '</node></hierarchy>')
    swipes = []
    dev = Device(lambda: xml, lambda *a: swipes.append(a), 1080, 2400, settle_s=0)
    res = read_full_list(dev)
    assert res.error and not swipes
    # explicitly named by the agent: allowed
    res2 = read_full_list(dev, prefer_id="com.android.camera2:id/filmstrip_view")
    assert res2.error is None


class NoisyFakeList(FakeListWithDetails):
    """Real-device-like: swipes/drags overshoot by a random amount (momentum), and cards cut by the
    container edge report CLIPPED bounds (UIAutomator), not their full height."""

    def __init__(self, items, details, overshoot=(0, 140), seed=0, **kw):
        super().__init__(items, details, **kw)
        import random as _r
        self._rng, self.overshoot = _r.Random(seed), overshoot

    def swipe(self, x1, y1, x2, y2, ms):
        d = y1 - y2
        extra = self._rng.randint(*self.overshoot) * (1 if d > 0 else -1)
        self.offset = min(self.max_offset, max(0, self.offset + d + extra))

    def device(self):
        dev = super().device()
        dev.drag = lambda x, y1, y2: setattr(self, "offset", min(self.max_offset, max(0, self.offset + (y1 - y2))))
        return dev


@pytest.mark.parametrize("seed", range(6))
def test_reader_exact_with_identical_rows_clipping_and_flings(seed):
    items = (["Avocado Toast | Healthy"] * 3 + [f"Recipe {i} | d" for i in range(8)]
             + ["Soup | Warm"] * 8 + [f"Tail {i} | d" for i in range(10)] + ["Soup | Warm"] * 2)
    fake = NoisyFakeList(items, [[t] for t in items], seed=seed)
    fake.offset = fake.max_offset // 3
    res = read_full_list(fake.device())
    assert res.rows == items and res.reached_end


def test_inspect_rows_detail_contains_and_identical_groups():
    from minitap.mobile_use.robustness.row_inspector import inspect_rows

    items = [f"Card {i}" for i in range(5)] + ["Stew | Hearty"] * 8 + [f"Card {i}" for i in range(5, 12)]
    details = [[f"title {it}", "servings 4", "dir: mix"] for it in items]
    details[5] = ["title Stew", "servings 2", "dir: simmer"]
    details[7] = ["title Stew", "servings 2", "dir: simmer"]      # the exact duplicate pair
    for i in (6, 8, 9, 10, 11, 12):
        details[i] = ["title Stew", f"servings {i}", "dir: simmer"]
    details[15] = ["title Card 7", "servings 4", "dir: add olives and mix"]
    fake = NoisyFakeList(items, details, seed=3)
    res = inspect_rows(fake.device(), "stew")
    assert res.error is None and res.stopped is None, res.render()
    assert [r["pos"] for r in res.rows] == list(range(6, 14)) and res.reached_end
    assert res.groups() == [[6, 8]]
    fake2 = NoisyFakeList(items, details, seed=4)
    res2 = inspect_rows(fake2.device(), "", detail_contains="olives")
    assert [r["pos"] for r in res2.rows] == [16] and res2.checked == len(items)


def test_compose_vertical_list_is_read_but_a_pager_is_not():
    from minitap.mobile_use.robustness.list_reader import find_main_container
    import xml.etree.ElementTree as ET

    rows = "".join(f'<node class="android.view.View" bounds="[0,{400+i*100}][720,{500+i*100}]"><node class="android.widget.TextView" text="App {i}" bounds="[10,{400+i*100}][700,{500+i*100}]"/></node>' for i in range(8))
    compose = f'<hierarchy><node class="android.view.View" scrollable="true" bounds="[0,400][720,1200]">{rows}</node></hierarchy>'
    assert find_main_container(ET.fromstring(compose), 720 * 1280) is not None
    pager = ('<hierarchy><node class="android.view.View" scrollable="true" bounds="[0,0][720,1280]">'
             '<node class="android.view.View" bounds="[0,0][720,1280]"/></node></hierarchy>')
    assert find_main_container(ET.fromstring(pager), 720 * 1280) is None


def test_action_log_records_each_executed_call_once():
    from types import SimpleNamespace

    from langchain_core.messages import AIMessage, ToolMessage

    from minitap.mobile_use.robustness.action_log import record_actions, render_action_log

    ctx = SimpleNamespace(p2_action_log=None, p2_action_ids=None, p2_action_count=0)
    shutter = {"resource_id": "com.example:id/shutter_button", "bounds": {"x": 0, "y": 2022}}
    turn1 = [
        AIMessage(content="", tool_calls=[{"name": "tap", "args": {"target": shutter}, "id": "c1"}]),
        ToolMessage(content="Tap ok", tool_call_id="c1", status="success"),
    ]
    record_actions(ctx, SimpleNamespace(executor_messages=turn1))
    record_actions(ctx, SimpleNamespace(executor_messages=turn1))  # same turn seen twice
    turn2 = [
        AIMessage(content="", tool_calls=[
            {"name": "focus_and_input_text", "args": {"target": '{"text": "Title"}', "text": "Hello"}, "id": "c2"},
            {"name": "launch_app", "args": {"app_name": "Notes"}, "id": "c3"},
        ]),
        ToolMessage(content="ok", tool_call_id="c2", status="success"),
        ToolMessage(content="boom", tool_call_id="c3", status="error"),
    ]
    record_actions(ctx, SimpleNamespace(executor_messages=turn2))
    out = render_action_log(ctx)
    lines = out.splitlines()
    assert len(lines) == 3
    assert lines[0] == "#1 tap(resource_id='com.example:id/shutter_button') -> ok"
    assert "text='Title'" in lines[1] and "text='Hello'" in lines[1]
    assert lines[2] == "#3 launch_app(app_name='Notes') -> failed"


def test_action_log_caps_entries_and_reports_dropped():
    from types import SimpleNamespace

    from langchain_core.messages import AIMessage, ToolMessage

    from minitap.mobile_use.robustness import action_log

    ctx = SimpleNamespace(p2_action_log=None, p2_action_ids=None, p2_action_count=0)
    msgs = []
    for i in range(action_log.MAX_ENTRIES + 5):
        msgs.append(AIMessage(content="", tool_calls=[{"name": "back", "args": {}, "id": f"b{i}"}]))
        msgs.append(ToolMessage(content="ok", tool_call_id=f"b{i}", status="success"))
    action_log.record_actions(ctx, SimpleNamespace(executor_messages=msgs))
    out = action_log.render_action_log(ctx)
    assert out.startswith("(5 earlier action(s) not shown)")
    assert out.splitlines()[-1].startswith(f"#{action_log.MAX_ENTRIES + 5} back()")


def test_no_null_treats_null_strings_as_omitted():
    from minitap.mobile_use.tools.p2_tools import _no_null

    assert _no_null("null") is None and _no_null(" None ") is None and _no_null('""') is None
    assert _no_null(None) is None and _no_null("") is None
    assert _no_null("Water") == "Water"


def _cel(bounds, **kw):
    x1, y1, x2, y2 = bounds
    return {"bounds": f"[{x1},{y1}][{x2},{y2}]", **kw}


def _ctx_fixes():
    from types import SimpleNamespace

    return SimpleNamespace(get_ablation_config=lambda: SimpleNamespace(p2_tool_fixes=True))


def _target(rid=None, text=None):
    from minitap.mobile_use.tools.types import Target

    return Target(resource_id=rid, text=text)


def test_tap_refused_when_a_labelled_control_is_drawn_over_the_target():
    from minitap.mobile_use.robustness.target_resolution import p2_covered_check

    elements = [
        _cel((0, 0, 1080, 2400), **{"class": "FrameLayout"}),
        _cel((500, 1400, 760, 1660), **{"resource-id": "app:id/add_point_button", "clickable": "true"}),
        _cel((0, 1300, 1080, 1800), **{"class": "LinearLayout"}),  # popup container, not clickable
        _cel((400, 1450, 900, 1600), text="NAVIGATION", clickable="true"),
    ]
    refusal, warning = p2_covered_check(_ctx_fixes(), _target(rid="app:id/add_point_button"), elements)
    assert refusal and "NAVIGATION" in refusal and warning is None


def test_tap_not_refused_for_children_wrappers_or_unlabelled_overlays():
    from minitap.mobile_use.robustness.target_resolution import p2_covered_check

    child = [
        _cel((100, 100, 500, 200), **{"resource-id": "app:id/row", "clickable": "true"}),
        _cel((120, 110, 300, 190), text="Title", clickable="true"),  # the target's own child
    ]
    assert p2_covered_check(_ctx_fixes(), _target(rid="app:id/row"), child) == (None, None)
    wrapper = [
        _cel((120, 110, 300, 190), text="Title"),
        _cel((100, 100, 500, 200), clickable="true", **{"content-desc": "Open Title"}),
    ]
    refusal, warning = p2_covered_check(_ctx_fixes(), _target(text="Title"), wrapper)
    assert refusal is None and warning  # a wrapper drawn after its text: warn only
    overlay = [
        _cel((100, 100, 500, 200), **{"resource-id": "app:id/btn", "clickable": "true"}),
        _cel((0, 0, 1080, 2400), clickable="true"),  # unlabelled scrim
    ]
    refusal, warning = p2_covered_check(_ctx_fixes(), _target(rid="app:id/btn"), overlay)
    assert refusal is None and warning


class FakeListWithFab(FakeList):
    """A floating button drawn over the middle-bottom of the list: drags that START on it move
    nothing (the button takes the touch)."""

    FAB = (260, 700, 460, 900)

    def dump_xml(self):
        x1, y1, x2, y2 = self.FAB
        fab = (f'<node class="android.widget.ImageButton" content-desc="New" clickable="true" '
               f'bounds="[{x1},{y1}][{x2},{y2}]"/>')
        return super().dump_xml().replace("</node></node></hierarchy>", "</node>" + fab + "</node></hierarchy>")

    def swipe(self, x1, y1, x2, y2, ms):
        fx1, fy1, fx2, fy2 = self.FAB
        if fx1 <= x1 < fx2 and fy1 <= y1 < fy2:
            self.swipes += 1
            return
        super().swipe(x1, y1, x2, y2, ms)


@pytest.mark.parametrize("n", [12, 30])
def test_drags_avoid_an_overlay_and_the_end_is_confirmed(n):
    items = [f"Task {i:02d}" for i in range(n)]
    res = read_full_list(FakeListWithFab(items).device())
    assert res.rows == items and res.reached_end


def test_a_drag_that_moves_nothing_is_not_the_end():
    from minitap.mobile_use.robustness import list_reader as lr

    items = [f"Row {i:02d}" for i in range(20)]
    fake = FakeList(items)
    calls = {"n": 0}
    real = fake.swipe

    def flaky(x1, y1, x2, y2, ms):  # the first downward drag is swallowed
        if y1 > y2:
            calls["n"] += 1
            if calls["n"] == 1:
                return
        real(x1, y1, x2, y2, ms)

    fake.swipe = flaky
    res = lr.read_full_list(fake.device())
    assert res.rows == items and res.reached_end


def test_container_resource_id_accepts_target_objects():
    from minitap.mobile_use.tools.p2_tools import _resource_id_of

    assert _resource_id_of({"resource_id": "app:id/list", "bounds": {"x": 0}}) == "app:id/list"
    assert _resource_id_of('{"resource_id": "app:id/list"}') == "app:id/list"
    assert _resource_id_of("app:id/list") == "app:id/list"
    assert _resource_id_of("null") is None and _resource_id_of(None) is None and _resource_id_of({}) is None


def test_read_full_list_tool_schema_accepts_an_object_container():
    from types import SimpleNamespace

    from minitap.mobile_use.tools.p2_tools import get_read_full_list_tool

    t = get_read_full_list_tool(SimpleNamespace())
    t.tool_call_schema.model_validate(
        {"agent_thought": "x", "container_resource_id": {"resource_id": "app:id/list", "bounds": {"x": 0}}}
    )


class FakeListSlop(FakeList):
    """Drags move the content by only `ratio` of the finger distance (touch slop), as on devices."""

    def __init__(self, items, ratio, **kw):
        super().__init__(items, **kw)
        self.ratio = ratio

    def swipe(self, x1, y1, x2, y2, ms):
        self.swipes += 1
        d = round((y1 - y2) * self.ratio) if y1 > y2 else (y1 - y2)
        self.offset = min(self.max_offset, max(0, self.offset + d))


@pytest.mark.parametrize("ratio", [0.80, 0.83, 0.86, 0.90])
@pytest.mark.parametrize(
    "items",
    [
        [f"U{i}" for i in range(15)] + ["Same card"] * 8 + [f"V{i}" for i in range(9)],
        ["Same card"] * 6 + [f"W{i}" for i in range(6)],
        [f"A{i}" for i in range(3)] + ["Same card"] * 14 + [f"B{i}" for i in range(4)],
    ],
)
def test_runs_of_identical_rows_are_counted_exactly_under_drag_slop(items, ratio):
    res = read_full_list(FakeListSlop(items, ratio).device())
    assert res.rows == items and res.reached_end


@pytest.mark.parametrize("ratio", [0.6, 0.7, 1.0])
def test_identical_rows_never_silently_miscounted(ratio):
    items = ["Same card"] * 12 + [f"W{i}" for i in range(6)]
    res = read_full_list(FakeListSlop(items, ratio).device())
    # either exact, or honestly flagged as possibly incomplete
    assert res.rows == items or not res.reached_end


def test_inspect_rows_groups_cover_every_opened_row_even_with_a_filter():
    from minitap.mobile_use.robustness.row_inspector import inspect_rows

    items = ["Pie", "Pie", "Pie", "Soup"]
    details = [["Pie", "2 servings", "apples"], ["Pie", "2 servings", "apples"], ["Pie", "4 servings", "pears"], ["Soup", "1 serving", "leeks"]]
    fake = FakeListWithDetails(items, details)
    res = inspect_rows(fake.device(), match="Pie", detail_contains="no such text")
    assert res.rows == [] and res.checked == 3
    assert res.groups() == [[1, 2]]
    assert "row 1 = row 2" in res.render()


def test_reader_refuses_the_home_screen():
    from minitap.mobile_use.robustness.list_reader import Device, read_full_list

    xml = ('<hierarchy><node class="android.widget.FrameLayout" package="com.example.launcher" bounds="[0,0][720,1600]">'
           '<node class="android.widget.ScrollView" scrollable="true" package="com.example.launcher" resource-id="com.example.launcher:id/workspace" bounds="[0,0][720,1600]">'
           + "".join(f'<node class="android.widget.TextView" package="com.example.launcher" text="App {i}" bounds="[0,{100+i*200}][720,{280+i*200}]"/>' for i in range(5))
           + '</node></node></hierarchy>')
    swipes = []
    dev = Device(lambda: xml, lambda *a: swipes.append(a), 720, 1600, settle_s=0, home_package="com.example.launcher")
    res = read_full_list(dev)
    assert res.error and "home screen" in res.error and swipes == []


def test_nested_scrollables_prefer_the_inner_list_and_relocate_by_id():
    import xml.etree.ElementTree as ET

    from minitap.mobile_use.robustness import list_reader as lr

    rows = "".join(f'<node class="android.widget.LinearLayout" bounds="[0,{200+i*180}][720,{380+i*180}]"><node class="android.widget.TextView" text="Task {i}" bounds="[10,{200+i*180}][700,{380+i*180}]"/></node>' for i in range(7))
    xml = ('<hierarchy><node class="android.widget.ScrollView" scrollable="true" resource-id="app:id/coordinator" bounds="[0,94][720,1574]">'
           '<node class="android.widget.TextView" text="Toolbar" bounds="[0,94][720,192]"/>'
           f'<node class="androidx.recyclerview.widget.RecyclerView" scrollable="true" resource-id="app:id/list" bounds="[0,192][720,1574]">{rows}</node>'
           '</node></hierarchy>')
    root = ET.fromstring(xml)
    assert lr.find_main_container(root, 720 * 1600).label == "app:id/list"
    collapsed = ET.fromstring(xml.replace("[0,192][720,1574]", "[0,94][720,1574]"))
    n, r = lr.locate_container(collapsed, lr.Rect(0, 94, 720, 1574), "app:id/list")
    assert n.attrib["resource-id"] == "app:id/list"


class FakeListWithDiscardDialog(FakeListWithDetails):
    """Leaving a detail screen raises 'discard your changes?' (DISCARD / KEEP EDITING)."""

    def __init__(self, items, details, **kw):
        super().__init__(items, details, **kw)
        self.dialog = False
        self.kept_editing = 0

    def dump_xml(self):
        if self.dialog:
            return ('<hierarchy><node class="android.widget.FrameLayout" bounds="[0,0][720,1280]">'
                    '<node class="android.widget.TextView" text="Are you sure you want to discard your changes?" bounds="[60,600][660,680]"/>'
                    '<node class="android.widget.Button" text="DISCARD" clickable="true" bounds="[200,700][400,760]"/>'
                    '<node class="android.widget.Button" text="KEEP EDITING" clickable="true" bounds="[420,700][660,760]"/>'
                    '</node></hierarchy>')
        return super().dump_xml()

    def tap(self, x, y):
        if self.dialog:
            if 200 <= x < 400 and 700 <= y < 760:
                self.dialog, self.open = False, None
            else:
                self.kept_editing += 1
            return
        super().tap(x, y)

    def back(self):
        if self.open is not None:
            self.dialog = True


def test_inspect_rows_discards_instead_of_saving_when_leaving_a_form():
    from minitap.mobile_use.robustness.row_inspector import inspect_rows

    items = [f"Task {i}" for i in range(5)]
    details = [[f"Task {i}", "Monday"] for i in range(5)]
    fake = FakeListWithDiscardDialog(items, details)
    res = inspect_rows(fake.device())
    assert res.stopped is None and res.checked == 5, res.render()
    assert res.discarded == [1, 2, 3, 4, 5] and fake.kept_editing == 0
    assert "nothing was saved" in res.render()


def test_drags_never_start_on_an_input_widget():
    import xml.etree.ElementTree as ET

    from minitap.mobile_use.robustness import list_reader as lr

    xml = ('<hierarchy><node class="android.widget.ScrollView" scrollable="true" resource-id="app:id/form" bounds="[0,100][720,1500]">'
           '<node class="android.widget.TextView" text="Title" bounds="[0,100][720,300]"/>'
           '<node class="android.widget.EditText" text="Notes" bounds="[0,900][720,1300]"/>'
           '</node></hierarchy>')
    root = ET.fromstring(xml)
    lanes = lr.drag_lanes(root, lr.Rect(0, 100, 720, 1500), "app:id/form")
    for x, y_from, _ in lanes:
        assert not (0 <= x < 720 and 900 <= y_from < 1300)


def test_split_screen_full_read_takes_the_list_not_the_edit_pane():
    import xml.etree.ElementTree as ET

    from minitap.mobile_use.robustness import list_reader as lr

    rows = "".join(f'<node class="android.widget.LinearLayout" bounds="[0,{100+i*100}][270,{200+i*100}]"><node class="android.widget.TextView" text="Task {i}" bounds="[5,{100+i*100}][265,{200+i*100}]"/></node>' for i in range(6))
    xml = ('<hierarchy><node class="android.widget.FrameLayout" bounds="[0,0][720,1600]">'
           f'<node class="androidx.recyclerview.widget.RecyclerView" scrollable="true" resource-id="app:id/list" bounds="[0,100][270,1500]">{rows}</node>'
           '<node class="android.widget.ScrollView" scrollable="true" resource-id="app:id/edit" bounds="[270,100][720,1500]">'
           '<node class="android.widget.EditText" text="Notes" bounds="[280,200][710,400]"/>'
           '<node class="android.widget.TextView" text="Monday" bounds="[280,500][710,600]"/><node class="android.widget.TextView" text="Priority" bounds="[280,700][710,800]"/></node>'
           '</node></hierarchy>')
    root = ET.fromstring(xml)
    assert lr.find_main_container(root, 720 * 1600).label == "app:id/edit"
    assert lr.find_main_container(root, 720 * 1600, exclude_forms=True).label == "app:id/list"


def test_completion_ids_are_unique_across_turns_so_the_action_log_keeps_them():
    from types import SimpleNamespace

    from langchain_core.messages import AIMessage, ToolMessage

    from minitap.mobile_use.robustness.action_log import record_actions
    from minitap.mobile_use.robustness.executor_completion import completion_calls

    class _T:
        class tool_call_schema:
            @staticmethod
            def model_validate(args):
                return args

    tools = {"focus_and_input_text": _T()}
    decisions = '[{"action": "focus_and_input_text", "target": {"text": "A"}, "text": "1"}, {"action": "focus_and_input_text", "target": {"text": "B"}, "text": "2"}]'
    ctx = SimpleNamespace(p2_action_log=None, p2_action_ids=None, p2_action_count=0)
    for _ in range(2):  # two Cortex turns with the same shape
        calls = completion_calls(decisions, [], tools)
        msgs = [AIMessage(content="", tool_calls=calls)] + [ToolMessage(content="ok", tool_call_id=c["id"], status="success") for c in calls]
        record_actions(ctx, SimpleNamespace(executor_messages=msgs))
    assert ctx.p2_action_count == 4


def test_screen_log_keeps_long_single_elements_and_marks_truncation():
    from minitap.mobile_use.robustness.screen_log import ELEMENT_TEXT_MAX, screen_texts

    doc = "\n".join(f"row {i} Fine Dining 12.50" for i in range(100))
    out = screen_texts([{"text": doc}])
    assert out and out[0] == doc
    big = "x" * (ELEMENT_TEXT_MAX + 50)
    assert "[truncated:" in screen_texts([{"text": big}])[0]


def test_list_rows_carry_their_checked_state():
    import xml.etree.ElementTree as ET

    from minitap.mobile_use.robustness import list_reader as lr

    row = ('<node class="android.widget.LinearLayout" bounds="[0,{y}][720,{y2}]">'
           '<node class="android.widget.CheckBox" checkable="true" checked="{c}" bounds="[0,{y}][80,{y2}]"/>'
           '<node class="android.widget.TextView" text="{t}" bounds="[90,{y}][700,{y2}]"/></node>')
    rows = "".join(row.format(y=200 + i * 100, y2=300 + i * 100, c="true" if i == 1 else "false", t=f"Task {i}") for i in range(4))
    xml = f'<hierarchy><node class="androidx.recyclerview.widget.RecyclerView" scrollable="true" resource-id="a:id/l" bounds="[0,200][720,1000]">{rows}</node></hierarchy>'
    texts = [r.text for r in lr.page_rows(ET.fromstring(xml), lr.Rect(0, 200, 720, 1000), "a:id/l")]
    assert texts[1].startswith("[checked]") and texts[0].startswith("[unchecked]")


def test_misshapen_bounds_fall_back_to_the_named_index():
    from minitap.mobile_use.robustness.target_resolution import resolve_target_bounds
    from minitap.mobile_use.utils.ui_hierarchy import ElementBounds

    rows = [{"resource-id": "a:id/conv", "bounds": f"[0,{296 + i*254}][1080,{550 + i*254}]"} for i in range(4)]
    given = ElementBounds(x=0, y=296, width=1080, height=550)  # centre (540, 571) lies in row 2
    res = resolve_target_bounds(rows, given, "a:id/conv", 0, None, None)
    assert res.corrected and res.bounds.y == 296 and res.bounds.height == 254
    ok = ElementBounds(x=0, y=550, width=1080, height=254)  # a real row's rect: trusted as given
    assert not resolve_target_bounds(rows, ok, "a:id/conv", 0, None, None).corrected


def test_stop_screenrecord_signals_only_our_own_recorder():
    import asyncio

    from minitap.mobile_use.controllers.android_controller import p2_stop_screenrecord

    cmds = []

    class Dev:
        def shell(self, c):
            cmds.append(c)
            return ""

    asyncio.run(p2_stop_screenrecord(Dev(), None, timeout_s=0.1, path="/sdcard/screen_recording_0.mp4"))
    assert cmds and "pgrep -f /sdcard/screen_recording_0.mp4" in cmds[0]
    assert not any("pkill" in c for c in cmds)


# --- D3: fixed checklist lines for goals that copy records from a named source file or image ---
from minitap.mobile_use.robustness.checklist import (  # noqa: E402
    SOURCE_COPY_REQUIREMENTS,
    ensure_goal_checklist,
    is_source_copy_goal,
)


@pytest.mark.parametrize(
    "goal",
    [
        "Add the entries from list.jpg in the photo viewer to the budget app.",
        "Go through the purchases in my_list.txt in the editor. Log the flagged purchases in the budget app.",
        "Add the items from items.txt in the editor that cost 5 to the shop app.",
        "Import the contacts from people.csv into the address book.",
    ],
)
def test_source_copy_trigger_matches(goal):
    assert is_source_copy_goal(goal)


@pytest.mark.parametrize(
    "goal",
    [
        'Record a clip and save it with name "brief.m4a".',
        "Create a new note in the editor named notes_1.md with the following text: hello.",
        "Move the file film.mp4 from DCIM to Movies.",
        "In the photo viewer, copy photo_1.jpg in DCIM and save a copy with the same name in Download.",
        "Delete the file song.mp3 from the Ringtones folder.",
        "How many entries do I have due next week?",
        "Add the following entries into the budget app: Lunch, 12.",
    ],
)
def test_source_copy_trigger_ignores_other_goals(goal):
    assert not is_source_copy_goal(goal)


def _checklist_ctx(enabled=True):
    abl = SimpleNamespace(p2_checklist=enabled)
    return SimpleNamespace(
        get_ablation_config=lambda: abl,
        p2_goal_checklist=None,
        device=SimpleNamespace(mobile_platform=SimpleNamespace(value="android")),
    )


def test_source_copy_lines_appended_even_if_llm_fails(monkeypatch):
    import minitap.mobile_use.robustness.checklist as cl

    class _Llm:
        def with_structured_output(self, _schema):
            return self

    async def boom(**_):
        raise RuntimeError("no llm")

    monkeypatch.setattr(cl, "get_llm", lambda **_: _Llm())
    monkeypatch.setattr(cl, "with_fallback", boom)
    monkeypatch.setattr(cl, "get_runtime", lambda: None)
    ctx = _checklist_ctx()
    items = asyncio.run(ensure_goal_checklist(ctx, "Add the entries from list.jpg in the viewer to the app."))
    assert items == SOURCE_COPY_REQUIREMENTS
    ctx2 = _checklist_ctx()
    assert asyncio.run(ensure_goal_checklist(ctx2, "Add an entry Lunch 12 to the app.")) == []
    assert asyncio.run(ensure_goal_checklist(_checklist_ctx(False), "Add the entries from a.jpg to b.")) is None


# --- D3: trailing-newline retry and the named-delete verifier gate ---
from minitap.mobile_use.robustness.delete_gate import delete_gate, is_named_delete_goal  # noqa: E402
from minitap.mobile_use.robustness.text_copy import trailing_newlines_missing  # noqa: E402


@pytest.mark.parametrize(
    "intended, read_back, missing",
    [
        ("Head\n\nBody.\n", "Head\n\nBody.", 1),
        ("Head\n\nBody.\n", "Head\n\nBody.\n", 0),
        ("Head\n\nBody.\n\n", "Head\n\nBody.", 2),
        ("query\n", "query", 0),  # single-line field: the Enter submitted, never press again
        ("Head\nBody.\n", "Head Body.", 0),  # field not shown multi-line
        ("Head\nBody.\n", None, 0),
        ("Head\nBody.", "Head\nBody.", 0),
    ],
)
def test_trailing_newlines_missing(intended, read_back, missing):
    assert trailing_newlines_missing(intended, read_back) == missing


@pytest.mark.parametrize(
    "goal, named",
    [
        ("Delete the following entries from the budget app: Lunch, Taxi.", True),
        ("Delete the file song.mp3 from the Ringtones folder.", True),
        ("Delete the note in the editor named my_note.", True),
        ("In the calendar, delete the event on 2023-10-17 at 13h with the title 'Review'.", True),
        ("Remove the contact titled Bob.", True),
        ("Delete all my notes in the editor.", False),
        ("Delete the newest note in the editor.", False),
        ("Delete all but one of any entries that are exact duplicates.", False),
        ("Delete the entries that use butter in the directions.", False),
        ("Add the following entries to the app: Lunch.", False),
    ],
)
def test_named_delete_trigger(goal, named):
    assert is_named_delete_goal(goal) is named


def _gate_ctx(seen=False):
    return SimpleNamespace(p2_delete_seen=seen, p2_delete_gate_used=False)


def test_delete_gate_fires_once_without_a_delete_action():
    ctx = _gate_ctx()
    goal = "Delete the following entries from the app: Pan-Fried Fish."
    assert delete_gate(ctx, goal)
    assert delete_gate(ctx, goal) is None  # at most once per run
    assert delete_gate(_gate_ctx(seen=True), goal) is None
    assert delete_gate(_gate_ctx(), "Delete all my notes.") is None


def test_action_log_marks_delete_actions():
    from langchain_core.messages import AIMessage, ToolMessage

    from minitap.mobile_use.robustness.action_log import record_actions

    ctx = SimpleNamespace(p2_action_log=None, p2_action_ids=None, p2_action_count=0, p2_delete_seen=False)
    msgs = [
        AIMessage(content="", tool_calls=[{"id": "a", "name": "tap", "args": {"target": {"text": "Search"}}}]),
        ToolMessage(content="ok", tool_call_id="a"),
    ]
    record_actions(ctx, SimpleNamespace(executor_messages=msgs))
    assert ctx.p2_delete_seen is False
    msgs += [
        AIMessage(content="", tool_calls=[{"id": "b", "name": "tap", "args": {"target": {"text": "Delete"}}}]),
        ToolMessage(content="boom", tool_call_id="b", status="error"),
    ]
    record_actions(ctx, SimpleNamespace(executor_messages=msgs))
    assert ctx.p2_delete_seen is False  # a failed tap is not a delete
    msgs += [
        AIMessage(content="", tool_calls=[{"id": "c", "name": "tap", "args": {"target": {"content_desc": "Delete"}}}]),
        ToolMessage(content="ok", tool_call_id="c"),
    ]
    record_actions(ctx, SimpleNamespace(executor_messages=msgs))
    assert ctx.p2_delete_seen is True


# --- D4 candidates (offline; not on the D3 pin) ---
from minitap.mobile_use.robustness.delete_gate import (  # noqa: E402
    add_delete_gate,
    listed_delete_names,
    names_still_listed,
    presence_gate,
)

_READ = (
    "Read 4 rows from list in 2 page(s); END OF LIST REACHED (this is the complete content).\n"
    "1. Pan-Fried Fish with Rice | A quick dinner\n"
    "2. Pan-Fried Fish with Rice Bowl | Lunch\n"
    "3. Green Salad | Fresh\n"
    '4. Fried "Rice" | Side'
)


def test_listed_delete_names():
    g = 'Delete the following entries from the app: Pan-Fried Fish with Rice, Tofu Bowl, Fried "Rice".'
    assert listed_delete_names(g) == ["Pan-Fried Fish with Rice", "Tofu Bowl", 'Fried "Rice"']
    assert listed_delete_names("Delete the note named a.") == []
    assert listed_delete_names("Add the following entries: A, B.") == []


def test_names_still_listed_matches_whole_segments_only():
    g = 'Delete the following entries from the app: Pan-Fried Fish with Rice, Tofu Bowl, Fried "Rice".'
    assert names_still_listed(g, _READ) == ["Pan-Fried Fish with Rice", 'Fried "Rice"']
    g2 = "Delete the following entries from the app: Pan-Fried Fish, Tofu Bowl."
    assert names_still_listed(g2, _READ) == []  # a prefix of a longer title is a different item
    assert names_still_listed(g, None) == []


def test_presence_gate_once():
    ctx = SimpleNamespace(p2_delete_presence_used=False)
    g = "Delete the following entries from the app: Green Salad."
    msg = presence_gate(ctx, g, _READ)
    assert msg and '"Green Salad"' in msg
    assert presence_gate(ctx, g, _READ) is None


def test_add_delete_gate_scope():
    src = "Add the entries from list.jpg in the viewer to the budget app."
    ctx = SimpleNamespace(p2_add_delete_gate_used=False, p2_delete_seen=True)
    assert add_delete_gate(ctx, src)
    assert add_delete_gate(ctx, src) is None
    assert add_delete_gate(SimpleNamespace(p2_add_delete_gate_used=False, p2_delete_seen=False), src) is None
    assert add_delete_gate(SimpleNamespace(p2_add_delete_gate_used=False, p2_delete_seen=True), "Add a song to the playlist.") is None


# --- D5: multi-line text is typed whole; only single-line text gets Enter key presses ---
from minitap.mobile_use.robustness.text_copy import split_trailing_enters  # noqa: E402


@pytest.mark.parametrize(
    "text, sent, enters",
    [
        ("query\n", "query", 1),  # single-line: Enter submits the field
        ("query\n\n", "query", 2),
        ("query", "query", 0),
        ("Head\n\nBody.\n", "Head\n\nBody.\n", 0),  # multi-line: typed whole, newline committed
        ("Head\nBody.", "Head\nBody.", 0),
        ("\n", "\n", 0),
        ("", "", 0),
    ],
)
def test_split_trailing_enters(text, sent, enters):
    assert split_trailing_enters(text) == (sent, enters)
