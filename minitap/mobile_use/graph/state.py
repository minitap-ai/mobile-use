from langchain_core.messages import AIMessage, AnyMessage
from langgraph.graph import add_messages
from langgraph.prebuilt.chat_agent_executor import AgentStatePydantic
from typing_extensions import Annotated, Optional

from minitap.mobile_use.agents.planner.types import Subgoal
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
    latest_screenshot_base64: Annotated[Optional[str], "Latest screenshot of the device", take_last]
    latest_ui_hierarchy: Annotated[
        Optional[list[dict]], "Latest UI hierarchy of the device", take_last
    ]
    focused_app_info: Annotated[Optional[str], "Focused app info", take_last]
    device_date: Annotated[Optional[str], "Date of the device", take_last]

    # cortex related keys
    structured_decisions: Annotated[
        Optional[str],
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
    cortex_last_thought: Annotated[Optional[str], "Last thought of the cortex for the executor"]

    # common keys
    agents_thoughts: Annotated[
        list[str],
        "All thoughts and reasons that led to actions (why a tool was called, expected outcomes..)",
        take_last,
    ]

    def sanitize_update(self, ctx: MobileUseContext, update: dict):
        """
        Sanitizes the state update to ensure it is valid and apply side effect logic where required.
        """
        updated_agents_thoughts: Optional[str | list[str]] = update.get("agents_thoughts", None)
        if updated_agents_thoughts is not None:
            if isinstance(updated_agents_thoughts, str):
                updated_agents_thoughts = [updated_agents_thoughts]
            elif not isinstance(updated_agents_thoughts, list):
                raise ValueError("agents_thoughts must be a str or list[str]")
            update["agents_thoughts"] = _add_agent_thoughts(
                ctx=ctx,
                old=self.agents_thoughts,
                new=updated_agents_thoughts,
            )
        return update


def _add_agent_thoughts(ctx: MobileUseContext, old: list[str], new: list[str]) -> list[str]:
    if ctx.execution_setup:
        record_interaction(ctx, response=AIMessage(content=str(new)))
    return old + new
