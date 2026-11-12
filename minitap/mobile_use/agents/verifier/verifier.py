"""Goal verification before the task ends (fix round, failure class M1: completion accepted
without evidence). Task-agnostic: the goal text is the only task input."""

from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Template
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from minitap.mobile_use.agents.planner.types import Subgoal, SubgoalStatus
from minitap.mobile_use.agents.planner.utils import generate_id
from minitap.mobile_use.benchmark.runtime import get_runtime
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.controller_factory import create_device_controller
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.services.llm import get_llm, invoke_llm_with_timeout_message, with_fallback
from minitap.mobile_use.utils.conversations import get_screenshot_message_for_llm
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)

MAX_REJECTIONS = 2  # per task; after that the task ends as the agents decided
RECENT_THOUGHTS = 40


class VerifierOutput(BaseModel):
    satisfied: bool = Field(description="True only if every requirement of the goal is met.")
    evidence: str = Field(description="What was checked and seen (1-3 sentences).")
    missing: str | None = Field(
        default=None, description="Requirement(s) still missing, actionable. Null if satisfied."
    )
    answer: str | None = Field(
        default=None, description="Final answer if the goal asks for information, else null."
    )


def rejection_update(state: State, out: VerifierOutput) -> tuple[list[Subgoal], list[str]]:
    """Plan with one FAILED subgoal carrying what is missing (convergence/post-gate -> replan)."""
    plan = [s.model_copy() for s in state.subgoal_plan]
    missing = (out.missing or "the goal is not fully satisfied").strip()
    plan.append(
        Subgoal(
            id=generate_id(),
            description=f"Satisfy the remaining goal requirement: {missing}",
            status=SubgoalStatus.FAILURE,
            completion_reason=f"Goal verification failed: {out.evidence}",
        )
    )
    thoughts = [
        f"Goal verification FAILED. Evidence: {out.evidence} Missing: {missing}",
        "==== GOAL NOT VERIFIED, REPLANNING ====",
    ]
    return plan, thoughts


class GoalVerifierNode:
    def __init__(self, ctx: MobileUseContext):
        self.ctx = ctx

    async def __call__(self, state: State):
        ctx = self.ctx
        if p2_verifier_active(ctx.get_ablation_config()):
            return await self._call_p2(state)  # version B only
        runtime = get_runtime()
        if ctx.goal_verification_rejections >= MAX_REJECTIONS:
            logger.warning("Goal verification limit reached; ending as decided by the agents")
            if runtime is not None:
                runtime.event("goal_verification", verdict="skipped_limit")
            return {}

        use_vision = ctx.get_ablation_config().use_vision
        controller = create_device_controller(ctx)
        screen = await controller.get_screen_data()
        system = Template(
            Path(__file__).parent.joinpath("verifier.md").read_text(encoding="utf-8")
        ).render(
            platform=ctx.device.mobile_platform.value,
            initial_goal=state.initial_goal,
            use_vision=use_vision,
        )
        thoughts = "\n".join(state.agents_thoughts[-RECENT_THOUGHTS:])
        messages = [
            SystemMessage(content=system),
            HumanMessage(
                content="Plan as executed:\n"
                + "\n".join(str(s) for s in state.subgoal_plan)
                + "\n\nRecent agent thoughts (oldest first):\n"
                + thoughts
            ),
            HumanMessage(
                content="Current UI hierarchy:\n"
                + json.dumps(screen.elements, indent=1, ensure_ascii=False)
            ),
        ]
        if use_vision and screen.base64:
            messages.append(
                get_screenshot_message_for_llm(
                    controller.get_compressed_b64_screenshot(screen.base64)
                )
            )

        llm = get_llm(ctx=ctx, name="cortex", temperature=1).with_structured_output(VerifierOutput)
        llm_fallback = get_llm(
            ctx=ctx, name="cortex", use_fallback=True, temperature=1
        ).with_structured_output(VerifierOutput)
        out: VerifierOutput = await with_fallback(
            main_call=lambda: invoke_llm_with_timeout_message(llm.ainvoke(messages)),
            fallback_call=lambda: invoke_llm_with_timeout_message(llm_fallback.ainvoke(messages)),
        )  # type: ignore

        if runtime is not None:
            runtime.event(
                "goal_verification",
                verdict="satisfied" if out.satisfied else "rejected",
                evidence=out.evidence,
                missing=out.missing,
                answer=out.answer,
                rejections_before=ctx.goal_verification_rejections,
            )

        if out.satisfied:
            new_thoughts = [f"Goal verification PASSED: {out.evidence}"]
            if out.answer:
                new_thoughts.append(f"Final answer: {out.answer}")
            return await state.asanitize_update(
                ctx=ctx, update={"agents_thoughts": new_thoughts}, agent="cortex"
            )

        ctx.goal_verification_rejections += 1
        plan, new_thoughts = rejection_update(state, out)
        if ctx.on_plan_changes:
            await ctx.on_plan_changes(plan, False)
        return await state.asanitize_update(
            ctx=ctx,
            update={"agents_thoughts": new_thoughts, "subgoal_plan": plan},
            agent="cortex",
        )


