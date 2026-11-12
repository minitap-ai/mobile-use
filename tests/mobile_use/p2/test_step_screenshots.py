"""Per-step screenshots (P2 recordings, measurement only): flag p2_step_screenshots + a runtime."""

import base64
import io
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from minitap.mobile_use.benchmark import runtime as runtime_mod
from minitap.mobile_use.benchmark import step_screenshots
from minitap.mobile_use.benchmark.runtime import BenchmarkRuntime, LLMPolicy


def _png(w=1080, h=2400) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (10, 200, 30)).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _ctx(flag: bool):
    return SimpleNamespace(get_ablation_config=lambda: SimpleNamespace(p2_step_screenshots=flag))


@pytest.fixture
def rt(tmp_path):
    r = BenchmarkRuntime(tmp_path / "Task-s40" / "events.jsonl", "run-1", LLMPolicy())
    runtime_mod.activate(r)
    yield r
    runtime_mod.deactivate()


def _events(r):
    return [json.loads(x) for x in r.events_path.read_text().splitlines()]


def test_saves_numbered_jpegs_at_most_720_wide_and_logs_events(rt):
    for _ in range(3):
        step_screenshots.save_step_screenshot(_ctx(True), _png())
    step_screenshots.flush()
    steps = sorted((rt.events_path.parent / "steps").iterdir())
    assert [p.name for p in steps] == ["0001.jpg", "0002.jpg", "0003.jpg"]
    img = Image.open(steps[0])
    assert img.format == "JPEG" and img.size == (720, 1600)
    saved = [e for e in _events(rt) if e["type"] == "screenshot_saved"]
    assert [e["file"] for e in saved] == ["steps/0001.jpg", "steps/0002.jpg", "steps/0003.jpg"]


def test_flag_off_is_a_no_op(rt):
    step_screenshots.save_step_screenshot(_ctx(False), _png())
    step_screenshots.flush()
    assert not (rt.events_path.parent / "steps").exists()
    assert not rt.events_path.read_text()


def test_no_runtime_is_a_no_op(tmp_path):
    assert runtime_mod.get_runtime() is None
    step_screenshots.save_step_screenshot(_ctx(True), _png())  # SDK/CLI use: nothing happens
    step_screenshots.flush()


def test_a_bad_frame_never_raises_and_is_logged(rt):
    step_screenshots.save_step_screenshot(_ctx(True), base64.b64encode(b"not a png").decode())
    step_screenshots.save_step_screenshot(_ctx(True), None)  # no screenshot at all: ignored
    step_screenshots.flush()
    assert [e["type"] for e in _events(rt)] == ["screenshot_save_failed"]


def test_contextor_saves_the_frame_after_the_reobserve_block():
    """The call site is one line, after the p2_no_redo re-capture (the frame the agent sees)."""
    src = (
        step_screenshots.__file__.replace("benchmark/step_screenshots.py", "")
        + "agents/contextor/contextor.py"
    )
    lines = open(src).read().splitlines()
    i_reobs = next(i for i, x in enumerate(lines) if "reobserve_if_unchanged(self.ctx" in x)
    i_save = next(i for i, x in enumerate(lines) if "save_step_screenshot(" in x)
    assert i_save == i_reobs + 1
    assert sum("save_step_screenshot" in x for x in lines) == 2  # import + call
