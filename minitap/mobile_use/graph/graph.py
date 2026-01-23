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
from minitap.mobile_use.agents.monolithic.monolithic import MonolithicContextorNode, MonolithicNode
from minitap.mobile_use.agents.orchestrator.orchestrator import OrchestratorNode
from minitap.mobile_use.agents.planner.planner import PlannerNode
from minitap.mobile_use.agents.planner.utils import (
    all_completed,
    get_current_subgoal,
    one_of_them_is_failure,
)
from minitap.mobile_use.agents.summarizer.summarizer import SummarizerNode
from minitap.mobile_use.config import AblationConfig
from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.tools.index import (
    EXECUTOR_WRAPPERS_TOOLS,
    VIDEO_RECORDING_WRAPPERS,
    get_tools_from_wrappers,
)
from minitap.mobile_use.tools.scratchpad import (
    list_notes_wrapper,
    read_note_wrapper,
    save_note_wrapper,
)
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


def convergence_node(state: State):
    """Convergence point for parallel execution paths."""
    return {}


def convergence_gate(
    state: State,
) -> Literal["continue", "replan", "end"]:
    """Check if all subgoals are completed at convergence point."""
    logger.info("Starting convergence_gate")

    if one_of_them_is_failure(state.subgoal_plan):
        logger.info("One of the subgoals is in failure state, asking to replan")
        return "replan"

    if all_completed(state.subgoal_plan):
        logger.info("All subgoals are completed, ending the goal")
        return "end"

    if not get_current_subgoal(state.subgoal_plan):
        logger.info("No subgoal running, ending the goal")
        return "end"

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


def _get_executor_wrappers(ctx: MobileUseContext, ablation_config: AblationConfig) -> list:
    """Get the list of executor tool wrappers based on ablation config."""
    executor_wrappers = list(EXECUTOR_WRAPPERS_TOOLS)
    
    # Remove scratchpad tools if disabled
    if not ablation_config.use_scratchpad:
        executor_wrappers = [
            w for w in executor_wrappers
            if w not in (save_note_wrapper, read_note_wrapper, list_notes_wrapper)
        ]
    
    # Add video recording tools if enabled
    if ctx.video_recording_enabled and ablation_config.use_video_recording:
        executor_wrappers.extend(VIDEO_RECORDING_WRAPPERS)
    
    return executor_wrappers


def post_monolithic_gate(state: State) -> Literal["invoke_tools", "complete", "continue"]:
    """Gate for monolithic agent - check if there are tool calls or if complete."""
    logger.info("Starting post_monolithic_gate")
    
    # Check if agent believes task is complete
    if state.monolithic_is_complete:
        logger.info("[monolithic] Agent believes task is complete")
        return "complete"
    
    messages = state.executor_messages
    if not messages:
        return "continue"
    
    last_message = messages[-1]
    if isinstance(last_message, AIMessage):
        tool_calls = getattr(last_message, "tool_calls", None)
        if tool_calls and len(tool_calls) > 0:
            logger.info(f"[monolithic] Executing {len(tool_calls)} tool calls")
            return "invoke_tools"
    
    return "continue"


async def get_monolithic_graph(ctx: MobileUseContext) -> CompiledStateGraph:
    """
    Build a simplified single-agent graph for ablation baseline.
    
    This graph has a simple loop:
    START -> contextor -> monolithic -> tools -> contextor -> ...
    
    No planning, no orchestration, no summarization.
    """
    logger.warning("Building MONOLITHIC graph (ablation baseline mode)")
    
    graph_builder = StateGraph(State)
    ablation_config = ctx.get_ablation_config()
    
    # Simplified contextor
    graph_builder.add_node("contextor", MonolithicContextorNode(ctx))
    
    # Single monolithic agent (combines planning + reasoning + execution)
    graph_builder.add_node("monolithic", MonolithicNode(ctx))
    
    # Tool execution node
    executor_wrappers = _get_executor_wrappers(ctx, ablation_config)
    executor_tool_node = ExecutorToolNode(
        tools=get_tools_from_wrappers(ctx=ctx, wrappers=executor_wrappers),
        messages_key=EXECUTOR_MESSAGES_KEY,
        trace_id=ctx.trace_id,
        sequential_execution=ablation_config.use_sequential_execution,
    )
    graph_builder.add_node("tools", executor_tool_node)
    
    # Simple graph flow
    graph_builder.add_edge(START, "contextor")
    graph_builder.add_edge("contextor", "monolithic")
    
    graph_builder.add_conditional_edges(
        "monolithic",
        post_monolithic_gate,
        {
            "invoke_tools": "tools",
            "complete": END,
            "continue": "contextor",  # No tools called, get new context
        },
    )
    
    # After tools, go back to contextor for new screen state
    graph_builder.add_edge("tools", "contextor")
    
    return graph_builder.compile()


async def get_multi_agent_graph(ctx: MobileUseContext) -> CompiledStateGraph:
    """
    Build the full multi-agent graph with all 6 agents.
    
    This is the production configuration with:
    Planner -> Orchestrator -> Contextor -> Cortex -> Executor -> Summarizer
    """
    logger.info("Building MULTI-AGENT graph (full system)")
    
    graph_builder = StateGraph(State)
    ablation_config = ctx.get_ablation_config()

    ## Define nodes
    graph_builder.add_node("planner", PlannerNode(ctx))
    graph_builder.add_node("orchestrator", OrchestratorNode(ctx))
    graph_builder.add_node("contextor", ContextorNode(ctx))
    graph_builder.add_node("cortex", CortexNode(ctx))
    graph_builder.add_node("executor", ExecutorNode(ctx))

    executor_wrappers = _get_executor_wrappers(ctx, ablation_config)

    executor_tool_node = ExecutorToolNode(
        tools=get_tools_from_wrappers(ctx=ctx, wrappers=executor_wrappers),
        messages_key=EXECUTOR_MESSAGES_KEY,
        trace_id=ctx.trace_id,
        sequential_execution=ablation_config.use_sequential_execution,
    )
    graph_builder.add_node("executor_tools", executor_tool_node)

    graph_builder.add_node("summarizer", SummarizerNode(ctx))

    graph_builder.add_node(node="convergence", action=convergence_node, defer=True)

    ## Linking nodes
    graph_builder.add_edge(START, "planner")
    graph_builder.add_edge("planner", "orchestrator")
    graph_builder.add_edge("orchestrator", "convergence")
    graph_builder.add_edge("contextor", "cortex")
    graph_builder.add_conditional_edges(
        "cortex",
        post_cortex_gate,
        {
            "review_subgoals": "orchestrator",
            "execute_decisions": "executor",
        },
    )
    graph_builder.add_conditional_edges(
        "executor",
        post_executor_gate,
        {"invoke_tools": "executor_tools", "skip": "summarizer"},
    )
    graph_builder.add_edge("executor_tools", "summarizer")

    graph_builder.add_edge("summarizer", "convergence")

    graph_builder.add_conditional_edges(
        source="convergence",
        path=convergence_gate,
        path_map={
            "continue": "contextor",
            "replan": "planner",
            "end": END,
        },
    )

    return graph_builder.compile()


async def get_graph(ctx: MobileUseContext) -> CompiledStateGraph:
    """
    Get the appropriate graph based on ablation configuration.
    
    If use_multi_agent is False, returns the monolithic baseline graph.
    Otherwise, returns the full multi-agent graph.
    """
    ablation_config = ctx.get_ablation_config()
    
    if not ablation_config.use_multi_agent:
        return await get_monolithic_graph(ctx)
    
    return await get_multi_agent_graph(ctx)
