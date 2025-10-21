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
from minitap.mobile_use.services.llm import get_llm, invoke_llm_with_timeout_message, with_fallback
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
            return await _get_state_update(
                ctx=self.ctx, state=state, thoughts=thoughts, update_plan=True
            )

        subgoals_to_examine = get_subgoals_by_ids(
            subgoals=state.subgoal_plan,
            ids=state.complete_subgoals_by_ids,
        )
        if len(subgoals_to_examine) <= 0:
            return await _get_state_update(
                ctx=self.ctx, state=state, thoughts=["No subgoal to examine."]
            )

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

        llm = get_llm(ctx=self.ctx, name="orchestrator", temperature=1).with_structured_output(
            OrchestratorOutput
        )
        llm_fallback = get_llm(
            ctx=self.ctx, name="orchestrator", use_fallback=True, temperature=1
        ).with_structured_output(OrchestratorOutput)
        response: OrchestratorOutput = await with_fallback(
            main_call=lambda: invoke_llm_with_timeout_message(llm.ainvoke(messages)),
            fallback_call=lambda: invoke_llm_with_timeout_message(llm_fallback.ainvoke(messages)),
        )  # type: ignore
        if response.needs_replaning:
            thoughts = [response.reason]
            state.subgoal_plan = fail_current_subgoal(state.subgoal_plan)
            thoughts.append("==== END OF PLAN, REPLANNING ====")
            return await _get_state_update(
                ctx=self.ctx, state=state, thoughts=thoughts, update_plan=True
            )

        state.subgoal_plan = complete_subgoals_by_ids(
            subgoals=state.subgoal_plan,
            ids=response.completed_subgoal_ids,
        )
        thoughts = [response.reason]
        if all_completed(state.subgoal_plan):
            logger.success("All the subgoals have been completed successfully.")
            return await _get_state_update(
                ctx=self.ctx, state=state, thoughts=thoughts, update_plan=True
            )

        if current_subgoal.id not in response.completed_subgoal_ids:
            # The current subgoal is not yet complete.
            return await _get_state_update(
                ctx=self.ctx, state=state, thoughts=thoughts, update_plan=True
            )

        state.subgoal_plan = start_next_subgoal(state.subgoal_plan)
        new_subgoal = get_current_subgoal(state.subgoal_plan)
        thoughts.append(f"==== NEXT SUBGOAL: {new_subgoal} ====")
        return await _get_state_update(
            ctx=self.ctx, state=state, thoughts=thoughts, update_plan=True
        )


async def _get_state_update(
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
        if ctx.on_plan_changes:
            await ctx.on_plan_changes(state.subgoal_plan, False)
    return await state.asanitize_update(ctx=ctx, update=update, agent="orchestrator")
