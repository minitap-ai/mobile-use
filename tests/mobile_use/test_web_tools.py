"""Run the maintained dispatcher over real MCP HTTP framing, without network access."""

import asyncio
import json
from typing import cast
from uuid import UUID

import httpx
import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import StreamableHttpConnection
from langgraph.graph import END, START, StateGraph

from minitap.mobile_use.agents.executor.tool_node import ExecutorToolNode
from minitap.mobile_use.config import get_default_llm_config
from minitap.mobile_use.context import DeviceContext, DevicePlatform, MobileUseContext
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.tools import web
from minitap.mobile_use.tools.index import EXECUTOR_WRAPPERS_TOOLS, get_tools_from_wrappers


def make_context(**kwargs):
    return MobileUseContext(
        trace_id="test-task",
        device=DeviceContext(
            host_platform="LINUX",
            mobile_platform=DevicePlatform.ANDROID,
            device_id="test",
            device_width=1080,
            device_height=1920,
        ),
        llm_config=get_default_llm_config(),
        **kwargs,
    )


def make_state(calls=()):
    return State(
        messages=[],
        initial_goal="Find public museum hours and draft a message",
        subgoal_plan=[],
        latest_ui_hierarchy=None,
        latest_screenshot=None,
        focused_app_info=None,
        device_date=None,
        structured_decisions="search",
        complete_subgoals_by_ids=[],
        agents_thoughts=[],
        executor_messages=[AIMessage(content="", tool_calls=list(calls))] if calls else [],
        cortex_last_thought="Look up current hours",
    )


def call(name="web_search", **arguments):
    if name == "web_search":
        arguments = {
            "objective": "Find public opening hours",
            "search_queries": ["museum opening hours"],
            **arguments,
        }
    return {
        "name": name,
        "args": {"agent_thought": "Find current public facts", **arguments},
        "id": f"call-{name}",
        "type": "tool_call",
    }


async def dispatch(ctx, calls):
    builder = StateGraph(State)
    builder.add_node(
        "tools",
        ExecutorToolNode(
            tools=get_tools_from_wrappers(ctx, EXECUTOR_WRAPPERS_TOOLS),
            messages_key="executor_messages",
        ),
    )
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    return await builder.compile().ainvoke(make_state(calls))


@pytest.fixture
def mcp_http(monkeypatch):
    requests = []
    behavior = {"mode": "success"}
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def handle(request):
        requests.append(request)
        assert str(request.url) == web.SEARCH_MCP_URL
        assert (
            request.headers["user-agent"] == "mobile-use (https://github.com/minitap-ai/mobile-use)"
        )
        assert "authorization" not in request.headers
        if request.method != "POST":
            return httpx.Response(405)
        payload = json.loads(request.content)
        method = payload["method"]
        if "id" not in payload:
            return httpx.Response(202)
        if method == "initialize":
            result = {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "test-search", "version": "1"},
            }
        elif method == "tools/list":
            result = {"tools": []}
        else:
            assert method == "tools/call"
            started.set()
            mode = behavior["mode"]
            if mode == "wait":
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            if mode == "transport":
                raise httpx.ConnectError("fixture disconnect", request=request)
            if mode == "empty":
                result = {"content": []}
            elif mode == "error":
                result = {
                    "content": [{"type": "text", "text": "Free anonymous quota reached"}],
                    "isError": True,
                }
            else:
                result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "results": [
                                        {
                                            "url": "https://example.org/museum?day=today",
                                            "excerpts": ["Open 10:00–18:00"],
                                        }
                                    ]
                                }
                            ),
                        }
                    ],
                    "isError": False,
                }
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": result})

    def factory(headers=None, timeout=None, auth=None):
        return httpx.AsyncClient(
            headers=headers, timeout=timeout, auth=auth, transport=httpx.MockTransport(handle)
        )

    connection = cast(StreamableHttpConnection, dict(web._mcp_client.connections["parallel"]))
    connection["httpx_client_factory"] = factory
    monkeypatch.setattr(web, "_mcp_client", MultiServerMCPClient({"parallel": connection}))
    return requests, behavior, started, cancelled


def tool_requests(requests):
    return [
        json.loads(r.content)["params"]
        for r in requests
        if r.method == "POST" and json.loads(r.content).get("method") == "tools/call"
    ]


