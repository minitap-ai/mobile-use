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

from minitap.mobile_use.agents.cortex.types import CortexOutput
from minitap.mobile_use.agents.planner.utils import get_current_subgoal
from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.services.llm import get_llm, invoke_llm_with_timeout_message, with_fallback
from minitap.mobile_use.tools.index import EXECUTOR_WRAPPERS_TOOLS, format_tools_list
from minitap.mobile_use.utils.decorators import wrap_with_callbacks
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


class CortexNode:
    def __init__(self, ctx: MobileUseContext):
        self.ctx = ctx

    @wrap_with_callbacks(
        before=lambda: logger.info("Starting Cortex Agent..."),
        on_success=lambda _: logger.success("Cortex Agent"),
        on_failure=lambda _: logger.error("Cortex Agent"),
    )
    async def __call__(self, state: State):
        executor_feedback = get_executor_agent_feedback(state)

        current_locked_app_package = (
            self.ctx.execution_setup.get_locked_app_package() if self.ctx.execution_setup else None
        )

        system_message = Template(
            Path(__file__).parent.joinpath("cortex.md").read_text(encoding="utf-8")
        ).render(
            platform=self.ctx.device.mobile_platform.value,
            initial_goal=state.initial_goal,
            subgoal_plan=state.subgoal_plan,
            current_subgoal=get_current_subgoal(state.subgoal_plan),
            executor_feedback=executor_feedback,
            executor_tools_list=format_tools_list(ctx=self.ctx, wrappers=EXECUTOR_WRAPPERS_TOOLS),
            locked_app_package=current_locked_app_package,
        )
        messages = [
            SystemMessage(content=system_message),
            HumanMessage(
                content="Here are my device info:\n"
                + self.ctx.device.to_str()
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

        llm = get_llm(ctx=self.ctx, name="cortex", temperature=1).with_structured_output(
            CortexOutput
        )
        llm_fallback = get_llm(
            ctx=self.ctx, name="cortex", use_fallback=True, temperature=1
        ).with_structured_output(CortexOutput)
        response: CortexOutput = await with_fallback(
            main_call=lambda: invoke_llm_with_timeout_message(llm.ainvoke(messages)),
            fallback_call=lambda: invoke_llm_with_timeout_message(llm_fallback.ainvoke(messages)),
        )  # type: ignore

        EMPTY_STRING_TOKENS = ["{}", "[]", "null", "", "None"]

        if response.decisions in EMPTY_STRING_TOKENS:
            response.decisions = None
        if response.goals_completion_reason in EMPTY_STRING_TOKENS:
            response.goals_completion_reason = None
        if response.screen_analysis_prompt in EMPTY_STRING_TOKENS:
            response.screen_analysis_prompt = None

        # Enforce mutual exclusivity: screen_analysis_prompt and decisions cannot coexist
        # If both are provided, prioritize decisions and discard screen_analysis_prompt
        if response.decisions is not None and response.screen_analysis_prompt is not None:
            logger.warning(
                "Both 'decisions' and 'screen_analysis_prompt' were provided. "
                "Prioritizing execution decisions and discarding screen analysis request."
            )
            response.screen_analysis_prompt = None

        thought_parts = []
        if response.decisions_reason:
            thought_parts.append(f"Decisions reason: {response.decisions_reason}")
        if response.goals_completion_reason:
            thought_parts.append(f"Goals completion reason: {response.goals_completion_reason}")
        if response.screen_analysis_prompt:
            thought_parts.append(f"Screen analysis query: {response.screen_analysis_prompt}")

        agent_thought = "\n\n".join(thought_parts)

        return await state.asanitize_update(
            ctx=self.ctx,
            update={
                "agents_thoughts": [agent_thought],
                "structured_decisions": response.decisions,
                "complete_subgoals_by_ids": response.complete_subgoals_by_ids,
                "screen_analysis_prompt": response.screen_analysis_prompt,
                "latest_ui_hierarchy": None,
                "focused_app_info": None,
                "device_date": None,
                # Executor related fields
                EXECUTOR_MESSAGES_KEY: [RemoveMessage(id=REMOVE_ALL_MESSAGES)],
                "cortex_last_thought": agent_thought,
            },
            agent="cortex",
        )


def get_executor_agent_feedback(state: State) -> str:
    if state.structured_decisions is None:
        return "None."
    executor_tool_messages = [m for m in state.executor_messages if isinstance(m, ToolMessage)]
    return (
        f"Latest UI decisions:\n{state.structured_decisions}"
        + "\n\n"
        + f"Executor feedback:\n{executor_tool_messages}"
    )
