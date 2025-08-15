from enum import Enum
from typing import Literal, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field
from requests import JSONDecodeError

from minitap.clients.device_hardware_client import get_client as get_device_hardware_client
from minitap.clients.screen_api_client import get_client as get_screen_api_client
from minitap.config import settings
from minitap.utils.errors import ControllerErrors
from minitap.utils.logger import get_logger

screen_api = get_screen_api_client(settings.DEVICE_SCREEN_API_BASE_URL)
device_hardware_api = get_device_hardware_client(settings.DEVICE_HARDWARE_BRIDGE_BASE_URL)
logger = get_logger(__name__)


###### Screen elements retrieval ######


class ScreenDataResponse(BaseModel):
    base64: str
    elements: list[dict]
    width: int
    height: int
    platform: str


def get_screen_data():
    response = screen_api.get("/screen-info")
    return ScreenDataResponse(**response.json())


def take_screenshot():
    return get_screen_data().base64


class RunFlowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    yaml: str
    dry_run: bool = Field(default=False, alias="dryRun")


def run_flow(flow_steps: list, dry_run: bool = False) -> Optional[dict]:
    """
    Run a flow i.e, a sequence of commands.
    Returns None on success, or the response body of the failed command.
    """
    logger.info(f"Running flow: {flow_steps}")

    for step in flow_steps:
        step_yml = yaml.dump(step)
        payload = RunFlowRequest(yaml=step_yml, dryRun=dry_run).model_dump(by_alias=True)
        response = device_hardware_api.post("run-command", json=payload)

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


SelectorRequest = Union[
    IdSelectorRequest,
    SelectorRequestWithCoordinates,
    SelectorRequestWithPercentages,
    TextSelectorRequest,
    IdWithTextSelectorRequest,
]


def tap(selector_request: SelectorRequest, dry_run: bool = False, index: Optional[int] = None):
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
    return run_flow_with_wait_for_animation_to_end(flow_input, dry_run=dry_run)


def long_press_on(
    selector_request: SelectorRequest, dry_run: bool = False, index: Optional[int] = None
):
    long_press_on_body = selector_request.to_dict()
    if not long_press_on_body:
        error = "Invalid longPressOn selector request, could not format yaml"
        logger.error(error)
        raise ControllerErrors(error)
    if index:
        long_press_on_body["index"] = index
    flow_input = [{"longPressOn": long_press_on_body}]
    return run_flow_with_wait_for_animation_to_end(flow_input, dry_run=dry_run)


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


class SwipeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    swipe_mode: (
        SwipeStartEndCoordinatesRequest
        | SwipeStartEndPercentagesRequest
        | Literal["UP", "DOWN", "LEFT", "RIGHT"]
    )
    duration: Optional[int] = None  # in ms, default is 400ms

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


def swipe(swipe_request: SwipeRequest, dry_run: bool = False):
    swipe_body = swipe_request.to_dict()
    if not swipe_body:
        error = "Invalid swipe selector request, could not format yaml"
        logger.error(error)
        raise ControllerErrors(error)
    flow_input = [{"swipe": swipe_body}]
    return run_flow_with_wait_for_animation_to_end(flow_input, dry_run=dry_run)


##### Text related commands #####


def input_text(text: str, dry_run: bool = False):
    return run_flow([{"inputText": text}], dry_run=dry_run)


def copy_text_from(selector_request: SelectorRequest, dry_run: bool = False):
    copy_text_from_body = selector_request.to_dict()
    if not copy_text_from_body:
        error = "Invalid copyTextFrom selector request, could not format yaml"
        logger.error(error)
        raise ControllerErrors(error)
    flow_input = [{"copyTextFrom": copy_text_from_body}]
    return run_flow(flow_input, dry_run=dry_run)


def paste_text(dry_run: bool = False):
    return run_flow(["pasteText"], dry_run=dry_run)


def erase_text(nb_chars: Optional[int] = None, dry_run: bool = False):
    """
    Removes characters from the currently selected textfield (if any)
    Removes 50 characters if nb_chars is not specified.
    """
    if nb_chars is None:
        return run_flow(["eraseText"], dry_run=dry_run)
    return run_flow([{"eraseText": nb_chars}], dry_run=dry_run)


##### App related commands #####


def launch_app(package_name: str, dry_run: bool = False):
    flow_input = [{"launchApp": package_name}]
    return run_flow_with_wait_for_animation_to_end(flow_input, dry_run=dry_run)


def stop_app(package_name: Optional[str] = None, dry_run: bool = False):
    if package_name is None:
        flow_input = ["stopApp"]
    else:
        flow_input = [{"stopApp": package_name}]
    return run_flow_with_wait_for_animation_to_end(flow_input, dry_run=dry_run)


def open_link(url: str, dry_run: bool = False):
    flow_input = [{"openLink": url}]
    return run_flow_with_wait_for_animation_to_end(flow_input, dry_run=dry_run)


##### Key related commands #####


def back(dry_run: bool = False):
    flow_input = ["back"]
    return run_flow_with_wait_for_animation_to_end(flow_input, dry_run=dry_run)


class Key(Enum):
    ENTER = "Enter"
    HOME = "Home"
    BACK = "Back"


def press_key(key: Key, dry_run: bool = False):
    flow_input = [{"pressKey": key.value}]
    return run_flow_with_wait_for_animation_to_end(flow_input, dry_run=dry_run)


#### Other commands ####


class WaitTimeout(Enum):
    SHORT = 500
    MEDIUM = 1000
    LONG = 5000


def wait_for_animation_to_end(timeout: Optional[WaitTimeout] = None, dry_run: bool = False):
    if timeout is None:
        return run_flow(["waitForAnimationToEnd"], dry_run=dry_run)
    return run_flow([{"waitForAnimationToEnd": {"timeout": timeout.value}}], dry_run=dry_run)


def run_flow_with_wait_for_animation_to_end(base_flow: list, dry_run: bool = False):
    base_flow.append({"waitForAnimationToEnd": {"timeout": WaitTimeout.MEDIUM.value}})
    return run_flow(base_flow, dry_run=dry_run)


if __name__ == "__main__":
    swipe(
        SwipeRequest(
            swipe_mode="LEFT",
            duration=700,
        )
    )
