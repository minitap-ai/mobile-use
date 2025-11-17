import re
import time
import uuid
from enum import Enum

import yaml
from adbutils import AdbClient
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field
from requests import JSONDecodeError

from minitap.mobile_use.clients.device_hardware_client import DeviceHardwareClient
from minitap.mobile_use.clients.screen_api_client import ScreenApiClient
from minitap.mobile_use.config import initialize_llm_config
from minitap.mobile_use.context import DeviceContext, DevicePlatform, MobileUseContext
from minitap.mobile_use.controllers.types import (
    Bounds,
    CoordinatesSelectorRequest,
    PercentagesSelectorRequest,
    SwipeRequest,
    SwipeStartEndCoordinatesRequest,
    SwipeStartEndPercentagesRequest,
    TapOutput,
)
from minitap.mobile_use.utils.errors import ControllerErrors
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


def _get_adb_device(ctx: MobileUseContext):
    """Get ADB device object from the client."""
    if ctx.adb_client is None:
        raise ValueError("ADB client is not initialized")
    return ctx.adb_client.device(serial=ctx.device.device_id)


###### Screen elements retrieval ######


class ScreenDataResponse(BaseModel):
    base64: str
    elements: list
    width: int
    height: int
    platform: str


def get_screen_data(screen_api_client: ScreenApiClient):
    response = screen_api_client.get_with_retry("/screen-info")
    return ScreenDataResponse(**response.json())


def take_screenshot(ctx: MobileUseContext):
    return get_screen_data(ctx.screen_api_client).base64


class RunFlowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    yaml: str
    dry_run: bool = Field(default=False, alias="dryRun")


def run_flow(ctx: MobileUseContext, flow_steps: list, dry_run: bool = False) -> dict | None:
    """
    Run a flow i.e, a sequence of commands.
    Returns None on success, or the response body of the failed command.
    """
    logger.info(f"Running flow: {flow_steps}")

    for step in flow_steps:
        step_yml = yaml.dump(step)
        payload = RunFlowRequest(yaml=step_yml, dryRun=dry_run).model_dump(by_alias=True)
        response = ctx.hw_bridge_client.post("run-command", json=payload)

        try:
            response_body = response.json()
        except JSONDecodeError:
            response_body = response.text

        if isinstance(response_body, dict):
            response_body = {k: v for k, v in response_body.items() if v is not None}

        if response.status_code >= 300:
            logger.error(f"Tool call failed with status code: {response.status_code}")
            return {"status_code": response.status_code, "body": response_body}

    logger.success("Tool call completed")
    return None


class IdSelectorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str

    def to_dict(self) -> dict[str, str | int]:
        return {"id": self.id}


# Useful to tap on an element when there are multiple views with the same id
class IdWithTextSelectorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    text: str

    def to_dict(self) -> dict[str, str | int]:
        return {"id": self.id, "text": self.text}


class TextSelectorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str

    def to_dict(self) -> dict[str, str | int]:
        return {"text": self.text}


class SelectorRequestWithCoordinates(BaseModel):
    model_config = ConfigDict(extra="forbid")
    coordinates: CoordinatesSelectorRequest

    def to_dict(self) -> dict[str, str | int]:
        return {"point": self.coordinates.to_str()}


class SelectorRequestWithPercentages(BaseModel):
    model_config = ConfigDict(extra="forbid")
    percentages: PercentagesSelectorRequest

    def to_dict(self) -> dict[str, str | int]:
        return {"point": self.percentages.to_str()}


SelectorRequest = (
    IdSelectorRequest
    | SelectorRequestWithCoordinates
    | SelectorRequestWithPercentages
    | TextSelectorRequest
    | IdWithTextSelectorRequest
)


##### Tap helper functions #####


