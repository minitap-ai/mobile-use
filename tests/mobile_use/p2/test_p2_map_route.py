"""P2 (version B): route/track-through-places procedure (robustness/map_route.py).

The procedure text is rendered only for goals that ask to create or save a track or route
with/through given places; every other goal's Planner, Cortex and verifier prompts must render
byte-identically to the same prompts without the variable.
"""

from pathlib import Path

import pytest
from jinja2 import Template

from minitap.mobile_use.config import AblationConfig
from minitap.mobile_use.robustness import p2_flags
from minitap.mobile_use.robustness.map_route import is_map_route_goal, map_route_flag

AGENTS = Path(__file__).resolve().parents[3] / "minitap" / "mobile_use" / "agents"
PROMPTS = [
    AGENTS / "cortex" / "cortex.md",
    AGENTS / "planner" / "planner.md",
    AGENTS / "verifier" / "verifier_p2.md",
]

ROUTE_GOALS = [
    "Save a track with waypoints Alpha, Beta, Gamma in the maps app in the same order as listed.",
    "Create a route through Paris and Lyon.",
    "Plan a route via the station, the museum and the harbour, then save it.",
    "Make a track passing by the lake and the castle.",
    "Save a route with stops at A and B.",
]
OTHER_GOALS = [
    "Add a favorite location marker for Alpha in the maps app.",
    "Add a location marker for 47.1, 9.5 in the maps app.",
    "Record a track of my run in the activity app.",
    "Delete the following tracks: Morning run, Evening walk.",
    "Create a playlist titled 'Road trip' with the songs A, B.",
    "What is the total distance of my cycling activities this week?",
    "Save a copy of the receipt in the Documents folder.",
    "Create a new note named route_notes.md with the text 'via the back door'.",
    "",
    None,
]


@pytest.mark.parametrize("goal", ROUTE_GOALS)
def test_trigger_matches_route_goals(goal):
    assert is_map_route_goal(goal)


@pytest.mark.parametrize("goal", OTHER_GOALS)
def test_trigger_ignores_other_goals(goal):
    assert not is_map_route_goal(goal)


def test_flag_needs_version_b():
    goal = ROUTE_GOALS[0]
    assert map_route_flag(AblationConfig(), goal) is False  # version A defaults: p2 off
    assert map_route_flag(AblationConfig(p2_coverage=True), goal) is True
    assert map_route_flag(AblationConfig(p2_coverage=True), OTHER_GOALS[0]) is False


def _vars(p2_on: bool) -> dict:
    ablation = AblationConfig(**{k: True for k in p2_flags(AblationConfig())}) if p2_on else AblationConfig()
    return dict(
        platform="android",
        initial_goal="g",
        executor_tools_list="tap, back",
        use_vision=True,
        use_meta_reasoning=True,
        use_data_fidelity=True,
        has_action_log=True,
        has_screen_log=True,
        has_full_read=True,
        **p2_flags(ablation),
    )


@pytest.mark.parametrize("path", PROMPTS, ids=lambda p: p.name)
@pytest.mark.parametrize("p2_on", [False, True])
def test_other_goals_render_byte_identically(path, p2_on):
    tpl = Template(path.read_text(encoding="utf-8"))
    base = tpl.render(**_vars(p2_on))
    assert tpl.render(**_vars(p2_on), p2_map_route=False) == base


@pytest.mark.parametrize("path", PROMPTS, ids=lambda p: p.name)
def test_route_goals_get_the_procedure(path):
    tpl = Template(path.read_text(encoding="utf-8"))
    on = tpl.render(**_vars(True), p2_map_route=True)
    off = tpl.render(**_vars(True), p2_map_route=False)
    assert on != off
    assert "Route or track through given places" in on or "Route points placed" in on
    assert "add-point" in on
    assert "Route or track through given places" not in off and "Route points placed" not in off
