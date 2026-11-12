"""P2 F3: the goal turned once into an explicit requirement checklist (Cortex model).

The checklist is derived from the goal text only (task-agnostic). It is shown to the Planner,
the Cortex and the goal verifier, which judges every requirement separately.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Template
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from minitap.mobile_use.benchmark.runtime import get_runtime
from minitap.mobile_use.services.llm import get_llm, invoke_llm_with_timeout_message, with_fallback
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


class ChecklistOutput(BaseModel):
    requirements: list[str] = Field(description="Numbered atomic requirements, verbatim values.")


def render_checklist(items: list[str] | None) -> str | None:
    if not items:
        return None
    return "\n".join(f"{i}. {r.strip()}" for i, r in enumerate(items, 1))


async def ensure_goal_checklist(ctx, goal: str) -> list[str] | None:
    if not ctx.get_ablation_config().p2_checklist:
        return None
    if ctx.p2_goal_checklist is not None:
        return ctx.p2_goal_checklist
    system = Template(Path(__file__).with_name("checklist.md").read_text(encoding="utf-8")).render(
        platform=ctx.device.mobile_platform.value, initial_goal=goal
    )
    messages = [SystemMessage(content=system), HumanMessage(content="Write the checklist.")]
    llm = get_llm(ctx=ctx, name="cortex", temperature=1).with_structured_output(ChecklistOutput)
    llm_fb = get_llm(ctx=ctx, name="cortex", use_fallback=True, temperature=1).with_structured_output(
        ChecklistOutput
    )
    try:
        out: ChecklistOutput = await with_fallback(
            main_call=lambda: invoke_llm_with_timeout_message(llm.ainvoke(messages)),
            fallback_call=lambda: invoke_llm_with_timeout_message(llm_fb.ainvoke(messages)),
        )  # type: ignore
        items = [r.strip() for r in out.requirements if r and r.strip()][:20]
    except Exception as e:  # never block the task on the checklist
        logger.warning(f"goal checklist failed: {e}")
        items = []
    ctx.p2_goal_checklist = items
    runtime = get_runtime()
    if runtime is not None:
        runtime.event("p2_checklist", requirements=items)
    return items
