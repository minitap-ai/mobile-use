"""P2 tools (version B only; registered when their `p2_*` flag is on, see `p2_tool_wrappers`)."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any

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
from minitap.mobile_use.robustness.list_reader import android_device
from minitap.mobile_use.robustness.list_reader import read_full_list as read_full_list_helper
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
            # NB: the @tool below is also named read_full_list; call the helper explicitly
            result = await asyncio.to_thread(read_full_list_helper, dev, container_resource_id)
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


def normalize_points(raw) -> list[dict]:
    """Accept the shapes models send: a JSON string, [[x, y], ...], [{"x":..,"y":..}], {"x","y"}."""
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if isinstance(raw, dict):
        raw = [raw]
    out = []
    for p in raw if isinstance(raw, list) else []:
        if isinstance(p, dict) and "x" in p and "y" in p:
            out.append({"x": int(p["x"]), "y": int(p["y"]), **({"label": p["label"]} if p.get("label") else {})})
        elif isinstance(p, list | tuple) and len(p) >= 2:
            out.append({"x": int(p[0]), "y": int(p[1])})
    return out


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(int(v) for v in rgb[:3])


def sample_colors_at(image, points: list[dict]) -> list[str]:
    """Exact colour at each point plus the most common colour in its 5x5 neighbourhood
    (anti-aliased edges and thin strokes)."""
    from collections import Counter

    img = image.convert("RGB")
    w, h = img.size
    out = []
    for p in points:
        x, y = int(p["x"]), int(p["y"])
        if not (0 <= x < w and 0 <= y < h):
            out.append(f"({x},{y}): outside the screen ({w}x{h})")
            continue
        centre = _hex(img.getpixel((x, y)))
        hood = Counter(
            _hex(img.getpixel((min(max(x + dx, 0), w - 1), min(max(y + dy, 0), h - 1))))
            for dx in range(-2, 3)
            for dy in range(-2, 3)
        )
        mode, n = hood.most_common(1)[0]
        label = f" {p['label']}" if p.get("label") else ""
        out.append(f"({x},{y}){label}: {centre} (5x5 most common {mode}, {n}/25)")
    return out


def get_sample_colors_tool(ctx: MobileUseContext) -> BaseTool:
    @tool
    async def sample_colors(
        agent_thought: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
        points: Any = None,
        coordinates: Any = None,
    ) -> Command:
        """Read the EXACT colour (hex) of screen pixels from a lossless screenshot.

        Use it to compare similar-looking colours (e.g. a target colour shown on screen vs the
        colour options or swatches): never judge shades by eye or by name.

        Args:
            points: list of {"x": int, "y": int, "label": optional str} screen coordinates
                (pixels), e.g. the centre of each swatch and of the reference colours.
        """
        try:
            from minitap.mobile_use.controllers.platform_specific_commands_controller import (
                get_adb_device,
            )

            pts = normalize_points(points if points is not None else coordinates)
            if not pts:
                raise ValueError("no points given: pass points=[{\"x\": 10, \"y\": 20}, ...]")
            image = await asyncio.to_thread(get_adb_device(ctx).screenshot)
            lines = sample_colors_at(image, pts[:40])
            outcome, ok = "Exact pixel colours:\n" + "\n".join(lines), True
        except Exception as e:
            outcome, ok = f"sample_colors failed: {e}", False
        return await _command(ctx, state, tool_call_id, agent_thought, outcome, ok)

    return sample_colors


sample_colors_wrapper = ToolWrapper(
    tool_fn_getter=get_sample_colors_tool,
    on_success_fn=lambda: "sample_colors done.",
    on_failure_fn=lambda: "sample_colors failed.",
)


def get_inspect_rows_tool(ctx: MobileUseContext) -> BaseTool:
    @tool
    async def inspect_rows(
        agent_thought: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
        match: str = "",
        detail_contains: str | None = None,
    ) -> Command:
        """Open rows of the current list one by one, read ALL the fields of each detail screen,
        go back, and report them, in ONE call (read-only: never edits or deletes). Rows are
        identified by their position in the list ("row 14"), so identical-looking cards stay
        distinct, and records identical on EVERY detail field are grouped for you.
        Use it (a) to compare look-alike records, e.g. to find exact duplicates: match = the text
        the cards share; (b) to find the records whose DETAILS contain a text that the list or a
        search box does not show (e.g. an ingredient, a note): match = "" (every row) and
        detail_contains = that text; (c) to check the saved fields of items.

        Args:
            match: only rows whose card text contains this ("" = every row of the list).
            detail_contains: report only rows whose detail screen contains this text.
        """
        try:
            from minitap.mobile_use.robustness.row_inspector import inspect_rows as _inspect

            dev = android_device(ctx)
            match, detail_contains = _no_null(match) or "", _no_null(detail_contains)
            res = await asyncio.to_thread(_inspect, dev, match or "", detail_contains)
            outcome, ok = res.render(), res.error is None
            if ok:
                ctx.p2_tool_evidence = ((ctx.p2_tool_evidence or []) + [f"[inspect_rows match={match!r} detail_contains={detail_contains!r}] {outcome[:12000]}"])[-6:]
        except Exception as e:
            outcome, ok = f"inspect_rows failed: {e}", False
        return await _command(ctx, state, tool_call_id, agent_thought, outcome, ok)

    return inspect_rows


inspect_rows_wrapper = ToolWrapper(
    tool_fn_getter=get_inspect_rows_tool,
    on_success_fn=lambda: "inspect_rows done.",
    on_failure_fn=lambda: "inspect_rows failed.",
)


def _no_null(v):
    """Models sometimes send the string "null"/"None" for an omitted optional argument."""
    if v is None:
        return None
    t = str(v).strip()
    return None if t.lower() in ("", "null", "none", "undefined", '""', "''") else t


def p2_tool_wrappers(ablation: AblationConfig) -> list[ToolWrapper]:
    """Extra Executor tools of version B; empty for every version-A config."""
    out: list[ToolWrapper] = []
    if getattr(ablation, "p2_coverage", False):
        out.append(read_full_list_wrapper)
        out.append(inspect_rows_wrapper)
    if getattr(ablation, "p2_tally", False):
        out.append(calculate_wrapper)
    if getattr(ablation, "p2_disambiguation", False):
        out.append(sample_colors_wrapper)
    return out
