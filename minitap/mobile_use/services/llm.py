import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, Literal, TypeVar, overload

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_vertexai import ChatVertexAI
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from minitap.mobile_use.config import (
    AgentNode,
    AgentNodeWithFallback,
    LLMUtilsNode,
    LLMUtilsNodeWithFallback,
    LLMWithFallback,
    settings,
)
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.utils.logger import get_logger

# Logger for internal messages (ex: fallback)
llm_logger = logging.getLogger(__name__)
# Logger for user messages
user_messages_logger = get_logger(__name__)


async def invoke_llm_with_timeout_message[T](
    llm_call: Coroutine[Any, Any, T],
    timeout_seconds: int = 10,
) -> T:
    """
    Send a LLM call and display a timeout message if it takes too long.

    Args:
        llm_call: The coroutine of the LLM call to execute.
        timeout_seconds: The delay in seconds before displaying the message.

    Returns:
        The result of the LLM call.
    """
    llm_task = asyncio.create_task(llm_call)
    waiter_task = asyncio.create_task(asyncio.sleep(timeout_seconds))

    done, _ = await asyncio.wait({llm_task, waiter_task}, return_when=asyncio.FIRST_COMPLETED)

    if llm_task in done:
        # The LLM call has finished before the timeout, cancel the timer
        waiter_task.cancel()
        return llm_task.result()
    else:
        # The timeout has been reached, display the message and wait for the call to finish
        user_messages_logger.info("Waiting for LLM call response...")
        return await llm_task


def get_minitap_llm(
    trace_id: str,
    remote_tracing: bool = False,
    model: str = "google/gemini-2.5-pro",
    temperature: float | None = None,
    max_retries: int | None = None,
    api_key: str | None = None,
) -> ChatOpenAI:
    if api_key:
        effective_api_key = SecretStr(api_key)
    elif settings.MINITAP_API_KEY:
        effective_api_key = settings.MINITAP_API_KEY
    else:
        raise ValueError("MINITAP_API_KEY must be provided or set in environment")

    if settings.MINITAP_BASE_URL is None:
        raise ValueError("MINITAP_BASE_URL must be set in environment")

    llm_base_url = f"{settings.MINITAP_BASE_URL}/api/v1"

    if max_retries is None and model.startswith("google/"):
        max_retries = 2
    client = ChatOpenAI(
        model=model,
        temperature=temperature,
        max_retries=max_retries,
        api_key=effective_api_key,
        base_url=llm_base_url,
        default_query={
            "sessionId": trace_id,
            "traceOnlyUsage": remote_tracing,
        },
    )
    return client


def get_google_llm(
    model_name: str = "gemini-2.5-pro",
    temperature: float = 0.7,
) -> ChatGoogleGenerativeAI:
    assert settings.GOOGLE_API_KEY is not None
    client = ChatGoogleGenerativeAI(
        model=model_name,
        max_tokens=None,
        temperature=temperature,
        api_key=settings.GOOGLE_API_KEY,
        max_retries=2,
    )
    return client


def get_vertex_llm(
    model_name: str = "gemini-2.5-pro",
    temperature: float = 0.7,
) -> ChatVertexAI:
    client = ChatVertexAI(
        model_name=model_name,
        max_tokens=None,
        temperature=temperature,
        max_retries=2,
    )
    return client


def get_openai_llm(
    model_name: str = "o3",
    temperature: float = 1,
) -> ChatOpenAI:
    assert settings.OPENAI_API_KEY is not None
    client = ChatOpenAI(
        model=model_name,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        temperature=temperature,
    )
    return client


def get_openrouter_llm(model_name: str, temperature: float = 1):
    assert settings.OPEN_ROUTER_API_KEY is not None
    client = ChatOpenAI(
        model=model_name,
        temperature=temperature,
        api_key=settings.OPEN_ROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
    )
    return client


def get_grok_llm(model_name: str, temperature: float = 1) -> ChatOpenAI:
    assert settings.XAI_API_KEY is not None
    client = ChatOpenAI(
        model=model_name,
        api_key=settings.XAI_API_KEY,
        temperature=temperature,
        base_url="https://api.x.ai/v1",
    )
    return client


@overload
def get_llm(
    ctx: MobileUseContext,
    name: AgentNodeWithFallback,
    *,
    use_fallback: bool = False,
    temperature: float = 1,
) -> BaseChatModel: ...


@overload
def get_llm(
    ctx: MobileUseContext,
    name: LLMUtilsNode,
    *,
    is_utils: Literal[True],
    temperature: float = 1,
) -> BaseChatModel: ...


@overload
def get_llm(
    ctx: MobileUseContext,
    name: LLMUtilsNodeWithFallback,
    *,
    is_utils: Literal[True],
    use_fallback: bool = False,
    temperature: float = 1,
) -> BaseChatModel: ...


def get_llm(
    ctx: MobileUseContext,
    name: AgentNode | LLMUtilsNode | AgentNodeWithFallback,
    is_utils: bool = False,
    use_fallback: bool = False,
    temperature: float = 1,
) -> BaseChatModel:
    llm = (
        ctx.llm_config.get_utils(name)  # type: ignore
        if is_utils
        else ctx.llm_config.get_agent(name)  # type: ignore
    )
    if use_fallback:
        if isinstance(llm, LLMWithFallback):
            llm = llm.fallback
        else:
            raise ValueError("LLM has no fallback!")
    if llm.provider == "openai":
        return get_openai_llm(llm.model, temperature)
    elif llm.provider == "google":
        return get_google_llm(llm.model, temperature)
    elif llm.provider == "vertexai":
        return get_vertex_llm(llm.model, temperature)
    elif llm.provider == "openrouter":
        return get_openrouter_llm(llm.model, temperature)
    elif llm.provider == "xai":
        return get_grok_llm(llm.model, temperature)
    elif llm.provider == "minitap":
        remote_tracing = False
        if ctx.execution_setup:
            remote_tracing = ctx.execution_setup.enable_remote_tracing
        return get_minitap_llm(
            trace_id=ctx.trace_id,
            remote_tracing=remote_tracing,
            model=llm.model,
            temperature=temperature,
            api_key=ctx.minitap_api_key,
        )
    else:
        raise ValueError(f"Unsupported provider: {llm.provider}")


T = TypeVar("T")


async def with_fallback(
    main_call: Callable[[], Awaitable[T]],
    fallback_call: Callable[[], Awaitable[T]],
    none_should_fallback: bool = True,
) -> T:
    try:
        result = await main_call()
        if result is None and none_should_fallback:
            llm_logger.warning("Main LLM inference returned None. Falling back...")
            return await fallback_call()
        return result
    except Exception as e:
        llm_logger.warning(f"❗ Main LLM inference failed: {e}. Falling back...")
        return await fallback_call()
