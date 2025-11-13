from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import BaseTool, InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import Field

from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.mobile_command_controller import swipe as swipe_controller
from minitap.mobile_use.controllers.types import (
    CoordinatesSelectorRequest,
    PercentagesSelectorRequest,
    SwipeRequest,
    SwipeStartEndCoordinatesRequest,
    SwipeStartEndPercentagesRequest,
)
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.tools.tool_wrapper import CompositeToolWrapper


def get_swipe_tool(ctx: MobileUseContext) -> BaseTool:
    @tool
    async def swipe(
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
        agent_thought: str,
        swipe_request: SwipeRequest,
    ) -> Command:
        """Swipe from start to end position on screen.

        Supports percentage-based or coordinate-based positioning.
        """
        output = swipe_controller(ctx=ctx, swipe_request=swipe_request)
        has_failed = output is not None

        agent_outcome = (
            swipe_wrapper.on_success_fn() if not has_failed else swipe_wrapper.on_failure_fn()
        )

        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=agent_outcome,
            additional_kwargs={"error": output} if has_failed else {},
            status="error" if has_failed else "success",
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

    return swipe


def get_composite_swipe_tools(ctx: MobileUseContext) -> list[BaseTool]:
    """
    Returns composite swipe tools for use with Vertex AI LLMs.
    Each tool handles a specific swipe mode to avoid complex Union type issues.
    """

    @tool
    def swipe_coordinates(
        agent_thought: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
        start_x: int = Field(description="Start X coordinate in pixels"),
        start_y: int = Field(description="Start Y coordinate in pixels"),
        end_x: int = Field(description="End X coordinate in pixels"),
        end_y: int = Field(description="End Y coordinate in pixels"),
        duration: int = Field(description="Duration in ms", ge=1, le=10000, default=400),
    ):
        """Swipe using pixel coordinates from start position to end position."""
        swipe_request = SwipeRequest(
            swipe_mode=SwipeStartEndCoordinatesRequest(
                start=CoordinatesSelectorRequest(x=start_x, y=start_y),
                end=CoordinatesSelectorRequest(x=end_x, y=end_y),
            ),
            duration=duration,
        )
        return get_swipe_tool(ctx=ctx).invoke(
            input={
                "tool_call_id": tool_call_id,
                "state": state,
                "agent_thought": agent_thought,
                "swipe_request": swipe_request,
            }
        )

    @tool
    def swipe_percentages(
        agent_thought: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
        start_x_percent: int = Field(description="Start X percent (0-100)", ge=0, le=100),
        start_y_percent: int = Field(description="Start Y percent (0-100)", ge=0, le=100),
        end_x_percent: int = Field(description="End X percent (0-100)", ge=0, le=100),
        end_y_percent: int = Field(description="End Y percent (0-100)", ge=0, le=100),
        duration: int = Field(description="Duration in ms", ge=1, le=10000, default=400),
    ):
        """Swipe using percentage coordinates from start position to end position."""
        swipe_request = SwipeRequest(
            swipe_mode=SwipeStartEndPercentagesRequest(
                start=PercentagesSelectorRequest(
                    x_percent=start_x_percent, y_percent=start_y_percent
                ),
                end=PercentagesSelectorRequest(x_percent=end_x_percent, y_percent=end_y_percent),
            ),
            duration=duration,
        )
        return get_swipe_tool(ctx=ctx).invoke(
            input={
                "tool_call_id": tool_call_id,
                "state": state,
                "agent_thought": agent_thought,
                "swipe_request": swipe_request,
            }
        )

    return [swipe_coordinates, swipe_percentages]


swipe_wrapper = CompositeToolWrapper(
    tool_fn_getter=get_swipe_tool,
    composite_tools_fn_getter=get_composite_swipe_tools,
    on_success_fn=lambda: "Swipe is successful.",
    on_failure_fn=lambda: "Failed to swipe.",
)