@pytest.mark.asyncio
async def test_dispatch_search_fetch_followup_and_result_consumption(mcp_http):
    from minitap.mobile_use.agents.cortex.cortex import get_executor_agent_feedback

    requests, _, _, _ = mcp_http
    ctx = make_context()
    # Discovery uses the same project headers as execution.
    async with web._mcp_client.session("parallel") as session:
        await session.list_tools()
    for invocation in [
        call(),
        call("web_fetch", urls=["https://example.org/museum?day=today"]),
        call(objective="Find holiday hours"),
    ]:
        result = await dispatch(ctx, [invocation])
        state = State(**result)
        feedback = get_executor_agent_feedback(state)
        assert "https://example.org/museum?day=today" in feedback
        assert "Open 10:00" in feedback
        assert "Open 10:00" in result["agents_thoughts"][-1]
        assert result["executor_messages"][-1].status == "success"
    calls = tool_requests(requests)
    assert [c["name"] for c in calls] == ["web_search", "web_fetch", "web_search"]
    assert {c["arguments"]["session_id"] for c in calls} == {ctx.web_search_session_id}
    assert calls[1]["arguments"]["urls"] == ["https://example.org/museum?day=today"]
    assert UUID(ctx.web_search_session_id).version == 4


@pytest.mark.asyncio
async def test_interleaved_tasks_and_retry_keep_task_identity(mcp_http):
    requests, behavior, _, _ = mcp_http
    a, b = make_context(), make_context()
    await asyncio.gather(dispatch(a, [call()]), dispatch(b, [call()]))
    behavior["mode"] = "error"
    error = await dispatch(a, [call()])
    assert error["executor_messages"][-1].status == "error"
    behavior["mode"] = "success"
    await asyncio.gather(dispatch(b, [call()]), dispatch(a, [call()]))
    ids = [c["arguments"]["session_id"] for c in tool_requests(requests)]
    assert a.web_search_session_id != b.web_search_session_id
    assert sorted(ids[:2]) == sorted([a.web_search_session_id, b.web_search_session_id])
    assert ids[2] == a.web_search_session_id
    assert sorted(ids[3:]) == sorted([a.web_search_session_id, b.web_search_session_id])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,expected",
    [("error", "quota"), ("transport", "unavailable"), ("empty", "no readable content")],
)
async def test_errors_abort_remaining_calls(mcp_http, mode, expected):
    requests, behavior, _, _ = mcp_http
    behavior["mode"] = mode
    result = await dispatch(
        make_context(), [call(), call("web_fetch", urls=["https://example.org"])]
    )
    messages = [m for m in result["executor_messages"] if isinstance(m, ToolMessage)]
    assert messages[0].status == "error"
    assert expected in messages[0].content
    assert messages[1].content == "Aborted: a previous tool call failed!"
    assert len(tool_requests(requests)) == 1


