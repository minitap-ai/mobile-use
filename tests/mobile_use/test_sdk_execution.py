import importlib
import sys
from unittest.mock import AsyncMock

import pytest

# A legacy outputter test installs a process-wide module mock during collection.
vertex_module = sys.modules.get("langchain_google_vertexai")
if vertex_module is not None and not hasattr(vertex_module, "__path__"):
    sys.modules.pop("langchain_google_vertexai", None)
    importlib.import_module("langchain_google_vertexai")

from minitap.mobile_use.sdk import Agent  # noqa: E402
from minitap.mobile_use.sdk.builders import Builders  # noqa: E402
from minitap.mobile_use.sdk.types import (  # noqa: E402
    CloudDevicePlatform,
    DevicePlatform,
    PocoConfig,
    Task,
    TaskRequest,
)
from minitap.mobile_use.context import DeviceContext, MobileUseContext  # noqa: E402


@pytest.mark.asyncio
async def test_cloud_device_tasks_run_through_local_agent(monkeypatch):
    config = Builders.AgentConfig.for_cloud_device(CloudDevicePlatform.ANDROID).build(
        validate_profiles=False
    )
    agent = Agent(config=config)
    captured_request = None

    async def run_locally(request: TaskRequest):
        nonlocal captured_request
        captured_request = request
        return "completed"

    monkeypatch.setattr(agent, "_run_task", run_locally)

    result = await agent.run_task(goal="Open settings")

    assert result == "completed"
    assert captured_request is not None
    assert captured_request.goal == "Open settings"


@pytest.mark.asyncio
async def test_request_overrides_are_applied_before_local_execution(monkeypatch):
    agent = Agent(config=Builders.AgentConfig.build(validate_profiles=False))
    request = agent.new_task("Open settings").with_locked_app_package("original.app").build()
    captured_request = None

    async def run_locally(request: TaskRequest):
        nonlocal captured_request
        captured_request = request
        return "completed"

    monkeypatch.setattr(agent, "_run_task", run_locally)

    await agent.run_task(request=request, locked_app_package="override.app")

    assert captured_request is request
    assert captured_request is not None
    assert captured_request.locked_app_package == "override.app"


@pytest.mark.parametrize("selection", ["unspecified", "ios", "cloud"])
def test_poco_configuration_requires_explicit_local_android(selection):
    builder = Builders.AgentConfig.with_poco_hierarchy(PocoConfig(package_name="com.example.game"))
    if selection == "ios":
        builder.for_device(DevicePlatform.IOS, "simulator")
    elif selection == "cloud":
        builder.for_cloud_device(CloudDevicePlatform.ANDROID)
    with pytest.raises(ValueError, match="explicitly selected local Android device"):
        builder.build(validate_profiles=False)


class ContextCaptured(Exception):
    pass


@pytest.mark.asyncio
async def test_poco_config_reaches_task_context(monkeypatch):
    poco = PocoConfig(package_name="com.example.game", port=5002)
    config = (
        Builders.AgentConfig.for_device(DevicePlatform.ANDROID, "game-device")
        .with_poco_hierarchy(poco)
        .build(validate_profiles=False)
    )
    assert config.poco_config == poco
    agent = Agent(config=config)
    agent._initialized = True
    agent._adb_client = None
    agent._ui_adb_client = None
    agent._ios_client = None
    agent._device_context = DeviceContext(
        host_platform="LINUX",
        mobile_platform=DevicePlatform.ANDROID,
        device_id="game-device",
        device_width=1000,
        device_height=500,
    )
    contexts: list[MobileUseContext] = []

    def capture_context(task: Task, context: MobileUseContext):
        contexts.append(context)
        raise ContextCaptured()

    monkeypatch.setattr(agent, "_prepare_tracing", capture_context)
    with pytest.raises(ContextCaptured):
        await agent.run_task(goal="Tap Play")
    assert len(contexts) == 1
    assert contexts[0].poco_client is agent._poco_client
    assert contexts[0].poco_client is not None
    assert contexts[0].poco_client.config == poco
    assert contexts[0].device.device_id == "game-device"


@pytest.mark.asyncio
@pytest.mark.parametrize("initialized", [False, True])
async def test_cleanup_closes_shared_poco_client(monkeypatch, initialized):
    config = (
        Builders.AgentConfig.for_device(DevicePlatform.ANDROID, "game-device")
        .with_poco_hierarchy(PocoConfig(package_name="com.example.game"))
        .build(validate_profiles=False)
    )
    agent = Agent(config=config)
    agent._initialized = initialized
    agent._ios_client = None
    assert agent._poco_client is not None
    close = AsyncMock()
    monkeypatch.setattr(agent._poco_client, "close", close)
    await agent.clean()
    close.assert_awaited_once()
