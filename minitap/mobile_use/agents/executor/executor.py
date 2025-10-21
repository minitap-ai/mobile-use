from pathlib import Path

from jinja2 import Template
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_vertexai.chat_models import ChatVertexAI

from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.services.llm import get_llm, invoke_llm_with_timeout_message, with_fallback
from minitap.mobile_use.tools.index import EXECUTOR_WRAPPERS_TOOLS, get_tools_from_wrappers
from minitap.mobile_use.utils.decorators import wrap_with_callbacks
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


class ExecutorNode:
    def __init__(self, ctx: MobileUseContext):
        self.ctx = ctx

    @wrap_with_callbacks(
        before=lambda: logger.info("Starting Executor Agent..."),
        on_success=lambda _: logger.success("Executor Agent"),
        on_failure=lambda _: logger.error("Executor Agent"),
    )
    async def __call__(self, state: State):
        structured_decisions = state.structured_decisions
        if not structured_decisions:
            logger.warning("No structured decisions found.")
            return await state.asanitize_update(
                ctx=self.ctx,
                update={
                    "agents_thoughts": [
                        "No structured decisions found, I cannot execute anything."
                    ],
                },
                agent="executor",
            )

        system_message = Template(
            Path(__file__).parent.joinpath("executor.md").read_text(encoding="utf-8")
        ).render(platform=self.ctx.device.mobile_platform.value)
        cortex_last_thought = (
            state.cortex_last_thought if state.cortex_last_thought else state.agents_thoughts[-1]
        )
        messages = [
            SystemMessage(content=system_message),
            HumanMessage(content=cortex_last_thought),
            HumanMessage(content=structured_decisions),
            *state.executor_messages,
        ]

        llm = get_llm(ctx=self.ctx, name="executor")
        llm_fallback = get_llm(ctx=self.ctx, name="executor", use_fallback=True)
        llm_bind_tools_kwargs: dict = {
            "tools": get_tools_from_wrappers(self.ctx, EXECUTOR_WRAPPERS_TOOLS),
        }

        # ChatGoogleGenerativeAI does not support the "parallel_tool_calls" keyword
        if not isinstance(llm, ChatGoogleGenerativeAI | ChatVertexAI):
            llm_bind_tools_kwargs["parallel_tool_calls"] = True

        llm = llm.bind_tools(**llm_bind_tools_kwargs)
        llm_fallback = llm_fallback.bind_tools(**llm_bind_tools_kwargs)
        response = await with_fallback(
            main_call=lambda: invoke_llm_with_timeout_message(llm.ainvoke(messages)),
            fallback_call=lambda: invoke_llm_with_timeout_message(llm_fallback.ainvoke(messages)),
        )
        return await state.asanitize_update(
            ctx=self.ctx,
            update={
                "cortex_last_thought": cortex_last_thought,
                EXECUTOR_MESSAGES_KEY: [response],
            },
            agent="executor",
        )
