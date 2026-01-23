"""W&B observability provider for mobile-use agent metrics.

This module implements W&B run resumption where mobile-use resumes an existing
W&B run created by android-world-runner. The run_id is encoded in the task name
using the format: "{task_name}__wandb_{run_id}"

This approach allows W&B tracking to flow through mobile-manager without any
changes to the mobile-manager codebase.
"""

import time
from typing import Any, Self

# Hardcoded project name - this won't change
WANDB_PROJECT = "mobile-use-androidworld-icml2026"


def parse_task_name_for_wandb(task_name: str) -> tuple[str, str | None]:
    """Parse task name to extract wandb run ID.

    The android-world-runner encodes the W&B run ID in the task name using
    the format: "{task_name}__wandb_{run_id}"

    Args:
        task_name: Task name, possibly with "__wandb_{run_id}" suffix

    Returns:
        Tuple of (clean_task_name, wandb_run_id or None)

    Examples:
        >>> parse_task_name_for_wandb("ContactsAddContact__wandb_abc123")
        ("ContactsAddContact", "abc123")
        >>> parse_task_name_for_wandb("ContactsAddContact")
        ("ContactsAddContact", None)
        >>> parse_task_name_for_wandb("Task__with__underscores__wandb_xyz789")
        ("Task__with__underscores", "xyz789")
    """
    if "__wandb_" in task_name:
        # Use rsplit to handle task names that contain underscores
        parts = task_name.rsplit("__wandb_", 1)
        if len(parts) == 2 and parts[1]:  # Ensure we have a non-empty run_id
            return parts[0], parts[1]
    return task_name, None


