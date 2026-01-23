"""W&B observability provider for mobile-use agent."""

import time
from typing import Self

from minitap.mobile_use.observability.base import WandbBaseManager


class WandbProvider(WandbBaseManager):
    """W&B provider that RESUMES an existing run created by android-world-runner.

    This class implements the ObservabilityProvider protocol and is used by
    mobile-use to log agent-level metrics (token usage, tool calls, etc.)
    to a W&B run that was created by the benchmark runner.

    Usage:
        async with WandbProvider(run_id="abc123") as provider:
            provider.log_agent_invocation(...)
            provider.flush(step=0)

    The provider does NOT call wandb.finish() - that's the runner's responsibility.
    """

    def __init__(
        self,
        run_id: str,
        project: str = "mobile-use-androidworld-icml2026",
        entity: str | None = None,
        enabled: bool = True,
        max_resume_retries: int = 3,
    ):
        """Initialize the W&B provider.

        Args:
            run_id: The W&B run ID to resume (from android-world-runner)
            project: W&B project name
            entity: W&B entity (team or username)
            enabled: Whether logging is enabled
            max_resume_retries: Max retries when resuming a run (for race conditions)
        """
        super().__init__(project=project, entity=entity, enabled=enabled)
        self._resume_run_id = run_id
        self._max_resume_retries = max_resume_retries
        self._task_start_time: float | None = None
        self._current_step: int = 0

    def __enter__(self) -> Self:
        """Synchronous context manager entry - resume the W&B run."""
        if not self.enabled:
            return self

        try:
            import wandb
        except ImportError:
            print("[W&B] wandb not installed, logging disabled")
            self.enabled = False
            return self

        # Check if there's already an active run with the same ID (same-process case)
        # This happens when WandbManager and WandbProvider run in the same process
        if wandb.run is not None and wandb.run.id == self._resume_run_id:
            self.run = wandb.run
            self.run_id = self.run.id
            self._same_process = True
            return self

        self._same_process = False

        # Resume the existing run with retry logic for race conditions
        for attempt in range(self._max_resume_retries):
            try:
                self.run = wandb.init(
                    id=self._resume_run_id,
                    project=self.project,
                    entity=self.entity,
                    resume="must",
                    # Match settings from WandbManager (android-world-runner)
                    settings=wandb.Settings(
                        disable_code=True,
                        disable_git=True,
                        x_disable_stats=True,  # Disable system metrics - we only want agent metrics
                        insecure_disable_ssl=True,  # Skip TLS verification for prod environments
                        x_update_finish_state=False,  # CRITICAL: Don't finalize run on process exit
                    ),
                )
                self.run_id = self.run.id
                return self
            except wandb.errors.CommError as e:
                if attempt < self._max_resume_retries - 1:
                    time.sleep(2**attempt)  # Exponential backoff
                else:
                    print(
                        f"[W&B] Failed to resume run after {self._max_resume_retries} "
                        f"attempts: {e}"
                    )
                    self.enabled = False
                    return self
            except Exception as e:
                print(f"[W&B] Unexpected error resuming run: {e}")
                self.enabled = False
                return self

        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager - DO NOT finish the run.

        The android-world-runner owns the run lifecycle and will call finish().
        We just need to make sure any remaining metrics are logged.

        Note: We use x_update_finish_state=False in wandb.Settings to prevent
        the W&B SDK's atexit handler from finalizing the run when this process
        exits. Without this, the run would be marked as finished before the
        runner can log the final task evaluation results.
        """
        if not self.enabled or not self.run:
            return

        # Flush any remaining accumulated metrics
        if self._metrics_buffer:
            self._flush_accumulated(self._current_step)

        # Note: We intentionally do NOT call wandb.finish() here
        # The runner will finish the run after logging evaluation results
        # The x_update_finish_state=False setting ensures the atexit handler
        # won't finalize the run either

    async def __aenter__(self):
        """Async context manager entry."""
        return self.__enter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        return self.__exit__(exc_type, exc_val, exc_tb)

    def set_step(self, step: int) -> None:
        """Set the current task/step index.

        Args:
            step: The current step index
        """
        self._current_step = step

    def start_task(self, task_id: str, task_name: str, step: int) -> None:
        """Mark the start of a task.

        Args:
            task_id: Unique task identifier
            task_name: Human-readable task name
            step: Task index in the benchmark
        """
        self._current_step = step
        self._task_start_time = time.time()
        self._task_id = task_id
        self._task_name = task_name

    def end_task(self, steps_taken: int | None = None) -> None:
        """Mark the end of a task and flush metrics.

        Args:
            steps_taken: Number of steps/actions the agent took to complete the task
        """
        if self._task_start_time:
            duration = time.time() - self._task_start_time
            self._accumulate("task/duration_seconds", duration)

        # Add task metadata to the flush (hierarchical naming)
        if hasattr(self, "_task_id"):
            self._metrics_buffer["task/id"] = self._task_id
        if hasattr(self, "_task_name"):
            self._metrics_buffer["task/name"] = self._task_name

        # Add steps taken
        if steps_taken is not None:
            self._metrics_buffer["task/steps_taken"] = steps_taken

        self.flush(self._current_step)

    # === ObservabilityProvider Protocol Implementation ===

    def log_agent_invocation(
        self,
        agent: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        duration_ms: float,
    ) -> None:
        """Log an LLM invocation by an agent."""
        total_tokens = input_tokens + output_tokens

        # Per-agent metrics (hierarchical naming for W&B panel organization)
        self._accumulate(f"agents/{agent}/input_tokens", input_tokens)
        self._accumulate(f"agents/{agent}/output_tokens", output_tokens)
        self._accumulate(f"agents/{agent}/total_tokens", total_tokens)
        self._accumulate(f"agents/{agent}/duration_ms", duration_ms)
        self._increment(f"agents/{agent}/invocations")

        # Per-model metrics
        model_key = model.replace("-", "_").replace(".", "_")
        self._accumulate(f"models/{model_key}/tokens", total_tokens)

        # Aggregate metrics
        self._accumulate("totals/input_tokens", input_tokens)
        self._accumulate("totals/output_tokens", output_tokens)
        self._accumulate("totals/tokens", total_tokens)
        self._accumulate("totals/llm_duration_ms", duration_ms)
        self._increment("totals/llm_invocations")

        # Log immediately for real-time visibility in W&B
        self._safe_log(
            {
                f"agents/{agent}/input_tokens": input_tokens,
                f"agents/{agent}/output_tokens": output_tokens,
                f"agents/{agent}/total_tokens": total_tokens,
                f"agents/{agent}/duration_ms": duration_ms,
                "model": model,
            }
        )

    def log_tool_call(
        self,
        tool: str,
        success: bool,
        duration_ms: float,
        error: str | None = None,
    ) -> None:
        """Log a tool call execution."""
        tool_key = tool.replace("-", "_")

        # Per-tool metrics (hierarchical naming)
        self._increment(f"tools/{tool_key}/calls")
        self._accumulate(f"tools/{tool_key}/duration_ms", duration_ms)

        if success:
            self._increment(f"tools/{tool_key}/success")
        else:
            self._increment(f"tools/{tool_key}/failures")

        # Aggregate metrics
        self._increment("totals/tool_calls")
        self._accumulate("totals/tool_duration_ms", duration_ms)
        if success:
            self._increment("totals/tool_success")
        else:
            self._increment("totals/tool_failures")

        # Log immediately for real-time visibility
        self._safe_log(
            {
                f"tools/{tool_key}/call": 1,
                f"tools/{tool_key}/success": 1 if success else 0,
                f"tools/{tool_key}/duration_ms": duration_ms,
                "tool_name": tool,
            }
        )

    def log_agent_thought(self, agent: str, thought: str) -> None:
        """Log an agent's reasoning/thought."""
        # We don't log full thoughts to W&B (too verbose)
        # Just count them for metrics
        self._increment(f"agents/{agent}/thoughts")
        self._increment("totals/thoughts")

    def log_node_execution(
        self,
        node: str,
        duration_ms: float,
        error: str | None = None,
    ) -> None:
        """Log a graph node execution."""
        node_key = node.replace("-", "_")

        # Per-node metrics (hierarchical naming)
        self._increment(f"nodes/{node_key}/executions")
        self._accumulate(f"nodes/{node_key}/duration_ms", duration_ms)

        if error:
            self._increment(f"nodes/{node_key}/errors")

    def log_error(self, source: str, error: str) -> None:
        """Log an error occurrence."""
        source_key = source.replace("-", "_")
        self._increment(f"errors/{source_key}")
        self._increment("totals/errors")

        # Log error details immediately (not buffered)
        self._safe_log(
            {
                "step": self._current_step,
                "error_source": source,
                "error_message": error[:500],  # Truncate long errors
            }
        )

    def flush(self, step: int) -> None:
        """Flush accumulated metrics for a step."""
        self._current_step = step
        self._flush_accumulated(step)
