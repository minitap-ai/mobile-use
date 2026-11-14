"""D6: soft cap on shutter taps for single-photo goals (deterministic, tool level).

Observed on D5 (dev seed, emulator): the goal asked for one photo; the agent's first capture worked, but the
gallery's newest item was a stale video left by an earlier session (every session resets the clock, so old media
can look newer than the agent's own). The agent deleted it, believed its capture had failed, and shot again: two
new photos, the checker wants exactly one. Backtest over all p2 runs of the matching goal: 1 shutter tap -> 12 pass
/ 1 fail (other cause); 2 taps -> 0 / 3 (all caught); 3-4 taps -> 2 pass (the cap fires there once).
The second shutter tap is refused ONCE (the camera may not have been ready); asked again, it goes through.
Trigger (goal wording only): "take one/a/1/a single photo|picture".
"""

from __future__ import annotations

import re

SINGLE_PHOTO_RE = re.compile(r"^\s*take\s+(?:one|a|1|a single)\s+(?:photo|picture)\b", re.IGNORECASE)
SHUTTER_RE = re.compile(r"shutter", re.IGNORECASE)

SHUTTER_REFUSAL = (
    "Refused once: this goal asks for ONE photo and the shutter was already pressed in this run. A gallery item "
    "that looks newer than your capture can be left over from an earlier session (the device clock is reset), so "
    "do not delete media and do not capture again. Check that your photo exists; only if no capture happened at "
    "all, press the shutter again (it will be allowed)."
)


def shutter_refusal(ctx, goal: str, target_desc: str) -> str | None:
    """Refusal for a repeated shutter tap in a single-photo goal (once per run), else None. Counts the taps."""
    if not SINGLE_PHOTO_RE.search(goal or "") or not SHUTTER_RE.search(target_desc or ""):
        return None
    if ctx.p2_shutter_taps >= 1 and not ctx.p2_shutter_refused:
        ctx.p2_shutter_refused = True
        return SHUTTER_REFUSAL
    ctx.p2_shutter_taps += 1
    return None
