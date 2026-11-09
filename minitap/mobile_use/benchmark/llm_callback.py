"""LangChain callback that records every LLM call into the active benchmark runtime.

Ported in spirit from `origin/logging-setup` (WandbLangChainCallback) without the W&B
dependency. The callback is attached at model construction (`ChatOpenAI(callbacks=...)`), so it
survives `with_structured_output()` and `bind_tools()` wrappers.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import LLMResult

from minitap.mobile_use.benchmark.runtime import BenchmarkRuntime


def _first_generation_info(response: LLMResult) -> dict[str, Any]:
    for gen_list in response.generations or []:
        for gen in gen_list:
            if getattr(gen, "generation_info", None):
                return gen.generation_info  # type: ignore[return-value]
    return {}


def _usage_from_message(response: LLMResult) -> dict[str, Any]:
    for gen_list in response.generations or []:
        for gen in gen_list:
            msg = getattr(gen, "message", None)
            usage = getattr(msg, "usage_metadata", None)
            if usage:
                return dict(usage)
    return {}


def extract_llm_metrics(response: LLMResult) -> dict[str, Any]:
    """Extract model/provider/tokens/cost from a LangChain LLMResult (OpenAI-compatible APIs)."""
    llm_output = response.llm_output or {}
    token_usage = llm_output.get("token_usage") or {}
    msg_usage = _usage_from_message(response)

    prompt_tokens = token_usage.get("prompt_tokens", msg_usage.get("input_tokens"))
    completion_tokens = token_usage.get("completion_tokens", msg_usage.get("output_tokens"))

    reasoning_tokens = None
    details = token_usage.get("completion_tokens_details") or {}
    if isinstance(details, dict):
        reasoning_tokens = details.get("reasoning_tokens")
    cached_tokens = None
    pdetails = token_usage.get("prompt_tokens_details") or {}
    if isinstance(pdetails, dict):
        cached_tokens = pdetails.get("cached_tokens")

    # OpenRouter returns the amount charged on OpenRouter credits in `usage.cost`. With BYOK
    # (the account's own provider key), `cost` is only the OpenRouter fee (often 0) and the
    # provider bill is in `cost_details.upstream_inference_cost`. Total = both.
    def _f(value):
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    openrouter_cost = _f(token_usage.get("cost"))
    cost_details = token_usage.get("cost_details") or {}
    upstream_cost = (
        _f(cost_details.get("upstream_inference_cost")) if isinstance(cost_details, dict) else None
    )
    is_byok = bool(token_usage.get("is_byok"))
    cost = openrouter_cost
    if is_byok and upstream_cost is not None:
        cost = (openrouter_cost or 0.0) + upstream_cost

    return {
        "resolved_model": llm_output.get("model_name"),
        "resolved_provider": llm_output.get("provider"),
        "generation_id": llm_output.get("id"),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "reasoning_tokens": reasoning_tokens,
        "cached_tokens": cached_tokens,
        "cost_usd": cost,
        "openrouter_cost_usd": openrouter_cost,
        "upstream_cost_usd": upstream_cost,
        "is_byok": is_byok,
        "finish_reason": _first_generation_info(response).get("finish_reason"),
    }


class BenchmarkLLMCallback(AsyncCallbackHandler):
    """Records one `llm_call` event per model invocation (success or error)."""

    raise_error = False
    run_inline = True

    def __init__(
        self,
        runtime: BenchmarkRuntime,
        *,
        agent: str,
        requested_model: str,
        provider_kind: str,
        is_fallback: bool,
    ):
        super().__init__()
        self.runtime = runtime
        self.agent = agent
        self.requested_model = requested_model
        self.provider_kind = provider_kind
        self.is_fallback = is_fallback
        self._starts: dict[UUID, float] = {}

    async def on_chat_model_start(self, serialized, messages, *, run_id: UUID, **kwargs: Any):
        self._starts[run_id] = time.perf_counter()

    async def on_llm_start(self, serialized, prompts, *, run_id: UUID, **kwargs: Any):
        self._starts[run_id] = time.perf_counter()

    def _elapsed(self, run_id: UUID) -> float:
        start = self._starts.pop(run_id, None)
        return time.perf_counter() - start if start is not None else 0.0

    async def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any):
        latency = self._elapsed(run_id)
        self.runtime.record_llm_call(
            agent=self.agent,
            requested_model=self.requested_model,
            provider_kind=self.provider_kind,
            is_fallback=self.is_fallback,
            latency_s=latency,
            status="ok",
            **extract_llm_metrics(response),
        )

    async def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any):
        latency = self._elapsed(run_id)
        self.runtime.record_llm_call(
            agent=self.agent,
            requested_model=self.requested_model,
            provider_kind=self.provider_kind,
            is_fallback=self.is_fallback,
            latency_s=latency,
            status="error",
            error=f"{type(error).__name__}: {error}",
        )