@pytest.mark.asyncio
async def test_timeout_closes_request(mcp_http, monkeypatch):
    _, behavior, _, cancelled = mcp_http
    behavior["mode"] = "wait"
    monkeypatch.setattr(web, "WEB_TIMEOUT_SECONDS", 0.1)
    result = await dispatch(make_context(), [call()])
    assert result["executor_messages"][-1].status == "error"
    assert "timed out" in result["executor_messages"][-1].content
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_cancellation_propagates_and_closes_request(mcp_http):
    _, behavior, started, cancelled = mcp_http
    behavior["mode"] = "wait"
    task = asyncio.create_task(dispatch(make_context(), [call()]))
    await asyncio.wait_for(started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_disabled_tools_are_absent_and_cannot_connect(mcp_http):
    requests, _, _, _ = mcp_http
    ctx = make_context(web_search_enabled=False)
    names = {t.name for t in get_tools_from_wrappers(ctx, EXECUTOR_WRAPPERS_TOOLS)}
    assert not names & {"web_search", "web_fetch"}
    result = await dispatch(ctx, [call()])
    assert result["executor_messages"][-1].status == "error"
    # Even a tool retained before revoking permission checks the task flag.
    enabled = make_context()
    retained = web.get_web_search_tool(enabled)
    enabled.web_search_enabled = False
    result = await retained.ainvoke({**call(), "args": {**call()["args"], "state": make_state()}})
    assert result.update["executor_messages"][-1].status == "error"
    assert not requests


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.org",
        "https://user:pass@example.org",
        "https://[invalid",
    ],
)
async def test_invalid_urls_do_not_connect(mcp_http, url):
    requests, _, _, _ = mcp_http
    result = await dispatch(make_context(), [call("web_fetch", urls=[url])])
    assert result["executor_messages"][-1].status == "error"
    assert not requests


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_sdk_tasks_use_production_graph_and_fresh_sessions(mcp_http, monkeypatch, enabled):
    """Script model decisions and device perception; retain real SDK/graph/tool paths."""
    from unittest.mock import AsyncMock

    from minitap.mobile_use.agents.cortex import cortex as cortex_module
    from minitap.mobile_use.agents.cortex.types import CortexOutput
    from minitap.mobile_use.agents.executor import executor as executor_module
    from minitap.mobile_use.agents.planner.types import Subgoal, SubgoalStatus
    from minitap.mobile_use.graph import graph as graph_module
    from minitap.mobile_use.sdk import Agent
    from minitap.mobile_use.sdk.builders import Builders

    requests, _, _, _ = mcp_http
    contexts = []
    bound_tools = []

    class Planner:
        def __init__(self, ctx):
            contexts.append(ctx)

        async def __call__(self, state):
            return {
                "subgoal_plan": [
                    Subgoal(id="hours", description="Find hours", status=SubgoalStatus.PENDING)
                ]
            }

    class Orchestrator:
        def __init__(self, ctx):
            pass

        async def __call__(self, state):
            if state.complete_subgoals_by_ids:
                return {
                    "subgoal_plan": [
                        Subgoal(id="hours", description="Find hours", status=SubgoalStatus.SUCCESS)
                    ]
                }
            return {}

    class Contextor:
        def __init__(self, ctx):
            pass

        async def __call__(self, state):
            return {}

    class ScriptedCortex:
        def with_structured_output(self, schema):
            return self

        async def ainvoke(self, messages):
            available = messages[0].content.split("Available tools: ")[1].split("\n")[0]
            assert ("web_search" in available) is enabled
            if not enabled or "Open 10:00" in messages[0].content:
                if enabled:
                    assert "https://example.org/museum?day=today" in messages[0].content
                return CortexOutput(
                    complete_subgoals_by_ids=["hours"], goals_completion_reason="Observed result"
                )
            return CortexOutput(
                decisions=json.dumps(call()["args"]), decisions_reason="Find public facts"
            )

    class ScriptedExecutor:
        def bind_tools(self, **kwargs):
            names = {t.name for t in kwargs["tools"]}
            assert {"web_search", "web_fetch"} <= names
            bound_tools.append(names)
            return self

        async def ainvoke(self, messages):
            return AIMessage(content="", tool_calls=[call()])

    monkeypatch.setattr(graph_module, "PlannerNode", Planner)
    monkeypatch.setattr(graph_module, "OrchestratorNode", Orchestrator)
    monkeypatch.setattr(graph_module, "ContextorNode", Contextor)
    monkeypatch.setattr(cortex_module, "get_llm", lambda **kwargs: ScriptedCortex())
    monkeypatch.setattr(executor_module, "get_llm", lambda **kwargs: ScriptedExecutor())
    config = Builders.AgentConfig.with_web_search(enabled).build(validate_profiles=False)
    agent = Agent(config=config)
    agent._initialized = True
    agent._device_context = make_context().device
    agent._adb_client = None
    agent._ui_adb_client = None
    agent._ios_client = None
    for name in ["_prepare_app_installation", "_prepare_app_lock", "_finalize_tracing"]:
        monkeypatch.setattr(agent, name, AsyncMock())
    for name in ["_prepare_tracing", "_prepare_output_files"]:
        monkeypatch.setattr(agent, name, lambda **kwargs: None)
    monkeypatch.setattr(agent, "_extract_output", AsyncMock(return_value="completed"))
    for _ in range(2):
        assert await agent.run_task(goal="Find museum hours") == "completed"
    assert len(contexts) == 2
    assert contexts[0].web_search_session_id != contexts[1].web_search_session_id
    assert all(ctx.web_search_enabled is enabled for ctx in contexts)
    calls = tool_requests(requests)
    if enabled:
        assert [c["arguments"]["session_id"] for c in calls] == [
            ctx.web_search_session_id for ctx in contexts
        ]
        assert len(bound_tools) == 4  # Primary and fallback model bindings for each task.
    else:
        assert not requests
        assert not bound_tools


def test_environment_defaults_saved_choices_and_explicit_overrides(monkeypatch):
    from minitap.mobile_use.config import Settings, settings
    from minitap.mobile_use.sdk.builders import Builders
    from minitap.mobile_use.sdk.types.agent import AgentConfig

    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.delenv("MOBILE_USE_WEB_SEARCH_ENABLED", raising=False)
    assert Settings().MOBILE_USE_WEB_SEARCH_ENABLED is True
    monkeypatch.setenv("MOBILE_USE_WEB_SEARCH_ENABLED", "false")
    assert Settings().MOBILE_USE_WEB_SEARCH_ENABLED is False
    monkeypatch.setattr(settings, "MOBILE_USE_WEB_SEARCH_ENABLED", False)
    disabled = Builders.AgentConfig.build(validate_profiles=False)
    assert disabled.web_search_enabled is False
    enabled = Builders.AgentConfig.with_web_search(True).build(validate_profiles=False)
    assert enabled.web_search_enabled is True
    assert enabled.default_profile.llm_config == disabled.default_profile.llm_config
    # Persisted SDK configuration keeps explicit choices under a changed default.
    saved = disabled.model_dump()
    monkeypatch.setattr(settings, "MOBILE_USE_WEB_SEARCH_ENABLED", True)
    assert AgentConfig.model_validate(saved).web_search_enabled is False
    assert (
        Builders.AgentConfig.with_web_search(False)
        .build(validate_profiles=False)
        .web_search_enabled
        is False
    )
