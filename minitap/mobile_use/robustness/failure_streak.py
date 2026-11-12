"""P2 F7: switch strategy after the same tool failed the same way twice in a row.

Version A kept calling a tool that failed identically (video analysis rejected, a tap missing,
a field refusing input) until the step limit. This tracks consecutive identical failures across
Cortex turns and, from the second one, tells the Cortex to change approach.
"""

from __future__ import annotations

import re

from langchain_core.messages import AIMessage, ToolMessage

THRESHOLD = 2


def _error_key(text: str) -> str:
    t = re.sub(r"\d+", "#", (text or "").lower())
    return " ".join(t.split())[:160]


def last_failures(state) -> list[tuple[str, str]]:
    names = {}
    for m in state.executor_messages or []:
        if isinstance(m, AIMessage):
            for call in getattr(m, "tool_calls", None) or []:
                names[call.get("id")] = call.get("name")
    out = []
    for m in state.executor_messages or []:
        if isinstance(m, ToolMessage) and m.status == "error":
            out.append((names.get(m.tool_call_id) or m.name or "tool", str(m.content)))
    return out


def update_streak(ctx, state) -> str | None:
    fails = last_failures(state)
    if not fails:
        ctx.p2_failure_streak = None
        return None
    tool, err = fails[-1]
    key = _error_key(err)
    prev = ctx.p2_failure_streak
    count = prev[2] + 1 if prev and prev[0] == tool and prev[1] == key else 1
    ctx.p2_failure_streak = (tool, key, count)
    if count < THRESHOLD:
        return None
    return (
        f"STRATEGY SWITCH REQUIRED: `{tool}` has now failed {count} times in a row with the same "
        f"error ({err[:200]}). Do not call it the same way again. Use a different approach to "
        "reach the same result (another tool, another element or input method, reading the "
        "information step by step from screenshots, or another path in the app)."
    )
