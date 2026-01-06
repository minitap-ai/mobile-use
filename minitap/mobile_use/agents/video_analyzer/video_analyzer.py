"""
Video Analyzer utility for analyzing video content using Gemini models.

This utility sends video files to video-capable Gemini models for analysis
and returns text descriptions based on the provided prompt.
"""

import base64
from pathlib import Path

from jinja2 import Template
from langchain_core.messages import HumanMessage, SystemMessage

from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.services.llm import get_llm, invoke_llm_with_timeout_message, with_fallback
from minitap.mobile_use.utils.logger import get_logger
from minitap.mobile_use.utils.video import compress_video_for_api

logger = get_logger(__name__)


async def analyze_video(
    ctx: MobileUseContext,
    video_path: Path,
    prompt: str,
) -> str:
    """
    Analyze a video file using a video-capable Gemini model.

    Args:
        ctx: The MobileUseContext containing LLM configuration
        video_path: Path to the video file (MP4)
        prompt: The analysis prompt/question about the video

    Returns:
        Text analysis result from the model

    Raises:
        Exception: If video analysis fails
    """
    logger.info(f"Starting video analysis for {video_path}")

    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    # Compress video if needed to fit within API limits
    compressed_path = await compress_video_for_api(video_path)

    try:
        with open(compressed_path, "rb") as video_file:
            video_bytes = video_file.read()

        video_base64 = base64.b64encode(video_bytes).decode("utf-8")

        suffix = compressed_path.suffix.lower()
        mime_type = "video/mp4" if suffix in [".mp4", ".m4v"] else f"video/{suffix[1:]}"

        system_message_content = Template(
            Path(__file__).parent.joinpath("video_analyzer.md").read_text(encoding="utf-8")
        ).render()

        human_message_content = Template(
            Path(__file__).parent.joinpath("human.md").read_text(encoding="utf-8")
        ).render(prompt=prompt)

        messages = [
            SystemMessage(content=system_message_content),
            HumanMessage(
                content=[
                    {
                        "type": "text",
                        "text": human_message_content,
                    },
                    {
                        "type": "file",
                        "source_type": "base64",
                        "mime_type": mime_type,
                        "data": video_base64,
                    },
                ]
            ),
        ]

        llm = get_llm(ctx=ctx, name="video_analyzer", is_utils=True, temperature=0.2)
        llm_fallback = get_llm(
            ctx=ctx, name="video_analyzer", is_utils=True, use_fallback=True, temperature=0.2
        )

        logger.info("Sending video to LLM for analysis...")

        response = await with_fallback(
            main_call=lambda: invoke_llm_with_timeout_message(
                llm.ainvoke(messages), timeout_seconds=120
            ),
            fallback_call=lambda: invoke_llm_with_timeout_message(
                llm_fallback.ainvoke(messages), timeout_seconds=120
            ),
        )

        content = response.content if hasattr(response, "content") else str(response)
        result = content if isinstance(content, str) else str(content)
        logger.info("Video analysis completed")

        return result
    finally:
        # Clean up compressed file if it differs from original
        if compressed_path != video_path and compressed_path.exists():
            try:
                compressed_path.unlink()
            except Exception:
                pass
