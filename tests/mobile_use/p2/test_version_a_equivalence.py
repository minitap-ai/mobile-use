"""P2: version A (every config with the p2_* flags off, e.g. full.jsonc) is the frozen 982b105 system.

1. Every agent prompt template renders byte-identically to its 982b105 version when the p2 flags
   are off (several variable combinations per template).
2. The resolved full.jsonc, minus the new p2_* keys (all false), is the golden version-A config.
3. No P2 tool is registered for any version-A config, and every p2 flag defaults to False.
"""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from jinja2 import Template

from minitap.mobile_use.benchmark.config import load_benchmark_config
from minitap.mobile_use.config import AblationConfig
from minitap.mobile_use.robustness import p2_flags
from minitap.mobile_use.tools.p2_tools import p2_tool_wrappers

ROOT = Path(__file__).resolve().parents[3]
FROZEN_AT = "982b10599ab79cf99fe4e5ccf565df8f0bf2a9f1"
GOLDEN_FULL_RESOLVED_988B436 = "5f3e5a9960590bf3b0dd039f3bbe76352cc514cd966e4d1fe4a500acf5862b24"
CONFIGS = ROOT / "benchmarks" / "configs"
VERSION_B = {"p2.jsonc"} | {p.name for p in CONFIGS.glob("p2-*.jsonc")}

PLAN = "[subgoal-1 ✅ Open app, subgoal-2 ❓ Do it]"
VARIANTS = {
    "minitap/mobile_use/agents/cortex/cortex.md": [
        dict(platform="android", initial_goal="Do X", subgoal_plan=PLAN, current_subgoal="s2",
             executor_feedback="None.", executor_tools_list="tap, back", locked_app_package=None,
             use_vision=v, use_meta_reasoning=m, use_data_fidelity=d)
        for v in (True, False) for m in (True, False) for d in (True, False)
    ] + [dict(platform="android", initial_goal="G", subgoal_plan=PLAN, current_subgoal=None,
              executor_feedback="fb", executor_tools_list="tap", locked_app_package="com.x")],
    "minitap/mobile_use/agents/planner/planner.md": [
        dict(platform="android", executor_tools_list="tap", locked_app_package=lock,
             current_foreground_app=fg, video_recording_enabled=vid)
        for lock in (None, "com.x") for fg in (None, "com.y") for vid in (True, False)
    ],
    "minitap/mobile_use/agents/planner/human.md": [
        dict(action=a, initial_goal="Goal", previous_plan="p", agent_thoughts="t")
        for a in ("plan", "replan")
    ],
    "minitap/mobile_use/agents/verifier/verifier.md": [
        dict(platform="android", initial_goal="G", use_vision=v) for v in (True, False)
    ],
    "minitap/mobile_use/agents/orchestrator/orchestrator.md": [dict(platform="android")],
    "minitap/mobile_use/agents/orchestrator/human.md": [
        dict(initial_goal="G", subgoal_plan="p", subgoals_to_examine="s", agent_thoughts="t")
    ],
    "minitap/mobile_use/agents/executor/executor.md": [dict(platform="android")],
    "minitap/mobile_use/agents/monolithic/monolithic.md": [dict(platform="android")],
    "minitap/mobile_use/agents/contextor/contextor.md": [
        dict(task_goal="G", subgoal_plan="p", locked_app_package="a", current_app_package="b",
             agents_thoughts=["t"])
    ],
    "minitap/mobile_use/agents/outputter/human.md": [
        dict(initial_goal="G", agents_thoughts=["a"], structured_output=None,
             output_description="d", last_ai_message="m")
    ],
}


def _frozen_available() -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(ROOT), "cat-file", "-e", f"{FROZEN_AT}^{{commit}}"],
            capture_output=True,
        ).returncode
        == 0
    )


def _frozen(path: str) -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{FROZEN_AT}:{path}"],
        capture_output=True, text=True, check=True,
    ).stdout


def _off_flags() -> dict:
    return p2_flags(AblationConfig())


@pytest.mark.parametrize("path", sorted(VARIANTS), ids=lambda p: p.split("agents/")[1])
def test_prompts_render_identically_with_p2_off(path):
    if not _frozen_available():
        pytest.skip("frozen commit not in local history")
    old_t = Template(_frozen(path))
    new_t = Template((ROOT / path).read_text(encoding="utf-8"))
    for variables in VARIANTS[path]:
        old = old_t.render(**variables)
        # P2 variables explicitly off, and also simply absent (both must be identical)
        assert new_t.render(**variables) == old, path
        assert new_t.render(**variables, **_off_flags(), p2_checklist_text=None,
                            p2_calendar=None) == old, path


def test_every_frozen_prompt_template_is_covered():
    if not _frozen_available():
        pytest.skip("frozen commit not in local history")
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-tree", "-r", "--name-only", FROZEN_AT, "minitap/mobile_use/agents"],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    frozen_md = {p for p in out if p.endswith(".md")}
    unchanged = {
        p for p in frozen_md - set(VARIANTS)
        if (ROOT / p).read_text(encoding="utf-8") == _frozen(p)
    }
    assert frozen_md - set(VARIANTS) - unchanged == set()


def _canonical_without_p2(resolved: dict) -> str:
    d = json.loads(json.dumps(resolved))
    d["ablation"] = {k: v for k, v in d["ablation"].items() if not k.startswith("p2_")}
    return hashlib.sha256(
        json.dumps(d, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_full_resolves_to_version_a_with_p2_off():
    full = load_benchmark_config(CONFIGS / "full.jsonc")
    assert not any(v for k, v in full.resolved["ablation"].items() if k.startswith("p2_"))
    assert _canonical_without_p2(full.resolved) == GOLDEN_FULL_RESOLVED_988B436


@pytest.mark.parametrize(
    "path",
    sorted(p for p in CONFIGS.glob("*.jsonc") if not p.name.startswith("_") and p.name not in VERSION_B),
    ids=lambda p: p.name,
)
def test_no_version_a_config_enables_p2(path):
    cfg = load_benchmark_config(path).config
    assert not any(p2_flags(cfg.ablation).values()), path.name
    assert p2_tool_wrappers(cfg.ablation) == []


def test_p2_flags_default_off():
    assert p2_flags(AblationConfig()) and not any(p2_flags(AblationConfig()).values())


def test_p2_config_enables_every_flag_on_top_of_full():
    full = load_benchmark_config(CONFIGS / "full.jsonc").resolved
    p2 = load_benchmark_config(CONFIGS / "p2.jsonc").resolved
    assert all(v for k, v in p2["ablation"].items() if k.startswith("p2_"))
    for d in (full, p2):
        d["ablation"] = {k: v for k, v in d["ablation"].items() if not k.startswith("p2_")}
        d.pop("name"), d.pop("description")
    assert full == p2  # same models, routing, agent settings: only the p2 flags differ
