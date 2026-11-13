"""P2 F3: a deterministic log of the actions the Executor actually ran, for the goal verifier.

Observed in version B (emulator, dev seed 46): after ONE capture, a gallery view listed the new
item twice (the entry being saved and the saved file). The verifier counted two items from that
view, asked the agents to delete the "extra" one, and the agents deleted the only item they had
created. The verifier only saw the agents' thoughts, not what was executed. This log records every
executed tool call (tool, target, outcome) from the Executor messages, once per call id, so counts
of things the agents created, sent or captured can be read from what was done.
"""

from __future__ import annotations

import json
import re

from langchain_core.messages import AIMessage, ToolMessage

MAX_ENTRIES = 80
# D3: an action whose target or text names a delete control (used by the verifier's delete gate)
DELETE_ACTION_RE = re.compile(r"delet|remov|trash", re.IGNORECASE)
TEXT_MAX = 60


def _short(v, n: int = TEXT_MAX) -> str:
    s = " ".join(str(v).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def describe(name: str, args: dict) -> str:
    args = args or {}
    parts: list[str] = []
    target = args.get("target")
    if isinstance(target, str):
        try:
            target = json.loads(target)
        except json.JSONDecodeError:
            parts.append(f"target={_short(target)!r}")
            target = None
    if isinstance(target, dict):
        for k in ("text", "resource_id", "content_desc", "accessibility_label"):
            if target.get(k):
                parts.append(f"{k}={_short(target[k])!r}")
                break
        else:
            c = target.get("coordinates") or target.get("bounds")
            if c:
                parts.append(f"at={_short(json.dumps(c, default=str), 40)}")
    for k in ("app_name", "package_name", "text", "direction", "key", "url", "match"):
        if args.get(k) not in (None, ""):
            parts.append(f"{k}={_short(args[k])!r}")
    for k in ("start_x_percent", "start_y_percent", "end_x_percent", "end_y_percent"):
        if k in args:
            parts.append(f"{k[0:-8]}={args[k]}")
    return f"{name}({', '.join(parts)})"


def record_actions(ctx, state) -> None:
    """Append the executed calls of `state.executor_messages` not yet logged (idempotent)."""
    calls: dict[str, tuple[str, dict]] = {}
    for m in state.executor_messages or []:
        if isinstance(m, AIMessage):
            for c in getattr(m, "tool_calls", None) or []:
                if c.get("id"):
                    calls[c["id"]] = (c.get("name") or "tool", c.get("args") or {})
    log = list(ctx.p2_action_log or [])
    seen = set(ctx.p2_action_ids or [])
    for m in state.executor_messages or []:
        if not isinstance(m, ToolMessage) or m.tool_call_id in seen:
            continue
        seen.add(m.tool_call_id)
        name, args = calls.get(m.tool_call_id, (m.name or "tool", {}))
        status = "failed" if m.status == "error" else "ok"
        ctx.p2_action_count += 1
        desc = describe(name, args)
        if status == "ok" and DELETE_ACTION_RE.search(desc):
            ctx.p2_delete_seen = True
        log.append(f"#{ctx.p2_action_count} {desc} -> {status}")
    ctx.p2_action_log = log[-MAX_ENTRIES:]
    ctx.p2_action_ids = seen


def render_action_log(ctx) -> str | None:
    log = ctx.p2_action_log or []
    if not log:
        return None
    dropped = ctx.p2_action_count - len(log)
    head = f"({dropped} earlier action(s) not shown)\n" if dropped > 0 else ""
    return head + "\n".join(log)
