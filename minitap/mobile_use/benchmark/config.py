"""Benchmark configuration files (benchmarks/configs/*.jsonc).

One file = one experimental condition (ablation flags + LLM routing + detector thresholds).
All conditions run on the same commit; only the file changes. A file may `extends` another
(path relative to itself); dictionaries are deep-merged, the child wins.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from minitap.mobile_use.benchmark.loop_detector import LoopDetectorConfig
from minitap.mobile_use.benchmark.runtime import LLMPolicy
from minitap.mobile_use.benchmark.text_check import TextCheckConfig
from minitap.mobile_use.config import AblationConfig, LLMConfig
from minitap.mobile_use.constants import RECURSION_LIMIT
from minitap.mobile_use.utils.file import load_jsonc

AGENT_KEYS = ("planner", "orchestrator", "contextor", "cortex", "executor")
UTIL_KEYS = ("hopper", "outputter", "video_analyzer")


class LLMPolicyConfig(BaseModel):
    model_config = {"extra": "forbid"}

    allow_fallback: bool = False
    max_retries: int = Field(default=4, ge=0)
    timeout_s: float = Field(default=180.0, gt=0)
    same_model_retries: int = Field(default=2, ge=0)
    retry_backoff_s: float = Field(default=2.0, ge=0)
    openrouter_provider: dict[str, Any] = Field(default_factory=dict)

    def to_policy(self) -> LLMPolicy:
        return LLMPolicy(
            allow_fallback=self.allow_fallback,
            max_retries=self.max_retries,
            timeout_s=self.timeout_s,
            same_model_retries=self.same_model_retries,
            retry_backoff_s=self.retry_backoff_s,
            openrouter_provider=dict(self.openrouter_provider),
        )


class AgentRunConfig(BaseModel):
    model_config = {"extra": "forbid"}

    max_steps: int = Field(default=RECURSION_LIMIT, ge=1)
    timeout_s: float | None = Field(default=None, gt=0)
    record_trace: bool = False


class BenchmarkConfig(BaseModel):
    model_config = {"extra": "forbid"}

    name: str
    description: str = ""
    paper_reference: str | None = None
    ablation: AblationConfig
    loop_detector: LoopDetectorConfig = Field(default_factory=LoopDetectorConfig)
    text_check: TextCheckConfig = Field(default_factory=TextCheckConfig)
    llm_policy: LLMPolicyConfig = Field(default_factory=LLMPolicyConfig)
    llm: LLMConfig
    agent: AgentRunConfig = Field(default_factory=AgentRunConfig)


class LoadedBenchmarkConfig(BaseModel):
    config: BenchmarkConfig
    resolved: dict[str, Any]
    resolved_sha256: str
    files: list[dict[str, str]]  # [{"path": ..., "sha256": ...}] (child first)


def _deep_merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _load_raw(path: Path, seen: tuple[Path, ...] = ()) -> tuple[dict, list[dict[str, str]]]:
    path = path.resolve()
    if path in seen:
        raise ValueError(f"Circular 'extends' chain: {[str(p) for p in (*seen, path)]}")
    raw_bytes = path.read_bytes()
    with open(path) as f:
        data = load_jsonc(f)
    files = [{"path": str(path), "sha256": hashlib.sha256(raw_bytes).hexdigest()}]
    parent = data.pop("extends", None)
    if parent:
        parent_data, parent_files = _load_raw(path.parent / parent, (*seen, path))
        data = _deep_merge(parent_data, data)
        files += parent_files
    return data, files


def _fill_fallbacks(llm: dict, allow_fallback: bool) -> dict:
    """LLMConfig requires a fallback per model; with fallbacks disabled it is never called, so
    files may omit it (it is then set to the main model)."""
    llm = copy.deepcopy(llm)

    def fill(entry: dict, where: str):
        if "fallback" not in entry:
            if allow_fallback:
                raise ValueError(f"llm.{where}: a 'fallback' is required when allow_fallback=true")
            entry["fallback"] = {"provider": entry["provider"], "model": entry["model"]}

    for key in AGENT_KEYS:
        if key in llm:
            fill(llm[key], key)
    for key in UTIL_KEYS:
        entry = (llm.get("utils") or {}).get(key)
        if entry:
            fill(entry, f"utils.{key}")
    return llm


def load_benchmark_config(path: str | Path) -> LoadedBenchmarkConfig:
    data, files = _load_raw(Path(path))
    data.pop("$schema", None)
    # Every ablation flag must be explicit in the resolved config (no silent defaults).
    missing = set(AblationConfig.model_fields) - set((data.get("ablation") or {}).keys())
    if missing:
        raise ValueError(
            f"{path}: ablation flags missing from the resolved config: {sorted(missing)}"
        )
    allow_fallback = bool((data.get("llm_policy") or {}).get("allow_fallback", False))
    if "llm" in data:
        data["llm"] = _fill_fallbacks(data["llm"], allow_fallback)
    config = BenchmarkConfig.model_validate(data)
    resolved = config.model_dump(mode="json")
    canonical = json.dumps(resolved, sort_keys=True, separators=(",", ":"))
    return LoadedBenchmarkConfig(
        config=config,
        resolved=resolved,
        resolved_sha256=hashlib.sha256(canonical.encode()).hexdigest(),
        files=files,
    )


def iter_model_ids(config: BenchmarkConfig) -> list[tuple[str, str, str]]:
    """(role, provider, model) for every configured model, fallbacks included."""
    out: list[tuple[str, str, str]] = []
    for key in AGENT_KEYS:
        entry = getattr(config.llm, key)
        out.append((key, entry.provider, entry.model))
        out.append((f"{key}.fallback", entry.fallback.provider, entry.fallback.model))
    for key in UTIL_KEYS:
        entry = getattr(config.llm.utils, key)
        if entry is not None:
            out.append((key, entry.provider, entry.model))
            out.append((f"{key}.fallback", entry.fallback.provider, entry.fallback.model))
    return out
