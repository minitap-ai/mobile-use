import json

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from minitap.mobile_use.benchmark import runtime as rt
from minitap.mobile_use.benchmark.llm_callback import extract_llm_metrics
from minitap.mobile_use.services.llm import LLMFallbackDisabledError, with_fallback


@pytest.fixture
def runtime(tmp_path):
    def make(allow_fallback=False):
        r = rt.BenchmarkRuntime(
            tmp_path / "events.jsonl", "run-1", rt.LLMPolicy(allow_fallback=allow_fallback, retry_backoff_s=0)
        )
        rt.activate(r)
        return r

    yield make
    rt.deactivate()


def read_events(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


async def _boom():
    raise RuntimeError("upstream 500")


async def _ok():
    return "fallback-result"


@pytest.mark.asyncio
async def test_fallback_blocked_in_benchmark_mode(runtime, tmp_path):
    r = runtime(allow_fallback=False)
    with pytest.raises(LLMFallbackDisabledError):
        await with_fallback(_boom, _ok)
    assert r.fallback_blocked == 1
    ev = read_events(tmp_path / "events.jsonl")
    assert ev[-1]["type"] == "llm_fallback" and ev[-1]["blocked"] is True


@pytest.mark.asyncio
async def test_fallback_logged_when_allowed(runtime, tmp_path):
    r = runtime(allow_fallback=True)
    assert await with_fallback(_boom, _ok) == "fallback-result"
    assert r.fallback_attempts == 1


@pytest.mark.asyncio
async def test_no_runtime_keeps_paper_behaviour():
    assert rt.get_runtime() is None
    assert await with_fallback(_boom, _ok) == "fallback-result"


def test_only_one_active_runtime(runtime, tmp_path):
    runtime()
    with pytest.raises(RuntimeError):
        rt.activate(rt.BenchmarkRuntime(tmp_path / "x.jsonl", "x", rt.LLMPolicy()))


def test_events_and_summary(runtime, tmp_path):
    r = runtime()
    r.record_llm_call(
        agent="cortex",
        requested_model="m",
        provider_kind="openrouter",
        is_fallback=False,
        latency_s=1.5,
        status="ok",
        resolved_model="m-2025",
        resolved_provider="P",
        prompt_tokens=100,
        completion_tokens=10,
        cost_usd=0.01,
    )
    r.record_llm_call(
        agent="cortex",
        requested_model="m",
        provider_kind="openrouter",
        is_fallback=False,
        latency_s=0.5,
        status="error",
        error="boom",
    )
    r.record_tool_call(tool="tap", args={"x": "y" * 5000}, status="success", latency_s=0.2)
    r.record_loop_trigger(
        kind="repeat",
        action="replan",
        evidence="e",
        turn=3,
        subgoal="s",
        details={"state_hash": "a", "action_hash": "b", "action": "collision-safe"},
    )
    r.record_text_check(verdict="MATCH", expected="a", actual="a")
    s = r.summary()
    assert s["llm"]["calls_by_agent"] == {"cortex": 2}
    assert s["llm"]["errors_by_agent"] == {"cortex": 1}
    assert s["llm"]["total_cost_usd"] == 0.01
    assert s["llm"]["resolved_models_by_agent"] == {"cortex": {"m-2025": 1}}
    assert s["loop_detector"] == {"triggers_by_kind": {"repeat": 1}, "forced_replans": 1}
    assert s["text_check"] == {"MATCH": 1}
    ev = read_events(tmp_path / "events.jsonl")
    assert [e["seq"] for e in ev] == [1, 2, 3, 4, 5]
    assert len(ev[2]["args"]["x"]) < 4100  # truncated
    assert {e["type"] for e in ev} == {"llm_call", "tool_call", "loop_detector", "text_check"}


def _result(usage, **llm_output):
    msg = AIMessage(content="x")
    return LLMResult(
        generations=[[ChatGeneration(message=msg, generation_info={"finish_reason": "stop"})]],
        llm_output={"token_usage": usage, **llm_output},
    )


def test_extract_metrics_openrouter_credit_and_byok():
    m = extract_llm_metrics(
        _result(
            {
                "prompt_tokens": 9,
                "completion_tokens": 3,
                "cost": 0.002,
                "completion_tokens_details": {"reasoning_tokens": 1},
            },
            model_name="google/gemini-2.5-pro",
            provider="Google AI Studio",
            id="gen-1",
        )
    )
    assert m["cost_usd"] == 0.002 and m["resolved_provider"] == "Google AI Studio"
    assert m["reasoning_tokens"] == 1 and m["finish_reason"] == "stop"
    byok = extract_llm_metrics(
        _result(
            {
                "prompt_tokens": 9,
                "completion_tokens": 9,
                "cost": 0,
                "is_byok": True,
                "cost_details": {"upstream_inference_cost": 0.0001125},
            },
            model_name="openai/gpt-4o",
        )
    )
    assert byok["cost_usd"] == pytest.approx(0.0001125) and byok["is_byok"] is True
    assert byok["openrouter_cost_usd"] == 0


def test_runner_module_forces_telemetry_off():
    import os

    from minitap.mobile_use.benchmark import runner  # noqa: F401
    from minitap.mobile_use.services.telemetry import telemetry

    assert os.environ["MOBILE_USE_TELEMETRY_ENABLED"] == "false"
    telemetry._config._enabled = False
    assert telemetry.is_enabled is False


@pytest.mark.asyncio
async def test_same_model_retry_recovers_transient_failure(runtime, tmp_path):
    r = runtime(allow_fallback=False)
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise TypeError("'NoneType' object is not iterable")
        return "ok"

    assert await with_fallback(flaky, _ok) == "ok"
    assert calls["n"] == 3 and r.same_model_retries == 2 and r.fallback_blocked == 0
    assert [e["type"] for e in read_events(tmp_path / "events.jsonl")] == ["llm_retry", "llm_retry"]
