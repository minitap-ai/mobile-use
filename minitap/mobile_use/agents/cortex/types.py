from pydantic import BaseModel, Field


class CortexOutput(BaseModel):
    decisions: str = Field(..., description="The decisions to be made. A stringified JSON object")
    decisions_reason: str = Field(..., description="The reason for the decisions")
    goals_completion_reason: str | None = Field(
        None,
        description="The reason for the goals completion, if there are any goals to be completed.",
    )
    complete_subgoals_by_ids: list[str] | None = Field(
        [], description="List of subgoal IDs to complete"
    )
    screen_analysis_prompt: str | None = Field(
        None,
        description=(
            "Optional prompt for the screen_analyzer agent. "
            "Set this if you need visual analysis of the current screen. "
            "The screen_analyzer will take a screenshot and answer your specific question."
        ),
    )
