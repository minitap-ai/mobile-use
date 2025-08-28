from typing import Annotated

from pydantic import BaseModel


class OrchestratorOutput(BaseModel):
    completed_subgoal_ids: Annotated[
        list[str], "IDs of subgoals that can now be marked as complete"
    ] = []
    needs_replaning: Annotated[bool, "Whether the orchestrator needs to replan the subgoal plan"]
    reason: str
