"""Single-task entry point for benchmark harnesses (see benchmarks/HARNESS_INTERFACE.md).

    from minitap.mobile_use.benchmark.runner import run_task
    result = await run_task(goal, serial, config_path, out_dir)

or from a shell (prints the result JSON on stdout):

    uv run python -m minitap.mobile_use.benchmark.runner \
        --goal "..." --serial emulator-5554 --config benchmarks/configs/full.jsonc --out runs/t1
"""

from __future__ import annotations

import os

# Telemetry must be off for every benchmark run. Set before any mobile-use module reads settings
# (load_dotenv never overrides an existing variable); also forced on the singleton below.
os.environ["MOBILE_USE_TELEMETRY_ENABLED"] = "false"

import argparse  # noqa: E402
import asyncio  # noqa: E402
import json  # noqa: E402
import platform  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import traceback  # noqa: E402
import uuid  # noqa: E402
from datetime import UTC, datetime  # noqa: E402
from importlib import metadata  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any, Literal  # noqa: E402

from pydantic import BaseModel, Field, SecretStr  # noqa: E402

from minitap.mobile_use.agents.planner.types import SubgoalStatus  # noqa: E402
from minitap.mobile_use.benchmark import runtime as runtime_mod  # noqa: E402
from minitap.mobile_use.benchmark.config import load_benchmark_config  # noqa: E402
from minitap.mobile_use.config import ROOT_DIR, settings  # noqa: E402
from minitap.mobile_use.context import DevicePlatform  # noqa: E402
from minitap.mobile_use.sdk.agent import Agent  # noqa: E402
from minitap.mobile_use.sdk.builders.agent_config_builder import AgentConfigBuilder  # noqa: E402
from minitap.mobile_use.sdk.types.task import AgentProfile  # noqa: E402
from minitap.mobile_use.services.llm import LLMFallbackDisabledError  # noqa: E402
from minitap.mobile_use.services.telemetry import telemetry  # noqa: E402
from minitap.mobile_use.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

Status = Literal["completed", "ended_incomplete", "max_steps", "timeout", "error", "init_error"]


class BenchmarkAnswer(BaseModel):
    """Structured output used when the task needs a textual answer (information retrieval)."""

    answer: str = Field(
        description=(
            "The final answer to the question asked in the goal, exactly as found on the device, "
            "as short as possible (e.g. a number, a name, a date, a comma-separated list). "
            "No explanation."
        )
    )


def _git(*args: str) -> str | None:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT_DIR, capture_output=True, text=True, check=True, timeout=10
        ).stdout.strip()
    except Exception:
        return None


