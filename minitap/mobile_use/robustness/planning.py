"""P2: extra Planner inputs (version B only)."""

from __future__ import annotations

from minitap.mobile_use.robustness import p2_flags
from minitap.mobile_use.robustness.calendar_context import calendar_context
from minitap.mobile_use.robustness.checklist import render_checklist


def p2_human_vars(ctx, state) -> dict:
    ablation = ctx.get_ablation_config()
    out: dict = dict(p2_flags(ablation))
    out["p2_checklist_text"] = render_checklist(ctx.p2_goal_checklist)
    if ablation.p2_tally:
        try:
            from minitap.mobile_use.controllers.platform_specific_commands_controller import (
                get_device_date,
            )

            out["p2_calendar"] = calendar_context(get_device_date(ctx))
        except Exception:
            out["p2_calendar"] = None
    return out


def _norm(text: str) -> str:
    return " ".join(text.lower().split()).strip(" .")


def keep_completed_subgoals(previous: list, new: list) -> list:
    """P2 F6: a replan keeps every completed subgoal (in front, unchanged) and adds only the new
    subgoals that are not a restatement of a completed one. Failed subgoals are replaced."""
    from minitap.mobile_use.agents.planner.types import Subgoal, SubgoalStatus
    from minitap.mobile_use.agents.planner.utils import generate_id

    kept = [s for s in previous if s.status == SubgoalStatus.SUCCESS]
    done = {_norm(s.description) for s in kept}
    fresh = [s for s in new if _norm(s.description) not in done]
    if not fresh:
        # A replan always has work to do (something failed): never end up with an all-done plan.
        # If every new subgoal restates a completed one, that completed one was wrong: keep the
        # planner's subgoals; if there are none, retry the failed requirement itself.
        fresh = list(new) or [
            Subgoal(id=generate_id(), description=s.description, status=SubgoalStatus.NOT_STARTED)
            for s in previous
            if s.status == SubgoalStatus.FAILURE
        ]
    return kept + fresh
