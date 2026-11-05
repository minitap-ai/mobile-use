"""Append-only records of strict app lock enforcement decisions.

When ``APP_LOCK_EVENTS_PATH`` is set, each block, restore, or abort decided by
the strict app lock is appended to that file as one JSON object per line. The
records hold only fixed reason codes and Android package names: never tool
arguments such as URLs, screen content, or model output.

These records are written by the harness, not by the model. They are not
signed and do not prove that no other action happened; they list what the
strict lock itself detected.
"""

import json
import os
from datetime import UTC, datetime
from typing import Literal

from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)

AppLockDecision = Literal["blocked", "restored", "aborted"]
AppLockReason = Literal[
    "launch_other_app",
    "os_routed_deep_link",
    "stop_app",
    "home_key",
    "foreground_mismatch",
    "foreground_unknown",
    "restore_failed",
    "initial_launch_unverified",
]


def record_app_lock_event(
    *,
    locked_app_package: str,
    action: str,
    decision: AppLockDecision,
    reason: AppLockReason,
    target_package: str | None = None,
) -> None:
    """Append one enforcement record if ``APP_LOCK_EVENTS_PATH`` is set.

    A failure to write is logged and swallowed: the lock itself has already
    been enforced, and recording must never weaken or bypass it.
    """

    path = os.getenv("APP_LOCK_EVENTS_PATH")
    if not path:
        return
    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "policy": "strict",
        "locked_app_package": locked_app_package,
        "action": action,
        "decision": decision,
        "reason": reason,
    }
    if target_package:
        record["target_package"] = target_package
    try:
        with open(path, "a", encoding="utf-8") as events_file:
            events_file.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError as error:
        logger.warning(f"Could not record strict app lock event: {type(error).__name__}")
