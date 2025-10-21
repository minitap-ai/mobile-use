from pathlib import Path

from jinja2 import Template
from langchain_core.messages import HumanMessage, SystemMessage

from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.mobile_command_controller import (
    take_screenshot as take_screenshot_controller,
)
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.services.llm import get_llm, invoke_llm_with_timeout_message, with_fallback
from minitap.mobile_use.utils.conversations import get_screenshot_message_for_llm
from minitap.mobile_use.utils.decorators import wrap_with_callbacks
from minitap.mobile_use.utils.logger import get_logger
from minitap.mobile_use.utils.media import compress_base64_jpeg

logger = get_logger(__name__)


class ScreenAnalyzerNode:
    def __init__(self, ctx: MobileUseContext):
        self.ctx = ctx

    @wrap_with_callbacks(
        before=lambda: logger.info("Starting Screen Analyzer Agent..."),
        on_success=lambda _: logger.success("Screen Analyzer Agent"),
        on_failure=lambda _: logger.error("Screen Analyzer Agent"),
    )
    async def __call__(self, state: State):
        # Check if there's a screen analysis request
        if not state.screen_analysis_prompt:
            logger.info("No screen analysis prompt, skipping")
            return {}

        prompt = state.screen_analysis_prompt
        analysis_result = "Analysis failed"
        has_failed = False

        try:
            # Take a fresh screenshot
            screenshot_output = take_screenshot_controller(ctx=self.ctx)
            compressed_image_base64 = compress_base64_jpeg(screenshot_output)

            # Invoke the screen_analyzer
            analysis_result = await screen_analyzer(
                ctx=self.ctx, screenshot_base64=compressed_image_base64, prompt=prompt
            )

        except Exception as e:
            logger.error(f"Screen analysis failed: {e}")
            analysis_result = f"Failed to analyze screen: {str(e)}"
            has_failed = True

        # Create outcome message
        if has_failed:
            agent_outcome = f"Screen analysis failed: {analysis_result}"
        else:
            agent_outcome = f"Screen analysis result: {analysis_result}"

        return await state.asanitize_update(
            ctx=self.ctx,
            update={
                "agents_thoughts": [agent_outcome],
                "screen_analysis_prompt": None,
            },
            agent="screen_analyzer",
        )


async def screen_analyzer(ctx: MobileUseContext, screenshot_base64: str, prompt: str) -> str:
    """
    Analyzes a screenshot using a VLM and returns a textual description based on the prompt.

    Args:
        ctx: The mobile use context
        screenshot_base64: Base64 encoded screenshot
        prompt: The specific question or instruction for analyzing the screenshot

    Returns:
        A concise textual description answering the prompt
    """
    logger.info("Starting Screen Analyzer Agent")

    system_message = (
        "You are a visual analysis assistant. "
        "Your task is to examine screenshots and provide accurate, "
        "concise answers to specific questions about what you see."
    )

    human_message = Template(
        Path(__file__).parent.joinpath("human.md").read_text(encoding="utf-8")
    ).render(prompt=prompt)

    messages = [
        SystemMessage(content=system_message),
        get_screenshot_message_for_llm(screenshot_base64),
        HumanMessage(content=human_message),
    ]

    llm = get_llm(ctx=ctx, name="screen_analyzer", temperature=0)
    llm_fallback = get_llm(ctx=ctx, name="screen_analyzer", use_fallback=True, temperature=0)

    response = await with_fallback(
        main_call=lambda: invoke_llm_with_timeout_message(llm.ainvoke(messages)),
        fallback_call=lambda: invoke_llm_with_timeout_message(llm_fallback.ainvoke(messages)),
    )
    return response.content  # type: ignore
