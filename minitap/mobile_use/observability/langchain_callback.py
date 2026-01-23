"""LangChain callback handler for automatic token tracking."""

import time
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from minitap.mobile_use.observability.protocols import ObservabilityProvider


class WandbLangChainCallback(BaseCallbackHandler):
    """LangChain callback handler that forwards metrics to an observability provider.
    
    This callback automatically captures:
    - LLM invocation timing and token usage
    - Tool call timing and success/failure
    
    Usage:
        callback = WandbLangChainCallback(provider, agent_name="planner")
        llm = llm.with_config(callbacks=[callback])
    """

    def __init__(self, provider: ObservabilityProvider, agent_name: str):
        """Initialize the callback handler.
        
        Args:
            provider: The observability provider to forward metrics to
            agent_name: Name of the agent using this LLM (e.g., "planner")
        """
        super().__init__()
        self.provider = provider
        self.agent_name = agent_name
        self._llm_start_time: float | None = None
        self._tool_start_times: dict[str, float] = {}
        self._current_model: str = "unknown"

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when LLM starts processing."""
        self._llm_start_time = time.perf_counter()
        
        # Try to extract model name from serialized config
        if serialized:
            self._current_model = serialized.get("kwargs", {}).get(
                "model_name", 
                serialized.get("kwargs", {}).get("model", "unknown")
            )

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when LLM finishes processing."""
        if self._llm_start_time is None:
            return

        duration_ms = (time.perf_counter() - self._llm_start_time) * 1000
        self._llm_start_time = None

        # Extract token usage from LLM output
        input_tokens = 0
        output_tokens = 0
        model_name = self._current_model

        if response.llm_output:
            token_usage = response.llm_output.get("token_usage", {})
            input_tokens = token_usage.get("prompt_tokens", 0)
            output_tokens = token_usage.get("completion_tokens", 0)
            
            # Update model name if available
            if "model_name" in response.llm_output:
                model_name = response.llm_output["model_name"]

        # Also check generation metadata for token usage
        if response.generations:
            for gen_list in response.generations:
                for gen in gen_list:
                    if hasattr(gen, "generation_info") and gen.generation_info:
                        usage = gen.generation_info.get("usage", {})
                        if not input_tokens:
                            input_tokens = usage.get("prompt_tokens", 0)
                        if not output_tokens:
                            output_tokens = usage.get("completion_tokens", 0)

        self.provider.log_agent_invocation(
            agent=self.agent_name,
            model=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_ms=duration_ms,
        )

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when LLM encounters an error."""
        self._llm_start_time = None
        self.provider.log_error(
            source=f"{self.agent_name}_llm",
            error=str(error),
        )

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when a tool starts execution."""
        tool_name = serialized.get("name", "unknown")
        self._tool_start_times[str(run_id)] = time.perf_counter()
        self._tool_names = getattr(self, "_tool_names", {})
        self._tool_names[str(run_id)] = tool_name

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when a tool finishes execution."""
        run_id_str = str(run_id)
        start_time = self._tool_start_times.pop(run_id_str, None)
        tool_name = getattr(self, "_tool_names", {}).pop(run_id_str, "unknown")

        if start_time is None:
            return

        duration_ms = (time.perf_counter() - start_time) * 1000

        self.provider.log_tool_call(
            tool=tool_name,
            success=True,
            duration_ms=duration_ms,
        )

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when a tool encounters an error."""
        run_id_str = str(run_id)
        start_time = self._tool_start_times.pop(run_id_str, None)
        tool_name = getattr(self, "_tool_names", {}).pop(run_id_str, "unknown")

        duration_ms = 0
        if start_time is not None:
            duration_ms = (time.perf_counter() - start_time) * 1000

        self.provider.log_tool_call(
            tool=tool_name,
            success=False,
            duration_ms=duration_ms,
            error=str(error),
        )
