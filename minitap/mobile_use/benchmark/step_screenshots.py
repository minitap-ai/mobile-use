"""Per-step screenshots for benchmark recordings (P2, measurement only).

When the `p2_step_screenshots` ablation flag is on AND a benchmark runtime is active, the screenshot
the Contextor just captured (the frame the agent decides on) is written as
`<task dir>/steps/NNNN.jpg` (JPEG q70, at most 720 px wide) and an event
`screenshot_saved {step, file, width, height}` is appended to events.jsonl.

Encoding runs on one background thread, so the agent never waits for it, and any failure is
logged as an event and swallowed: it never changes what the agent sees or decides. Outside a
benchmark run, or with the flag off, it is a no-op.
"""

from __future__ import annotations

import base64
import io
import itertools
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from minitap.mobile_use.benchmark.runtime import BenchmarkRuntime, get_runtime

if TYPE_CHECKING:
    from minitap.mobile_use.context import MobileUseContext

MAX_WIDTH = 720
JPEG_QUALITY = 70

_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="step-screenshots")
_lock = threading.Lock()


def _next_step(runtime: BenchmarkRuntime) -> int:
    with _lock:
        counter = getattr(runtime, "_step_screenshot_counter", None)
        if counter is None:
            counter = itertools.count(1)
            runtime._step_screenshot_counter = counter  # type: ignore[attr-defined]
        return next(counter)


def _write(runtime: BenchmarkRuntime, step: int, screenshot_base64: str) -> None:
    from PIL import Image  # noqa: PLC0415 (only imported when the flag is on)

    try:
        img = Image.open(io.BytesIO(base64.b64decode(screenshot_base64)))
        img = img.convert("RGB")
        if img.width > MAX_WIDTH:
            img = img.resize((MAX_WIDTH, round(img.height * MAX_WIDTH / img.width)))
        rel = f"steps/{step:04d}.jpg"
        path = runtime.events_path.parent / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path, "JPEG", quality=JPEG_QUALITY)
        runtime.event("screenshot_saved", step=step, file=rel, width=img.width, height=img.height)
    except Exception as e:  # noqa: BLE001 - measurement must never break a run
        runtime.event("screenshot_save_failed", step=step, error=f"{type(e).__name__}: {e}"[:300])


def save_step_screenshot(ctx: MobileUseContext, screenshot_base64: str | None) -> None:
    """Queue the Contextor's screenshot for saving (no-op unless the flag and a runtime are on)."""
    runtime = get_runtime()
    if runtime is None or not screenshot_base64:
        return
    if not getattr(ctx.get_ablation_config(), "p2_step_screenshots", False):
        return
    _pool.submit(_write, runtime, _next_step(runtime), screenshot_base64)


def flush(timeout_s: float = 10.0) -> None:
    """Wait for queued screenshots (call before closing the runtime)."""
    _pool.submit(lambda: None).result(timeout=timeout_s)
