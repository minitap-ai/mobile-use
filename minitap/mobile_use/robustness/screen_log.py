"""P2 F3: deterministic log of the recent screens' UI text, for the goal verifier.

Version B's verifier rejected a claim it could not see, the agents then opened each record to
check it, and the verifier accepted the agents' DESCRIPTION of those records (a claim). This log
keeps what the device actually showed (texts and content descriptions of the UI tree) for the
last screens, so the verifier can judge records opened before the final screen on real evidence.
"""

from __future__ import annotations

MAX_SCREENS = 14
MAX_ITEMS = 120


def _iter(elements):
    for el in elements or []:
        if isinstance(el, dict):
            yield el
            yield from _iter(el.get("children") or [])


def screen_texts(elements) -> list[str]:
    out: list[str] = []
    for el in _iter(elements):
        for key in ("text", "content-desc"):
            v = (el.get(key) or "").strip()
            if v and v not in out:
                out.append(v[:200])
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


def render_screen_log(log) -> str | None:
    if not log:
        return None
    return "\n".join(
        f"[screen {e['step']}, {e.get('app') or '?'}] " + " | ".join(e["texts"]) for e in log
    )
