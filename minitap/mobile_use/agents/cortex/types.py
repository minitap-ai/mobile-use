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
    screen_analysis_prompt: str | None = Field(
        default=None,
        description=(
            "Optional prompt for the screen_analyzer agent. "
            "Set this if you need visual analysis of the current screen. "
            "The screen_analyzer will take a screenshot and answer your specific question."
        ),
    )
