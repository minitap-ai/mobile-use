import uuid
from enum import Enum
from typing import Annotated, Literal

import yaml
from langgraph.types import Command
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
from requests import JSONDecodeError

from minitap.mobile_use.clients.device_hardware_client import DeviceHardwareClient
from minitap.mobile_use.clients.screen_api_client import ScreenApiClient
from minitap.mobile_use.config import initialize_llm_config
from minitap.mobile_use.context import DeviceContext, DevicePlatform, MobileUseContext
from minitap.mobile_use.utils.errors import ControllerErrors
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


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


class CoordinatesSelectorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: int
    y: int

    def to_str(self):
        return f"{self.x}, {self.y}"


class PercentagesSelectorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    """
    0%,0%        # top-left corner
    100%,100%    # bottom-right corner
    50%,50%      # center
    """

    x_percent: int
    y_percent: int

    def to_str(self):
        return f"{self.x_percent}%, {self.y_percent}%"


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


def tap(
    ctx: MobileUseContext,
    selector_request: SelectorRequest,
    dry_run: bool = False,
    index: int | None = None,
):
    """
    Tap on a selector.
    Index is optional and is used when you have multiple views matching the same selector.
    """
    tap_body = selector_request.to_dict()
    if not tap_body:
        error = "Invalid tap selector request, could not format yaml"
        logger.error(error)
        raise ControllerErrors(error)
    if index:
        tap_body["index"] = index
    flow_input = [{"tapOn": tap_body}]
    return run_flow_with_wait_for_animation_to_end(ctx, flow_input, dry_run=dry_run)


def long_press_on(
    ctx: MobileUseContext,
    selector_request: SelectorRequest,
    dry_run: bool = False,
    index: int | None = None,
):
    long_press_on_body = selector_request.to_dict()
    if not long_press_on_body:
        error = "Invalid longPressOn selector request, could not format yaml"
        logger.error(error)
        raise ControllerErrors(error)
    if index:
        long_press_on_body["index"] = index
    flow_input = [{"longPressOn": long_press_on_body}]
    return run_flow_with_wait_for_animation_to_end(ctx, flow_input, dry_run=dry_run)


class SwipeStartEndCoordinatesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: CoordinatesSelectorRequest
    end: CoordinatesSelectorRequest

    def to_dict(self):
        return {"start": self.start.to_str(), "end": self.end.to_str()}


class SwipeStartEndPercentagesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: PercentagesSelectorRequest
    end: PercentagesSelectorRequest

    def to_dict(self):
        return {"start": self.start.to_str(), "end": self.end.to_str()}


SwipeDirection = Annotated[
    Literal["UP", "DOWN", "LEFT", "RIGHT"],
    BeforeValidator(lambda v: v.upper() if isinstance(v, str) else v),
]


class SwipeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    swipe_mode: SwipeStartEndCoordinatesRequest | SwipeStartEndPercentagesRequest | SwipeDirection
    duration: int | None = None  # in ms, default is 400ms

    def to_dict(self):
        res = {}
        if isinstance(self.swipe_mode, SwipeStartEndCoordinatesRequest):
            res |= self.swipe_mode.to_dict()
        elif isinstance(self.swipe_mode, SwipeStartEndPercentagesRequest):
            res |= self.swipe_mode.to_dict()
        elif self.swipe_mode in ["UP", "DOWN", "LEFT", "RIGHT"]:
            res |= {"direction": self.swipe_mode}
        if self.duration:
            res |= {"duration": self.duration}
        return res


def swipe(ctx: MobileUseContext, swipe_request: SwipeRequest, dry_run: bool = False):
    swipe_body = swipe_request.to_dict()
    if not swipe_body:
        error = "Invalid swipe selector request, could not format yaml"
        logger.error(error)
        raise ControllerErrors(error)
    flow_input = [{"swipe": swipe_body}]
    return run_flow_with_wait_for_animation_to_end(ctx, flow_input, dry_run=dry_run)


##### Text related commands #####


def input_text(ctx: MobileUseContext, text: str, dry_run: bool = False):
    return run_flow(ctx, [{"inputText": text}], dry_run=dry_run)


def copy_text_from(ctx: MobileUseContext, selector_request: SelectorRequest, dry_run: bool = False):
    copy_text_from_body = selector_request.to_dict()
    if not copy_text_from_body:
        error = "Invalid copyTextFrom selector request, could not format yaml"
        logger.error(error)
        raise ControllerErrors(error)
    flow_input = [{"copyTextFrom": copy_text_from_body}]
    return run_flow(ctx, flow_input, dry_run=dry_run)


