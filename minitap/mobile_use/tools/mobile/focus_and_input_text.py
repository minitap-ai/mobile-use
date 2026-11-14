from __future__ import annotations

from typing import Annotated, Literal

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel

from minitap.mobile_use.benchmark.runtime import get_runtime
from minitap.mobile_use.benchmark.text_check import (
    TextCheckConfig,
    compare_text,
    find_by_resource_id,
    find_focused_text_element,
)
from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.robustness.text_copy import (
    restore_from_decision,
    split_trailing_enters,
    trailing_newlines_missing,
)
from minitap.mobile_use.tools.text_fidelity import restore_text
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.controller_factory import create_device_controller
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.tools.tool_wrapper import ToolWrapper
from minitap.mobile_use.tools.types import Target
from minitap.mobile_use.tools.utils import (
    focus_element_if_needed,
    legacy_v1,
    move_cursor_to_end_if_bounds,
)
from minitap.mobile_use.utils.logger import get_logger
from minitap.mobile_use.utils.ui_hierarchy import find_element_by_resource_id, get_element_text

logger = get_logger(__name__)


class InputResult(BaseModel):
    """Result of an input operation from the controller layer."""

    ok: bool
    error: str | None = None


async def _controller_input_text(ctx: MobileUseContext, text: str) -> InputResult:
    """
    Thin wrapper to normalize the controller result.
    """
    controller = create_device_controller(ctx)
    success = await controller.input_text(text)
    if success:
        return InputResult(ok=True)
    return InputResult(ok=False, error="Failed to type text")


