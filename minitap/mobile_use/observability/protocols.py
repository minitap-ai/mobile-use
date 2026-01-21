"""Protocol definitions for observability providers."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class ObservabilityProvider(Protocol):
    """Protocol for observability backends (W&B, PostHog, custom, etc.).
    
    This protocol defines the interface that any observability provider must implement.
    Using a protocol allows for easy swapping of backends and simplified testing.
    """

    def log_agent_invocation(
        self,
        agent: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        duration_ms: float,
    ) -> None:
        """Log an LLM invocation by an agent.
        
        Args:
            agent: Name of the agent (e.g., "planner", "cortex", "executor")
            model: Model name used (e.g., "gpt-4", "claude-3-opus")
            input_tokens: Number of input/prompt tokens
            output_tokens: Number of output/completion tokens
            duration_ms: Duration of the call in milliseconds
        """
        ...

    def log_tool_call(
        self,
        tool: str,
        success: bool,
        duration_ms: float,
        error: str | None = None,
    ) -> None:
        """Log a tool call execution.
        
        Args:
            tool: Name of the tool (e.g., "tap", "swipe", "type_text")
            success: Whether the tool call succeeded
            duration_ms: Duration of the call in milliseconds
            error: Error message if the call failed
        """
        ...

    def log_agent_thought(self, agent: str, thought: str) -> None:
        """Log an agent's reasoning/thought.
        
        Args:
            agent: Name of the agent
            thought: The agent's thought or reasoning text
        """
        ...

    def log_node_execution(
        self,
        node: str,
        duration_ms: float,
        error: str | None = None,
    ) -> None:
        """Log a graph node execution.
        
        Args:
            node: Name of the node (e.g., "planner_node", "cortex_node")
            duration_ms: Duration of the node execution in milliseconds
            error: Error message if the node failed
        """
        ...

    def log_error(self, source: str, error: str) -> None:
        """Log an error occurrence.
        
        Args:
            source: Source of the error (agent name, node name, etc.)
            error: Error message or description
        """
        ...

    def flush(self, step: int) -> None:
        """Flush accumulated metrics for a step.
        
        Args:
            step: The step/task index for this batch of metrics
        """
        ...
