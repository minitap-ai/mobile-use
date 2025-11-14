from typing import Annotated

from langchain_core.messages import AIMessage, AnyMessage
from langgraph.graph import add_messages
from pydantic import BaseModel

from minitap.mobile_use.agents.planner.types import Subgoal
from minitap.mobile_use.config import AgentNode
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.utils.logger import get_logger
from minitap.mobile_use.utils.recorder import record_interaction

logger = get_logger(__name__)


def take_last(a, b):
    return b


class State(BaseModel):
    messages: Annotated[list[AnyMessage], "Sequential messages", add_messages]
    remaining_steps: Annotated[int | None, "Remaining steps before the task is completed"] = None

    # planner related keys
    initial_goal: Annotated[str, "Initial goal given by the user"]

    # orchestrator related keys
    subgoal_plan: Annotated[list[Subgoal], "The current plan, made of subgoals"]

    # contextor related keys
    latest_ui_hierarchy: Annotated[
        list[dict] | None, "Latest UI hierarchy of the device", take_last
    ]
    focused_app_info: Annotated[str | None, "Focused app info", take_last]
    device_date: Annotated[str | None, "Date of the device", take_last]

    # cortex related keys
    structured_decisions: Annotated[
        str | None,
        "Structured decisions made by the cortex, for the executor to follow",
        take_last,
    ]
    complete_subgoals_by_ids: Annotated[
        list[str],
        "List of subgoal IDs to complete",
        take_last,
    ]

    # screen_analyzer related keys
    screen_analysis_prompt: Annotated[
        str | None,
        "Prompt for the screen_analyzer agent to analyze the screen",
        take_last,
    ]

    # executor related keys
    executor_messages: Annotated[list[AnyMessage], "Sequential Executor messages", add_messages]
    cortex_last_thought: Annotated[str | None, "Last thought of the cortex for the executor"]

    # common keys
    agents_thoughts: Annotated[
        list[str],
        "All thoughts and reasons that led to actions (why a tool was called, expected outcomes..)",
        take_last,
    ]

    async def asanitize_update(
        self,
        ctx: MobileUseContext,
        update: dict,
        agent: AgentNode | None = None,
    ):
        """
        Sanitizes the state update to ensure it is valid and apply side effect logic where required.
        The agent is required if the update contains the "agents_thoughts" key.
        """
        updated_agents_thoughts: str | list[str] | None = update.get("agents_thoughts", None)
        if updated_agents_thoughts is not None:
            if isinstance(updated_agents_thoughts, str):
                updated_agents_thoughts = [updated_agents_thoughts]
            elif isinstance(updated_agents_thoughts, list):
                updated_agents_thoughts = [t for t in updated_agents_thoughts if t is not None]
            else:
                raise ValueError("agents_thoughts must be a str or list[str]")

            if updated_agents_thoughts:
                if agent is None:
                    raise ValueError("Agent is required when updating the 'agents_thoughts' key")
                update["agents_thoughts"] = await _add_agent_thoughts(
                    ctx=ctx,
                    old=self.agents_thoughts,
                    new=updated_agents_thoughts,
                    agent=agent,
                )
            else:
                update["agents_thoughts"] = []
        return update


async def _add_agent_thoughts(
    ctx: MobileUseContext,
    old: list[str],
    new: list[str],
    agent: AgentNode,
) -> list[str]:
    if ctx.on_agent_thought:
        for thought in new:
            await ctx.on_agent_thought(agent, thought)

    named_thoughts = [f"[{agent}] {thought}" for thought in new]
    if (
        ctx.execution_setup
        and ctx.execution_setup.traces_path is not None
        and ctx.execution_setup.trace_name is not None
    ):
        record_interaction(ctx, response=AIMessage(content=str(named_thoughts)))
    return old + named_thoughts
