import asyncio
import os
from shutil import which
from typing import Annotated

import typer
from adbutils import AdbClient
from langchain.callbacks.base import Callbacks
from rich.console import Console

from minitap.mobile_use.clients.ios_client_config import (
    IdbClientConfig,
    IosClientConfig,
    WdaClientConfig,
)
from minitap.mobile_use.config import initialize_llm_config, settings
from minitap.mobile_use.sdk import Agent
from minitap.mobile_use.sdk.builders import Builders
from minitap.mobile_use.sdk.types.task import AgentProfile
from minitap.mobile_use.utils.cli_helpers import display_device_status
from minitap.mobile_use.utils.logger import get_logger

app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)
logger = get_logger(__name__)


async def run_automation(
    goal: str,
    locked_app_package: str | None = None,
    test_name: str | None = None,
    traces_output_path_str: str = "traces",
    output_description: str | None = None,
    graph_config_callbacks: Callbacks = [],
    wda_url: str | None = None,
    wda_timeout: float | None = None,
    wda_auto_start_iproxy: bool | None = None,
    wda_auto_start_wda: bool | None = None,
    wda_project_path: str | None = None,
    wda_startup_timeout: float | None = None,
    idb_host: str | None = None,
    idb_port: int | None = None,
):
    llm_config = initialize_llm_config()
    agent_profile = AgentProfile(name="default", llm_config=llm_config)
    config = Builders.AgentConfig.with_default_profile(profile=agent_profile)

    # Build iOS client config from CLI options
    wda_config = WdaClientConfig.with_overrides(
        wda_url=wda_url,
        timeout=wda_timeout,
        auto_start_iproxy=wda_auto_start_iproxy,
        auto_start_wda=wda_auto_start_wda,
        wda_project_path=wda_project_path,
        wda_startup_timeout=wda_startup_timeout,
    )
    idb_config = IdbClientConfig.with_overrides(host=idb_host, port=idb_port)
    config.with_ios_client_config(IosClientConfig(wda=wda_config, idb=idb_config))

    if settings.ADB_HOST:
        config.with_adb_server(host=settings.ADB_HOST, port=settings.ADB_PORT)
    if graph_config_callbacks:
        config.with_graph_config_callbacks(graph_config_callbacks)

    agent: Agent | None = None
    try:
        agent = Agent(config=config.build())
        await agent.init(
            retry_count=int(os.getenv("MOBILE_USE_HEALTH_RETRIES", 5)),
            retry_wait_seconds=int(os.getenv("MOBILE_USE_HEALTH_DELAY", 2)),
        )

        task = agent.new_task(goal)
        if locked_app_package:
            task.with_locked_app_package(locked_app_package)
        if test_name:
            task.with_name(test_name).with_trace_recording(path=traces_output_path_str)
        if output_description:
            task.with_output_description(output_description)

        agent_thoughts_path = os.getenv("EVENTS_OUTPUT_PATH", None)
        llm_result_path = os.getenv("RESULTS_OUTPUT_PATH", None)
        if agent_thoughts_path:
            task.with_thoughts_output_saving(path=agent_thoughts_path)
        if llm_result_path:
            task.with_llm_output_saving(path=llm_result_path)

        await agent.run_task(request=task.build())
    finally:
        if agent is not None:
            await agent.clean()


@app.command()
def main(
    goal: Annotated[str, typer.Argument(help="The main goal for the agent to achieve.")],
    test_name: Annotated[
        str | None,
        typer.Option(
            "--test-name",
            "-n",
            help="A name for the test recording. If provided, a trace will be saved.",
        ),
    ] = None,
    traces_path: Annotated[
        str,
        typer.Option(
            "--traces-path",
            "-p",
            help="The path to save the traces.",
        ),
    ] = "traces",
    output_description: Annotated[
        str | None,
        typer.Option(
            "--output-description",
            "-o",
            help=(
                """
                A dict output description for the agent.
                Ex: a JSON schema with 2 keys: type, price
                """
            ),
        ),
    ] = None,
    wda_url: Annotated[
        str | None,
        typer.Option(
            "--wda-url",
            help="Override WebDriverAgent URL (e.g. http://localhost:8100).",
        ),
    ] = None,
    wda_timeout: Annotated[
        float | None,
        typer.Option(
            "--wda-timeout",
            help="Timeout (seconds) for WDA operations.",
        ),
    ] = None,
    wda_auto_start_iproxy: Annotated[
        bool | None,
        typer.Option(
            "--wda-auto-start-iproxy/--no-wda-auto-start-iproxy",
            help="Auto-start iproxy if not running.",
        ),
    ] = None,
    wda_auto_start_wda: Annotated[
        bool | None,
        typer.Option(
            "--wda-auto-start-wda/--no-wda-auto-start-wda",
            help="Auto-build and run WDA via xcodebuild if not responding.",
        ),
    ] = None,
    wda_project_path: Annotated[
        str | None,
        typer.Option(
            "--wda-project-path",
            help="Path to WebDriverAgent.xcodeproj.",
        ),
    ] = None,
    wda_startup_timeout: Annotated[
        float | None,
        typer.Option(
            "--wda-startup-timeout",
            help="Timeout (seconds) while waiting for WDA to start.",
        ),
    ] = None,
    idb_host: Annotated[
        str | None,
        typer.Option(
            "--idb-host",
            help="IDB companion host (for simulators).",
        ),
    ] = None,
    idb_port: Annotated[
        int | None,
        typer.Option(
            "--idb-port",
            help="IDB companion port (for simulators).",
        ),
    ] = None,
):
    """
    Run the Mobile-use agent to automate tasks on a mobile device.
    """
    console = Console()

    adb_client = None
    try:
        if which("adb"):
            adb_client = AdbClient(
                host=settings.ADB_HOST or "localhost",
                port=settings.ADB_PORT or 5037,
            )
    except Exception:
        pass  # ADB not available, will only support iOS devices

    display_device_status(console, adb_client=adb_client)
    asyncio.run(
        run_automation(
            goal=goal,
            test_name=test_name,
            traces_output_path_str=traces_path,
            output_description=output_description,
            wda_url=wda_url,
            wda_timeout=wda_timeout,
            wda_auto_start_iproxy=wda_auto_start_iproxy,
            wda_auto_start_wda=wda_auto_start_wda,
            wda_project_path=wda_project_path,
            wda_startup_timeout=wda_startup_timeout,
            idb_host=idb_host,
            idb_port=idb_port,
        )
    )


def cli():
    app()


if __name__ == "__main__":
    cli()