def get_bounds_for_element(element: dict) -> Bounds | None:
    """Extract bounds from a UI element."""
    bounds_str = element.get("bounds")
    if not bounds_str:
        return None
    try:
        # Parse bounds string like "[x1,y1][x2,y2]" using regex
        match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_str)
        if match:
            return Bounds(
                x1=int(match.group(1)),
                y1=int(match.group(2)),
                x2=int(match.group(3)),
                y2=int(match.group(4)),
            )
    except (ValueError, IndexError):
        return None


def _extract_resource_id_and_text_from_selector(
    selector: SelectorRequest,
) -> tuple[str | None, str | None]:
    """Extract resource_id and text from a selector."""
    resource_id = None
    text = None

    if isinstance(selector, IdSelectorRequest):
        resource_id = selector.id
    elif isinstance(selector, TextSelectorRequest):
        text = selector.text
    elif isinstance(selector, IdWithTextSelectorRequest):
        resource_id = selector.id
        text = selector.text

    return resource_id, text


def _get_ui_element(
    ui_hierarchy: list[dict],
    resource_id: str | None = None,
    text: str | None = None,
    index: int | None = None,
) -> tuple[dict | None, str | None]:
    """Find a UI element in the hierarchy by resource_id or text."""
    if not resource_id and not text:
        return None, "No resource_id or text provided"

    matches = []
    for element in ui_hierarchy:
        if resource_id and element.get("resource-id") == resource_id:
            matches.append(element)
        elif text and (element.get("text") == text or element.get("accessibilityText") == text):
            matches.append(element)

    if not matches:
        criteria = f"resource_id='{resource_id}'" if resource_id else f"text='{text}'"
        return None, f"No element found with {criteria}"

    target_index = index if index is not None else 0
    if target_index >= len(matches):
        criteria = f"resource_id='{resource_id}'" if resource_id else f"text='{text}'"
        return (
            None,
            f"Index {target_index} out of range for {criteria} (found {len(matches)} matches)",
        )

    return matches[target_index], None


def _android_tap_by_coordinates(
    ctx: MobileUseContext,
    coords: CoordinatesSelectorRequest,
    long_press: bool = False,
    long_press_duration: int = 1000,
) -> TapOutput:
    """Tap at specific coordinates using ADB."""
    if ctx.adb_client is None:
        return TapOutput(error="ADB client is not initialized")

    if long_press:
        # Long press is simulated as a swipe at the same location
        cmd = f"input swipe {coords.x} {coords.y} {coords.x} {coords.y} {long_press_duration}"
    else:
        cmd = f"input tap {coords.x} {coords.y}"

    try:
        device = _get_adb_device(ctx)
        device.shell(cmd)
        return TapOutput(error=None)
    except Exception as e:
        return TapOutput(error=f"ADB tap failed: {str(e)}")


def _android_tap_by_resource_id_or_text(
    ctx: MobileUseContext,
    ui_hierarchy: list[dict],
    resource_id: str | None = None,
    text: str | None = None,
    index: int | None = None,
    long_press: bool = False,
    long_press_duration: int = 1000,
) -> TapOutput:
    """Tap on an element by finding it in the UI hierarchy."""
    if ctx.adb_client is None:
        return TapOutput(error="ADB client is not initialized")

    ui_element, error_msg = _get_ui_element(
        ui_hierarchy=ui_hierarchy,
        resource_id=resource_id,
        text=text,
        index=index,
    )

    if not ui_element:
        return TapOutput(error=error_msg)

    bounds = get_bounds_for_element(ui_element)
    if not bounds:
        criteria = f"resource_id='{resource_id}'" if resource_id else f"text='{text}'"
        return TapOutput(error=f"Could not extract bounds for element with {criteria}")

    center = bounds.get_center()
    return _android_tap_by_coordinates(
        ctx=ctx, coords=center, long_press=long_press, long_press_duration=long_press_duration
    )


