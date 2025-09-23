from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel


class PlannerSubgoalOutput(BaseModel):
    description: str


class PlannerOutput(BaseModel):
    subgoals: list[PlannerSubgoalOutput]


class SubgoalStatus(Enum):
    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


class Subgoal(BaseModel):
    id: Annotated[str, "Unique identifier of the subgoal"]
    description: Annotated[str, "Description of the subgoal"]
    completion_reason: Annotated[
        str | None, "Reason why the subgoal was completed (failure or success)"
    ] = None
    status: SubgoalStatus
    started_at: Annotated[datetime | None, "When the subgoal started"] = None
    ended_at: Annotated[datetime | None, "When the subgoal ended"] = None

    def __str__(self):
        status_emoji = "❓"
        match self.status:
            case SubgoalStatus.SUCCESS:
                status_emoji = "✅"
            case SubgoalStatus.FAILURE:
                status_emoji = "❌"
            case SubgoalStatus.PENDING:
                status_emoji = "⏳"
            case SubgoalStatus.NOT_STARTED:
                status_emoji = "(not started yet)"

        output = f"- [ID:{self.id}]: {self.description} : {status_emoji}."
        if self.completion_reason:
            output += f" Completion reason: {self.completion_reason}"
        return output

    def __repr__(self):
        return str(self)