def get_focus_and_input_text_tool(ctx: MobileUseContext) -> BaseTool:
    @tool
    async def focus_and_input_text(
        agent_thought: str,
        text: str,
        target: Target,
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
    ):
        """
        Focus a text field and type text into it.

        - Ensure the corresponding element is focused (tap if necessary).
        - If bounds are available, tap near the end to place the cursor at the end.
        - Type the provided `text` using the controller.

        Args:
            agent_thought: The thought of the agent.
            text: The text to type.
            target: The target of the text input (if available).
        """
        # Get ablation config to determine execution mode
        ablation_config = ctx.get_ablation_config()

        # P2 F7 (version B only): never type into a field that is not on the screen (the Executor
        # invented a target and the text went into another field at guessed coordinates).
        if ablation_config.p2_tool_fixes and (target.resource_id or target.text):
            from minitap.mobile_use.controllers.unified_controller import (
                UnifiedMobileController as _UMC,
            )
            from minitap.mobile_use.robustness.target_resolution import target_exists

            live = await _UMC(ctx).get_ui_elements()
            if live and not target_exists(live, target.resource_id or None, target.text or None):
                error_message = (
                    f"No element with resource_id={target.resource_id!r} or text={target.text!r} "
                    "is on the current screen: nothing was typed. Target a field that is visible "
                    "in the UI hierarchy."
                )
                tool_message = ToolMessage(
                    tool_call_id=tool_call_id,
                    content=focus_and_input_text_wrapper.on_failure_fn(text, error_message),
                    additional_kwargs={"error": error_message},
                    status="error",
                )
                return Command(
                    update=await state.asanitize_update(
                        ctx=ctx,
                        update={
                            "agents_thoughts": [agent_thought, error_message],
                            EXECUTOR_MESSAGES_KEY: [tool_message],
                        },
                        agent="executor",
                    ),
                )
        use_deterministic = ablation_config.use_deterministic_text
        use_validation = ablation_config.use_post_validation

        focus_method: str | None = None
        
        if use_deterministic:
            # PRODUCTION MODE: Deterministic state machine
            # Step 1: Focus the element
            focus_method = await focus_element_if_needed(ctx=ctx, target=target)
            if not focus_method:
                error_message = "Failed to focus the text input element before typing."
                tool_message = ToolMessage(
                    tool_call_id=tool_call_id,
                    content=focus_and_input_text_wrapper.on_failure_fn(text, error_message),
                    additional_kwargs={"error": error_message},
                    status="error",
                )
                return Command(
                    update=await state.asanitize_update(
                        ctx=ctx,
                        update={
                            "agents_thoughts": [agent_thought, error_message],
                            EXECUTOR_MESSAGES_KEY: [tool_message],
                        },
                        agent="executor",
                    ),
                )

            # Step 2: Move cursor to end
            await move_cursor_to_end_if_bounds(ctx=ctx, state=state, target=target)
        else:
            # ABLATION BASELINE MODE: Simple direct input
            # Just tap on the target without sophisticated focus handling
            logger.warning("Using SIMPLE text input mode (ablation baseline)")
            if target.bounds:
                controller = create_device_controller(ctx)
                center = target.bounds.get_center()
                await controller.tap_at(center.x, center.y)
                focus_method = "simple_tap"
            elif target.resource_id:
                # Try a simple tap by resource_id without verification
                from minitap.mobile_use.controllers.unified_controller import UnifiedMobileController
                controller = UnifiedMobileController(ctx)
                await controller.tap_element(resource_id=target.resource_id, index=target.resource_id_index or 0)
                focus_method = "simple_tap"
            else:
                focus_method = "none"

        # Fix round (M3): type exactly what was meant (escapes, truncation at a quote, goal quotes)
        fidelity = restore_text(
            text, goal=state.initial_goal, decisions=state.structured_decisions
        )
        if fidelity.changes:
            runtime = get_runtime()
            if runtime is not None:
                runtime.event(
                    "text_fidelity", original=text, typed=fidelity.text, changes=fidelity.changes
                )
            logger.info(f"Text fidelity {fidelity.changes}: {text!r} -> {fidelity.text!r}")
            text = fidelity.text

        if ablation_config.p2_tool_fixes:  # P2 F7: type the Cortex's text, not a corrupted copy
            restored = restore_from_decision(text, state.structured_decisions)
            if restored is not None:
                runtime = get_runtime()
                if runtime is not None:
                    runtime.event("p2_text_restored", original=text, typed=restored)
                text = restored

        # Step 3: Type the text
        trailing_enters = 0
        multi_line = "\n" in text.rstrip("\n")
        if ablation_config.p2_tool_fixes and split_trailing_enters(text)[1]:
            # P2 F7: a trailing newline typed into a single-line field (a search box) becomes a
            # space instead of submitting. Type the text, then press Enter once per newline: it
            # submits the field.
            # D5: ONLY for single-line text (split_trailing_enters). Multi-line text is typed whole,
            # trailing newlines included, through the input method: a separate Enter key event
            # right after the text was lost in multi-line editors on held-out seeds, while the
            # newline committed with the text was kept in every observed readback.
            body, trailing_enters = split_trailing_enters(text)
            result = await _controller_input_text(ctx=ctx, text=body)
            if result.ok:
                controller = create_device_controller(ctx)
                for _ in range(trailing_enters):
                    await controller.press_enter()
        else:
            result = await _controller_input_text(ctx=ctx, text=text)
        status: Literal["success", "error"] = "success" if result.ok else "error"

        text_input_content = ""
        readback_element: dict | None = None
        readback_hierarchy: list[dict] | None = None
        if use_validation and status == "success" and target.resource_id:
            # PRODUCTION MODE: Post-validation - verify text was entered
            controller = create_device_controller(ctx)
            screen_data = await controller.get_screen_data()
            state.latest_ui_hierarchy = screen_data.elements
            readback_hierarchy = screen_data.elements
            element = find_element_by_resource_id(
                ui_hierarchy=state.latest_ui_hierarchy,
                resource_id=target.resource_id,
                index=target.resource_id_index,
                legacy_v1=legacy_v1(ctx),
            )
            if element:
                readback_element = element
                text_input_content = get_element_text(element)
        elif not use_validation:
            # ABLATION BASELINE MODE: No validation, just report success
            logger.warning("Skipping post-input validation (ablation baseline)")
            text_input_content = f"(validation skipped) {text}"

        if (
            ablation_config.p2_tool_fixes
            and multi_line
            and text.endswith("\n")
            and readback_element is not None
        ):
            # D3/D5: a final line break can still be lost (the whitespace-normalized check then
            # says MATCH). When the raw readback of this multi-line field has fewer trailing
            # newlines than the text, commit the missing newlines ONCE through the input method
            # (not as Enter key events, which were the ones lost) and read the field again.
            missing = trailing_newlines_missing(text, text_input_content)
            if missing:
                await _controller_input_text(ctx=ctx, text="\n" * missing)
                controller = create_device_controller(ctx)
                screen_data = await controller.get_screen_data()
                state.latest_ui_hierarchy = screen_data.elements
                readback_hierarchy = screen_data.elements
                element = find_element_by_resource_id(
                    ui_hierarchy=state.latest_ui_hierarchy,
                    resource_id=target.resource_id,
                    index=target.resource_id_index,
                    legacy_v1=legacy_v1(ctx),
                )
                if element:
                    readback_element = element
                    text_input_content = get_element_text(element)
                runtime = get_runtime()
                if runtime is not None:
                    runtime.event("p2_trailing_newline_retry", missing=missing)

        agent_outcome = (
            focus_and_input_text_wrapper.on_success_fn(
                text_to_type=text,
                text_from_resource_id=text_input_content,
                target_resource_id=target.resource_id,
                focus_method=focus_method or "unknown",
            )
            if result.ok
            else focus_and_input_text_wrapper.on_failure_fn(text_to_type=text, error=result.error)
        )

        # paper/androidworld-rework: deterministic MATCH/MISMATCH verdict (flag-gated, audit A3)
        if ablation_config.use_text_match_check and result.ok:
            check_feedback, check_failed = await _run_text_match_check(
                ctx=ctx,
                text=text,
                target=target,
                focus_method=focus_method,
                readback_element=readback_element,
                readback_hierarchy=readback_hierarchy,
            )
            agent_outcome = f"{agent_outcome}\n{check_feedback}"
            if check_failed:
                status = "error"

        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=agent_outcome,
            additional_kwargs={"error": result.error} if not result.ok else {},
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

    return focus_and_input_text


