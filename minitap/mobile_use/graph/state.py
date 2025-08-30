from langchain_core.messages import AIMessage, AnyMessage
from langgraph.graph import add_messages
from langgraph.prebuilt.chat_agent_executor import AgentStatePydantic
from typing import Annotated

from minitap.mobile_use.agents.planner.types import Subgoal
from minitap.mobile_use.config import AgentNode
from minitap.mobile_use.utils.logger import get_logger
from minitap.mobile_use.utils.recorder import record_interaction
from minitap.mobile_use.context import MobileUseContext

logger = get_logger(__name__)


def take_last(a, b):
    return b


class State(AgentStatePydantic):
    # planner related keys
    initial_goal: Annotated[str, "Initial goal given by the user"]

    # orchestrator related keys
    subgoal_plan: Annotated[list[Subgoal], "The current plan, made of subgoals"]

    # contextor related keys
    latest_screenshot_base64: Annotated[str | None, "Latest screenshot of the device", take_last]
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

    # executor related keys
    executor_messages: Annotated[list[AnyMessage], "Sequential Executor messages", add_messages]
    cortex_last_thought: Annotated[str | None, "Last thought of the cortex for the executor"]

    # common keys
    agents_thoughts: Annotated[
        list[str],
        "All thoughts and reasons that led to actions (why a tool was called, expected outcomes..)",
        take_last,
    ]

    def sanitize_update(
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
            elif not isinstance(updated_agents_thoughts, list):
                raise ValueError("agents_thoughts must be a str or list[str]")
            if agent is None:
                raise ValueError("Agent is required when updating the 'agents_thoughts' key")
            update["agents_thoughts"] = _add_agent_thoughts(
                ctx=ctx,
                old=self.agents_thoughts,
                new=updated_agents_thoughts,
                agent=agent,
            )
        return update


def _add_agent_thoughts(
    ctx: MobileUseContext,
    old: list[str],
    new: list[str],
    agent: AgentNode,
) -> list[str]:
    named_thoughts = [f"[{agent}] {thought}" for thought in new]
    if ctx.execution_setup:
        record_interaction(ctx, response=AIMessage(content=str(named_thoughts)))
    return old + named_thoughts
