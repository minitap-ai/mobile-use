"""P2 F6: re-observe a screen that did not change after a device action.

Version A repeated additive/destructive actions (add to queue, delete) because the capture right
after the action was stale (slow UI): the Cortex saw "no change" and did it again. When the UI
tree after an executed screen-changing action is identical to the one before it, wait and
capture once more before the Cortex decides.
"""

from __future__ import annotations

import asyncio
import hashlib
import json

from langchain_core.messages import AIMessage

from minitap.mobile_use.benchmark.runtime import get_runtime

SCREEN_CHANGING_TOOLS = {
    "tap", "long_press_on", "back", "launch_app", "stop_app", "open_link", "press_key",
    "focus_and_input_text", "focus_and_clear_text", "erase_one_char", "swipe",
    "swipe_percentages", "swipe_coordinates",
}
WAIT_S = 1.5


def ui_fingerprint(elements) -> str:
    def strip(e):
        if isinstance(e, dict):
            return {k: strip(v) for k, v in e.items() if k not in ("focused", "selected")}
        if isinstance(e, list):
            return [strip(x) for x in e]
        return e

    return hashlib.sha256(
        json.dumps(strip(elements), sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def executed_screen_actions(state) -> list[str]:
    names = []
    for m in state.executor_messages or []:
        if isinstance(m, AIMessage):
            for call in getattr(m, "tool_calls", None) or []:
                if call.get("name") in SCREEN_CHANGING_TOOLS:
                    names.append(call["name"])
    return names


SETTLE_S = 0.4
MAX_SETTLE_CAPTURES = 3


async def settle(controller, data, fp):
    """Re-capture until two consecutive UI trees are identical (the screen stopped changing);
    a frame taken mid-transition showed a value that was already gone (dev round 5)."""
    for _ in range(MAX_SETTLE_CAPTURES):
        await asyncio.sleep(SETTLE_S)
        nxt = await controller.get_screen_data()
        nfp = ui_fingerprint(nxt.elements)
        if nfp == fp:
            return nxt, nfp, True
        data, fp = nxt, nfp
    return data, fp, False


async def reobserve_if_unchanged(ctx, state, controller, data):
    fp = ui_fingerprint(data.elements)
    actions = executed_screen_actions(state)
    if actions:
        data, fp, stable = await settle(controller, data, fp)
        if not stable:
            runtime = get_runtime()
            if runtime is not None:
                runtime.event("p2_settle", stable=False, actions=actions)
    previous, ctx.p2_last_ui_hash = ctx.p2_last_ui_hash, fp
    if previous is None or fp != previous or not actions:
        return data
    await asyncio.sleep(WAIT_S)
    data2 = await controller.get_screen_data()
    fp2 = ui_fingerprint(data2.elements)
    ctx.p2_last_ui_hash = fp2
    runtime = get_runtime()
    if runtime is not None:
        runtime.event("p2_reobserve", actions=actions, changed_after_wait=fp2 != fp)
    return data2
