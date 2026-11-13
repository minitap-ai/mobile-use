"""P2 F3: the goal turned once into an explicit requirement checklist (Cortex model).

The checklist is derived from the goal text only (task-agnostic). It is shown to the Planner,
the Cortex and the goal verifier, which judges every requirement separately.
"""

from __future__ import annotations

import re
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


# D3: fixed requirements for goals that copy records into an app from a named source file or image.
# The checklist LLM sometimes dropped the marker rule or turned the goal's word for the records into a
# filter (both rules exist in the prompts); these lines are appended deterministically instead.
# Trigger (goal wording only): a copy verb (add / log / enter / import / copy) and a source named as a
# file with a document or image extension, introduced by "from" or "in".
_SOURCE_FILE = r"\b(?:from|in)\s+(?:the\s+)?[\w.-]+\.(?:txt|md|csv|jpg|jpeg|png)\b"
_COPY_VERB = r"\b(?:add|log|enter|import|copy)\b"
_SOURCE_COPY_RE = re.compile(
    rf"{_COPY_VERB}.*?{_SOURCE_FILE}|{_SOURCE_FILE}.*?{_COPY_VERB}", re.IGNORECASE | re.DOTALL
)
SOURCE_COPY_REQUIREMENTS = [
    "Every record in the named source file or image is in scope. The goal's word for the records "
    '(e.g. "the entries", "the items", "the purchases") names the kind of record, not a filter: a '
    "record's own category or type value never excludes it. Only a condition the goal states in words "
    '(e.g. "the flagged ones", "the ones over 50") selects records.',
    "If the goal selects records by a property that the source writes as a tag or marker word on each "
    'record (e.g. a note ending in "Flagged."), that marker is left out of the copied fields; every '
    "other field is copied exactly as in the source.",
]


def is_source_copy_goal(goal: str) -> bool:
    return bool(_SOURCE_COPY_RE.search(goal or ""))


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
    if is_source_copy_goal(goal):
        items = items + SOURCE_COPY_REQUIREMENTS
    ctx.p2_goal_checklist = items
    runtime = get_runtime()
    if runtime is not None:
        runtime.event("p2_checklist", requirements=items)
    return items