def tap_android(
    ctx: MobileUseContext,
    selector: SelectorRequest,
    index: int | None = None,
    ui_hierarchy: list[dict] | None = None,
    long_press: bool = False,
    long_press_duration: int = 1000,
) -> TapOutput:
    """Execute tap using ADB with fallback strategies."""
    if not ctx.adb_client:
        raise ValueError("ADB client is not initialized")

    # Direct coordinate tap
    if isinstance(selector, SelectorRequestWithCoordinates):
        return _android_tap_by_coordinates(
            ctx=ctx,
            coords=selector.coordinates,
            long_press=long_press,
            long_press_duration=long_press_duration,
        )

    # Convert percentage-based selectors to coordinates
    if isinstance(selector, SelectorRequestWithPercentages):
        coords = selector.percentages.to_coords(
            width=ctx.device.device_width,
            height=ctx.device.device_height,
        )
        return _android_tap_by_coordinates(
            ctx=ctx,
            coords=coords,
            long_press=long_press,
            long_press_duration=long_press_duration,
        )

    # For other selectors, we need the UI hierarchy
    resource_id, text = _extract_resource_id_and_text_from_selector(selector)

    if not ui_hierarchy:
        ui_hierarchy = get_screen_data(screen_api_client=ctx.screen_api_client).elements

    return _android_tap_by_resource_id_or_text(
        ctx=ctx,
        ui_hierarchy=ui_hierarchy,
        resource_id=resource_id,
        text=text,
        index=index,
        long_press=long_press,
        long_press_duration=long_press_duration,
    )


def tap(
    ctx: MobileUseContext,
    selector_request: SelectorRequest,
    dry_run: bool = False,
    index: int | None = None,
    ui_hierarchy: list[dict] | None = None,
):
    """
    Tap on a selector.
    Index is optional and is used when you have multiple views matching the same selector.
    ui_hierarchy is optional and used for ADB taps to find elements.
    """
    # Prioritize ADB
    if ctx.adb_client:
        output = tap_android(
            ctx=ctx,
            selector=selector_request,
            index=index,
            ui_hierarchy=ui_hierarchy,
        )
        return output.error if output.error else None

    # Fallback to Maestro
    tap_body = selector_request.to_dict()
    if not tap_body:
        error = "Invalid tap selector request, could not format yaml"
        logger.error(error)
        raise ControllerErrors(error)
    if index:
        tap_body["index"] = index
    flow_input = [{"tapOn": tap_body}]
    return run_flow(ctx, flow_input, dry_run=dry_run)


def long_press_on(
    ctx: MobileUseContext,
    selector_request: SelectorRequest,
    dry_run: bool = False,
    index: int | None = None,
    ui_hierarchy: list[dict] | None = None,
    long_press_duration: int = 1000,
):
    """
    Long press on a selector.
    Index is optional and is used when you have multiple views matching the same selector.
    ui_hierarchy is optional and used for ADB long press to find elements.
    """
    # Prioritize ADB
    if ctx.adb_client:
        output = tap_android(
            ctx=ctx,
            selector=selector_request,
            index=index,
            ui_hierarchy=ui_hierarchy,
            long_press=True,
            long_press_duration=long_press_duration,
        )
        return output.error if output.error else None

    # Fallback to Maestro
    long_press_on_body = selector_request.to_dict()
    if not long_press_on_body:
        error = "Invalid longPressOn selector request, could not format yaml"
        logger.error(error)
        raise ControllerErrors(error)
    if index:
        long_press_on_body["index"] = index
    flow_input = [{"longPressOn": long_press_on_body}]
    return run_flow_with_wait_for_animation_to_end(ctx, flow_input, dry_run=dry_run)


