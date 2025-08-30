"""
Task-related type definitions for the Mobile-use SDK.
"""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar, overload

from pydantic import BaseModel, Field

from minitap.mobile_use.config import LLMConfig, get_default_llm_config
from minitap.mobile_use.constants import RECURSION_LIMIT
from minitap.mobile_use.context import DeviceContext
from minitap.mobile_use.sdk.utils import load_llm_config_override


class AgentProfile(BaseModel):
    """
    Represents a mobile-use agent profile.

    Attributes:
        name: Name of the agent - used to reference the agent when running tasks.
        llm_config: LLM configuration for the agent.
    """

    name: str
    llm_config: LLMConfig = Field(default_factory=get_default_llm_config)

    @overload
    def __init__(self, *, name: str, llm_config: LLMConfig): ...

    @overload
    def __init__(self, *, name: str, from_file: str): ...

    def __init__(
        self,
        *,
        name: str,
        llm_config: LLMConfig | None = None,
        from_file: str | None = None,
        **kwargs,
    ):
        kwargs["name"] = name
        if from_file:
            kwargs["llm_config"] = load_llm_config_override(Path(from_file))
        elif llm_config:
            kwargs["llm_config"] = llm_config
        else:
            raise ValueError("Either llm_config or from_file must be provided")
        super().__init__(**kwargs)

    def __str__(self):
        return f"Profile {self.name}:\n{self.llm_config}"


class TaskStatus(str, Enum):
    """Task execution status enumeration."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


T = TypeVar("T", bound=BaseModel)
TOutput = TypeVar("TOutput", bound=BaseModel | None)


class TaskRequestCommon(BaseModel):
    """
    Defines common parameters of a mobile automation task request.
    """

    max_steps: int = RECURSION_LIMIT
    record_trace: bool = False
    trace_path: Path = Path("mobile-use-traces")
    llm_output_path: Path | None = None
    thoughts_output_path: Path | None = None


class TaskRequest[TOutput](TaskRequestCommon):
    """
    Defines the format of a mobile automation task request.

    Attributes:
        goal: Natural language description of the goal to achieve
        profile: Optional agent profile to use for executing the task
        task_name: Optional name for the task
        output_description: Optional natural language description of expected output format
        output_format: Optional pydantic model for the output format of the task
        max_steps: Maximum number of steps the agent can take (default: 20)
        record_trace: Whether to record a trace (screenshots, actions) of the execution
                      (default: False)
        trace_path: Directory path to save trace data if recording is enabled
        llm_output_path: Path to save LLM output data
        thoughts_output_path: Path to save thoughts output data
    """

    goal: str
    profile: str | None = None
    task_name: str | None = None
    output_description: str | None = None
    output_format: type[TOutput] | None = None


class TaskResult(BaseModel):
    """
    Result of a mobile automation task.

    Attributes:
        content: Raw result content (could be text or structured data)
        error: Error message if the task failed
        execution_time_seconds: How long the task took to execute
        steps_taken: Number of steps the agent took to complete the task
    """

    content: Any = None
    error: str | None = None
    execution_time_seconds: float
    steps_taken: int

    def get_as_model(self, model_class: type[T]) -> T:
        """
        Parse the content into a Pydantic model instance.

        Args:
            model_class: The Pydantic model class to parse the data into

        Returns:
            An instance of the specified model class

        Raises:
            ValueError: If content is None or not compatible with the model
        """
        if self.content is None:
            raise ValueError("No content available to parse into a model")
        if isinstance(self.content, model_class):
            return self.content
        return model_class.model_validate(self.content)


class Task(BaseModel):
    """
    A mobile automation task to be executed.

    Attributes:
        id: Unique identifier for the task
        device: Information about the target device
        status: Current status of the task execution
        request: User task request
        created_at: ISO timestamp when the task was created
        ended_at: ISO timestamp when the task ended
    """

    id: str
    device: DeviceContext
    status: TaskStatus
    request: TaskRequest
    created_at: datetime
    ended_at: datetime | None = None
    result: TaskResult | None = None

    def finalize(
        self,
        content: Any | None = None,
        state: dict | None = None,
        error: str | None = None,
        cancelled: bool = False,
    ):
        self.status = TaskStatus.COMPLETED if error is None else TaskStatus.FAILED
        if self.status == TaskStatus.FAILED and cancelled:
            self.status = TaskStatus.CANCELLED
        self.ended_at = datetime.now()

        duration = self.ended_at - self.created_at
        steps_taken = -1
        if state is not None:
            metadata = state.get("metadata", None)
            if metadata:
                steps_taken = metadata.get("step_count", -1)

        self.result = TaskResult(
            content=content,
            error=error,
            execution_time_seconds=duration.total_seconds(),
            steps_taken=steps_taken,
        )

    def get_name(self) -> str:
        return self.request.task_name or self.id
