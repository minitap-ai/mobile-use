"""Decorators for automatic node instrumentation with observability."""

import time
import asyncio
from functools import wraps
from typing import Any, TypeVar
from collections.abc import Callable

from minitap.mobile_use.observability.protocols import ObservabilityProvider

# Type variable for the decorated function
F = TypeVar("F", bound=Callable[..., Any])


def instrumented_node(node_name: str) -> Callable[[F], F]:
    """Decorator that automatically instruments a graph node with observability.
    
    This decorator wraps agent nodes to automatically:
    - Track execution duration
    - Log errors
    - Forward metrics to the observability provider
    
    The decorator looks for the observability provider in:
    1. config["configurable"]["context"].observability
    2. config["configurable"]["observability"]
    
    Usage:
        @instrumented_node("planner")
        async def planner_node(state: State, config: RunnableConfig = None) -> State:
            # ... node logic unchanged
            pass
    
    Args:
        node_name: Name of the node for metrics (e.g., "planner", "cortex")
    
    Returns:
        Decorated function with automatic instrumentation
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            # Extract config from kwargs or args
            config = kwargs.get("config")
            if config is None and len(args) > 1:
                config = args[1] if isinstance(args[1], dict) else None

            # Try to get observability provider from config
            observability: ObservabilityProvider | None = None
            if config and isinstance(config, dict):
                configurable = config.get("configurable", {})
                
                # Try context.observability first
                ctx = configurable.get("context")
                if ctx and hasattr(ctx, "observability"):
                    observability = ctx.observability
                
                # Fallback to direct observability in config
                if observability is None:
                    observability = configurable.get("observability")

            # Execute the node with timing
            start_time = time.perf_counter()
            error_msg: str | None = None

            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                error_msg = str(e)
                raise
            finally:
                duration_ms = (time.perf_counter() - start_time) * 1000

                if observability:
                    observability.log_node_execution(
                        node=node_name,
                        duration_ms=duration_ms,
                        error=error_msg,
                    )

        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            # Extract config from kwargs or args
            config = kwargs.get("config")
            if config is None and len(args) > 1:
                config = args[1] if isinstance(args[1], dict) else None

            # Try to get observability provider from config
            observability: ObservabilityProvider | None = None
            if config and isinstance(config, dict):
                configurable = config.get("configurable", {})
                
                ctx = configurable.get("context")
                if ctx and hasattr(ctx, "observability"):
                    observability = ctx.observability
                
                if observability is None:
                    observability = configurable.get("observability")

            # Execute the node with timing
            start_time = time.perf_counter()
            error_msg: str | None = None

            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                error_msg = str(e)
                raise
            finally:
                duration_ms = (time.perf_counter() - start_time) * 1000

                if observability:
                    observability.log_node_execution(
                        node=node_name,
                        duration_ms=duration_ms,
                        error=error_msg,
                    )

        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore
        else:
            return sync_wrapper  # type: ignore

    return decorator


def with_observability(
    provider_getter: Callable[..., ObservabilityProvider | None],
) -> Callable[[F], F]:
    """Decorator factory for custom observability provider injection.
    
    This is useful when the observability provider needs to be obtained
    from a custom source (not from config).
    
    Usage:
        def get_provider(state, config):
            return my_custom_provider
        
        @with_observability(get_provider)
        async def my_node(state, config):
            ...
    
    Args:
        provider_getter: Function that takes (state, config) and returns provider
    
    Returns:
        Decorator that injects observability
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            state = args[0] if args else kwargs.get("state")
            config = kwargs.get("config") or (args[1] if len(args) > 1 else None)
            
            provider = provider_getter(state, config)
            
            start_time = time.perf_counter()
            error_msg: str | None = None
            
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                error_msg = str(e)
                raise
            finally:
                if provider:
                    duration_ms = (time.perf_counter() - start_time) * 1000
                    provider.log_node_execution(
                        node=func.__name__,
                        duration_ms=duration_ms,
                        error=error_msg,
                    )

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore
        else:
            raise ValueError("with_observability only supports async functions")

    return decorator