def swipe_android(
    ctx: MobileUseContext,
    request: SwipeRequest,
) -> str | None:
    """Returns an error_message in case of failure."""
    if not ctx.adb_client:
        raise ValueError("ADB client is not initialized")

    mode = request.swipe_mode
    if isinstance(mode, SwipeStartEndCoordinatesRequest):
        swipe_coords = mode
    elif isinstance(mode, SwipeStartEndPercentagesRequest):
        swipe_coords = mode.to_coords(
            width=ctx.device.device_width,
            height=ctx.device.device_height,
        )
    else:
        return "Unsupported selector type"

    duration = request.duration if request.duration else 400  # in ms

    cmd = (
        "input touchscreen swipe "
        f"{swipe_coords.start.x} {swipe_coords.start.y} "
        f"{swipe_coords.end.x} {swipe_coords.end.y} "
        f"{duration}"
    )
    device = _get_adb_device(ctx)
    device.shell(cmd)
    return None


def swipe(ctx: MobileUseContext, swipe_request: SwipeRequest, dry_run: bool = False):
    if ctx.adb_client:
        error_msg = swipe_android(ctx=ctx, request=swipe_request)
        return {"error": error_msg} if error_msg else None
    swipe_body = swipe_request.to_dict()
    if not swipe_body:
        error = "Invalid swipe selector request, could not format yaml"
        logger.error(error)
        raise ControllerErrors(error)
    flow_input = [{"swipe": swipe_body}]
    return run_flow(ctx, flow_input, dry_run=dry_run)


##### Text related commands #####


def input_text(ctx: MobileUseContext, text: str, dry_run: bool = False):
    adb_client = ctx.adb_client
    if adb_client:
        logger.info("Inputting text with adb")
        parts = text.split("%s")
        for i, part in enumerate(parts):
            to_write = ""
            if i > 0:
                to_write += "s"
            to_write += part
            if i < len(parts) - 1:
                to_write += "%"

            device = _get_adb_device(ctx)
            device.shell(["input", "text", to_write])

        return None

    # Fallback to Maestro
    return run_flow(ctx, [{"inputText": text}], dry_run=dry_run)


def erase_text(ctx: MobileUseContext, nb_chars: int | None = None, dry_run: bool = False):
    """
    Removes characters from the currently selected textfield (if any)
    Removes 50 characters if nb_chars is not specified.
    """
    adb_client = ctx.adb_client
    if adb_client:
        logger.info("Erasing text with adb")
        chars_to_delete = nb_chars if nb_chars is not None else 50
        for _ in range(chars_to_delete):
            device = _get_adb_device(ctx)
            device.shell("input keyevent KEYCODE_DEL")
        return None

    # Fallback to Maestro
    if nb_chars is None:
        return run_flow(ctx, ["eraseText"], dry_run=dry_run)
    return run_flow(ctx, [{"eraseText": nb_chars}], dry_run=dry_run)


##### App related commands #####


def launch_app(ctx: MobileUseContext, package_name: str, dry_run: bool = False):
    adb_client = ctx.adb_client
    if adb_client:
        logger.info("Launching app with adb")
        device = _get_adb_device(ctx)
        result = str(
            device.shell(
                f"monkey -p {package_name} -c android.intent.category.LAUNCHER 1 --pct-syskeys 0 1"
            )
        )
        result_lower = result.lower()
        if "error" in result_lower or "not found" in result_lower:
            logger.error(f"Failed to launch {package_name}: {result}")
            return {"error": result}
        return None

    flow_input = [{"launchApp": package_name}]
    return run_flow_with_wait_for_animation_to_end(
        ctx, flow_input, dry_run=dry_run, wait_for_animation_to_end=True
    )


def stop_app(ctx: MobileUseContext, package_name: str | None = None, dry_run: bool = False):
    if package_name is None:
        flow_input = ["stopApp"]
    else:
        flow_input = [{"stopApp": package_name}]
    return run_flow_with_wait_for_animation_to_end(ctx, flow_input, dry_run=dry_run)


