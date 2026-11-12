"""P2 F6: step-budget checkpoint.

Observed in version B (dev rounds 2-5): 7 of 13 max_steps failures had already reached a state the
official checker scores as correct; the remaining budget went into re-checking, re-scrolling and
replans, and the episode ended on the step limit without ever being declared done. When the step
budget is nearly spent, hand the task to the goal verifier once: if the device state satisfies the
goal, the task ends properly; if not, the verifier's rejection replans as usual.
"""

from __future__ import annotations

from minitap.mobile_use.agents.planner.types import SubgoalStatus

RESERVE_NODE_RUNS = 70  # verifier + one replan cycle


def node_runs_used(runtime) -> int | None:
    if runtime is None:
        return None
    return int(sum(runtime.node_runs.values()))


def checkpoint_due(ctx, state, runtime) -> bool:
    if getattr(ctx, "p2_budget_checkpoint_done", False):
        return False
    used = node_runs_used(runtime)
    limit = state.remaining_steps
    if used is None or not limit:
        return False
    return used >= limit - RESERVE_NODE_RUNS


def checkpoint_plan(plan: list) -> list:
    out = [s.model_copy() for s in plan]
    for s in out:
        if s.status != SubgoalStatus.SUCCESS:
            s.status = SubgoalStatus.SUCCESS
            s.completion_reason = (
                "Step budget checkpoint: the remaining budget is reserved for verifying the goal "
                "on the device now."
            )
    return out
