"""Telemetry service for mobile-use SDK using PostHog."""

import json
import platform
import threading
from pathlib import Path

import uuid_utils
from posthog import Posthog

from minitap.mobile_use.config import settings
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


POSTHOG_API_KEY = "phc_MTwMcqOjMpTdTdrYwQUlsWaKkB7C8MPAw9YyZhRv8B8"
POSTHOG_HOST = "https://eu.i.posthog.com"
EVENT_PREFIX = "mobile_use_"

TELEMETRY_CONFIG_DIR = Path.home() / ".minitap"
TELEMETRY_CONFIG_FILE = TELEMETRY_CONFIG_DIR / "telemetry.json"


class TelemetryConfig:
    """Manages telemetry consent and configuration persistence."""

    def __init__(self):
        self._distinct_id: str | None = None
        self._enabled: bool | None = None

    @property
    def config_exists(self) -> bool:
        return TELEMETRY_CONFIG_FILE.exists()

    def load(self) -> dict:
        """Load telemetry config from disk."""
        if not self.config_exists:
            return {}
        try:
            with open(TELEMETRY_CONFIG_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def save(self, enabled: bool, distinct_id: str) -> None:
        """
        Save telemetry config to disk.

        Only persists if enabled=True. If disabled, we don't persist
        so the user will be asked again next session.
        """
        TELEMETRY_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if enabled:
            config = {"enabled": enabled, "distinct_id": distinct_id}
            with open(TELEMETRY_CONFIG_FILE, "w") as f:
                json.dump(config, f, indent=2)
        else:
            # Don't persist denial - user will be asked again next session
            # But still save distinct_id for consistency if they enable later
            config = {"distinct_id": distinct_id}
            with open(TELEMETRY_CONFIG_FILE, "w") as f:
                json.dump(config, f, indent=2)

    @property
    def distinct_id(self) -> str:
        """Get or generate a persistent anonymous distinct ID."""
        if self._distinct_id is None:
            config = self.load()
            self._distinct_id = config.get("distinct_id") or str(uuid_utils.uuid4())
        return self._distinct_id

    @property
    def enabled(self) -> bool | None:
        """
        Check if telemetry is enabled.

        Priority:
        1. Environment variable MOBILE_USE_TELEMETRY_ENABLED (true/false/1/0)
        2. Persisted config file
        3. None if not configured (needs consent prompt)
        """
        if self._enabled is not None:
            return self._enabled

        telemetry_enabled = settings.MOBILE_USE_TELEMETRY_ENABLED
        if telemetry_enabled is not None:
            self._enabled = telemetry_enabled
            return self._enabled

        config = self.load()
        if "enabled" in config:
            self._enabled = config["enabled"]
            return self._enabled

        return None

    def set_enabled(self, enabled: bool) -> None:
        """Set telemetry enabled state and persist to config."""
        self._enabled = enabled
        self.save(enabled=enabled, distinct_id=self.distinct_id)


class TelemetryService:
    """PostHog telemetry service for mobile-use SDK."""

    _instance: "TelemetryService | None" = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self):
        self._config = TelemetryConfig()
        self._initialized = False
        self._client: Posthog | None = None
        self._session_id: str | None = None
        self._session_context: dict = {}

    @classmethod
    def get_instance(cls) -> "TelemetryService":
        """Get singleton instance of TelemetryService (thread-safe)."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = TelemetryService()
        return cls._instance

    @property
    def is_enabled(self) -> bool:
        """Check if telemetry is enabled."""
        return self._config.enabled is True

    @property
    def needs_consent(self) -> bool:
        """Check if user consent is needed (not yet configured)."""
        return self._config.enabled is None

    def initialize(self) -> None:
        """Initialize PostHog client if telemetry is enabled."""
        if self._initialized:
            return

        if not self.is_enabled:
            logger.debug("Telemetry disabled, skipping PostHog initialization")
            return

        try:
            self._client = Posthog(
                project_api_key=POSTHOG_API_KEY,
                host=POSTHOG_HOST,
                debug=False,
            )
            self._initialized = True
            logger.debug("PostHog telemetry initialized")
        except Exception as e:
            logger.debug(f"Failed to initialize PostHog: {e}")
            self._initialized = False

    def set_consent(self, enabled: bool) -> None:
        """Set user consent for telemetry."""
        self._config.set_enabled(enabled)
        if enabled:
            self.initialize()
        else:
            if self._client:
                self._client.disabled = True

    def start_session(self, context: dict | None = None) -> str:
        """
        Start a new telemetry session for CLI usage.

        Args:
            context: Initial session context (e.g., goal, platform, device_id)

        Returns:
            The session ID
        """
        self._session_id = str(uuid_utils.uuid7())
        self._session_context = context or {}

        if self.is_enabled:
            self.capture(
                "session_started",
                {
                    "$session_id": self._session_id,
                    **self._session_context,
                },
            )

        return self._session_id

    def update_session_context(self, context: dict) -> None:
        """Update the current session context with additional data."""
        self._session_context.update(context)

    def end_session(self, success: bool = True, error: str | None = None) -> None:
        """
        End the current telemetry session.

        Args:
            success: Whether the session completed successfully
            error: Error message if session failed
        """
        if not self._session_id:
            return

        if self.is_enabled:
            self.capture(
                "session_ended",
                {
                    "$session_id": self._session_id,
                    "success": success,
                    "error": error,
                    **self._session_context,
                },
            )

        self._session_id = None
        self._session_context = {}

    def capture_action(self, action: str, details: dict | None = None) -> None:
        """
        Capture an action within the current session.

        Args:
            action: The action name (e.g., "screenshot_taken", "tap_performed")
            details: Additional action details
        """
        properties = {
            "action": action,
            **(details or {}),
        }

        if self._session_id:
            properties["$session_id"] = self._session_id
            properties.update(self._session_context)

        self.capture("action", properties)

    def capture(self, event: str, properties: dict | None = None) -> None:
        """Capture a telemetry event."""
        if not self.is_enabled:
            return

        # Lazy initialization for SDK usage (non-CLI)
        # If user has previously consented via config/env, auto-initialize
        if not self._initialized:
            self.initialize()
            if not self._initialized:
                return

        try:
            all_properties = {
                "sdk_version": self._get_sdk_version(),
                "python_version": platform.python_version(),
                "os": platform.system(),
                "os_version": platform.release(),
                **(properties or {}),
            }

            # Include session ID if available
            if self._session_id and "$session_id" not in all_properties:
                all_properties["$session_id"] = self._session_id

            if self._client:
                prefixed_event = f"{EVENT_PREFIX}{event}"
                self._client.capture(
                    distinct_id=self._config.distinct_id,
                    event=prefixed_event,
                    properties=all_properties,
                )
        except Exception as e:
            logger.debug(f"Failed to capture telemetry event: {e}")

    def capture_exception(
        self,
        exception: Exception,
        context: dict | None = None,
    ) -> None:
        """
        Capture an exception event to PostHog Error Tracking.

        Uses PostHog's native capture_exception method for proper
        integration with the Error Tracking dashboard.

        Args:
            exception: The exception to capture
            context: Additional context properties
        """
        if not self.is_enabled:
            return

        # Lazy init for SDK usage
        if not self._initialized:
            self.initialize()
            if not self._initialized:
                return

        try:
            if self._client:
                # Use PostHog's native capture_exception for Error Tracking
                self._client.capture_exception(
                    exception,
                    distinct_id=self._config.distinct_id,
                    properties={
                        "sdk_version": self._get_sdk_version(),
                        "source": "mobile_use",
                        **(context or {}),
                    },
                )
        except Exception as e:
            logger.debug(f"Failed to capture exception telemetry: {e}")

    def capture_task_started(
        self,
        task_id: str,
        platform: str,
        has_locked_app: bool = False,
    ) -> None:
        """Capture task started event."""
        self.capture(
            "task_started",
            {
                "task_id": task_id,
                "device_platform": platform,
                "has_locked_app": has_locked_app,
            },
        )

    def capture_task_completed(
        self,
        task_id: str,
        success: bool,
        steps_count: int,
        duration_seconds: float,
        cancelled: bool = False,
    ) -> None:
        """Capture task completed event."""
        self.capture(
            "task_completed",
            {
                "task_id": task_id,
                "success": success,
                "cancelled": cancelled,
                "steps_count": steps_count,
                "duration_seconds": duration_seconds,
            },
        )

    def capture_agent_initialized(self, platform: str, device_id: str | None = None) -> None:
        """Capture agent initialization event."""
        self.capture(
            "agent_initialized",
            {
                "device_platform": platform,
                "has_device_id": device_id is not None,
            },
        )

    def capture_cortex_decision(
        self,
        task_id: str,
        has_decisions: bool = False,
        has_goals_completion: bool = False,
        completed_subgoals_count: int = 0,
    ) -> None:
        """Capture cortex agent decision event (only non-sensitive flags)."""
        self.capture(
            "cortex_decision",
            {
                "task_id": task_id,
                "has_decisions": has_decisions,
                "has_goals_completion": has_goals_completion,
                "completed_subgoals_count": completed_subgoals_count,
            },
        )

    def capture_executor_action(
        self,
        task_id: str,
        tool_name: str,
        success: bool,
        error: str | None = None,
    ) -> None:
        """Capture executor tool action event."""
        self.capture(
            "executor_action",
            {
                "task_id": task_id,
                "tool_name": tool_name,
                "success": success,
                "error": error,
            },
        )

    def flush(self) -> None:
        """Flush pending events to PostHog."""
        if self.is_enabled and self._initialized and self._client:
            try:
                self._client.flush()
            except Exception as e:
                logger.debug(f"Failed to flush telemetry: {e}")

    def shutdown(self) -> None:
        """Shutdown telemetry service."""
        self.flush()
        if self._client:
            try:
                self._client.shutdown()
            except Exception:
                pass

    def _get_sdk_version(self) -> str:
        """Get the mobile-use SDK version."""
        try:
            from importlib.metadata import version

            return version("minitap-mobile-use")
        except Exception:
            return "unknown"


telemetry = TelemetryService.get_instance()
