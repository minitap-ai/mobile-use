"""One minimal real call per model id used by benchmarks/configs/**, through the same client
code path as the agent (ChatOpenRouter + benchmark policy), using the capability each role
needs: structured output (json_schema) for most agents, tool calling for the Executor (and for
the Cortex of the monolithic a0 baseline), a short video for the video analyzer.

    set -a; source ~/.opencode-creds/openrouter-paper.env; set +a
    uv run python benchmarks/smoke_models.py [--extra-model google/gemini-3-pro-preview ...]

Writes benchmarks/smoke_models.last.json (no secrets) and prints a table.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ["MOBILE_USE_TELEMETRY_ENABLED"] = "false"

from langchain_core.messages import HumanMessage  # noqa: E402
from langchain_core.tools import tool  # noqa: E402
from pydantic import BaseModel, SecretStr  # noqa: E402

from minitap.mobile_use.benchmark import runtime as rt  # noqa: E402
from minitap.mobile_use.benchmark.config import iter_model_ids, load_benchmark_config  # noqa: E402
from minitap.mobile_use.config import settings  # noqa: E402
from minitap.mobile_use.services.llm import get_openrouter_llm  # noqa: E402
from minitap.mobile_use.benchmark.llm_callback import BenchmarkLLMCallback  # noqa: E402

HERE = Path(__file__).parent


class Answer(BaseModel):
    city: str


@tool
def tap(element_text: str) -> str:
    """Tap the UI element that displays the given text."""
    return "ok"


def _entry(cfg, role: str):
    if role in ("hopper", "outputter", "video_analyzer"):
        return getattr(cfg.llm.utils, role)
    return getattr(cfg.llm, role, None)


def capability_for(role: str, monolithic: bool) -> str:
    base = role.split(".")[0]
    if base == "executor" or (monolithic and base == "cortex"):
        return "tools"
    if base == "video_analyzer":
        return "video"
    return "structured"


def make_video() -> str:
    """2-second solid red 320x240 mp4 (the expected description mentions red)."""
    path = Path(tempfile.mkdtemp()) / "smoke.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=320x240:d=2",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        timeout=60,
    )
    return base64.b64encode(path.read_bytes()).decode()


async def smoke_one(
    runtime: rt.BenchmarkRuntime,
    model: str,
    capability: str,
    video_b64: str | None,
    routing: dict | None,
):
    cb = BenchmarkLLMCallback(
        runtime,
        agent=f"smoke:{capability}",
        requested_model=model,
        provider_kind="openrouter",
        is_fallback=False,
    )
    llm = get_openrouter_llm(model, temperature=1, provider_routing=routing, callbacks=[cb])
    try:
        if capability == "structured":
            out = await llm.with_structured_output(Answer).ainvoke(
                [HumanMessage(content="What is the capital of France? Answer with the city only.")]
            )
            detail = f"structured={out!r}"
        elif capability == "tools":
            # Same bind kwargs as executor.py (parallel_tool_calls=True).
            msg = await llm.bind_tools([tap], parallel_tool_calls=True).ainvoke(
                [HumanMessage(content="Use the tap tool to tap the element labelled 'Settings'.")]
            )
            detail = f"tool_calls={[c['name'] for c in msg.tool_calls]}"
            if not msg.tool_calls:
                return {"ok": False, "detail": "no tool call returned: " + str(msg.content)[:200]}
        else:
            msg = await llm.ainvoke(
                [
                    HumanMessage(
                        content=[
                            {
                                "type": "text",
                                "text": "Describe this video in one short sentence (colour, text).",
                            },
                            {
                                "type": "file",
                                "source_type": "base64",
                                "mime_type": "video/mp4",
                                "data": video_b64,
                            },
                        ]
                    )
                ]
            )
            detail = "video=" + str(msg.content)[:120]
        return {"ok": True, "detail": detail}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "detail": f"{type(e).__name__}: {str(e)[:300]}"}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--extra-model",
        action="append",
        default=[],
        help="model[:capability] to test in addition (e.g. a paper id)",
    )
    args = ap.parse_args()

    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        print("OPENROUTER_API_KEY not set", file=sys.stderr)
        return 2
    settings.OPEN_ROUTER_API_KEY = SecretStr(key)

    wanted: dict[tuple[str, str], set[str]] = {}
    routing: dict[tuple[str, str], dict | None] = {}
    for f in sorted((HERE / "configs").rglob("*.jsonc")):
        if f.name.startswith("_"):
            continue
        cfg = load_benchmark_config(f).config
        mono = not cfg.ablation.use_multi_agent
        for role, provider, model in iter_model_ids(cfg):
            if provider != "openrouter" or role.endswith(".fallback"):
                continue
            cap = capability_for(role, mono)
            wanted.setdefault((model, cap), set()).add(cfg.name)
            entry = _entry(cfg, role)
            if entry is not None and entry.openrouter_provider:
                routing[(model, cap)] = entry.openrouter_provider
    for spec in args.extra_model:
        model, _, cap = spec.partition(":")
        wanted.setdefault((model, cap or "structured"), set()).add("(extra)")

    policy = load_benchmark_config(HERE / "configs" / "full.jsonc").config.llm_policy.to_policy()
    policy.max_retries = 1
    out_dir = Path(tempfile.mkdtemp())
    runtime = rt.BenchmarkRuntime(out_dir / "smoke.jsonl", "smoke", policy)
    rt.activate(runtime)
    video_b64 = make_video() if any(c == "video" for _, c in wanted) else None
    results = []
    for (model, cap), configs in sorted(wanted.items()):
        res = await smoke_one(runtime, model, cap, video_b64, routing.get((model, cap)))
        results.append({"model": model, "capability": cap, "configs": sorted(configs), **res})
    rt.deactivate()

    calls = [json.loads(line) for line in (out_dir / "smoke.jsonl").read_text().splitlines()]
    by_model = {}
    for c in calls:
        if c["type"] == "llm_call":
            by_model.setdefault((c["requested_model"], c["agent"].split(":")[1]), c)
    for r in results:
        c = by_model.get((r["model"], r["capability"]), {})
        r.update(
            {
                k: c.get(k)
                for k in (
                    "resolved_model",
                    "resolved_provider",
                    "prompt_tokens",
                    "completion_tokens",
                    "cost_usd",
                    "openrouter_cost_usd",
                    "upstream_cost_usd",
                    "is_byok",
                    "latency_s",
                    "generation_id",
                )
            }
        )
        flag = "OK  " if r["ok"] else "FAIL"
        print(
            f"{flag} {r['model']:42s} {r['capability']:10s} -> {r.get('resolved_model')} "
            f"@ {r.get('resolved_provider')} cost={r.get('cost_usd')} byok={r.get('is_byok')} "
            f"| {r['detail'][:90]}"
        )
    (HERE / "smoke_models.last.json").write_text(json.dumps(results, indent=2))
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