def paste_text(ctx: MobileUseContext, dry_run: bool = False):
    return run_flow(ctx, ["pasteText"], dry_run=dry_run)


def erase_text(ctx: MobileUseContext, nb_chars: int | None = None, dry_run: bool = False):
    """
    Removes characters from the currently selected textfield (if any)
    Removes 50 characters if nb_chars is not specified.
    """
    if nb_chars is None:
        return run_flow(ctx, ["eraseText"], dry_run=dry_run)
    return run_flow(ctx, [{"eraseText": nb_chars}], dry_run=dry_run)


##### App related commands #####


def launch_app(ctx: MobileUseContext, package_name: str, dry_run: bool = False):
    flow_input = [{"launchApp": package_name}]
    return run_flow_with_wait_for_animation_to_end(ctx, flow_input, dry_run=dry_run)


def stop_app(ctx: MobileUseContext, package_name: str | None = None, dry_run: bool = False):
    if package_name is None:
        flow_input = ["stopApp"]
    else:
        flow_input = [{"stopApp": package_name}]
    return run_flow_with_wait_for_animation_to_end(ctx, flow_input, dry_run=dry_run)


def open_link(ctx: MobileUseContext, url: str, dry_run: bool = False):
    flow_input = [{"openLink": url}]
    return run_flow_with_wait_for_animation_to_end(ctx, flow_input, dry_run=dry_run)


##### Key related commands #####


def back(ctx: MobileUseContext, dry_run: bool = False):
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


class WaitTimeout(Enum):
    SHORT = "500"
    MEDIUM = "1000"
    LONG = "5000"


def wait_for_animation_to_end(
    ctx: MobileUseContext, timeout: WaitTimeout | None = None, dry_run: bool = False
):
    if timeout is None:
        return run_flow(ctx, ["waitForAnimationToEnd"], dry_run=dry_run)
    return run_flow(ctx, [{"waitForAnimationToEnd": {"timeout": timeout.value}}], dry_run=dry_run)


def run_flow_with_wait_for_animation_to_end(
    ctx: MobileUseContext, base_flow: list, dry_run: bool = False
):
    base_flow.append({"waitForAnimationToEnd": {"timeout": int(WaitTimeout.MEDIUM.value)}})
    return run_flow(ctx, base_flow, dry_run=dry_run)


if __name__ == "__main__":
    ctx = MobileUseContext(
        llm_config=initialize_llm_config(),
        device=DeviceContext(
            host_platform="WINDOWS",
            mobile_platform=DevicePlatform.ANDROID,
            device_id="emulator-5554",
            device_width=1080,
            device_height=1920,
        ),
        hw_bridge_client=DeviceHardwareClient("http://localhost:9999"),
        screen_api_client=ScreenApiClient("http://localhost:9998"),
    )
    screen_data = get_screen_data(ctx.screen_api_client)
    from minitap.mobile_use.graph.state import State

    dummy_state = State(
        latest_ui_hierarchy=screen_data.elements,
        messages=[],
        initial_goal="",
        subgoal_plan=[],
        latest_screenshot_base64=screen_data.base64,
        focused_app_info=None,
        device_date="",
        structured_decisions=None,
        complete_subgoals_by_ids=[],
        executor_messages=[],
        cortex_last_thought="",
        agents_thoughts=[],
    )

    # from minitap.mobile_use.tools.mobile.input_text import get_input_text_tool

    # input_resource_id = "com.google.android.apps.nexuslauncher:id/search_container_hotseat"
    # command_output: Command = get_input_text_tool(ctx=ctx).invoke(
    #     {
    #         "tool_call_id": uuid.uuid4().hex,
    #         "agent_thought": "",
    #         "text_input_resource_id": input_resource_id,
    #         "text": "Hello World",
    #         "state": dummy_state,
    #         "executor_metadata": None,
    #     }
    # )
    from minitap.mobile_use.tools.mobile.clear_text import get_clear_text_tool

    input_resource_id = "com.google.android.apps.nexuslauncher:id/input"
    command_output: Command = get_clear_text_tool(ctx=ctx).invoke(
        {
            "tool_call_id": uuid.uuid4().hex,
            "agent_thought": "",
            "text_input_resource_id": input_resource_id,
            "state": dummy_state,
            "executor_metadata": None,
        }
    )
    print(command_output)
