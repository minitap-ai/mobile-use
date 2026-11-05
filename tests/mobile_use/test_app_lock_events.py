import importlib
import json
import sys
from types import SimpleNamespace
from typing import cast

import pytest

# A legacy outputter test installs a process-wide module mock during collection.
vertex_module = sys.modules.get("langchain_google_vertexai")
if vertex_module is not None and not hasattr(vertex_module, "__path__"):
    sys.modules.pop("langchain_google_vertexai", None)
    importlib.import_module("langchain_google_vertexai")

from minitap.mobile_use.context import (  # noqa: E402
    AppLaunchResult,
    AppLockPolicy,
    MobileUseContext,
)
from minitap.mobile_use.sdk.types.exceptions import AppLockViolationError  # noqa: E402
from minitap.mobile_use.tools.mobile.launch_app import get_launch_app_tool  # noqa: E402
from minitap.mobile_use.tools.mobile.open_link import get_open_link_tool  # noqa: E402
from minitap.mobile_use.tools.mobile.press_key import Key, get_press_key_tool  # noqa: E402
from minitap.mobile_use.tools.mobile.stop_app import get_stop_app_tool  # noqa: E402
from minitap.mobile_use.utils.app_launch_utils import enforce_strict_app_lock  # noqa: E402
from minitap.mobile_use.utils.app_lock_events import record_app_lock_event  # noqa: E402


def _context(policy: AppLockPolicy = "strict") -> MobileUseContext:
    return cast(
        MobileUseContext,
        SimpleNamespace(
            execution_setup=SimpleNamespace(
                app_lock_status=AppLaunchResult(
                    locked_app_package="com.example.approved",
                    locked_app_initial_launch_success=True,
                    locked_app_initial_launch_error=None,
                    app_lock_policy=policy,
                )
            )
        ),
    )


class _ToolState:
    async def asanitize_update(self, *, update, **_kwargs):
        return update


def _records(path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def events_path(tmp_path, monkeypatch):
    path = tmp_path / "app-lock-events.jsonl"
    monkeypatch.setenv("APP_LOCK_EVENTS_PATH", str(path))
    return path


def test_nothing_is_written_without_an_events_path(tmp_path, monkeypatch):
    monkeypatch.delenv("APP_LOCK_EVENTS_PATH", raising=False)
    monkeypatch.chdir(tmp_path)

    record_app_lock_event(
        locked_app_package="com.example.approved",
        action="press_key",
        decision="blocked",
        reason="home_key",
    )

    assert list(tmp_path.iterdir()) == []


def test_a_write_failure_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_LOCK_EVENTS_PATH", str(tmp_path))  # a directory, not a file

    record_app_lock_event(
        locked_app_package="com.example.approved",
        action="press_key",
        decision="blocked",
        reason="home_key",
    )


@pytest.mark.asyncio
async def test_blocked_launch_records_the_requested_package(events_path, monkeypatch):
    import minitap.mobile_use.tools.mobile.launch_app as launch_app_module

    async def find_unapproved_package(*_args, **_kwargs):
        return "com.android.settings"

    monkeypatch.setattr(launch_app_module, "find_package", find_unapproved_package)
    tool = get_launch_app_tool(_context())

    await tool.coroutine(  # type: ignore
        app_name="Settings",
        agent_thought="Open settings",
        tool_call_id="call-1",
        state=_ToolState(),
    )

    [record] = _records(events_path)
    assert record["action"] == "launch_app"
    assert record["decision"] == "blocked"
    assert record["reason"] == "launch_other_app"
    assert record["target_package"] == "com.android.settings"
    assert record["locked_app_package"] == "com.example.approved"
    assert record["policy"] == "strict"


@pytest.mark.asyncio
async def test_blocked_deep_link_never_records_the_url(events_path):
    tool = get_open_link_tool(_context())

    await tool.coroutine(  # type: ignore
        agent_thought="Open the recovery link",
        url="https://example.test/recovery?token=secret-value",
        tool_call_id="call-1",
        state=_ToolState(),
    )

    raw = events_path.read_text(encoding="utf-8")
    assert "example.test" not in raw
    assert "secret-value" not in raw
    [record] = _records(events_path)
    assert (record["action"], record["decision"], record["reason"]) == (
        "open_link",
        "blocked",
        "os_routed_deep_link",
    )


@pytest.mark.asyncio
async def test_blocked_stop_app_and_home_key_are_recorded(events_path, monkeypatch):
    import minitap.mobile_use.tools.mobile.press_key as press_key_module

    monkeypatch.setattr(press_key_module, "UnifiedMobileController", lambda _ctx: None)
    await get_stop_app_tool(_context()).coroutine(  # type: ignore
        agent_thought="Close the app",
        package_name="com.example.approved",
        tool_call_id="call-1",
        state=_ToolState(),
    )
    await get_press_key_tool(_context()).coroutine(  # type: ignore
        agent_thought="Go home",
        key=Key.HOME,
        tool_call_id="call-2",
        state=_ToolState(),
    )

    assert [(r["action"], r["reason"]) for r in _records(events_path)] == [
        ("stop_app", "stop_app"),
        ("press_key", "home_key"),
    ]


@pytest.mark.asyncio
async def test_permissive_lock_records_nothing(events_path, monkeypatch):
    tool = get_open_link_tool(_context(policy="permissive"))
    import minitap.mobile_use.tools.mobile.open_link as open_link_module

    class FakeController:
        def __init__(self, _ctx):
            pass

        async def open_url(self, _url):
            return True

    monkeypatch.setattr(open_link_module, "UnifiedMobileController", FakeController)

    await tool.coroutine(  # type: ignore
        agent_thought="Open a link",
        url="https://example.test",
        tool_call_id="call-1",
        state=_ToolState(),
    )

    assert _records(events_path) == []


@pytest.mark.asyncio
async def test_foreground_restore_is_recorded_with_the_observed_package(events_path, monkeypatch):
    observed = iter(["com.android.settings", "com.example.approved"])

    async def fake_foreground(_ctx):
        return next(observed)

    async def fake_relaunch(_ctx, app_package):
        return True, None

    import minitap.mobile_use.utils.app_launch_utils as app_launch_utils

    monkeypatch.setattr(app_launch_utils, "get_current_foreground_package_async", fake_foreground)
    monkeypatch.setattr(app_launch_utils, "launch_app_with_retries", fake_relaunch)

    assert await enforce_strict_app_lock(_context()) is True

    [record] = _records(events_path)
    assert (record["decision"], record["reason"], record["target_package"]) == (
        "restored",
        "foreground_mismatch",
        "com.android.settings",
    )


@pytest.mark.asyncio
async def test_failed_restore_is_recorded_as_an_abort(events_path, monkeypatch):
    async def fake_foreground(_ctx):
        return "com.android.settings"

    async def failed_relaunch(_ctx, app_package):
        return False, "launch failed"

    import minitap.mobile_use.utils.app_launch_utils as app_launch_utils

    monkeypatch.setattr(app_launch_utils, "get_current_foreground_package_async", fake_foreground)
    monkeypatch.setattr(app_launch_utils, "launch_app_with_retries", failed_relaunch)

    with pytest.raises(AppLockViolationError, match="could not restore"):
        await enforce_strict_app_lock(_context())

    [record] = _records(events_path)
    assert (record["decision"], record["reason"]) == ("aborted", "restore_failed")
