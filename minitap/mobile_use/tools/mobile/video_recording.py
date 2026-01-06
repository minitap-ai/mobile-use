"""
Video recording tools for mobile devices.

Provides start/stop video recording tools that delegate to platform-specific
controllers (AndroidDeviceController, iOSDeviceController).
"""

import shutil
from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import BaseTool, InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import DevicePlatform, MobileUseContext
from minitap.mobile_use.controllers.controller_factory import get_controller
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.tools.tool_wrapper import ToolWrapper
from minitap.mobile_use.utils.logger import get_logger
from minitap.mobile_use.utils.video import DEFAULT_MAX_DURATION_SECONDS

logger = get_logger(__name__)


def get_start_video_recording_tool(ctx: MobileUseContext) -> BaseTool:
    @tool
    async def start_video_recording(
        agent_thought: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
    ):
        """
        Starts a background screen recording on the mobile device.
        Recording continues until stop_video_recording is called.
        Max duration: 3 min (Android) / 15 min (iOS). Audio is not captured.
        """
        platform = ctx.device.mobile_platform
        controller = get_controller(ctx)

        if platform in (DevicePlatform.ANDROID, DevicePlatform.IOS):
            result = await controller.start_video_recording(DEFAULT_MAX_DURATION_SECONDS)
        else:
            from minitap.mobile_use.utils.video import VideoRecordingResult

            result = VideoRecordingResult(
                success=False,
                message=f"Unsupported platform: {platform}",
            )

        if result.success:
            agent_outcome = start_video_recording_wrapper.on_success_fn(result.message)
        else:
            agent_outcome = start_video_recording_wrapper.on_failure_fn(result.message)

        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=agent_outcome,
            status="success" if result.success else "error",
        )

        return Command(
            update=await state.asanitize_update(
                ctx=ctx,
                update={
                    "agents_thoughts": [agent_thought, agent_outcome],
                    EXECUTOR_MESSAGES_KEY: [tool_message],
                },
                agent="executor",
            ),
        )

    return start_video_recording


def get_stop_video_recording_tool(ctx: MobileUseContext) -> BaseTool:
    from minitap.mobile_use.agents.video_analyzer.video_analyzer import analyze_video

    @tool
    async def stop_video_recording(
        agent_thought: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
        prompt: str = "Describe what happened in the video.",
    ):
        """
        Stops the current screen recording and analyzes the video content.
        Use `prompt` to specify what to extract (e.g., "What happens after each 10s of the video?").
        """
        platform = ctx.device.mobile_platform
        controller = get_controller(ctx)

        if platform in (DevicePlatform.ANDROID, DevicePlatform.IOS):
            result = await controller.stop_video_recording()
        else:
            from minitap.mobile_use.utils.video import VideoRecordingResult

            result = VideoRecordingResult(
                success=False,
                message=f"Unsupported platform: {platform}",
            )

        if not result.success or result.video_path is None:
            agent_outcome = stop_video_recording_wrapper.on_failure_fn(result.message)
            tool_message = ToolMessage(
                tool_call_id=tool_call_id,
                content=agent_outcome,
                status="error",
            )
            return Command(
                update=await state.asanitize_update(
                    ctx=ctx,
                    update={
                        "agents_thoughts": [agent_thought, agent_outcome],
                        EXECUTOR_MESSAGES_KEY: [tool_message],
                    },
                    agent="executor",
                ),
            )

        video_path = result.video_path
        try:
            analysis_result = await analyze_video(
                ctx=ctx,
                video_path=video_path,
                prompt=prompt,
            )
            agent_outcome = stop_video_recording_wrapper.on_success_fn(analysis_result)
            status = "success"
        except Exception as e:
            logger.error(f"Video analysis failed: {e}")
            agent_outcome = stop_video_recording_wrapper.on_failure_fn(
                f"Recording stopped but analysis failed: {e}"
            )
            status = "error"
        finally:
            try:
                if video_path and video_path.exists():
                    video_path.unlink()
                    if video_path.parent.exists():
                        shutil.rmtree(video_path.parent)
            except Exception:
                pass

        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=agent_outcome,
            status=status,
        )

        return Command(
            update=await state.asanitize_update(
                ctx=ctx,
                update={
                    "agents_thoughts": [agent_thought, agent_outcome],
                    EXECUTOR_MESSAGES_KEY: [tool_message],
                },
                agent="executor",
            ),
        )

    return stop_video_recording


start_video_recording_wrapper = ToolWrapper(
    tool_fn_getter=get_start_video_recording_tool,
    on_success_fn=lambda message: f"Video recording started successfully. {message}",
    on_failure_fn=lambda message: f"Failed to start video recording: {message}",
)

stop_video_recording_wrapper = ToolWrapper(
    tool_fn_getter=get_stop_video_recording_tool,
    on_success_fn=lambda analysis: f"Video stopped successfully. Analysis result:\n{analysis}",
    on_failure_fn=lambda message: f"Video recording/analysis failed: {message}",
)
