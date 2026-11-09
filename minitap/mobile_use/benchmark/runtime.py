"""Per-task benchmark runtime: JSONL event recorder + LLM policy for benchmark runs.

Only one benchmark task runs per Python process at a time (one process per device), so the
active runtime is a module-level singleton. When no runtime is active (normal SDK/CLI use),
every hook in the agent code is a no-op and behaviour is identical to the paper-era code.
"""

from __future__ import annotations

import json
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

# Strings longer than this are truncated in the JSONL (UI hierarchies, screenshots...).
MAX_FIELD_CHARS = 4000


@dataclass
class LLMPolicy:
    """How LLM clients behave during a benchmark run."""

    allow_fallback: bool = False
    max_retries: int = 4
    timeout_s: float = 180.0
    # Default OpenRouter `provider` routing object, merged under each model's own preferences.
    openrouter_provider: dict[str, Any] = field(default_factory=dict)
    openrouter_app_title: str = "mobile-use AndroidWorld paper rework"


def _truncate(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_FIELD_CHARS:
        return value[:MAX_FIELD_CHARS] + f"...<truncated {len(value) - MAX_FIELD_CHARS} chars>"
    if isinstance(value, dict):
        return {k: _truncate(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_truncate(v) for v in value]
    return value


class BenchmarkRuntime:
    """Writes one JSONL file per task and keeps running counters for the task summary."""

    def __init__(self, events_path: Path, run_id: str, llm_policy: LLMPolicy):
        self.events_path = events_path
        self.run_id = run_id
        self.llm_policy = llm_policy
        self._lock = threading.Lock()
        self._t0 = time.monotonic()
        self._seq = 0
        events_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(events_path, "a", encoding="utf-8")  # noqa: SIM115

        # Counters for the per-task summary
        self.llm_calls: Counter[str] = Counter()
        self.llm_errors: Counter[str] = Counter()
        self.llm_prompt_tokens: Counter[str] = Counter()
        self.llm_completion_tokens: Counter[str] = Counter()
        self.llm_cost: defaultdict[str, float] = defaultdict(float)
        self.llm_cost_missing_calls = 0
        self.llm_byok_calls = 0
        self.llm_latency_s: defaultdict[str, float] = defaultdict(float)
        self.resolved_models: defaultdict[str, Counter[str]] = defaultdict(Counter)
        self.resolved_providers: defaultdict[str, Counter[str]] = defaultdict(Counter)
        self.fallback_attempts = 0
        self.fallback_blocked = 0
        self.tool_calls: Counter[str] = Counter()
        self.tool_failures: Counter[str] = Counter()
        self.node_runs: Counter[str] = Counter()
        self.loop_triggers: Counter[str] = Counter()
        self.loop_replans = 0
        self.text_checks: Counter[str] = Counter()

    # ------------------------------------------------------------------ events
    def event(self, type: str, **fields: Any) -> None:
        with self._lock:
            self._seq += 1
            record = {
                "schema": SCHEMA_VERSION,
                "run_id": self.run_id,
                "seq": self._seq,
                "ts": datetime.now(UTC).isoformat(),
                "t_rel_s": round(time.monotonic() - self._t0, 4),
                "type": type,
                **_truncate(fields),
            }
            if self._fh.closed:
                return
            self._fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            self._fh.flush()

    def close(self) -> None:
        with self._lock:
            if not self._fh.closed:
                self._fh.close()

    # ---------------------------------------------------------------- recorders
    def record_llm_call(
        self,
        *,
        agent: str,
        requested_model: str,
        provider_kind: str,
        is_fallback: bool,
        latency_s: float,
        status: str,
        resolved_model: str | None = None,
        resolved_provider: str | None = None,
        generation_id: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        reasoning_tokens: int | None = None,
        cached_tokens: int | None = None,
        cost_usd: float | None = None,
        openrouter_cost_usd: float | None = None,
        upstream_cost_usd: float | None = None,
        is_byok: bool | None = None,
        finish_reason: str | None = None,
        error: str | None = None,
    ) -> None:
        self.llm_calls[agent] += 1
        self.llm_latency_s[agent] += latency_s
        if status != "ok":
            self.llm_errors[agent] += 1
        else:
            self.llm_prompt_tokens[agent] += prompt_tokens or 0
            self.llm_completion_tokens[agent] += completion_tokens or 0
            if cost_usd is None:
                self.llm_cost_missing_calls += 1
            else:
                self.llm_cost[agent] += cost_usd
            if is_byok:
                self.llm_byok_calls += 1
            if resolved_model:
                self.resolved_models[agent][resolved_model] += 1
            if resolved_provider:
                self.resolved_providers[agent][resolved_provider] += 1
        self.event(
            "llm_call",
            agent=agent,
            requested_model=requested_model,
            provider_kind=provider_kind,
            is_fallback=is_fallback,
            status=status,
            resolved_model=resolved_model,
            resolved_provider=resolved_provider,
            generation_id=generation_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_tokens=reasoning_tokens,
            cached_tokens=cached_tokens,
            cost_usd=cost_usd,
            openrouter_cost_usd=openrouter_cost_usd,
            upstream_cost_usd=upstream_cost_usd,
            is_byok=is_byok,
            finish_reason=finish_reason,
            latency_s=round(latency_s, 4),
            error=error,
        )

    def record_fallback(self, *, reason: str, blocked: bool) -> None:
        if blocked:
            self.fallback_blocked += 1
        else:
            self.fallback_attempts += 1
        self.event("llm_fallback", blocked=blocked, reason=reason)

    def record_tool_call(
        self,
        *,
        tool: str,
        args: dict[str, Any],
        status: str,
        latency_s: float,
        output: str | None = None,
    ) -> None:
        self.tool_calls[tool] += 1
        if status != "success":
            self.tool_failures[tool] += 1
        self.event(
            "tool_call",
            tool=tool,
            args=args,
            status=status,
            latency_s=round(latency_s, 4),
            output=output,
        )

    def record_node(self, node: str) -> None:
        self.node_runs[node] += 1
        self.event("node", node=node)

    def record_loop_trigger(self, *, kind: str, action: str, **details: Any) -> None:
        self.loop_triggers[kind] += 1
        if action == "replan":
            self.loop_replans += 1
        self.event("loop_detector", kind=kind, action=action, **details)

    def record_text_check(self, *, verdict: str, **details: Any) -> None:
        self.text_checks[verdict] += 1
        self.event("text_check", verdict=verdict, **details)

    # ------------------------------------------------------------------ summary
    def summary(self) -> dict[str, Any]:
        total_cost = sum(self.llm_cost.values())
        return {
            "llm": {
                "calls_by_agent": dict(self.llm_calls),
                "errors_by_agent": dict(self.llm_errors),
                "prompt_tokens_by_agent": dict(self.llm_prompt_tokens),
                "completion_tokens_by_agent": dict(self.llm_completion_tokens),
                "cost_usd_by_agent": {k: round(v, 6) for k, v in self.llm_cost.items()},
                "latency_s_by_agent": {k: round(v, 3) for k, v in self.llm_latency_s.items()},
                "resolved_models_by_agent": {k: dict(v) for k, v in self.resolved_models.items()},
                "resolved_providers_by_agent": {
                    k: dict(v) for k, v in self.resolved_providers.items()
                },
                "total_calls": sum(self.llm_calls.values()),
                "total_prompt_tokens": sum(self.llm_prompt_tokens.values()),
                "total_completion_tokens": sum(self.llm_completion_tokens.values()),
                "total_cost_usd": round(total_cost, 6),
                "calls_without_cost": self.llm_cost_missing_calls,
                "byok_calls": self.llm_byok_calls,
                "fallback_attempts": self.fallback_attempts,
                "fallback_blocked": self.fallback_blocked,
            },
            "tools": {
                "calls_by_tool": dict(self.tool_calls),
                "failures_by_tool": dict(self.tool_failures),
                "total_calls": sum(self.tool_calls.values()),
            },
            "nodes": dict(self.node_runs),
            "loop_detector": {
                "triggers_by_kind": dict(self.loop_triggers),
                "forced_replans": self.loop_replans,
            },
            "text_check": dict(self.text_checks),
        }


_active: BenchmarkRuntime | None = None


def get_runtime() -> BenchmarkRuntime | None:
    return _active


def activate(runtime: BenchmarkRuntime) -> None:
    global _active
    if _active is not None:
        raise RuntimeError(
            "A benchmark runtime is already active in this process. "
            "Run one task per process (one process per device)."
        )
    _active = runtime


def deactivate() -> None:
    global _active
    if _active is not None:
        _active.close()
    _active = None
