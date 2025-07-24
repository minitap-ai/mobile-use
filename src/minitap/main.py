import asyncio
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import typer
from langchain_core.messages import AIMessage
from typing_extensions import Annotated

from minitap.client.adb import adb, get_device
from minitap.constants import RECURSION_LIMIT
from minitap.graph.graph import get_graph
from minitap.graph.state import State
from minitap.utils.media import (
    create_gif_from_trace_folder,
    create_steps_json_from_trace_folder,
    remove_images_from_trace_folder,
    remove_steps_json_from_trace_folder,
)
from minitap.utils.time import convert_timestamp_to_str

print("🔥 Minitap loaded")
app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)


def print_ai_response_to_stderr(graph_result: dict[str, Any]):
    for msg in reversed(graph_result["messages"]):
        if isinstance(msg, AIMessage):
            print(msg.content, file=sys.stderr)
            return


async def run_automation(
    goal: str,
    test_name: Optional[str] = uuid.uuid4().hex[:5].upper(),
    traces_output_path_str: str = "traces",
):
    start_time = time.time()
    traces_output_path = Path(traces_output_path_str).resolve()
    print(f"📂 Traces output path: {traces_output_path}")
    traces_temp_path = Path(__file__).parent.joinpath(f"../traces/{test_name}").resolve()
    print(f"📄📂 Traces temp path: {traces_temp_path}")
    if not adb.device_list():
        print("❌ No Android device found. Please connect a device and enable USB debugging.")
        raise typer.Exit(code=1)
    traces_output_path.mkdir(parents=True, exist_ok=True)
    traces_temp_path.mkdir(parents=True, exist_ok=True)

    device = get_device()
    assert device.serial is not None, "Device serial cannot be None after check."
    trace_id: str | None = None
    if test_name:
        print(f"Recording test with name: {test_name}", flush=True)
        trace_id = test_name

    print(f"Starting graph with goal: {goal}", flush=True)
    graph_input = State(
        initial_goal=goal,
        remaining_steps=RECURSION_LIMIT,
        messages=[],
        is_goal_achieved=False,
        device_id=device.serial,
        latest_ui_hierarchy=None,
        trace_id=trace_id,
        current_subgoal=None,
        subgoal_history=[],
        memory=None,
    ).model_dump()

    success = False
    try:
        print(f"Invoking graph with input: {graph_input}", flush=True)
        result = await (await get_graph()).ainvoke(
            input=graph_input, config={"recursion_limit": RECURSION_LIMIT}
        )

        print_ai_response_to_stderr(graph_result=result)

        print("✅ Test is success ✅")
        success = True
    except Exception as e:
        print(f"❌ Test failed with error: {e} ❌")
        raise
    finally:
        if traces_temp_path and start_time:
            formatted_ts = convert_timestamp_to_str(start_time)
            status = "_PASS" if success else "_FAIL"
            new_name = f"{test_name}{status}_{formatted_ts}"

            print("Compiling trace FROM FOLDER: " + str(traces_temp_path))
            create_gif_from_trace_folder(traces_temp_path)
            create_steps_json_from_trace_folder(traces_temp_path)

            print("Video created, removing dust...")
            remove_images_from_trace_folder(traces_temp_path)
            remove_steps_json_from_trace_folder(traces_temp_path)
            print("📽️ Trace compiled, moving to output path 📽️")

            # moving all the content that is inside the traces folder into the new path
            output_folder_path = traces_temp_path.rename(traces_output_path / new_name)
            print(f"📂✅ Trace folder renamed to: {output_folder_path.name}")

        await asyncio.sleep(1)


@app.command()
def main(
    goal: Annotated[str, typer.Argument(help="The main goal for the AGENT to achieve.")],
    test_name: Annotated[
        Optional[str],
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
):
    """
    Run the Minitap agent to automate tasks on a mobile device.
    """
    asyncio.run(run_automation(goal, test_name, traces_path))


def cli():
    app()


if __name__ == "__main__":
    cli()
