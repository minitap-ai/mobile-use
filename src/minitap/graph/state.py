from typing import Union

from langchain_core.messages import AIMessage, AnyMessage
from langgraph.graph import add_messages
from langgraph.prebuilt.chat_agent_executor import AgentStatePydantic
from typing_extensions import Annotated, Optional

from minitap.agents.planner.types import Subgoal
from minitap.context import is_execution_setup_set
from minitap.utils.logger import get_logger
from minitap.utils.recorder import record_interaction

logger = get_logger(__name__)


def add_agent_thought(a: list[str], b: Union[str, list[str]]) -> list[str]:
    if is_execution_setup_set():
        record_interaction(response=AIMessage(content=str(b)))
    if isinstance(b, str):
        return a + [b]
    elif isinstance(b, list):
        return a + b
    raise TypeError("b must be a str or list[str]")


def take_last(a, b):
    return b


class State(AgentStatePydantic):
    # planner related keys
    initial_goal: Annotated[str, "Initial goal given by the user"]

    # orchestrator related keys
    subgoal_plan: Annotated[list[Subgoal], "The current plan, made of subgoals"]

    # contextor related keys
    latest_ui_hierarchy: Annotated[Optional[list], "Latest UI hierarchy of the device", take_last]
    focused_app_info: Annotated[Optional[str], "Focused app info", take_last]
    device_date: Annotated[Optional[str], "Date of the device", take_last]

    # cortex related keys
    structured_decisions: Annotated[
        Optional[str],
        "Structured decisions made by the cortex, for the executor to follow",
        take_last,
    ]

    # executor related keys
    executor_retrigger: Annotated[Optional[bool], "Whether the executor must be retriggered"]
    executor_failed: Annotated[bool, "Whether a tool call made by the executor failed"]
    executor_messages: Annotated[list[AnyMessage], "Sequential Executor messages", add_messages]
    cortex_last_thought: Annotated[Optional[str], "Last thought of the cortex for the executor"]

    # common keys
    agents_thoughts: Annotated[
        list[str],
        "All thoughts and reasons that led to actions (why a tool was called, expected outcomes..)",
        add_agent_thought,
    ]
