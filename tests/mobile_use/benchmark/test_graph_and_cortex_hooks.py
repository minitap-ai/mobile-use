from langchain_core.messages import AIMessage, ToolMessage

from minitap.mobile_use.agents.cortex.cortex import get_executed_tool_calls
from minitap.mobile_use.agents.planner.types import Subgoal, SubgoalStatus
from minitap.mobile_use.graph.graph import post_cortex_gate
from minitap.mobile_use.graph.state import State


def make_state(**kw):
    base = dict(
        messages=[],
        initial_goal="g",
        subgoal_plan=[],
        latest_ui_hierarchy=None,
        latest_screenshot=None,
        focused_app_info=None,
        device_date=None,
        structured_decisions=None,
        complete_subgoals_by_ids=[],
        executor_messages=[],
        cortex_last_thought=None,
        agents_thoughts=[],
    )
    base.update(kw)
    return State(**base)


def test_post_cortex_gate_routes_failed_plan_to_planner():
    plan = [Subgoal(id="a", description="d", status=SubgoalStatus.FAILURE)]
    assert post_cortex_gate(make_state(subgoal_plan=plan)) == ["force_replan"]


def test_post_cortex_gate_unchanged_otherwise():
    plan = [Subgoal(id="a", description="d", status=SubgoalStatus.PENDING)]
    assert post_cortex_gate(make_state(subgoal_plan=plan, structured_decisions="[...]")) == [
        "execute_decisions"
    ]
    assert post_cortex_gate(make_state(subgoal_plan=plan)) == ["review_subgoals"]


def test_get_executed_tool_calls():
    ai = AIMessage(
        content="", tool_calls=[{"name": "tap", "args": {"target": {"text": "OK"}}, "id": "1"}]
    )
    st = make_state(executor_messages=[ai, ToolMessage(content="ok", tool_call_id="1")])
    assert get_executed_tool_calls(st) == [{"name": "tap", "args": {"target": {"text": "OK"}}}]
