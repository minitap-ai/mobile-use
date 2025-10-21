from collections.abc import Sequence
from typing import Literal

from langchain_core.messages import AIMessage
from langgraph.constants import END, START
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph

from minitap.mobile_use.agents.contextor.contextor import ContextorNode
from minitap.mobile_use.agents.cortex.cortex import CortexNode
from minitap.mobile_use.agents.executor.executor import ExecutorNode
from minitap.mobile_use.agents.executor.tool_node import ExecutorToolNode
from minitap.mobile_use.agents.orchestrator.orchestrator import OrchestratorNode
from minitap.mobile_use.agents.planner.planner import PlannerNode
from minitap.mobile_use.agents.planner.utils import (
    all_completed,
    get_current_subgoal,
    one_of_them_is_failure,
)
from minitap.mobile_use.agents.screen_analyzer.screen_analyzer import ScreenAnalyzerNode
from minitap.mobile_use.agents.summarizer.summarizer import SummarizerNode
from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.tools.index import EXECUTOR_WRAPPERS_TOOLS, get_tools_from_wrappers
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


def convergence_node(state: State):
    """Convergence point for parallel execution paths."""
    return {}


def convergence_gate(
    state: State,
) -> Literal["continue", "end"]:
    """Check if all subgoals are completed at convergence point."""
    logger.info("Starting convergence_gate")
    if all_completed(state.subgoal_plan):
        logger.info("All subgoals are completed, ending the goal")
        return "end"
    return "continue"


def post_orchestrator_gate(
    state: State,
) -> Literal["continue", "replan", "end"]:
    logger.info("Starting post_orchestrator_gate")
    if one_of_them_is_failure(state.subgoal_plan):
        logger.info("One of the subgoals is in failure state, asking to replan")
        return "replan"

    if all_completed(state.subgoal_plan):
        logger.info("All subgoals are completed, ending the goal")
        return "end"

    if not get_current_subgoal(state.subgoal_plan):
        logger.info("No subgoal running, ending the goal")
        return "end"

    logger.info("Goal is not achieved, continuing")
    return "continue"


def post_cortex_gate(
    state: State,
) -> Sequence[str]:
    logger.info("Starting post_cortex_gate")
    node_sequence = []

    if len(state.complete_subgoals_by_ids) > 0 or not state.structured_decisions:
        # If subgoals need to be marked as complete, add the path to the orchestrator.
        # The 'or not state.structured_decisions' ensures we don't get stuck if Cortex does nothing.
        node_sequence.append("review_subgoals")

    if state.structured_decisions:
        node_sequence.append("execute_decisions")

    if state.screen_analysis_prompt:
        node_sequence.append("analyze_screen")

    return node_sequence


def post_executor_gate(
    state: State,
) -> Literal["invoke_tools", "skip"]:
    logger.info("Starting post_executor_gate")
    messages = state.executor_messages
    if not messages:
        return "skip"
    last_message = messages[-1]

    if isinstance(last_message, AIMessage):
        tool_calls = getattr(last_message, "tool_calls", None)
        if tool_calls and len(tool_calls) > 0:
            logger.info("[executor] Executing " + str(len(tool_calls)) + " tool calls:")
            for tool_call in tool_calls:
                logger.info("-------------")
                logger.info("[executor] - " + str(tool_call) + "\n")
            logger.info("-------------")
            return "invoke_tools"
        else:
            logger.info("[executor] ❌ No tool calls found")
    return "skip"


async def get_graph(ctx: MobileUseContext) -> CompiledStateGraph:
    graph_builder = StateGraph(State)

    ## Define nodes
    graph_builder.add_node("planner", PlannerNode(ctx))
    graph_builder.add_node("orchestrator", OrchestratorNode(ctx))

    graph_builder.add_node("contextor", ContextorNode(ctx))

    graph_builder.add_node("cortex", CortexNode(ctx))

    graph_builder.add_node("executor", ExecutorNode(ctx))
    executor_tool_node = ExecutorToolNode(
        tools=get_tools_from_wrappers(ctx=ctx, wrappers=EXECUTOR_WRAPPERS_TOOLS),
        messages_key=EXECUTOR_MESSAGES_KEY,
    )
    graph_builder.add_node("executor_tools", executor_tool_node)

    graph_builder.add_node("summarizer", SummarizerNode(ctx))

    graph_builder.add_node("screen_analyzer", ScreenAnalyzerNode(ctx))

    graph_builder.add_node(node="convergence", action=convergence_node, defer=True)

    ## Linking nodes
    graph_builder.add_edge(START, "planner")
    graph_builder.add_edge("planner", "orchestrator")
    graph_builder.add_conditional_edges(
        "orchestrator",
        post_orchestrator_gate,
        {
            "continue": "contextor",
            "replan": "planner",
            "end": END,
        },
    )
    graph_builder.add_edge("contextor", "cortex")
    graph_builder.add_conditional_edges(
        "cortex",
        post_cortex_gate,
        {
            "review_subgoals": "orchestrator",
            "analyze_screen": "screen_analyzer",
            "execute_decisions": "executor",
        },
    )
    graph_builder.add_conditional_edges(
        "executor",
        post_executor_gate,
        {"invoke_tools": "executor_tools", "skip": "summarizer"},
    )
    graph_builder.add_edge("executor_tools", "summarizer")

    graph_builder.add_edge("orchestrator", "convergence")
    graph_builder.add_edge("screen_analyzer", "convergence")
    graph_builder.add_edge("summarizer", "convergence")

    graph_builder.add_conditional_edges(
        source="convergence",
        path=convergence_gate,
        path_map={
            "continue": "contextor",
            "end": END,
        },
    )

    return graph_builder.compile()
