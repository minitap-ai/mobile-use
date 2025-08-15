import json
from pathlib import Path

from jinja2 import Template
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from minitap.agents.cortex.types import CortexOutput
from minitap.agents.planner.utils import get_current_subgoal
from minitap.config import LLM
from minitap.context import get_device_context
from minitap.graph.state import State
from minitap.services.llm import get_llm, with_fallback
from minitap.utils.decorators import wrap_with_callbacks
from minitap.utils.logger import get_logger

logger = get_logger(__name__)


@wrap_with_callbacks(
    before=lambda: logger.info("Starting Cortex Agent..."),
    on_success=lambda _: logger.success("Cortex Agent"),
    on_failure=lambda _: logger.error("Cortex Agent"),
)
async def cortex_node(state: State):
    device_context = get_device_context()
    executor_feedback = get_executor_agent_feedback(state)

    system_message = Template(
        Path(__file__).parent.joinpath("cortex.md").read_text(encoding="utf-8")
    ).render(
        platform=device_context.mobile_platform,
        initial_goal=state.initial_goal,
        subgoal_plan=state.subgoal_plan,
        current_subgoal=get_current_subgoal(state.subgoal_plan),
        agents_thoughts=state.agents_thoughts,
        executor_feedback=executor_feedback,
    )
    messages = [
        SystemMessage(content=system_message),
        HumanMessage(
            content="Here are my device info:\n"
            + device_context.to_str()
            + f"Device date: {state.device_date}\n"
            if state.device_date
            else "" + f"Focused app info: {state.focused_app_info}\n"
            if state.focused_app_info
            else ""
        ),
    ]
    for thought in state.agents_thoughts:
        messages.append(AIMessage(content=thought))

    if state.latest_ui_hierarchy:
        ui_hierarchy_dict: list[dict] = state.latest_ui_hierarchy
        ui_hierarchy_str = json.dumps(ui_hierarchy_dict, indent=2, ensure_ascii=False)
        messages.append(HumanMessage(content="Here is the UI hierarchy:\n" + ui_hierarchy_str))

    llm = get_llm(agent_node="cortex", temperature=1).with_structured_output(CortexOutput)
    llm_fallback = get_llm(
        override_llm=LLM(provider="openai", model="gpt-5")
    ).with_structured_output(CortexOutput)
    response: CortexOutput = await with_fallback(
        main_call=lambda: llm.ainvoke(messages),
        fallback_call=lambda: llm_fallback.ainvoke(messages),
    )  # type: ignore

    is_subgoal_completed = response.complete_current_subgoal
    return {
        "agents_thoughts": [response.agent_thought],
        "structured_decisions": response.decisions if not is_subgoal_completed else None,
        "latest_ui_hierarchy": None,
        "focused_app_info": None,
        "device_date": None,
        # Executor related fields
        "executor_messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES)],
        "cortex_last_thought": response.agent_thought,
    }


def get_executor_agent_feedback(state: State) -> str:
    if state.structured_decisions is None:
        return "None."
    executor_tool_messages = [m for m in state.executor_messages if isinstance(m, ToolMessage)]
    return (
        f"Latest UI decisions:\n{state.structured_decisions}"
        + "\n\n"
        + f"Executor feedback:\n{executor_tool_messages}"
    )
