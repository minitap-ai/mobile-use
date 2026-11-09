from minitap.mobile_use.benchmark.loop_detector import (
    LoopDetector,
    LoopDetectorConfig,
    canonical_action,
    hash_state,
)


def screen(*texts, app="com.app", clock="10:41"):
    return [
        {"package": "com.android.systemui", "text": clock, "resource-id": "clock"},
        *[
            {"package": app, "text": t, "resource-id": f"id/{i}", "class": "TextView"}
            for i, t in enumerate(texts)
        ],
    ]


def tap(label, thought="whatever"):
    return [{"name": "tap", "args": {"target": {"text": label}, "agent_thought": thought}}]


def feed(det, steps):
    """steps: list of (ui, action). Returns triggers per step."""
    out = []
    for ui, action in steps:
        out.append(det.observe(ui_hierarchy=ui, focused_app="com.app", executed_tool_calls=action))
    return out


def test_state_hash_ignores_systemui_clock_and_whitespace():
    a = hash_state(screen("Hello  world", clock="10:41"), "com.app")
    b = hash_state(screen("Hello world", clock="10:42"), "com.app")
    assert a == b
    assert a != hash_state(screen("Hello there"), "com.app")
    assert a != hash_state(screen("Hello world"), "com.other")


def test_state_hash_masks_in_app_clock_strings():
    assert hash_state(screen("Alarm 7:30 AM"), "x") == hash_state(screen("Alarm 8:15 PM"), "x")


def test_action_hash_ignores_free_text_and_key_order():
    h1, names, _ = canonical_action(tap("OK", thought="first try"))
    h2, _, _ = canonical_action(
        [{"name": "tap", "args": {"agent_thought": "again", "target": {"text": "OK"}}}]
    )
    assert h1 == h2 and names == ("tap",)
    assert h1 != canonical_action(tap("Cancel"))[0]


def test_no_trigger_while_making_progress():
    det = LoopDetector()
    steps = [(screen(f"page {i}"), tap("Next")) for i in range(20)]
    assert all(t is None for t in feed(det, steps))


def test_no_change_trigger():
    det = LoopDetector(LoopDetectorConfig(no_change_threshold=3, repeat_threshold=10))
    ui = screen("Stuck")
    triggers = feed(det, [(ui, None), (ui, tap("A")), (ui, tap("B")), (ui, tap("C"))])
    assert triggers[:3] == [None, None, None]
    assert triggers[3] is not None and triggers[3].kind == "no_change"
    assert "unchanged" in triggers[3].evidence


def test_repeat_trigger_same_state_same_action():
    cfg = LoopDetectorConfig(repeat_threshold=3, no_change_threshold=10, cycle_window=20)
    det = LoopDetector(cfg)
    a, b = screen("A"), screen("B")
    # A --tap X--> B --back--> A --tap X--> B ... : (A, tap X) repeats
    steps = [(a, None)]
    for _ in range(3):
        steps += [(b, tap("X")), (a, [{"name": "back", "args": {}}])]
    triggers = feed(det, steps)
    fired = [t for t in triggers if t]
    assert fired and fired[0].kind == "repeat"
    assert fired[0].details["count"] == 3


def test_cycle_trigger_oscillation_between_two_screens():
    cfg = LoopDetectorConfig(
        repeat_threshold=50, no_change_threshold=50, cycle_window=6, cycle_max_distinct=2
    )
    det = LoopDetector(cfg)
    a, b = screen("A"), screen("B")
    steps = [(a, None)] + [((b if i % 2 == 0 else a), tap(f"t{i}")) for i in range(6)]
    fired = [t for t in feed(det, steps) if t]
    assert fired and fired[0].kind == "cycle"


def test_non_ui_tools_do_not_count_as_no_change():
    det = LoopDetector(LoopDetectorConfig(no_change_threshold=2, repeat_threshold=50))
    ui = screen("Same")
    note = [{"name": "save_note", "args": {"key": "k", "content": "v"}}]
    triggers = feed(det, [(ui, None), (ui, note), (ui, [{"name": "wait_for_delay", "args": {}}])])
    assert all(t is None for t in triggers)


def test_cooldown_and_escalation():
    cfg = LoopDetectorConfig(
        no_change_threshold=2, repeat_threshold=50, cooldown=1, escalate_after=2
    )
    det = LoopDetector(cfg)
    ui = screen("Stuck")
    triggers = feed(det, [(ui, None)] + [(ui, tap(f"b{i}")) for i in range(6)])
    fired = [(i, t) for i, t in enumerate(triggers) if t]
    # step 2: first trigger, step 3: cooldown, step 4: second trigger -> escalate
    assert [i for i, _ in fired][:2] == [2, 4]
    assert fired[0][1].escalate is False
    assert fired[1][1].escalate is True
    assert "replan" in fired[1][1].cortex_message()


def test_progress_resets_escalation():
    cfg = LoopDetectorConfig(
        no_change_threshold=2, repeat_threshold=50, cooldown=0, escalate_after=2
    )
    det = LoopDetector(cfg)
    ui = screen("Stuck")
    t = feed(det, [(ui, None), (ui, tap("a")), (ui, tap("b"))])
    assert t[2] is not None and not t[2].escalate
    # reach a brand-new screen (progress), then get stuck again: no escalation yet
    t = feed(det, [(screen("New"), tap("c")), (screen("New"), tap("d")), (screen("New"), tap("e"))])
    fired = [x for x in t if x]
    assert fired and fired[0].escalate is False


def test_reset_history_after_replan():
    det = LoopDetector(LoopDetectorConfig(no_change_threshold=2, repeat_threshold=50))
    ui = screen("Stuck")
    feed(det, [(ui, None), (ui, tap("a")), (ui, tap("b"))])
    det.reset_history()
    assert len(det.transitions) == 0
    assert feed(det, [(ui, None), (ui, tap("c"))]) == [None, None]


def test_trigger_details_can_be_recorded(tmp_path):
    """Regression: details used to be splatted into record_loop_trigger(action=...) and a
    `repeat` trigger crashed the task (TypeError: multiple values for 'action')."""
    import json

    from minitap.mobile_use.benchmark import runtime as rt

    cfg = LoopDetectorConfig(repeat_threshold=3, no_change_threshold=10, cycle_window=20)
    det = LoopDetector(cfg)
    a, b = screen("A"), screen("B")
    steps = [(a, None)]
    for _ in range(3):
        steps += [(b, tap("X")), (a, [{"name": "back", "args": {}}])]
    triggers = [t for t in feed(det, steps) if t]
    r = rt.BenchmarkRuntime(tmp_path / "e.jsonl", "r", rt.LLMPolicy())
    for t in triggers:
        r.record_loop_trigger(
            kind=t.kind,
            action="inject",
            evidence=t.evidence,
            turn=t.turn,
            subgoal=None,
            details=t.details,
        )
    r.close()
    ev = [json.loads(x) for x in (tmp_path / "e.jsonl").read_text().splitlines()]
    assert ev and ev[0]["kind"] == "repeat" and "action_hash" in ev[0]["details"]
