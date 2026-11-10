"""Fix round: stall detector (flag use_loop_detector). Cortex -> Orchestrator rounds without the
Executor (an unnecessary plan step that was neither completed nor replanned) force a replan."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from minitap.mobile_use.agents.cortex import cortex as cx
from minitap.mobile_use.agents.planner.types import Subgoal, SubgoalStatus
from minitap.mobile_use.benchmark.loop_detector import LoopDetector, LoopDetectorConfig
from minitap.mobile_use.config import AblationConfig
from minitap.mobile_use.graph.graph import post_cortex_gate
from minitap.mobile_use.graph.state import State


def test_stall_after_n_turns_without_action_and_reset_on_action():
    det = LoopDetector(LoopDetectorConfig(stall_rounds=4))
    for _ in range(3):
        det.note_cortex_turn(decided_action=False)
        assert det.check_stall() is None
    det.note_cortex_turn(decided_action=True)  # an action resets the count
    for _ in range(3):
        det.note_cortex_turn(decided_action=False)
    assert det.check_stall() is None
    det.note_cortex_turn(decided_action=False)
    trig = det.check_stall()
    assert trig is not None and trig.kind == "stall" and trig.escalate
    assert trig.details == {"turns_without_action": 4}
    assert det.check_stall() is None  # counter restarts after a trigger


def test_stall_disabled_and_reset_history():
    off = LoopDetector(LoopDetectorConfig(stall_rounds=0))
    for _ in range(10):
        off.note_cortex_turn(decided_action=False)
    assert off.check_stall() is None
    det = LoopDetector(LoopDetectorConfig(stall_rounds=2))
    det.note_cortex_turn(decided_action=False)
    det.reset_history()
    det.note_cortex_turn(decided_action=False)
    assert det.check_stall() is None


def _state():
    return State(
        messages=[],
        initial_goal="answer a question",
        latest_ui_hierarchy=None,
        latest_screenshot=None,
        focused_app_info=None,
        device_date=None,
        structured_decisions=None,
        complete_subgoals_by_ids=[],
        executor_messages=[],
        cortex_last_thought=None,
        agents_thoughts=["[orchestrator] the answer is known"],
        subgoal_plan=[
            Subgoal(id="a", description="open", status=SubgoalStatus.SUCCESS),
            Subgoal(id="b", description="navigate", status=SubgoalStatus.PENDING),
            Subgoal(id="c", description="answer", status=SubgoalStatus.SUCCESS),
        ],
    )


def _ctx(detector):
    ctx = MagicMock()
    ctx.loop_detector = detector
    ctx.get_ablation_config.return_value = AblationConfig(use_vision=False)
    ctx.device.mobile_platform.value = "android"
    ctx.device.to_str.return_value = "android device\n"
    ctx.on_plan_changes = None
    ctx.on_agent_thought = None
    ctx.execution_setup = None
    ctx.video_recording_enabled = False
    return ctx


@pytest.fixture
def no_llm(monkeypatch):
    monkeypatch.setattr(cx, "format_tools_list", lambda **kw: "tools")
    llm = MagicMock()
    llm.with_structured_output.return_value.ainvoke = AsyncMock(
        side_effect=AssertionError("the Cortex LLM must not be called on a stall")
    )
    monkeypatch.setattr(cx, "get_llm", lambda **kw: llm)
    return llm


def test_cortex_forces_replan_on_stall(no_llm):
    det = LoopDetector(LoopDetectorConfig(stall_rounds=4))
    for _ in range(4):
        det.note_cortex_turn(decided_action=False)
    upd = asyncio.run(cx.CortexNode(_ctx(det))(_state()))
    plan = upd["subgoal_plan"]
    assert [s.status for s in plan] == [
        SubgoalStatus.SUCCESS,
        SubgoalStatus.FAILURE,
        SubgoalStatus.SUCCESS,
    ]
    assert "stall" in plan[1].completion_reason
    assert upd["structured_decisions"] is None
    assert post_cortex_gate(_state().model_copy(update={"subgoal_plan": plan})) == ["force_replan"]


def test_cortex_counts_turns_without_decisions(monkeypatch):
    monkeypatch.setattr(cx, "format_tools_list", lambda **kw: "tools")
    out = cx.CortexOutput(
        decisions=None,
        decisions_reason="nothing to do",
        goals_completion_reason=None,
        complete_subgoals_by_ids=[],
    )
    llm = MagicMock()
    llm.with_structured_output.return_value.ainvoke = AsyncMock(return_value=out)
    monkeypatch.setattr(cx, "get_llm", lambda **kw: llm)
    det = LoopDetector(LoopDetectorConfig(stall_rounds=4))
    node = cx.CortexNode(_ctx(det))
    for _ in range(4):
        upd = asyncio.run(node(_state()))
        assert "subgoal_plan" not in upd
    # the 5th turn sees 4 turns without action: replan without calling the LLM
    calls = llm.with_structured_output.return_value.ainvoke.await_count
    upd = asyncio.run(node(_state()))
    assert upd["subgoal_plan"][1].status == SubgoalStatus.FAILURE
    assert llm.with_structured_output.return_value.ainvoke.await_count == calls