def open_link(ctx: MobileUseContext, url: str, dry_run: bool = False):
    adb_client = ctx.adb_client
    if adb_client:
        logger.info("Opening link with adb")
        device = _get_adb_device(ctx)
        device.shell(["am", "start", "-a", "android.intent.action.VIEW", "-d", url])
        return None

    # Fallback to Maestro
    flow_input = [{"openLink": url}]
    return run_flow_with_wait_for_animation_to_end(ctx, flow_input, dry_run=dry_run)


##### Key related commands #####


def back(ctx: MobileUseContext, dry_run: bool = False):
    adb_client = ctx.adb_client
    if adb_client:
        logger.info("Pressing back with adb")
        device = _get_adb_device(ctx)
        device.shell("input keyevent KEYCODE_BACK")
        return None

    # Fallback to Maestro
    flow_input = ["back"]
    return run_flow_with_wait_for_animation_to_end(ctx, flow_input, dry_run=dry_run)


class Key(Enum):
    ENTER = "Enter"
    HOME = "Home"
    BACK = "Back"


def press_key(ctx: MobileUseContext, key: Key, dry_run: bool = False):
    flow_input = [{"pressKey": key.value}]
    return run_flow_with_wait_for_animation_to_end(ctx, flow_input, dry_run=dry_run)


#### Other commands ####


def wait_for_delay(time_in_ms: int):
    """Wait for a specified delay in milliseconds."""
    time.sleep(time_in_ms / 1000)
    return None


def run_flow_with_wait_for_animation_to_end(
    ctx: MobileUseContext,
    base_flow: list,
    dry_run: bool = False,
    wait_for_animation_to_end: bool = False,
):
    if wait_for_animation_to_end:
        base_flow.append({"waitForAnimationToEnd": {"timeout": 500}})
    return run_flow(ctx, base_flow, dry_run=dry_run)


if __name__ == "__main__":
    adb_client = AdbClient(host="192.168.43.107", port=5037)
    ctx = MobileUseContext(
        trace_id="trace_id",
        llm_config=initialize_llm_config(),
        device=DeviceContext(
            host_platform="WINDOWS",
            mobile_platform=DevicePlatform.ANDROID,
            device_id="986066a",
            device_width=1080,
            device_height=2340,
        ),
        hw_bridge_client=DeviceHardwareClient("http://localhost:9999"),
        screen_api_client=ScreenApiClient("http://localhost:9998"),
        adb_client=adb_client,
    )
    screen_data = get_screen_data(ctx.screen_api_client)
    from minitap.mobile_use.graph.state import State

    dummy_state = State(
        latest_ui_hierarchy=screen_data.elements,
        messages=[],
        initial_goal="",
        subgoal_plan=[],
        focused_app_info=None,
        device_date="",
        structured_decisions=None,
        complete_subgoals_by_ids=[],
        screen_analysis_prompt=None,
        executor_messages=[],
        cortex_last_thought="",
        agents_thoughts=[],
    )

    # from minitap.mobile_use.tools.mobile.focus_and_input_text import get_focus_and_input_text_tool

    # input_resource_id = "com.google.android.apps.nexuslauncher:id/search_container_hotseat"
    # command_output: Command = get_focus_and_input_text_tool(ctx=ctx).invoke(
    #     {
    #         "tool_call_id": uuid.uuid4().hex,
    #         "agent_thought": "",
    #         "text_input_resource_id": input_resource_id,
    #         "text": "Hello World",
    #         "state": dummy_state,
    #         "executor_metadata": None,
    #     }
    # )
    from minitap.mobile_use.tools.mobile.focus_and_clear_text import get_focus_and_clear_text_tool

    input_resource_id = "com.google.android.apps.nexuslauncher:id/input"
    command_output: Command = get_focus_and_clear_text_tool(ctx=ctx).invoke(
        {
            "tool_call_id": uuid.uuid4().hex,
            "agent_thought": "",
            "text_input_resource_id": input_resource_id,
            "state": dummy_state,
            "executor_metadata": None,
        }
    )
    print(command_output)
