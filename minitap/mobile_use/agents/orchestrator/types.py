from typing import Annotated

from pydantic import BaseModel


class SubgoalCompletionReport(BaseModel):
    completed_subgoal_ids: Annotated[list[str], "IDs of subgoals that have been completed"] = []
    incomplete_subgoal_ids: Annotated[list[str], "IDs of subgoals to keep in PENDING state"] = []


class OrchestratorOutput(BaseModel):
    subgoal_completion_report: Annotated[
        SubgoalCompletionReport,
        "Report of subgoals that have been completed and subgoals to keep in PENDING state",
    ]
    needs_replaning: Annotated[bool, "Whether the orchestrator needs to replan the subgoal plan"]
    reason: str
