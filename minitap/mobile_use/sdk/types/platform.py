from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer
from pydantic.v1.utils import to_lower_camel

TaskRunStatus = Literal["pending", "running", "completed", "failed", "cancelled"]

IsoDatetime = Annotated[
    datetime,
    PlainSerializer(
        func=lambda v: v.isoformat() if v else None,
        return_type=str,
        when_used="unless-none",
    ),
]


class BaseApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_lower_camel,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class LLMProfileResponse(BaseApiModel):
    """Response model for LLM profile."""

    id: str = Field(..., description="Profile ID")
    name: str = Field(..., description="Profile name")
    description: str | None = Field(None, description="Profile description")
    llms: dict[str, Any] = Field(..., description="LLM configuration")
    created_at: str = Field(..., description="Creation timestamp (ISO format)")
    updated_at: str = Field(..., description="Last update timestamp (ISO format)")


class TaskOptionsResponse(BaseApiModel):
    """Response model for task options."""

    id: str = Field(..., description="Options ID")
    enable_tracing: bool = Field(..., description="Whether tracing is enabled")
    max_steps: int = Field(..., description="Maximum number of steps")
    created_at: str = Field(..., description="Creation timestamp (ISO format)")
    updated_at: str = Field(..., description="Last update timestamp (ISO format)")


class TaskResponse(BaseApiModel):
    """Response model for task."""

    id: str = Field(..., description="Task ID")
    name: str = Field(..., description="Task name")
    description: str | None = Field(None, description="Task description")
    input_prompt: str = Field(..., description="Input prompt")
    output_description: str | None = Field(None, description="Output description")
    options: TaskOptionsResponse = Field(..., description="Task options")
    created_at: str = Field(..., description="Creation timestamp (ISO format)")
    updated_at: str = Field(..., description="Last update timestamp (ISO format)")


class CreateTaskRunRequest(BaseApiModel):
    """Request model for creating a task run."""

    task_id: str = Field(..., description="ID of the task to run")
    llm_profile_id: str = Field(..., description="LLM profile ID to use")
    virtual_mobile_id: str | None = Field(None, description="Virtual mobile ID to use")
    locked_app_package: str | None = Field(None, description="App package to lock for the task run")
    execution_origin: str | None = Field(None, description="Origin of the task execution")


class UpdateTaskRunStatusRequest(BaseApiModel):
    """Request model for updating task run status."""

    status: TaskRunStatus = Field(..., description="New status of the task run")
    message: str | None = Field(None, description="Message associated with the status")
    output: str | None = Field(None, description="Output of the task run")


class TaskRunResponse(BaseApiModel):
    """Response model for a single task run."""

    id: str = Field(..., description="Unique identifier for the task run")
    task: TaskResponse | None = Field(
        ..., description="ID of the task this run is for or None if manually created"
    )
    llm_profile: LLMProfileResponse = Field(..., description="LLM profile ID used for this run")
    status: TaskRunStatus = Field(..., description="Current status of the task run")
    input_prompt: str = Field(..., description="Input prompt for this task run")
    output_description: str | None = Field(None, description="Description of expected output")
    created_at: datetime = Field(..., description="When the task run was created")
    started_at: datetime | None = Field(None, description="When the task run started")
    finished_at: datetime | None = Field(None, description="When the task run finished")
    locked_app_package: str | None = Field(
        None, description="The app package to lock for the task run"
    )


SubgoalState = Literal["pending", "started", "completed", "failed"]


class MobileUseSubgoal(BaseModel):
    """Upsert MobileUseSubgoal API model."""

    name: str = Field(..., description="Name of the subgoal")
    state: SubgoalState = Field(default="pending", description="Current state of the subgoal")
    started_at: IsoDatetime | None = Field(default=None, description="When the subgoal started")
    ended_at: IsoDatetime | None = Field(default=None, description="When the subgoal ended")


class UpsertTaskRunPlanRequest(BaseApiModel):
    """Upsert MobileUseSubgoal API model."""

    started_at: IsoDatetime = Field(..., description="When the plan started")
    subgoals: list[MobileUseSubgoal] = Field(..., description="Subgoals of the plan")
    ended_at: IsoDatetime | None = Field(
        default=None,
        description="When the plan ended (replanned or completed)",
    )


class TaskRunPlanResponse(UpsertTaskRunPlanRequest):
    """Response model for a task run plan."""

    id: str = Field(..., description="Unique identifier for the task run plan")
    task_run_id: str = Field(..., description="ID of the task run this plan is for")


class UpsertTaskRunAgentThoughtRequest(BaseApiModel):
    """Upsert MobileUseAgentThought request model."""

    agent: str = Field(..., description="Agent that produced the thought")
    content: str = Field(..., description="Content of the thought")
    timestamp: IsoDatetime = Field(..., description="Timestamp of the thought (UTC)")
