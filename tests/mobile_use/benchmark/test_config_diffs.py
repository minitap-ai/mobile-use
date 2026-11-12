"""Every runnable config must differ from full.jsonc by exactly what it declares.

One table, one row per config: a new config without a row fails, so every condition of the
study is an explicit, reviewed diff against the headline system.
"""

from pathlib import Path

import pytest

from minitap.mobile_use.benchmark.config import load_benchmark_config

CONFIG_DIR = Path(__file__).resolve().parents[3] / "benchmarks" / "configs"
RUNNABLE = sorted(p for p in CONFIG_DIR.rglob("*.jsonc") if not p.name.startswith("_"))
IGNORED_KEYS = {"name", "description", "paper_reference"}

ALL_FLAGS_OFF = {
    f"ablation.{f}"
    for f in (
        "use_multi_agent",
        "use_sequential_execution",
        "use_post_validation",
        "use_deterministic_text",
        "use_vision",
        "use_meta_reasoning",
        "use_scratchpad",
        "use_video_recording",
        "use_data_fidelity_prompts",
        "use_loop_detector",
        "use_text_match_check",
        "use_goal_verification",
    )
}
# The monolithic agent binds tools with parallel_tool_calls=true on the Cortex model, so its
# Cortex entry carries {"require_parameters": false} (null in full.jsonc).
# (flattened: the null leaf on one side, the nested key on the other)
MONOLITHIC_ROUTING = {
    "llm.cortex.openrouter_provider",
    "llm.cortex.openrouter_provider.require_parameters",
}

# config name -> exact set of differing paths, or "llm-only" (routing/model rows: any llm.*
# difference allowed, nothing else may differ).
EXPECTED: dict[str, set[str] | str] = {
    "full": set(),
    # Table 2 leave-one-out rows
    "no-loop-detector": {"ablation.use_loop_detector"},
    "no-text-match-check": {"ablation.use_text_match_check"},
    "no-goal-verification": {"ablation.use_goal_verification"},
    "no-sequential-execution": {"ablation.use_sequential_execution"},
    "no-hybrid-perception": {"ablation.use_vision"},
    "no-scratchpad": {"ablation.use_scratchpad"},
    "no-data-fidelity": {"ablation.use_data_fidelity_prompts"},
    "no-video": {"ablation.use_video_recording"},
    # post-validation off also removes the verdict that reads the post-validation read-back;
    # meta-reasoning off also removes the loop detector (both are meta-reasoning mechanisms)
    "no-post-validation": {"ablation.use_post_validation", "ablation.use_text_match_check"},
    "no-meta-reasoning": {"ablation.use_meta_reasoning", "ablation.use_loop_detector"},
    # WMAC: what decomposition adds
    "decomposition-only": {"ablation.use_multi_agent"} | MONOLITHIC_ROUTING,
    "a0-single-agent": ALL_FLAGS_OFF | MONOLITHIC_ROUTING,
    # reference rows
    "full-jan2026": {
        "ablation.use_loop_detector",
        "ablation.use_text_match_check",
        "ablation.use_goal_verification",
    },
    "v1-as-shipped": {
        "ablation.use_loop_detector",
        "ablation.use_text_match_check",
        "ablation.use_goal_verification",
        "ablation.legacy_v1_android_bugs",
    },
    # P2 version B (local only): full + every P2 robustness flag
    "p2": {
        "ablation.p2_coverage",
        "ablation.p2_tally",
        "ablation.p2_checklist",
        "ablation.p2_final_state",
        "ablation.p2_disambiguation",
        "ablation.p2_no_redo",
        "ablation.p2_tool_fixes",
        "ablation.p2_step_screenshots",
    },
    # routing / model rows
    "full-all-frontier": "llm-only",
    "cortex-budget": "llm-only",
    "planner-budget": "llm-only",
    "noncortex-budget": "llm-only",
    "routing-all-gemini-2.5-pro": "llm-only",
    "routing-degrade-cortex": "llm-only",
    "routing-degrade-planner": "llm-only",
    "routing-degrade-orchestrator": "llm-only",
    "routing-degrade-contextor": "llm-only",
    "routing-frontier-cortex-only": "llm-only",
    "routing-gpt4o-cortex": "llm-only",
    "routing-flash-cortex": "llm-only",
}


def _flatten(value, prefix=""):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else k))
        return out
    return {prefix: value}


def _diff(a: dict, b: dict) -> set[str]:
    fa = {k: v for k, v in _flatten(a).items() if k.split(".")[0] not in IGNORED_KEYS}
    fb = {k: v for k, v in _flatten(b).items() if k.split(".")[0] not in IGNORED_KEYS}
    return {k for k in fa.keys() | fb.keys() if fa.get(k, object()) != fb.get(k, object())}


FULL = load_benchmark_config(CONFIG_DIR / "full.jsonc").resolved


def test_every_runnable_config_has_an_expected_diff():
    names = {load_benchmark_config(p).config.name for p in RUNNABLE}
    assert names == set(
        EXPECTED
    ), f"missing rows: {sorted(names - set(EXPECTED))}, stale rows: {sorted(set(EXPECTED) - names)}"


@pytest.mark.parametrize("path", RUNNABLE, ids=lambda p: str(p.relative_to(CONFIG_DIR)))
def test_config_differs_from_full_by_exactly_its_own_flags(path):
    loaded = load_benchmark_config(path)
    diff = _diff(loaded.resolved, FULL)
    expected = EXPECTED[loaded.config.name]
    if expected == "llm-only":
        assert diff, "a routing row must change at least one model"
        assert all(k.startswith("llm.") for k in diff), sorted(
            k for k in diff if not k.startswith("llm.")
        )
    else:
        assert (
            diff == expected
        ), f"unexpected: {sorted(diff - expected)}, missing: {sorted(expected - diff)}"


def test_unused_routing_rows_are_marked():
    for path in (CONFIG_DIR / "routing").glob("*.jsonc"):
        if path.name.startswith("_"):
            continue
        ref = load_benchmark_config(path).config.paper_reference or ""
        assert ref.startswith("NOT USED IN THE PAPER"), path.name


@pytest.mark.parametrize("name", ["decomposition-only", "a0-single-agent"])
def test_monolithic_rows_only_relax_require_parameters_on_the_cortex(name):
    cfg = load_benchmark_config(CONFIG_DIR / f"{name}.jsonc").config
    assert cfg.llm.cortex.openrouter_provider == {"require_parameters": False}
    full = load_benchmark_config(CONFIG_DIR / "full.jsonc").config
    assert cfg.llm.cortex.model == full.llm.cortex.model
