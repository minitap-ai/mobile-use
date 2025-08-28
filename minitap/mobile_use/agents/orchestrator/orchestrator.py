from pathlib import Path

from jinja2 import Template
from langchain_core.messages import HumanMessage, SystemMessage

from minitap.mobile_use.agents.orchestrator.types import OrchestratorOutput
from minitap.mobile_use.agents.planner.utils import (
    all_completed,
    complete_subgoals_by_ids,
    fail_current_subgoal,
    get_current_subgoal,
    get_subgoals_by_ids,
    nothing_started,
    start_next_subgoal,
)
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.services.llm import get_llm
from minitap.mobile_use.utils.decorators import wrap_with_callbacks
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


class OrchestratorNode:
    def __init__(self, ctx: MobileUseContext):
        self.ctx = ctx

    @wrap_with_callbacks(
        before=lambda: logger.info("Starting Orchestrator Agent..."),
        on_success=lambda _: logger.success("Orchestrator Agent"),
        on_failure=lambda _: logger.error("Orchestrator Agent"),
    )
    async def __call__(self, state: State):
        no_subgoal_started = nothing_started(state.subgoal_plan)
        current_subgoal = get_current_subgoal(state.subgoal_plan)

        if no_subgoal_started or not current_subgoal:
            state.subgoal_plan = start_next_subgoal(state.subgoal_plan)
            new_subgoal = get_current_subgoal(state.subgoal_plan)
            thoughts = [
                (
                    f"Starting the first subgoal: {new_subgoal}"
                    if no_subgoal_started
                    else f"Starting the next subgoal: {new_subgoal}"
                )
            ]
            return _get_state_update(ctx=self.ctx, state=state, thoughts=thoughts, update_plan=True)

        subgoals_to_examine = get_subgoals_by_ids(
            subgoals=state.subgoal_plan,
            ids=state.complete_subgoals_by_ids,
        )
        if len(subgoals_to_examine) <= 0:
            return _get_state_update(ctx=self.ctx, state=state, thoughts=["No subgoal to examine."])

        system_message = Template(
            Path(__file__).parent.joinpath("orchestrator.md").read_text(encoding="utf-8")
        ).render(platform=self.ctx.device.mobile_platform.value)
        human_message = Template(
            Path(__file__).parent.joinpath("human.md").read_text(encoding="utf-8")
        ).render(
            initial_goal=state.initial_goal,
            subgoal_plan="\n".join(str(s) for s in state.subgoal_plan),
            subgoals_to_examine="\n".join(str(s) for s in subgoals_to_examine),
            agent_thoughts="\n".join(state.agents_thoughts),
        )
        messages = [
            SystemMessage(content=system_message),
            HumanMessage(content=human_message),
        ]

        llm = get_llm(ctx=self.ctx, name="orchestrator", temperature=1)
        llm = llm.with_structured_output(OrchestratorOutput)
        response: OrchestratorOutput = await llm.ainvoke(messages)  # type: ignore

        if response.needs_replaning:
            thoughts = [response.reason]
            state.subgoal_plan = fail_current_subgoal(state.subgoal_plan)
            thoughts.append("==== END OF PLAN, REPLANNING ====")
            return _get_state_update(ctx=self.ctx, state=state, thoughts=thoughts, update_plan=True)

        state.subgoal_plan = complete_subgoals_by_ids(
            subgoals=state.subgoal_plan,
            ids=response.completed_subgoal_ids,
        )
        thoughts = [response.reason]
        if all_completed(state.subgoal_plan):
            logger.success("All the subgoals have been completed successfully.")
            return _get_state_update(ctx=self.ctx, state=state, thoughts=thoughts, update_plan=True)

        if current_subgoal.id not in response.completed_subgoal_ids:
            # The current subgoal is not yet complete.
            return _get_state_update(ctx=self.ctx, state=state, thoughts=thoughts, update_plan=True)

        state.subgoal_plan = start_next_subgoal(state.subgoal_plan)
        new_subgoal = get_current_subgoal(state.subgoal_plan)
        thoughts.append(f"==== NEXT SUBGOAL: {new_subgoal} ====")
        return _get_state_update(ctx=self.ctx, state=state, thoughts=thoughts, update_plan=True)


def _get_state_update(
    ctx: MobileUseContext,
    state: State,
    thoughts: list[str],
    update_plan: bool = False,
):
    update = {
        "agents_thoughts": thoughts,
        "complete_subgoals_by_ids": [],
    }
    if update_plan:
        update["subgoal_plan"] = state.subgoal_plan
    return state.sanitize_update(ctx=ctx, update=update, agent="orchestrator")
