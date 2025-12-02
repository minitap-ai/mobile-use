from pydantic import BaseModel, Field


class CortexOutput(BaseModel):
    decisions: str | None = Field(
        default=None, description="The decisions to be made. A stringified JSON object"
    )
    decisions_reason: str | None = Field(default=None, description="The reason for the decisions")
    goals_completion_reason: str | None = Field(
        default=None,
        description="The reason for the goals completion, if there are any goals to be completed.",
    )
    complete_subgoals_by_ids: list[str] = Field(
        default_factory=list, description="List of subgoal IDs to complete"
    )
