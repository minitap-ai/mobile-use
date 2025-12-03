import base64
import time

from colorama import Fore, Style
from langchain_core.messages import BaseMessage

from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.controller_factory import create_device_controller
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


async def record_interaction(ctx: MobileUseContext, response: BaseMessage):
    if not ctx.execution_setup:
        raise ValueError("No execution setup found")
    if not ctx.execution_setup.traces_path or not ctx.execution_setup.trace_name:
        raise ValueError("No traces path or trace name found")

    logger.info("Recording interaction")
    controller = create_device_controller(ctx)
    screenshot_base64 = await controller.screenshot()
    logger.info("Screenshot taken")
    try:
        controller = create_device_controller(ctx)
        compressed_screenshot_base64 = controller.get_compressed_b64_screenshot(screenshot_base64)
    except Exception as e:
        logger.error(f"Error compressing screenshot: {e}")
        return "Could not record this interaction"
    timestamp = time.time()
    folder = ctx.execution_setup.traces_path.joinpath(ctx.execution_setup.trace_name).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    try:
        with open(
            folder.joinpath(f"{int(timestamp)}.jpeg").resolve(),
            "wb",
        ) as f:
            f.write(base64.b64decode(compressed_screenshot_base64))

        with open(
            folder.joinpath(f"{int(timestamp)}.json").resolve(),
            "w",
            encoding="utf-8",
        ) as f:
            f.write(response.model_dump_json())
    except Exception as e:
        logger.error(f"Error recording interaction: {e}")
    return "Screenshot recorded successfully"


def log_agent_thought(agent_thought: str):
    logger.info(f"💭 {Fore.LIGHTMAGENTA_EX}{agent_thought}{Style.RESET_ALL}")