class WandbResumeProvider:
    """Resumes an existing W&B run created by android-world-runner.

    This provider resumes a W&B run using the run_id extracted from the task name.
    It logs agent-level metrics (tokens, tool calls, durations) to the same run
    that android-world-runner uses for task-level metrics (success/failure).

    Usage:
        clean_name, run_id = parse_task_name_for_wandb(task_name)
        if run_id:
            with WandbResumeProvider(run_id=run_id, task_name=clean_name) as provider:
                provider.log_agent_invocation(...)
                provider.log_tool_call(...)

    Note:
        This provider does NOT call wandb.finish() since android-world-runner
        owns the run lifecycle.
    """

    def __init__(
        self,
        run_id: str,
        task_name: str,
        entity: str | None = None,
        enabled: bool = True,
    ):
        """Initialize the W&B resume provider.

        Args:
            run_id: W&B run ID to resume (extracted from task name)
            task_name: Clean task name (without wandb suffix)
            entity: W&B entity (team or username), optional
            enabled: Whether logging is enabled
        """
        self.run_id = run_id
        self.task_name = task_name
        self.project = WANDB_PROJECT
        self.entity = entity
        self.enabled = enabled

        self.run = None
        self._task_start_time: float | None = None
        self._metrics_buffer: dict[str, Any] = {}
        self._failed_logs: list[tuple[dict, float]] = []

    def __enter__(self) -> Self:
        """Enter context manager - resume W&B run."""
        if not self.enabled:
            return self

        try:
            import wandb
        except ImportError:
            print("[W&B] wandb not installed, logging disabled")
            self.enabled = False
            return self

        try:
            # Resume the existing run created by android-world-runner
            self.run = wandb.init(
                project=self.project,
                entity=self.entity,
                id=self.run_id,
                resume="must",  # Fail if run doesn't exist
                reinit=True,  # Allow multiple runs in same process
                settings=wandb.Settings(
                    disable_code=True,
                    disable_git=True,
                    x_disable_stats=True,  # Disable system metrics
                    insecure_disable_ssl=True,  # Skip TLS verification for prod
                ),
            )

            self._task_start_time = time.time()
            print(f"[W&B] Resumed run for task '{self.task_name}': {self.run.url}")
            return self

        except Exception as e:
            print(f"[W&B] Failed to resume run {self.run_id}: {e}")
            self.enabled = False
            return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager - flush metrics but DO NOT finish run.

        The android-world-runner owns the run lifecycle and will call finish().
        We only flush any remaining buffered metrics.
        """
        if not self.enabled or not self.run:
            return

        try:
            # Flush any remaining metrics
            if self._metrics_buffer:
                self._flush_accumulated()

            # Log task duration for this specific task
            if self._task_start_time:
                duration = time.time() - self._task_start_time
                self._safe_log(
                    {
                        f"task/{self.task_name}/duration_seconds": duration,
                    }
                )

            # DO NOT call wandb.finish() - android-world-runner owns the run
            print(f"[W&B] Finished logging for task '{self.task_name}'")

        except Exception as e:
            print(f"[W&B] Error flushing metrics: {e}")

    async def __aenter__(self):
        """Async context manager entry."""
        return self.__enter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        return self.__exit__(exc_type, exc_val, exc_tb)

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

        # Per-agent metrics with task prefix for disambiguation
        prefix = f"task/{self.task_name}"

        self._accumulate(f"{prefix}/agents/{agent}/input_tokens", input_tokens)
        self._accumulate(f"{prefix}/agents/{agent}/output_tokens", output_tokens)
        self._accumulate(f"{prefix}/agents/{agent}/total_tokens", total_tokens)
        self._accumulate(f"{prefix}/agents/{agent}/duration_ms", duration_ms)
        self._increment(f"{prefix}/agents/{agent}/invocations")

        # Aggregate metrics for this task
        self._accumulate(f"{prefix}/totals/input_tokens", input_tokens)
        self._accumulate(f"{prefix}/totals/output_tokens", output_tokens)
        self._accumulate(f"{prefix}/totals/tokens", total_tokens)
        self._accumulate(f"{prefix}/totals/llm_duration_ms", duration_ms)
        self._increment(f"{prefix}/totals/llm_invocations")

        # Log immediately for real-time visibility
        self._safe_log(
            {
                f"{prefix}/agents/{agent}/input_tokens": input_tokens,
                f"{prefix}/agents/{agent}/output_tokens": output_tokens,
                f"{prefix}/agents/{agent}/total_tokens": total_tokens,
                f"{prefix}/agents/{agent}/duration_ms": duration_ms,
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
        prefix = f"task/{self.task_name}"

        # Per-tool metrics
        self._increment(f"{prefix}/tools/{tool_key}/calls")
        self._accumulate(f"{prefix}/tools/{tool_key}/duration_ms", duration_ms)

        if success:
            self._increment(f"{prefix}/tools/{tool_key}/success")
        else:
            self._increment(f"{prefix}/tools/{tool_key}/failures")

        # Aggregate metrics
        self._increment(f"{prefix}/totals/tool_calls")
        self._accumulate(f"{prefix}/totals/tool_duration_ms", duration_ms)

        # Log immediately
        self._safe_log(
            {
                f"{prefix}/tools/{tool_key}/call": 1,
                f"{prefix}/tools/{tool_key}/success": 1 if success else 0,
            }
        )

    def log_step_completed(self, step_num: int) -> None:
        """Log completion of a step."""
        prefix = f"task/{self.task_name}"
        self._safe_log(
            {
                f"{prefix}/step": step_num,
            }
        )

    def log_error(self, source: str, error: str) -> None:
        """Log an error occurrence."""
        source_key = source.replace("-", "_")
        prefix = f"task/{self.task_name}"

        self._increment(f"{prefix}/errors/{source_key}")
        self._increment(f"{prefix}/totals/errors")

        self._safe_log(
            {
                f"{prefix}/error_source": source,
            }
        )

    def flush(self) -> None:
        """Flush accumulated metrics."""
        self._flush_accumulated()

    def get_run_url(self) -> str | None:
        """Get the W&B run URL."""
        if self.run:
            return self.run.url
        return None

    # === Private methods ===

    def _safe_log(self, data: dict[str, Any]) -> None:
        """Thread-safe logging with retry buffer."""
        if not self.enabled or not self.run:
            return

        try:
            self.run.log(data)
            self._retry_failed_logs()
        except Exception as e:
            print(f"[W&B] Log failed (buffered): {e}")
            self._failed_logs.append((data, time.time()))
            if len(self._failed_logs) > 100:
                self._failed_logs = self._failed_logs[-100:]

    def _retry_failed_logs(self) -> None:
        """Retry previously failed log calls."""
        if not self._failed_logs or not self.run:
            return

        remaining = []
        for data, timestamp in self._failed_logs:
            if time.time() - timestamp > 300:  # Skip logs older than 5 min
                continue
            try:
                self.run.log(data)
            except Exception:
                remaining.append((data, timestamp))

        self._failed_logs = remaining

    def _accumulate(self, key: str, value: float | int) -> None:
        """Accumulate a metric for batch logging."""
        current = self._metrics_buffer.get(key, 0)
        if isinstance(current, int | float):
            self._metrics_buffer[key] = current + value
        else:
            self._metrics_buffer[key] = value

    def _increment(self, key: str) -> None:
        """Increment a counter metric by 1."""
        self._accumulate(key, 1)

    def _flush_accumulated(self) -> None:
        """Flush accumulated metrics."""
        if self._metrics_buffer:
            self._safe_log(self._metrics_buffer)
            self._metrics_buffer = {}
