import json
from pathlib import Path

import pytest

from minitap.mobile_use.benchmark.config import iter_model_ids, load_benchmark_config

CONFIG_DIR = Path(__file__).resolve().parents[3] / "benchmarks" / "configs"
RUNNABLE = sorted(p for p in CONFIG_DIR.rglob("*.jsonc") if not p.name.startswith("_"))


@pytest.mark.parametrize("path", RUNNABLE, ids=lambda p: str(p.relative_to(CONFIG_DIR)))
def test_every_config_loads_and_uses_openrouter_without_fallback(path):
    loaded = load_benchmark_config(path)
    cfg = loaded.config
    assert cfg.llm_policy.allow_fallback is False
    for role, provider, model in iter_model_ids(cfg):
        assert provider == "openrouter", (role, provider)
        assert "/" in model
    assert len(loaded.resolved_sha256) == 64


def test_names_are_unique():
    names = [load_benchmark_config(p).config.name for p in RUNNABLE]
    assert len(names) == len(set(names))


def test_p3_configs_differ_from_full_only_where_intended():
    full = load_benchmark_config(CONFIG_DIR / "full.jsonc").config
    assert full.ablation.get_disabled_features() == []

    def off(name):
        return load_benchmark_config(CONFIG_DIR / name).config.ablation.get_disabled_features()

    assert off("no-post-validation.jsonc") == ["post_validation", "text_match_check"]
    assert off("no-meta-reasoning.jsonc") == ["meta_reasoning", "loop_detector"]
    assert off("full-jan2026.jsonc") == ["loop_detector", "text_match_check"]
    assert off("no-video.jsonc") == ["video_recording"]
    assert off("no-data-fidelity.jsonc") == ["data_fidelity_prompts"]
    a0 = load_benchmark_config(CONFIG_DIR / "a0-single-agent.jsonc").config
    assert a0.ablation.get_enabled_features() == []


def _write(tmp_path, name, data):
    p = tmp_path / name
    p.write_text(json.dumps(data))
    return p


def test_missing_flag_and_typo_are_rejected(tmp_path):
    base = load_benchmark_config(CONFIG_DIR / "full.jsonc").resolved
    data = json.loads(json.dumps(base))
    del data["ablation"]["use_vision"]
    with pytest.raises(ValueError, match="use_vision"):
        load_benchmark_config(_write(tmp_path, "a.jsonc", data))
    data = json.loads(json.dumps(base))
    data["ablation"]["use_visoin"] = False
    with pytest.raises(Exception):
        load_benchmark_config(_write(tmp_path, "b.jsonc", data))


def test_extends_merges_and_fills_fallback(tmp_path):
    child = _write(
        tmp_path,
        "child.jsonc",
        {
            "extends": str(CONFIG_DIR / "full.jsonc"),
            "name": "child",
            "llm": {"planner": {"provider": "openrouter", "model": "x/y"}},
        },
    )
    loaded = load_benchmark_config(child)
    assert loaded.config.llm.planner.model == "x/y"
    assert loaded.config.llm.planner.fallback.model == "x/y"
    assert (
        loaded.config.llm.cortex.model
        == load_benchmark_config(CONFIG_DIR / "full.jsonc").config.llm.cortex.model
    )
    assert [Path(f["path"]).name for f in loaded.files] == [
        "child.jsonc",
        "full.jsonc",
        "_base.jsonc",
    ]


def test_fallback_required_when_allowed(tmp_path):
    child = _write(
        tmp_path,
        "c.jsonc",
        {
            "extends": str(CONFIG_DIR / "full.jsonc"),
            "name": "c",
            "llm_policy": {"allow_fallback": True},
        },
    )
    with pytest.raises(ValueError, match="fallback"):
        load_benchmark_config(child)


def test_every_model_has_a_single_pinned_provider_without_fallback():
    for path in RUNNABLE:
        cfg = load_benchmark_config(path).config
        pins = cfg.llm_policy.openrouter_provider_by_model
        for role, _provider, model in iter_model_ids(cfg):
            assert model in pins, f"{path.name}: {role} model {model} has no provider pin"
            pin = pins[model]
            assert pin.get("allow_fallbacks") is False, (model, pin)
            assert len(pin.get("order", [])) == 1, (model, pin)