def code_version() -> dict[str, Any]:
    status = _git("status", "--porcelain", "--untracked-files=no")
    versions = {}
    for pkg in ("minitap-mobile-use", "langgraph", "langchain-core", "langchain-openai", "openai"):
        try:
            versions[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            versions[pkg] = None
    return {
        "git_sha": _git("rev-parse", "HEAD"),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_dirty": bool(status) if status is not None else None,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packages": versions,
    }


def _configure_openrouter_key(allow_dotenv_key: bool) -> str:
    env_key = os.environ.get("OPENROUTER_API_KEY")
    if env_key:
        settings.OPEN_ROUTER_API_KEY = SecretStr(env_key)
        return "env:OPENROUTER_API_KEY"
    if allow_dotenv_key and settings.OPEN_ROUTER_API_KEY:
        return "settings:OPEN_ROUTER_API_KEY"
    raise RuntimeError(
        "OPENROUTER_API_KEY is not set in the process environment. Load the benchmark key with "
        "`set -a; source ~/.opencode-creds/openrouter-paper.env; set +a` "
        "(or pass allow_dotenv_key=True to accept OPEN_ROUTER_API_KEY from .env)."
    )


def _classify_error(exc: BaseException) -> str:
    name = type(exc).__name__
    module = type(exc).__module__ or ""
    if isinstance(exc, LLMFallbackDisabledError) or module.startswith(("openai", "httpx")):
        return "llm_api"
    if module.startswith(("adbutils", "uiautomator2")) or isinstance(exc, ConnectionError):
        return "device"
    if name == "GraphRecursionError":
        return "max_steps"
    return "agent"


def _plan_summary(state) -> list[dict[str, Any]]:
    if state is None:
        return []
    return [
        {
            "id": s.id,
            "description": s.description,
            "status": s.status.value,
            "completion_reason": s.completion_reason,
        }
        for s in state.subgoal_plan
    ]


async def run_task(
    goal: str,
    serial: str,
    config_path: str | Path,
    out_dir: str | Path,
    *,
    adb_host: str = "127.0.0.1",
    adb_port: int = 5037,
    task_name: str | None = None,
    answer_required: bool = False,
    max_steps: int | None = None,
    timeout_s: float | None = None,
    run_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    allow_dotenv_key: bool = False,
) -> dict[str, Any]:
    """Run one task on one Android device and return {final_answer, status, metrics, ...}.

    Never raises for task-level problems: errors are returned as status "error"/"init_error"
    with `error` and `error_kind` set, so the harness can decide whether to re-queue.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    run_id = run_id or str(uuid.uuid4())
    loaded = load_benchmark_config(config_path)
    cfg = loaded.config
    effective_max_steps = max_steps or cfg.agent.max_steps
    effective_timeout = timeout_s if timeout_s is not None else cfg.agent.timeout_s

    # Benchmark hygiene: no telemetry, no hosted-platform calls.
    settings.MOBILE_USE_TELEMETRY_ENABLED = False
    telemetry._config._enabled = False  # in-memory only, never persisted
    key_source = _configure_openrouter_key(allow_dotenv_key)
    if adb_host not in ("127.0.0.1", "localhost") or adb_port != 5037:
        # uiautomator2/adbutils read these to reach a non-default adb server.
        os.environ["ANDROID_ADB_SERVER_HOST"] = adb_host
        os.environ["ANDROID_ADB_SERVER_PORT"] = str(adb_port)

    runtime = runtime_mod.BenchmarkRuntime(
        events_path=out / "events.jsonl", run_id=run_id, llm_policy=cfg.llm_policy.to_policy()
    )
    runtime_mod.activate(runtime)
    version = code_version()
    started_at = datetime.now(UTC)
    t0 = time.monotonic()
    runtime.event(
        "run_start",
        goal=goal,
        task_name=task_name,
        serial=serial,
        adb_server=f"{adb_host}:{adb_port}",
        answer_required=answer_required,
        max_steps=effective_max_steps,
        timeout_s=effective_timeout,
        config_name=cfg.name,
        config_files=loaded.files,
        config_resolved_sha256=loaded.resolved_sha256,
        config_resolved=loaded.resolved,
        openrouter_key_source=key_source,
        code=version,
        metadata=metadata or {},
    )

    status: Status = "error"
    error: str | None = None
    error_kind: str | None = None
    final_answer: str | None = None
    raw_output: Any = None
    agent: Agent | None = None
    try:
        try:
            builder = (
                AgentConfigBuilder()
                .add_profile(AgentProfile(name=cfg.name, llm_config=cfg.llm))
                .with_default_profile(cfg.name)
                .for_device(platform=DevicePlatform.ANDROID, device_id=serial)
                .with_adb_server(host=adb_host, port=adb_port)
            )
            if cfg.ablation.use_video_recording:
                if cfg.llm.utils.video_analyzer is None:
                    raise ValueError("use_video_recording=true requires llm.utils.video_analyzer")
                builder = builder.with_video_recording_tools()
            agent = Agent(
                config=builder.build(),
                ablation_config=cfg.ablation,
                loop_detector_config=cfg.loop_detector,
                text_check_config=cfg.text_check,
            )
            await agent.init()
        except Exception as exc:
            status, error, error_kind = "init_error", f"{type(exc).__name__}: {exc}", "device"
            runtime.event("error", phase="init", error=error, traceback=traceback.format_exc())
            raise _Handled() from exc

        request_builder = agent.new_task(goal).with_max_steps(effective_max_steps)
        if task_name:
            request_builder = request_builder.with_name(task_name)
        if cfg.agent.record_trace:
            request_builder = request_builder.with_trace_recording(
                enabled=True, path=str(out / "traces")
            )
        if answer_required:
            request_builder = request_builder.with_output_format(BenchmarkAnswer)
        request = request_builder.build()

        try:
            coro = agent.run_task(request=request)
            raw_output = (
                await asyncio.wait_for(coro, timeout=effective_timeout)
                if effective_timeout
                else await coro
            )
            plan = agent.last_task_state.subgoal_plan if agent.last_task_state else []
            all_done = bool(plan) and all(s.status == SubgoalStatus.SUCCESS for s in plan)
            status = "completed" if all_done else "ended_incomplete"
        except TimeoutError:
            status, error, error_kind = (
                "timeout",
                f"wall-clock timeout after {effective_timeout}s",
                "timeout",
            )
        except Exception as exc:
            error_kind = _classify_error(exc)
            status = "max_steps" if error_kind == "max_steps" else "error"
            error = f"{type(exc).__name__}: {exc}"
            runtime.event("error", phase="task", error=error, traceback=traceback.format_exc())

        if isinstance(raw_output, BenchmarkAnswer):
            final_answer = raw_output.answer
        elif isinstance(raw_output, dict) and "answer" in raw_output:
            final_answer = str(raw_output["answer"])
        elif isinstance(raw_output, str):
            final_answer = raw_output
    except _Handled:
        pass
    finally:
        if agent is not None:
            try:
                await agent.clean()
            except Exception as exc:  # pragma: no cover - best effort
                runtime.event("warning", phase="clean", error=f"{type(exc).__name__}: {exc}")

    state = agent.last_task_state if agent is not None else None
    wall = time.monotonic() - t0
    summary = runtime.summary()
    metrics = {
        "wall_clock_s": round(wall, 3),
        "graph_node_runs": sum(summary["nodes"].values()),
        "cortex_turns": summary["nodes"].get("cortex", 0),
        "agent_thoughts": len(state.agents_thoughts) if state else 0,
        **summary,
    }
    result = {
        "run_id": run_id,
        "task_name": task_name,
        "goal": goal,
        "status": status,
        "final_answer": final_answer,
        "error": error,
        "error_kind": error_kind,
        "infra_suspect": status == "init_error" or error_kind in ("llm_api", "device"),
        "subgoal_plan": _plan_summary(state),
        "last_thought": state.agents_thoughts[-1] if state and state.agents_thoughts else None,
        "config_name": cfg.name,
        "config_resolved_sha256": loaded.resolved_sha256,
        "git_sha": version["git_sha"],
        "git_dirty": version["git_dirty"],
        "started_at": started_at.isoformat(),
        "ended_at": datetime.now(UTC).isoformat(),
        "metrics": metrics,
        "events_path": str(out / "events.jsonl"),
    }
    runtime.event("run_end", **{k: v for k, v in result.items() if k != "events_path"})
    runtime_mod.deactivate()
    (out / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return result


class _Handled(Exception):
    """Internal: an error already recorded in the result."""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one mobile-use benchmark task.")
    parser.add_argument("--goal", required=True)
    parser.add_argument(
        "--serial", required=True, help="adb serial, e.g. emulator-5554 or host:port"
    )
    parser.add_argument("--config", required=True, help="benchmarks/configs/<name>.jsonc")
    parser.add_argument("--out", required=True, help="output directory for this task")
    parser.add_argument("--adb-host", default="127.0.0.1")
    parser.add_argument("--adb-port", type=int, default=5037)
    parser.add_argument("--task-name")
    parser.add_argument("--answer-required", action="store_true")
    parser.add_argument("--max-steps", type=int)
    parser.add_argument("--timeout-s", type=float)
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    result = asyncio.run(
        run_task(
            goal=args.goal,
            serial=args.serial,
            config_path=args.config,
            out_dir=args.out,
            adb_host=args.adb_host,
            adb_port=args.adb_port,
            task_name=args.task_name,
            answer_required=args.answer_required,
            max_steps=args.max_steps,
            timeout_s=args.timeout_s,
            run_id=args.run_id,
        )
    )
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
