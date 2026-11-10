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