# ---------------------------------------------------------------------------------------------
# P2 (version B): per-requirement verification on device evidence (F3), complete list content
# (F1), calendar facts (F2), final-state hygiene (F4). Version A never reaches this code.

P2_MAX_REJECTIONS = 3


class P2Check(BaseModel):
    requirement: str
    met: bool
    evidence: str


class P2VerifierOutput(VerifierOutput):
    checks: list[P2Check] = Field(default_factory=list)


def p2_verifier_active(ablation) -> bool:
    return bool(
        ablation.p2_checklist or ablation.p2_coverage or ablation.p2_final_state or ablation.p2_tally
    )


def _has_edit_field(xml_text: str) -> bool:
    return "android.widget.EditText" in xml_text


async def _p2_full_read(ctx) -> str | None:
    """Complete content of the current screen's main list (never on forms/editors)."""
    import asyncio
    import xml.etree.ElementTree as ET

    from minitap.mobile_use.robustness.list_reader import (
        android_device,
        find_main_container,
        read_full_list,
    )

    dev = android_device(ctx)
    xml_text = dev.dump_xml()
    root = ET.fromstring(xml_text)
    cont = find_main_container(root, dev.screen_w * dev.screen_h)
    if cont is None or _has_edit_field(ET.tostring(cont.node, encoding="unicode")):
        return None
    result = await asyncio.to_thread(read_full_list, dev)
    return None if result.error else result.render()


async def _p2_hide_keyboard(ctx) -> str:
    from minitap.mobile_use.controllers.platform_specific_commands_controller import (
        get_adb_device,
    )
    from minitap.mobile_use.robustness.device_state import hide_soft_keyboard

    return hide_soft_keyboard(get_adb_device(ctx))


