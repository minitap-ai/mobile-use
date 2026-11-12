"""P2 tools (version B only; registered when their `p2_*` flag is on, see `p2_tool_wrappers`)."""

from __future__ import annotations

import asyncio
from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import BaseTool, InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from minitap.mobile_use.config import AblationConfig
from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.robustness.calculator import calculate as safe_calculate
from minitap.mobile_use.robustness.list_reader import android_device, read_full_list
from minitap.mobile_use.tools.tool_wrapper import ToolWrapper
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


async def _command(ctx, state, tool_call_id, agent_thought, outcome, ok: bool):
    tool_message = ToolMessage(
        tool_call_id=tool_call_id, content=outcome, status="success" if ok else "error"
    )
    return Command(
        update=await state.asanitize_update(
            ctx=ctx,
            update={
                "agents_thoughts": [agent_thought, outcome],
                EXECUTOR_MESSAGES_KEY: [tool_message],
            },
            agent="executor",
        )
    )


def get_read_full_list_tool(ctx: MobileUseContext) -> BaseTool:
    @tool
    async def read_full_list(
        agent_thought: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
        container_resource_id: str | None = None,
    ) -> Command:
        """Read the WHOLE scrollable list or document on the current screen, top to bottom.

        Scrolls the main scrollable container to its top, then page by page to its end, and
        returns every row once, in order (identical rows are kept, so duplicates are counted),
        then scrolls back to the top. Use it before answering a question about items in a list,
        before counting, before deciding which items are duplicates/newest/missing, and before
        declaring a multi-item goal done. It never taps. Collapsed groups (e.g. a hidden
        "completed" section) are not expanded: expand them first.

        Args:
            container_resource_id: optional resource-id of the scrollable container to read when
                the screen has several; by default the largest one.
        """
        try:
            dev = android_device(ctx)
            result = await asyncio.to_thread(read_full_list, dev, container_resource_id)
            outcome, ok = result.render(), result.error is None
            if ok:
                app = ""
                try:
                    from minitap.mobile_use.controllers.platform_specific_commands_controller import (
                        get_current_foreground_package,
                    )

                    app = get_current_foreground_package(ctx) or ""
                except Exception:
                    pass
                ctx.p2_tool_evidence = ((ctx.p2_tool_evidence or []) + [f"[{app}] {outcome[:4000]}"])[-6:]
        except Exception as e:  # device errors are reported, not raised
            logger.warning(f"read_full_list failed: {e}")
            outcome, ok = f"read_full_list failed: {e}", False
        return await _command(ctx, state, tool_call_id, agent_thought, outcome, ok)

    return read_full_list


def get_calculate_tool(ctx: MobileUseContext) -> BaseTool:
    @tool
    async def calculate(
        agent_thought: str,
        expression: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
    ) -> Command:
        """Evaluate arithmetic exactly (never compute counts, sums, products or durations in
        your head). Python syntax: + - * / // % **, parentheses, lists, and the functions
        round, abs, min, max, sum, len, prod, sqrt, floor, ceil,
        convert(value, "from_unit", "to_unit") for length (m, km, mi, ft, yd, in), time
        (s, min, h, day, week), mass (g, kg, lb, oz) and temperature (C, F),
        seconds("h:mm:ss" or "m:ss") and hms(seconds).
        Example: sum([seconds("3:45"), seconds("4:10")]) or round(convert(1.24, "mi", "m")).
        """
        try:
            value = safe_calculate(expression)
            outcome, ok = f"calculate({expression}) = {value!r}", True
        except Exception as e:
            outcome, ok = f"calculate({expression}) failed: {e}", False
        return await _command(ctx, state, tool_call_id, agent_thought, outcome, ok)

    return calculate


read_full_list_wrapper = ToolWrapper(
    tool_fn_getter=get_read_full_list_tool,
    on_success_fn=lambda: "read_full_list done.",
    on_failure_fn=lambda: "read_full_list failed.",
)
calculate_wrapper = ToolWrapper(
    tool_fn_getter=get_calculate_tool,
    on_success_fn=lambda: "calculate done.",
    on_failure_fn=lambda: "calculate failed.",
)


def p2_tool_wrappers(ablation: AblationConfig) -> list[ToolWrapper]:
    """Extra Executor tools of version B; empty for every version-A config."""
    out: list[ToolWrapper] = []
    if getattr(ablation, "p2_coverage", False):
        out.append(read_full_list_wrapper)
    if getattr(ablation, "p2_tally", False):
        out.append(calculate_wrapper)
    return out
