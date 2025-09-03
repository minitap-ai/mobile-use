import uuid
from pathlib import Path

from jinja2 import Template
from langchain_core.messages import HumanMessage, SystemMessage

from minitap.mobile_use.agents.planner.types import PlannerOutput, Subgoal, SubgoalStatus
from minitap.mobile_use.agents.planner.utils import one_of_them_is_failure
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.services.llm import get_llm
from minitap.mobile_use.tools.index import EXECUTOR_WRAPPERS_TOOLS, format_tools_list
from minitap.mobile_use.utils.decorators import wrap_with_callbacks
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


class PlannerNode:
    def __init__(self, ctx: MobileUseContext):
        self.ctx = ctx

    @wrap_with_callbacks(
        before=lambda: logger.info("Starting Planner Agent..."),
        on_success=lambda _: logger.success("Planner Agent"),
        on_failure=lambda _: logger.error("Planner Agent"),
    )
    async def __call__(self, state: State):
        needs_replan = one_of_them_is_failure(state.subgoal_plan)

        system_message = Template(
            Path(__file__).parent.joinpath("planner.md").read_text(encoding="utf-8")
        ).render(
            platform=self.ctx.device.mobile_platform.value,
            executor_tools_list=format_tools_list(ctx=self.ctx, wrappers=EXECUTOR_WRAPPERS_TOOLS),
        )
        human_message = Template(
            Path(__file__).parent.joinpath("human.md").read_text(encoding="utf-8")
        ).render(
            action="replan" if needs_replan else "plan",
            initial_goal=state.initial_goal,
            previous_plan="\n".join(str(s) for s in state.subgoal_plan),
            agent_thoughts="\n".join(state.agents_thoughts),
        )
        messages = [
            SystemMessage(content=system_message),
            HumanMessage(content=human_message),
        ]

        llm = get_llm(ctx=self.ctx, name="planner")
        llm = llm.with_structured_output(PlannerOutput)
        response: PlannerOutput = await llm.ainvoke(messages)  # type: ignore

        subgoals_plan = [
            Subgoal(
                id=subgoal.id or str(uuid.uuid4()),
                description=subgoal.description,
                status=SubgoalStatus.NOT_STARTED,
                completion_reason=None,
            )
            for subgoal in response.subgoals
        ]
        logger.info("📜 Generated plan:")
        logger.info("\n".join(str(s) for s in subgoals_plan))

        return state.sanitize_update(
            ctx=self.ctx,
            update={
                "subgoal_plan": subgoals_plan,
            },
            agent="planner",
        )