async def _p2_call(self, state: State):
    from minitap.mobile_use.controllers.platform_specific_commands_controller import (
        get_device_date,
    )
    from minitap.mobile_use.robustness.calendar_context import calendar_context
    from minitap.mobile_use.robustness.checklist import render_checklist

    ctx = self.ctx
    ablation = ctx.get_ablation_config()
    runtime = get_runtime()
    android = ctx.device.mobile_platform.value.lower() == "android"

    if ablation.p2_final_state and android:
        try:
            kb = await _p2_hide_keyboard(ctx)
        except Exception as e:
            kb = f"error: {e}"
        if runtime is not None:
            runtime.event("p2_final_state", keyboard=kb)

    max_rejections = P2_MAX_REJECTIONS if ablation.p2_checklist else MAX_REJECTIONS
    if ctx.goal_verification_rejections >= max_rejections:
        logger.warning("Goal verification limit reached; ending as decided by the agents")
        if runtime is not None:
            runtime.event("goal_verification", verdict="skipped_limit")
        return {}

    full_read = None
    if ablation.p2_coverage and android:
        try:
            full_read = await _p2_full_read(ctx)
        except Exception as e:
            logger.warning(f"verifier full read failed: {e}")
        if runtime is not None:
            runtime.event("p2_verifier_full_read", read=bool(full_read))

    calendar = None
    if ablation.p2_tally:
        try:
            calendar = calendar_context(get_device_date(ctx))
        except Exception:
            calendar = None

    from minitap.mobile_use.robustness.screen_log import render_screen_log

    screen_log = render_screen_log(ctx.p2_screen_log) if ablation.p2_checklist else None
    use_vision = ablation.use_vision
    controller = create_device_controller(ctx)
    screen = await controller.get_screen_data()
    system = Template(
        Path(__file__).parent.joinpath("verifier_p2.md").read_text(encoding="utf-8")
    ).render(
        platform=ctx.device.mobile_platform.value,
        initial_goal=state.initial_goal,
        use_vision=use_vision,
        checklist_text=render_checklist(ctx.p2_goal_checklist) if ablation.p2_checklist else None,
        calendar=calendar,
        has_full_read=bool(full_read),
        has_screen_log=bool(screen_log),
    )
    thoughts = "\n".join(state.agents_thoughts[-RECENT_THOUGHTS:])
    notes = "\n".join(f"- {k}: {v}" for k, v in (state.scratchpad or {}).items())
    messages = [
        SystemMessage(content=system),
        HumanMessage(
            content="Plan as executed:\n"
            + "\n".join(str(s) for s in state.subgoal_plan)
            + ("\n\nAgent notes (scratchpad):\n" + notes if notes else "")
            + "\n\nRecent agent thoughts (oldest first):\n"
            + thoughts
        ),
        HumanMessage(
            content="Current UI hierarchy:\n"
            + json.dumps(screen.elements, indent=1, ensure_ascii=False)
        ),
    ]
    if ablation.p2_disambiguation and ctx.p2_sort_fact:
        messages.append(HumanMessage(content=ctx.p2_sort_fact))
    if ablation.p2_checklist and ctx.p2_tool_evidence:
        messages.append(
            HumanMessage(
                content="Complete list reads done earlier by the agents' read_full_list tool "
                "(deterministic tool outputs, oldest first):\n" + "\n\n".join(ctx.p2_tool_evidence)
            )
        )
    if screen_log:
        messages.append(
            HumanMessage(
                content="UI text of the recent screens, captured from the device (oldest first; "
                "this is what the screens actually showed, not what the agents said):\n" + screen_log
            )
        )
    if full_read:
        messages.append(
            HumanMessage(
                content="Complete content of the main list/document on the current screen "
                "(read deterministically, top to bottom, just now):\n" + full_read
            )
        )
    if use_vision and screen.base64:
        messages.append(
            get_screenshot_message_for_llm(controller.get_compressed_b64_screenshot(screen.base64))
        )

    llm = get_llm(ctx=ctx, name="cortex", temperature=1).with_structured_output(P2VerifierOutput)
    llm_fallback = get_llm(
        ctx=ctx, name="cortex", use_fallback=True, temperature=1
    ).with_structured_output(P2VerifierOutput)
    out: P2VerifierOutput = await with_fallback(
        main_call=lambda: invoke_llm_with_timeout_message(llm.ainvoke(messages)),
        fallback_call=lambda: invoke_llm_with_timeout_message(llm_fallback.ainvoke(messages)),
    )  # type: ignore
    if out.checks and any(not c.met for c in out.checks):
        out.satisfied = False
        if not out.missing:
            out.missing = "; ".join(c.requirement for c in out.checks if not c.met)

    if runtime is not None:
        runtime.event(
            "goal_verification",
            verdict="satisfied" if out.satisfied else "rejected",
            evidence=out.evidence,
            missing=out.missing,
            answer=out.answer,
            rejections_before=ctx.goal_verification_rejections,
            checks=[c.model_dump() for c in out.checks],
        )

    if out.satisfied:
        new_thoughts = [f"Goal verification PASSED: {out.evidence}"]
        if out.answer:
            new_thoughts.append(f"Final answer: {out.answer}")
        return await state.asanitize_update(
            ctx=ctx, update={"agents_thoughts": new_thoughts}, agent="cortex"
        )

    ctx.goal_verification_rejections += 1
    plan, new_thoughts = rejection_update(state, out)
    if ctx.on_plan_changes:
        await ctx.on_plan_changes(plan, False)
    return await state.asanitize_update(
        ctx=ctx,
        update={"agents_thoughts": new_thoughts, "subgoal_plan": plan},
        agent="cortex",
    )


GoalVerifierNode._call_p2 = _p2_call  # type: ignore[attr-defined]
