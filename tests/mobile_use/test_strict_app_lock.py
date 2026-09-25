import importlib
import sys
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import ToolMessage

# A legacy outputter test installs a process-wide module mock during collection.
vertex_module = sys.modules.get("langchain_google_vertexai")
if vertex_module is not None and not hasattr(vertex_module, "__path__"):
    sys.modules.pop("langchain_google_vertexai", None)
    importlib.import_module("langchain_google_vertexai")

from minitap.mobile_use.agents.contextor.contextor import ContextorNode  # noqa: E402
from minitap.mobile_use.agents.executor.tool_node import ExecutorToolNode  # noqa: E402
from minitap.mobile_use.context import AppLaunchResult, MobileUseContext  # noqa: E402
from minitap.mobile_use.graph.state import State  # noqa: E402
from minitap.mobile_use.sdk.agent import Agent  # noqa: E402
from minitap.mobile_use.sdk.types.exceptions import AppLockViolationError  # noqa: E402
from minitap.mobile_use.tools.mobile.launch_app import get_launch_app_tool  # noqa: E402
from minitap.mobile_use.tools.mobile.open_link import get_open_link_tool  # noqa: E402
from minitap.mobile_use.tools.mobile.press_key import Key, get_press_key_tool  # noqa: E402
from minitap.mobile_use.utils.app_launch_utils import (  # noqa: E402
    assert_strict_app_launch_allowed,
    enforce_strict_app_lock,
)


def _strict_context() -> MobileUseContext:
    return cast(
        MobileUseContext,
        SimpleNamespace(
            execution_setup=SimpleNamespace(
                app_lock_status=AppLaunchResult(
                    locked_app_package="com.example.approved",
                    locked_app_initial_launch_success=True,
                    locked_app_initial_launch_error=None,
                    app_lock_policy="strict",
                )
            )
        ),
    )


class _ToolState:
    async def asanitize_update(self, *, update, **_kwargs):
        return update


@pytest.mark.asyncio
async def test_strict_lock_never_asks_llm_to_allow_a_mismatched_app(monkeypatch):
    node = ContextorNode(_strict_context())
    state = cast(
        State,
        SimpleNamespace(
            initial_goal="Stay in the approved app", subgoal_plan=[], agents_thoughts=[]
        ),
    )
    relaunched = False

    async def fake_relaunch(*_args, **_kwargs):
        nonlocal relaunched
        relaunched = True
        return True, None

    async def llm_must_not_run(*_args, **_kwargs):
        raise AssertionError("strict app lock must not delegate a violation to the LLM")

    import minitap.mobile_use.agents.contextor.contextor as contextor_module

    monkeypatch.setattr(contextor_module, "launch_app_with_retries", fake_relaunch)
    monkeypatch.setattr(node, "_invoke_contextor_llm", llm_must_not_run)

    result = await node._handle_app_lock_verification(
        state=state,
        current_app_package="com.example.unapproved",
        locked_app_package="com.example.approved",
    )

    assert relaunched is True
    assert result.status == "relaunched"


@pytest.mark.asyncio
async def test_strict_lock_fails_when_the_approved_app_cannot_be_restored(monkeypatch):
    node = ContextorNode(_strict_context())
    state = cast(
        State,
        SimpleNamespace(
            initial_goal="Stay in the approved app", subgoal_plan=[], agents_thoughts=[]
        ),
    )

    async def failed_relaunch(*_args, **_kwargs):
        return False, "foreground verification failed"

    import minitap.mobile_use.agents.contextor.contextor as contextor_module

    monkeypatch.setattr(contextor_module, "launch_app_with_retries", failed_relaunch)

    with pytest.raises(AppLockViolationError, match="could not restore"):
        await node._handle_app_lock_verification(
            state=state,
            current_app_package="com.example.unapproved",
            locked_app_package="com.example.approved",
        )


