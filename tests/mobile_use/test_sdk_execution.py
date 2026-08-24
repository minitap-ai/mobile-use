import importlib
import sys

import pytest

# A legacy outputter test installs a process-wide module mock during collection.
vertex_module = sys.modules.get("langchain_google_vertexai")
if vertex_module is not None and not hasattr(vertex_module, "__path__"):
    sys.modules.pop("langchain_google_vertexai", None)
    importlib.import_module("langchain_google_vertexai")

from minitap.mobile_use.sdk import Agent  # noqa: E402
from minitap.mobile_use.sdk.builders import Builders  # noqa: E402
from minitap.mobile_use.sdk.types import CloudDevicePlatform, TaskRequest  # noqa: E402


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
