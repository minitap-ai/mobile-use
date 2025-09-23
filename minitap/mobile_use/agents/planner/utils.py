import random
import string

from minitap.mobile_use.agents.planner.types import Subgoal, SubgoalStatus
from datetime import datetime, UTC


def get_current_subgoal(subgoals: list[Subgoal]) -> Subgoal | None:
    return next((s for s in subgoals if s.status == SubgoalStatus.PENDING), None)


def get_subgoals_by_ids(subgoals: list[Subgoal], ids: list[str]) -> list[Subgoal]:
    return [s for s in subgoals if s.id in ids]


def get_next_subgoal(subgoals: list[Subgoal]) -> Subgoal | None:
    return next((s for s in subgoals if s.status == SubgoalStatus.NOT_STARTED), None)


def nothing_started(subgoals: list[Subgoal]) -> bool:
    return all(s.status == SubgoalStatus.NOT_STARTED for s in subgoals)


def complete_current_subgoal(subgoals: list[Subgoal]) -> list[Subgoal]:
    current_subgoal = get_current_subgoal(subgoals)
    if not current_subgoal:
        return subgoals
    current_subgoal.status = SubgoalStatus.SUCCESS
    current_subgoal.ended_at = datetime.now(UTC)
    return subgoals


def complete_subgoals_by_ids(subgoals: list[Subgoal], ids: list[str]) -> list[Subgoal]:
    for subgoal in subgoals:
        if subgoal.id in ids:
            subgoal.status = SubgoalStatus.SUCCESS
            subgoal.ended_at = datetime.now(UTC)
    return subgoals


def fail_current_subgoal(subgoals: list[Subgoal]) -> list[Subgoal]:
    current_subgoal = get_current_subgoal(subgoals)
    if not current_subgoal:
        return subgoals
    current_subgoal.status = SubgoalStatus.FAILURE
    current_subgoal.ended_at = datetime.now(UTC)
    return subgoals


def all_completed(subgoals: list[Subgoal]) -> bool:
    return all(s.status == SubgoalStatus.SUCCESS for s in subgoals)


def one_of_them_is_failure(subgoals: list[Subgoal]) -> bool:
    return any(s.status == SubgoalStatus.FAILURE for s in subgoals)


def start_next_subgoal(subgoals: list[Subgoal]) -> list[Subgoal]:
    next_subgoal = get_next_subgoal(subgoals)
    if not next_subgoal:
        return subgoals
    next_subgoal.status = SubgoalStatus.PENDING
    next_subgoal.started_at = datetime.now(UTC)
    return subgoals


def generate_id(length: int = 6) -> str:
    """Generates a small and distinct random string ID."""
    chars = string.ascii_lowercase + string.digits
    return "".join(random.choice(chars) for _ in range(length))