@pytest.mark.asyncio
async def test_strict_lock_fails_closed_when_foreground_app_is_unknown(monkeypatch):
    node = ContextorNode(_strict_context())

    class FakeDeviceController:
        async def get_screen_data(self):
            return SimpleNamespace(elements=[], base64="", width=1, height=1)

    async def no_foreground_app(_ctx):
        return None

    import minitap.mobile_use.agents.contextor.contextor as contextor_module

    monkeypatch.setattr(
        contextor_module, "create_device_controller", lambda _ctx: FakeDeviceController()
    )
    monkeypatch.setattr(contextor_module, "get_current_foreground_package_async", no_foreground_app)
    monkeypatch.setattr(contextor_module, "get_device_date", lambda _ctx: None)

    with pytest.raises(AppLockViolationError, match="foreground app is unknown"):
        await node(SimpleNamespace())


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["relaunch", "verification"])
async def test_strict_lock_never_reads_screen_after_a_verification_exception(
    monkeypatch, failure_stage
):
    node = ContextorNode(_strict_context())
    screen_read = AsyncMock(return_value=SimpleNamespace(elements=[], base64="", width=1, height=1))
    controller_failure = RuntimeError("device controller failed")
    foreground_reads = 0

    async def foreground(_ctx):
        nonlocal foreground_reads
        foreground_reads += 1
        if foreground_reads > 1:
            raise controller_failure
        return "com.example.unapproved"

    async def relaunch(*_args, **_kwargs):
        if failure_stage == "relaunch":
            raise controller_failure
        return True, None

    import minitap.mobile_use.agents.contextor.contextor as contextor_module

    monkeypatch.setattr(
        contextor_module,
        "create_device_controller",
        lambda _ctx: SimpleNamespace(get_screen_data=screen_read),
    )
    monkeypatch.setattr(contextor_module, "get_current_foreground_package_async", foreground)
    monkeypatch.setattr(contextor_module, "get_device_date", lambda _ctx: None)
    monkeypatch.setattr(contextor_module, "launch_app_with_retries", relaunch)

    with pytest.raises(AppLockViolationError, match="Could not verify strict app lock") as caught:
        await node(_ToolState())

    assert caught.value.__cause__ is controller_failure
    screen_read.assert_not_awaited()


@pytest.mark.asyncio
async def test_initial_strict_lock_failure_stops_before_the_graph(monkeypatch):
    task = SimpleNamespace(
        request=SimpleNamespace(
            locked_app_package="com.example.approved",
            app_lock_policy="strict",
        ),
        get_name=lambda: "strict-lock-test",
    )
    context = SimpleNamespace(execution_setup=None)

    async def failed_initial_launch(**_kwargs):
        return AppLaunchResult(
            locked_app_package="com.example.approved",
            locked_app_initial_launch_success=False,
            locked_app_initial_launch_error="launch command failed",
            app_lock_policy="strict",
        )

    import minitap.mobile_use.sdk.agent as agent_module

    monkeypatch.setattr(agent_module, "_handle_initial_app_launch", failed_initial_launch)

    with pytest.raises(AppLockViolationError, match="could not launch"):
        await Agent._prepare_app_lock(SimpleNamespace(), task, context)  # type: ignore

    assert context.execution_setup.app_lock_status.app_lock_policy == "strict"


@pytest.mark.asyncio
async def test_strict_lock_requires_an_explicit_app_package():
    task = SimpleNamespace(
        request=SimpleNamespace(locked_app_package=None, app_lock_policy="strict"),
        get_name=lambda: "strict-lock-test",
    )

    with pytest.raises(AppLockViolationError, match="requires a locked_app_package"):
        await Agent._prepare_app_lock(
            SimpleNamespace(),  # type: ignore
            task,  # type: ignore
            SimpleNamespace(execution_setup=None),  # type: ignore
        )


def test_strict_lock_refuses_an_executor_launch_of_another_package():
    with pytest.raises(AppLockViolationError, match="only allows"):
        assert_strict_app_launch_allowed(_strict_context(), "com.example.other")


@pytest.mark.asyncio
async def test_post_action_strict_check_restores_the_approved_foreground_app(monkeypatch):
    ctx = _strict_context()
    observed_packages = iter(["com.example.other", "com.example.approved"])
    launches = []

    async def fake_foreground(_ctx):
        return next(observed_packages)

    async def fake_relaunch(_ctx, app_package):
        launches.append(app_package)
        return True, None

    import minitap.mobile_use.utils.app_launch_utils as app_launch_utils

    monkeypatch.setattr(app_launch_utils, "get_current_foreground_package_async", fake_foreground)
    monkeypatch.setattr(app_launch_utils, "launch_app_with_retries", fake_relaunch)

    restored = await enforce_strict_app_lock(ctx)

    assert restored is True
    assert launches == ["com.example.approved"]


@pytest.mark.asyncio
async def test_post_action_strict_check_fails_closed_if_foreground_is_unknown(monkeypatch):
    async def no_foreground_app(_ctx):
        return None

    import minitap.mobile_use.utils.app_launch_utils as app_launch_utils

    monkeypatch.setattr(app_launch_utils, "get_current_foreground_package_async", no_foreground_app)

    with pytest.raises(AppLockViolationError, match="foreground app is unknown"):
        await enforce_strict_app_lock(_strict_context())


