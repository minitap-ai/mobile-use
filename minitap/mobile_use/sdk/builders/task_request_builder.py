"""
Builder for TaskRequest objects using a fluent interface.
"""

from pathlib import Path
from typing import Self, TypeVar, cast

from pydantic import BaseModel

from minitap.mobile_use.constants import RECURSION_LIMIT
from minitap.mobile_use.sdk.types.agent import AgentProfile
from minitap.mobile_use.sdk.types.task import TaskRequest, TaskRequestCommon


TIn = TypeVar("TIn", bound=BaseModel | None)
TOut = TypeVar("TOut", bound=BaseModel)


class TaskRequestCommonBuilder(BaseModel):
    """
    Builder class providing a fluent interface for creating TaskRequestCommon objects.
    """

    def __init__(self):
        self._max_steps = RECURSION_LIMIT
        self._record_trace = False
        self._trace_path = Path("mobile-use-traces")
        self._llm_output_path: Path | None = None
        self._thoughts_output_path: Path | None = None
        self._locked_app_package: str | None = None

    def with_max_steps(self, max_steps: int) -> Self:
        """
        Set the maximum number of steps the task can take.

        Args:
            max_steps: Maximum number of steps
        """
        self._max_steps = max_steps
        return self

    def with_trace_recording(self, enabled: bool = True, path: str | None = None) -> Self:
        """
        Configure trace recording for the task.

        Traces record screenshots and actions during execution.

        Args:
            enabled: Whether to enable trace recording
            path: Directory path where traces should be saved
        """
        self._record_trace = enabled
        if enabled and path:
            self._trace_path = Path(path)
        return self

    def with_llm_output_saving(self, path: str) -> Self:
        """
        Configure LLM output saving for the task.

        Args:
            path: Path where to save the LLM output message
        """
        self._llm_output_path = Path(path)
        return self

    def with_thoughts_output_saving(self, path: str) -> Self:
        """
        Configure thoughts output saving for the task.

        Args:
            path: Path where to save the thoughts output message
        """
        self._thoughts_output_path = Path(path)
        return self

    def with_locked_app_package(self, package_name: str) -> Self:
        """
        Set the app package to lock execution to.

        This ensures the specified app is launched and in the foreground before
        the agentic loop starts.

        Args:
            package_name: Package name (Android, e.g., 'com.whatsapp') or
                         bundle ID (iOS, e.g., 'com.apple.mobilesafari')
        """
        self._locked_app_package = package_name
        return self

    def build(self) -> TaskRequestCommon:
        """
        Build the TaskRequestCommon object.

        Returns:
            A configured TaskRequestCommon object

        Raises:
            ValueError: If required fields are missing
        """
        return TaskRequestCommon(
            max_steps=self._max_steps,
            record_trace=self._record_trace,
            trace_path=self._trace_path,
            llm_output_path=self._llm_output_path,
            thoughts_output_path=self._thoughts_output_path,
            locked_app_package=self._locked_app_package,
        )


class TaskRequestBuilder[TIn](TaskRequestCommonBuilder):
    """
    Builder class providing a fluent interface for creating TaskRequest objects.

    This builder allows for step-by-step construction of a TaskRequest with
    clear methods that make the configuration process intuitive and type-safe.

    Examples:
        >>> builder = TaskRequestBuilder[None](goal="Open Gmail and check unread emails")
        >>> task_request = (
        ...     builder
        ...     .with_max_steps(30)
        ...     .using_profile("LowReasoning")
        ...     .with_output_description("A list of email subjects and senders")
        ...     .build()
        ... )
    """

    def __init__(self, goal: str):
        """Initialize an empty TaskRequestBuilder."""
        super().__init__()
        self._goal = goal
        self._profile: str | AgentProfile | None = None
        self._name: str | None = None
        self._output_description = None
        self._output_format: type[TIn] | None = None

    @classmethod
    def from_common(cls, goal: str, common: TaskRequestCommon):
        res = cls(goal=goal)
        res._max_steps = common.max_steps
        res._record_trace = common.record_trace
        res._trace_path = common.trace_path
        res._llm_output_path = common.llm_output_path
        res._thoughts_output_path = common.thoughts_output_path
        res._locked_app_package = common.locked_app_package
        return res

    def using_profile(self, profile: str | AgentProfile) -> "TaskRequestBuilder[TIn]":
        """
        Set the agent profile for executing the task.

        Args:
            profile: The agent profile to use
        """
        self._profile = profile
        return self

    def with_name(self, name: str) -> "TaskRequestBuilder[TIn]":
        """
        Set the name of the task - useful when recording traces.
        Otherwise, a random name will be generated.

        Args:
            name: Name of the task
        """
        self._name = name
        return self

    def without_llm_output_saving(self) -> Self:
        """
        Disable LLM output saving for the task.
        """
        self._llm_output_path = None
        return self

    def without_thoughts_output_saving(self):
        """
        Disable thoughts output saving for the task.
        """
        self._thoughts_output_path = None
        return self

    def with_output_description(self, description: str) -> "TaskRequestBuilder[TIn]":
        """
        Set the description of the expected output format.
        This is especially useful for data extraction tasks.

        Args:
            description: Description of the expected output format
        """
        self._output_description = description
        return self

    def with_output_format(self, output_format: type[TOut]) -> "TaskRequestBuilder[TOut]":
        """
        Set the pydantic model for the expected output format.

        Args:
            output_format: Pydantic model instance defining the output format
        """
        self._output_format = output_format  # type: ignore
        return cast(TaskRequestBuilder[TOut], self)

    def build(self) -> TaskRequest[TIn]:
        """
        Build the TaskRequest object.

        Returns:
            A configured TaskRequest object

        Raises:
            ValueError: If required fields are missing
        """
        if not self._goal:
            raise ValueError("Task goal is required")

        if self._output_format and self._output_description:
            raise ValueError("Output format and description are mutually exclusive")

        task_request = TaskRequest(
            goal=self._goal,
            profile=self._profile.name
            if isinstance(self._profile, AgentProfile)
            else self._profile,
            task_name=self._name,
            output_description=self._output_description,
            output_format=self._output_format,
            max_steps=self._max_steps,
            record_trace=self._record_trace,
            trace_path=self._trace_path,
            llm_output_path=self._llm_output_path,
            thoughts_output_path=self._thoughts_output_path,
            locked_app_package=self._locked_app_package,
        )
        return task_request
