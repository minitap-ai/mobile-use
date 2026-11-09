#!/usr/bin/env python3
"""Per-config cost estimate for a matrix spec, from a measured token profile.

Cost per cell = sum over agents of (prompt tokens x input price + completion tokens x output
price), where the per-agent tokens are the mean of measured runs (by default the agent
`result.json` metrics of a pilot) and the prices are today's OpenRouter prices of the endpoint each
config pins (`llm_policy.openrouter_provider_by_model`), falling back to the model list price.

ASSUMPTION (printed with the result): every config has the same token profile as the measured
runs; only prices change. Configs that change the agent's behaviour (ablations, a0, other
models) will use a different number of tokens: those estimates are UNVERIFIED until the first
cells of each config have run (`matrix.py status` then reports the measured cost).

    uv run python benchmarks/matrix/estimate_cost.py <spec.jsonc> --profile '<results glob>'
"""

from __future__ import annotations

import argparse
import glob
import json
import statistics
import sys
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import matrix  # noqa: E402

from minitap.mobile_use.benchmark.config import load_benchmark_config  # noqa: E402

ROLES = ("planner", "orchestrator", "contextor", "cortex", "executor")
UTILS = ("hopper", "outputter", "video_analyzer")


def token_profile(pattern: str) -> tuple[dict[str, tuple[float, float]], int, float]:
    rows = []
    for f in glob.glob(pattern, recursive=True):
        for line in open(f, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                if ((r.get("metrics") or {}).get("llm") or {}).get("prompt_tokens_by_agent"):
                    rows.append(r)
    if not rows:
        raise SystemExit(f"no rows with per-agent token metrics in {pattern}")
    pt, ct = defaultdict(float), defaultdict(float)
    for r in rows:
        llm = r["metrics"]["llm"]
        for a, v in llm.get("prompt_tokens_by_agent", {}).items():
            pt[a] += v
        for a, v in llm.get("completion_tokens_by_agent", {}).items():
            ct[a] += v
    n = len(rows)
    measured = statistics.mean(r["metrics"]["llm"]["total_cost_usd"] or 0 for r in rows)
    return {a: (pt[a] / n, ct[a] / n) for a in set(pt) | set(ct)}, n, measured


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


_PRICE_CACHE: dict[tuple[str, str | None], tuple[float, float]] = {}


def price(model: str, tag: str | None) -> tuple[float, float]:
    """(USD per prompt token, USD per completion token) for the pinned endpoint."""
    key = (model, tag)
    if key in _PRICE_CACHE:
        return _PRICE_CACHE[key]
    p = None
    if tag:
        eps = _get(f"https://openrouter.ai/api/v1/models/{model}/endpoints")["data"]["endpoints"]
        for e in eps:
            if e.get("tag") == tag:
                p = (float(e["pricing"]["prompt"]), float(e["pricing"]["completion"]))
    if p is None:
        models = {m["id"]: m for m in _get("https://openrouter.ai/api/v1/models")["data"]}
        m = models[model]["pricing"]
        p = (float(m["prompt"]), float(m["completion"]))
    _PRICE_CACHE[key] = p
    return p


def cell_cost(cfg, profile) -> float:
    pins = cfg.llm_policy.openrouter_provider_by_model
    total = 0.0
    for agent, (ptok, ctok) in profile.items():
        entry = getattr(cfg.llm, agent, None) if agent in ROLES else None
        if entry is None and agent in UTILS:
            entry = getattr(cfg.llm.utils, agent)
        if entry is None:
            continue
        if not cfg.ablation.use_multi_agent and agent in ("planner", "orchestrator", "executor"):
            # monolithic graph: those agents don't exist; their work is done by the Cortex model
            entry = cfg.llm.cortex
        tag = (pins.get(entry.model) or {}).get("order", [None])[0]
        pin, cin = price(entry.model, tag)
        total += ptok * pin + ctok * cin
    return total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument(
        "--profile", required=True, help="glob of harness results.jsonl with agent metrics"
    )
    a = ap.parse_args()
    spec = matrix.Spec.load(Path(a.spec))
    profile, n, measured = token_profile(a.profile)
    cells = Counter(c.config for c in spec.cells())
    rows, total = [], 0.0
    for name in spec.configs:
        cfg = load_benchmark_config(spec.mobile_use_path / spec.config_path(name)).config
        per = cell_cost(cfg, profile)
        rows.append(
            {
                "config": name,
                "cells": cells[name],
                "usd_per_cell": round(per, 3),
                "usd_total": round(per * cells[name], 1),
            }
        )
        total += per * cells[name]
    print(
        json.dumps(
            {
                "profile_runs": n,
                "profile_measured_usd_per_task": round(measured, 3),
                "assumption": "same per-agent token profile as the measured runs; only prices "
                "change (UNVERIFIED for configs that change behaviour)",
                "per_config": rows,
                "total_usd": round(total, 1),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
