"""P2 F3: deterministic log of the recent screens' UI text, for the goal verifier.

Version B's verifier rejected a claim it could not see, the agents then opened each record to
check it, and the verifier accepted the agents' DESCRIPTION of those records (a claim). This log
keeps what the device actually showed (texts and content descriptions of the UI tree) for the
last screens, so the verifier can judge records opened before the final screen on real evidence.
"""

from __future__ import annotations

MAX_SCREENS = 40  # whole-run evidence: detail/edit screens opened early must stay visible
MAX_ITEMS = 120


SCREEN_TEXT_MAX = 20000  # per screen
ELEMENT_TEXT_MAX = 16000  # a whole document can be ONE element (e.g. a text editor)


def _iter(elements):
    for el in elements or []:
        if isinstance(el, dict):
            yield el
            yield from _iter(el.get("children") or [])


def screen_texts(elements) -> list[str]:
    out: list[str] = []
    used = 0
    for el in _iter(elements):
        for key in ("text", "content-desc"):
            v = (el.get(key) or "").strip()
            if v and v not in out:
                cap = ELEMENT_TEXT_MAX if used < SCREEN_TEXT_MAX else 200
                item = v if len(v) <= cap else v[:cap] + f" [truncated: {len(v)} chars in total]"
                out.append(item)
                used += len(item)
        if len(out) >= MAX_ITEMS:
            break
    return out


def record_screen(ctx, step: int, package: str | None, elements) -> None:
    texts = screen_texts(elements)
    log = list(ctx.p2_screen_log or [])
    if log and log[-1]["texts"] == texts:
        return
    log.append({"step": step, "app": package, "texts": texts})
    recent = log[-MAX_SCREENS:]
    # Keep the last screen of every app that left the window (e.g. the source document app
    # after switching to the target app): the verifier needs one result screen per app.
    apps_recent = {e["app"] for e in recent}
    last_by_app: dict = {}
    for e in log[:-MAX_SCREENS]:
        if e["app"] not in apps_recent:
            last_by_app[e["app"]] = e
    ctx.p2_screen_log = list(last_by_app.values())[-4:] + recent


RENDER_MAX = 90000  # total characters given to the verifier


def render_screen_log(log) -> str | None:
    if not log:
        return None
    lines = [f"[screen {e['step']}, {e.get('app') or '?'}] " + " | ".join(e["texts"]) for e in log]
    out, used = [], 0
    for line in reversed(lines):  # newest first, until the budget is used
        if used + len(line) > RENDER_MAX and out:
            out.append(f"[{len(lines) - len(out)} older screen(s) not shown]")
            break
        out.append(line)
        used += len(line)
    return "\n".join(reversed(out))