async def _run_text_match_check(
    ctx: MobileUseContext,
    text: str,
    target: Target,
    focus_method: str | None,
    readback_element: dict | None,
    readback_hierarchy: list[dict] | None,
) -> tuple[str, bool]:
    """Compare the read-back field value with the intended text. Returns (feedback, failed)."""
    method = "resource_id"
    element = readback_element
    if element is None:
        if readback_hierarchy is None:
            controller = create_device_controller(ctx)
            screen_data = await controller.get_screen_data()
            readback_hierarchy = screen_data.elements
        # Look for the target by resource-id (both hierarchy key formats, see A10), else for
        # the focused text field.
        if target.resource_id:
            element = find_by_resource_id(
                readback_hierarchy, target.resource_id, target.resource_id_index
            )
        if element is None:
            method = "focused_element"
            element = find_focused_text_element(readback_hierarchy)
    actual = get_element_text(element) if element is not None else None
    is_password = element is not None and str(element.get("password", "")).lower() == "true"
    check = compare_text(text, actual, is_password=is_password)

    cfg = ctx.text_check_config or TextCheckConfig()
    failed = cfg.mismatch_as_error and check.verdict in ("MISMATCH", "CASE_ONLY")
    runtime = get_runtime()
    if runtime is not None:
        runtime.record_text_check(
            verdict=check.verdict,
            expected=check.expected,
            actual=check.actual,
            expected_normalized=check.expected_normalized,
            actual_normalized=check.actual_normalized,
            match=check.verdict == "MATCH",
            readback_method=method if element is not None else "none",
            focus_method=focus_method,
            target_resource_id=target.resource_id,
            marked_as_error=failed,
        )
    logger.info(f"Text match check: {check.verdict} (expected={text!r}, actual={actual!r})")
    feedback = check.as_feedback()
    _abl = getattr(ctx, "get_ablation_config", None)
    _p2_fixes = bool(_abl and getattr(_abl(), "p2_tool_fixes", False))
    if _p2_fixes and method == "focused_element" and element is not None:
        # P2 F7: typed by coordinates: say WHICH field received the text, so a field that changed
        # under the finger (a dialog that closed, focus that moved) is visible to the agent.
        rid = element.get("resource-id") or element.get("resourceId") or ""
        hint = element.get("hint") or element.get("hintText") or element.get("content-desc") or ""
        name = " ".join(x for x in (repr(rid) if rid else "", f"hint {hint!r}" if hint else "") if x) or "unnamed field"
        feedback += f" (read back from the focused field {name}: check it is the field you meant)"
    return feedback, failed


def _on_input_success(text_to_type, text_from_resource_id, target_resource_id, focus_method):
    """Success message handler for input text operations."""
    if focus_method == "resource_id":
        return (
            f"Typed {repr(text_to_type)}\n"
            f"Here is the whole content of input with id {repr(target_resource_id)}: "
            f"{repr(text_from_resource_id)}"
        )
    else:
        return (
            f"Typed {repr(text_to_type)} using {focus_method}."
            + " Should now verify before moving forward."
        )


focus_and_input_text_wrapper = ToolWrapper(
    tool_fn_getter=get_focus_and_input_text_tool,
    on_success_fn=_on_input_success,
    on_failure_fn=lambda text, error: f"Failed to input text {repr(text)}. Reason: {error}",
)