@pytest.mark.asyncio
async def test_executor_enforces_the_strict_lock_after_a_tool_and_aborts_the_batch(monkeypatch):
    """A foreground violation must prevent the next LLM-requested tool call."""

    node = ExecutorToolNode(
        tools=[],
        messages_key="executor_messages",
        ctx=_strict_context(),
    )
    calls_run: list[str] = []
    checks_run = 0

    async def run_one(call, *_args):
        calls_run.append(call["id"])
        return ToolMessage(content="done", tool_call_id=call["id"], status="success")

    async def lock_violation(_ctx):
        nonlocal checks_run
        checks_run += 1
        if checks_run == 1:
            return False
        raise AppLockViolationError("foreground package changed")

    tool_calls = [
        {"name": "tap", "args": {}, "id": "call-1", "type": "tool_call"},
        {"name": "tap", "args": {}, "id": "call-2", "type": "tool_call"},
    ]
    monkeypatch.setattr(node, "_parse_input", lambda _input: (tool_calls, "dict"))
    monkeypatch.setattr(node, "_build_tool_runtime", lambda *_args: None)
    monkeypatch.setattr(node, "_arun_one", run_one)
    monkeypatch.setattr(node, "_combine_tool_outputs", lambda outputs, _input_type: outputs)

    import minitap.mobile_use.agents.executor.tool_node as tool_node_module

    monkeypatch.setattr(tool_node_module, "enforce_strict_app_lock", lock_violation)

    with pytest.raises(AppLockViolationError, match="foreground package changed"):
        await node._ExecutorToolNode__func(  # type: ignore
            is_async=True,
            input={},
            config=SimpleNamespace(),
            runtime=SimpleNamespace(),
        )

    assert calls_run == ["call-1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("is_async", [True, False])
async def test_executor_rejects_unverified_foreground_before_first_tool(monkeypatch, is_async):
    node = ExecutorToolNode(
        tools=[],
        messages_key="executor_messages",
        ctx=_strict_context(),
    )
    calls_run: list[str] = []

    def run_one(call, *_args):
        calls_run.append(call["id"])
        return ToolMessage(content="done", tool_call_id=call["id"], status="success")

    async def arun_one(call, *_args):
        return run_one(call)

    async def lock_violation(_ctx):
        raise AppLockViolationError("foreground app is unknown")

    tool_calls = [{"name": "tap", "args": {}, "id": "call-1", "type": "tool_call"}]
    monkeypatch.setattr(node, "_parse_input", lambda _input: (tool_calls, "dict"))
    monkeypatch.setattr(node, "_build_tool_runtime", lambda *_args: None)
    monkeypatch.setattr(node, "_arun_one", arun_one)
    monkeypatch.setattr(node, "_run_one", run_one)

    import minitap.mobile_use.agents.executor.tool_node as tool_node_module

    monkeypatch.setattr(tool_node_module, "enforce_strict_app_lock", lock_violation)

    with pytest.raises(AppLockViolationError, match="foreground app is unknown"):
        await node._ExecutorToolNode__func(  # type: ignore
            is_async=is_async,
            input={},
            config=SimpleNamespace(),
            runtime=SimpleNamespace(),
        )

    assert calls_run == []


@pytest.mark.asyncio
async def test_strict_lock_blocks_deep_links_before_the_operating_system_can_route_them():
    tool = get_open_link_tool(_strict_context())

    result = await tool.coroutine(  # type: ignore
        agent_thought="Open the account recovery link",
        url="https://example.test/recovery",
        tool_call_id="call-1",
        state=_ToolState(),
    )

    message = result.update["executor_messages"][-1]
    assert message.status == "error"
    assert "Strict app lock blocks deep links" in message.additional_kwargs["error"]


@pytest.mark.asyncio
async def test_strict_lock_tells_the_executor_why_home_was_blocked(monkeypatch):
    import minitap.mobile_use.tools.mobile.press_key as press_key_module

    monkeypatch.setattr(press_key_module, "UnifiedMobileController", lambda _ctx: None)
    tool = get_press_key_tool(_strict_context())

    result = await tool.coroutine(  # type: ignore
        agent_thought="Go home",
        key=Key.HOME,
        tool_call_id="call-3",
        state=_ToolState(),
    )

    message = result.update["executor_messages"][-1]
    assert message.status == "error"
    assert "Strict app lock blocks the Home key" in message.additional_kwargs["error"]


@pytest.mark.asyncio
async def test_strict_lock_blocks_executor_launch_of_another_package(monkeypatch):
    import minitap.mobile_use.tools.mobile.launch_app as launch_app_module

    async def find_unapproved_package(*_args, **_kwargs):
        return "com.example.unapproved"

    async def launch_must_not_run(*_args, **_kwargs):
        raise AssertionError("strict lock must block this launch before device access")

    monkeypatch.setattr(launch_app_module, "find_package", find_unapproved_package)
    monkeypatch.setattr(launch_app_module, "launch_app_with_retries", launch_must_not_run)
    tool = get_launch_app_tool(_strict_context())

    result = await tool.coroutine(  # type: ignore
        app_name="Unapproved app",
        agent_thought="Open another app",
        tool_call_id="call-2",
        state=_ToolState(),
    )

    message = result.update["executor_messages"][-1]
    assert message.status == "error"
    assert "Strict app lock only allows" in message.additional_kwargs["error"]
