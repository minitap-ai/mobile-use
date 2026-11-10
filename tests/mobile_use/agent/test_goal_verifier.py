"""Fix round 3: goal verification before the task ends (failure class M1)."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from minitap.mobile_use.agents.planner.types import Subgoal, SubgoalStatus
from minitap.mobile_use.agents.verifier import verifier as v
from minitap.mobile_use.config import AblationConfig
from minitap.mobile_use.graph.graph import post_goal_verifier_gate
from minitap.mobile_use.graph.state import State


def make_state(**kw):
    base = dict(
        messages=[],
        initial_goal="do the thing",
        latest_ui_hierarchy=None,
        latest_screenshot=None,
        focused_app_info=None,
        device_date=None,
        structured_decisions=None,
        complete_subgoals_by_ids=[],
        executor_messages=[],
        cortex_last_thought=None,
        agents_thoughts=["[cortex] step"],
        subgoal_plan=[Subgoal(id="a", description="d", status=SubgoalStatus.SUCCESS)],
    )
    base.update(kw)
    return State(**base)


def test_rejection_adds_one_failed_subgoal_and_routes_to_planner():
    st = make_state()
    plan, thoughts = v.rejection_update(
        st, v.VerifierOutput(satisfied=False, evidence="form not submitted", missing="press submit")
    )
    assert [s.status for s in plan] == [SubgoalStatus.SUCCESS, SubgoalStatus.FAILURE]
    assert "press submit" in plan[-1].description and "REPLANNING" in thoughts[-1]
    assert post_goal_verifier_gate(make_state(subgoal_plan=plan)) == "replan"
    assert post_goal_verifier_gate(st) == "end"


def _ctx(rejections=0):
    ctx = MagicMock()
    ctx.goal_verification_rejections = rejections
    ctx.get_ablation_config.return_value = AblationConfig(use_vision=False)
    ctx.device.mobile_platform.value = "android"
    ctx.on_plan_changes = None
    ctx.on_agent_thought = None
    ctx.execution_setup = None
    return ctx


def _patch(monkeypatch, out):
    controller = MagicMock()
    controller.get_screen_data = AsyncMock(
        return_value=SimpleNamespace(elements=[{"text": "x"}], base64=None)
    )
    monkeypatch.setattr(v, "create_device_controller", lambda ctx: controller)
    llm = MagicMock()
    llm.with_structured_output.return_value.ainvoke = AsyncMock(return_value=out)
    monkeypatch.setattr(v, "get_llm", lambda **kw: llm)
    return llm


def test_satisfied_goal_records_evidence_and_answer(monkeypatch):
    _patch(monkeypatch, v.VerifierOutput(satisfied=True, evidence="list shows 3 items", answer="3"))
    ctx = _ctx()
    upd = asyncio.run(v.GoalVerifierNode(ctx)(make_state()))
    assert upd["agents_thoughts"][-1] == "[cortex] Final answer: 3"
    assert "subgoal_plan" not in upd and ctx.goal_verification_rejections == 0


def test_rejected_goal_replans_and_counts(monkeypatch):
    _patch(
        monkeypatch,
        v.VerifierOutput(satisfied=False, evidence="nothing copied", missing="tap Copy"),
    )
    ctx = _ctx()
    upd = asyncio.run(v.GoalVerifierNode(ctx)(make_state()))
    assert upd["subgoal_plan"][-1].status == SubgoalStatus.FAILURE
    assert ctx.goal_verification_rejections == 1


def test_limit_reached_ends_without_llm_call(monkeypatch):
    llm = _patch(monkeypatch, v.VerifierOutput(satisfied=False, evidence="x", missing="y"))
    upd = asyncio.run(v.GoalVerifierNode(_ctx(rejections=v.MAX_REJECTIONS))(make_state()))
    assert upd == {}
    llm.with_structured_output.return_value.ainvoke.assert_not_called()


@pytest.mark.parametrize("flag", [True, False])
def test_graph_routes_end_through_verifier_only_when_enabled(flag):
    from minitap.mobile_use.graph import graph as g

    ctx = MagicMock()
    ctx.get_ablation_config.return_value = AblationConfig(use_goal_verification=flag)
    ctx.video_recording_enabled = False
    compiled = asyncio.run(g.get_multi_agent_graph(ctx))
    assert ("goal_verifier" in compiled.get_graph().nodes) is flag


def test_verifier_prompt_is_task_agnostic():
    text = (v.Path(v.__file__).parent / "verifier.md").read_text()
    assert "{{ initial_goal }}" in text
