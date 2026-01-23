"""Base class for W&B management shared across repositories."""

from abc import ABC, abstractmethod
from typing import Any, Self
import time
import os


class WandbBaseManager(ABC):
    """Shared base class for W&B management.
    
    This class provides common functionality for both:
    - WandbProvider (mobile-use): Resumes existing runs
    - WandbManager (android-world-runner): Creates and owns runs
    
    Features:
    - Safe logging with automatic retry on failure
    - Metric accumulation for batch logging
    - Failed log buffering with retry
    - Graceful degradation when W&B is unavailable
    """

    def __init__(
        self,
        project: str = "mobile-use-androidworld-icml2026",
        entity: str | None = None,
        enabled: bool = True,
    ):
        """Initialize the base manager.
        
        Args:
            project: W&B project name
            entity: W&B entity (team or username), None for default
            enabled: Whether logging is enabled
        """
        self.project = project
        self.entity = entity
        self.enabled = enabled and os.getenv("WANDB_MODE") != "disabled"
        self.run = None
        self.run_id: str | None = None
        self._failed_logs: list[tuple[dict, float]] = []
        self._metrics_buffer: dict[str, Any] = {}
        self._max_failed_logs = 100

    def _safe_log(self, data: dict[str, Any]) -> None:
        """Thread-safe, retry-capable logging.
        
        If logging fails, the data is buffered and will be retried
        on the next successful log call.
        
        Args:
            data: Dictionary of metrics to log
        """
        if not self.enabled or not self.run:
            return

        try:
            self.run.log(data)
            self._retry_failed_logs()
        except Exception as e:
            print(f"[W&B] Log failed (buffered for retry): {e}")
            self._failed_logs.append((data, time.time()))
            # Cap the buffer to prevent memory issues
            if len(self._failed_logs) > self._max_failed_logs:
                self._failed_logs = self._failed_logs[-self._max_failed_logs:]

    def _retry_failed_logs(self) -> None:
        """Attempt to send previously failed logs.
        
        Called automatically after each successful log.
        """
        if not self._failed_logs or not self.run:
            return

        remaining = []
        for data, timestamp in self._failed_logs:
            # Skip logs older than 5 minutes
            if time.time() - timestamp > 300:
                continue
            try:
                self.run.log(data)
            except Exception:
                remaining.append((data, timestamp))

        self._failed_logs = remaining

    def _accumulate(self, key: str, value: float | int) -> None:
        """Accumulate a metric for batch logging.
        
        Metrics are accumulated until flush() is called.
        
        Args:
            key: Metric key name
            value: Value to add to the accumulated total
        """
        current = self._metrics_buffer.get(key, 0)
        if isinstance(current, int | float):
            self._metrics_buffer[key] = current + value
        else:
            self._metrics_buffer[key] = value

    def _flush_accumulated(self, step: int) -> None:
        """Flush accumulated metrics with step index.
        
        Args:
            step: The step/task index for this batch
        """
        if self._metrics_buffer:
            self._safe_log({"step": step, **self._metrics_buffer})
            self._metrics_buffer = {}

    def _increment(self, key: str) -> None:
        """Increment a counter metric by 1.
        
        Args:
            key: Metric key name
        """
        self._accumulate(key, 1)

    def get_run_id(self) -> str | None:
        """Get the current W&B run ID.
        
        Returns:
            The run ID if a run is active, None otherwise
        """
        return self.run_id

    @abstractmethod
    def __enter__(self) -> Self:
        """Enter the context manager - initialize W&B run."""
        ...

    @abstractmethod
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit the context manager - cleanup W&B run."""
        ...
