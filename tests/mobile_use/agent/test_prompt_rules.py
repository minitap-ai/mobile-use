"""Fix round 4: task-agnostic prompt rules (classes M1 completion evidence, M2 several items /
destructive actions, M4 structured transfer, M6 long sources)."""

from pathlib import Path

from jinja2 import Template

AGENTS = Path(__file__).resolve().parents[3] / "minitap" / "mobile_use" / "agents"


def render(name, **kw):
    return Template((AGENTS / name).read_text(encoding="utf-8")).render(**kw)


def test_cortex_rules():
    text = render(
        "cortex/cortex.md",
        platform="android",
        initial_goal="g",
        subgoal_plan=[],
        current_subgoal=None,
        executor_feedback="",
        executor_tools_list="",
        locked_app_package=None,
        use_vision=True,
        use_meta_reasoning=True,
        use_data_fidelity=True,
    )
    for phrase in (
        "effect is visible",
        "re-read the list",
        "one entry per item",
        "another identical copy still remains",
        "to its end",
        "exact answer",
    ):
        assert phrase in text, phrase


def test_planner_rules():
    text = render(
        "planner/planner.md",
        platform="android",
        executor_tools_list="",
        locked_app_package=None,
        current_foreground_app=None,
        video_recording_enabled=False,
    )
    for phrase in ("inventories them", "one entry per item", "commits it", "State the answer"):
        assert phrase in text, phrase


def test_orchestrator_rule():
    text = render("orchestrator/orchestrator.md", platform="android")
    assert "observed evidence of the effect" in text
