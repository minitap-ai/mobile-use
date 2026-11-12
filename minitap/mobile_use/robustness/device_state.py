"""P2 F4: deterministic device-state helpers used before the task ends."""

from __future__ import annotations

import re
import time

from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)

_SHOWN_PATTERNS = (
    re.compile(r"\bmInputShown=(true|false)\b"),
    re.compile(r"\bmIsInputViewShown=(true|false)\b"),
    re.compile(r"\bisInputViewShown=(true|false)\b"),
)


def parse_ime_shown(dumpsys_input_method: str) -> bool | None:
    """True/False from `dumpsys input_method`, None when the output says nothing."""
    for pat in _SHOWN_PATTERNS:
        m = pat.search(dumpsys_input_method or "")
        if m:
            return m.group(1) == "true"
    return None


def ime_shown(device) -> bool | None:
    try:
        return parse_ime_shown(str(device.shell("dumpsys input_method")))
    except Exception as e:
        logger.warning(f"ime_shown: {e}")
        return None


def hide_soft_keyboard(device, settle_s: float = 0.8) -> str:
    """Hide the soft keyboard if (and only if) it is shown: one BACK while the IME is shown
    closes the IME only. Returns what happened (for the event log)."""
    shown = ime_shown(device)
    if shown is not True:
        return "not_shown" if shown is False else "unknown"
    device.shell("input keyevent 4")
    time.sleep(settle_s)
    after = ime_shown(device)
    return "hidden" if after is False else f"still_shown={after}"
