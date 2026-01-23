"""
Monolithic Agent for Ablation Baseline.

This single-agent implementation combines all functionality into one agent,
representing the baseline configuration (a0-baseline) for ablation studies.
It lacks the sophisticated multi-agent reasoning, meta-cognition, and 
specialized roles of the full system.
"""

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
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_vertexai.chat_models import ChatVertexAI
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.controller_factory import create_device_controller
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.services.llm import get_llm, invoke_llm_with_timeout_message, with_fallback
from minitap.mobile_use.tools.index import (
    EXECUTOR_WRAPPERS_TOOLS,
    VIDEO_RECORDING_WRAPPERS,
    format_tools_list,
    get_tools_from_wrappers,
)
from minitap.mobile_use.utils.conversations import get_screenshot_message_for_llm
from minitap.mobile_use.utils.decorators import wrap_with_callbacks
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


class MonolithicNode:
    """
    Single monolithic agent that combines planning, reasoning, and execution.
    
    This represents the baseline for ablation studies - a simpler architecture
    without the benefits of specialized agents (Planner, Orchestrator, Contextor,
    Cortex, Executor, Summarizer).
    """

    def __init__(self, ctx: MobileUseContext):
        self.ctx = ctx

    @wrap_with_callbacks(
        before=lambda: logger.info("Starting Monolithic Agent..."),
        on_success=lambda _: logger.success("Monolithic Agent"),
        on_failure=lambda _: logger.error("Monolithic Agent"),
    )
    async def __call__(self, state: State):
        # Get executor feedback from previous tool calls
        executor_feedback = self._get_executor_feedback(state)

        # Determine which tool wrappers to include
        executor_wrappers = list(EXECUTOR_WRAPPERS_TOOLS)
        
        # Check ablation config for scratchpad
        ablation_config = self.ctx.get_ablation_config()
        if not ablation_config.use_scratchpad:
            # Remove scratchpad tools
            from minitap.mobile_use.tools.scratchpad import (
                list_notes_wrapper,
                read_note_wrapper,
                save_note_wrapper,
            )
            executor_wrappers = [
                w for w in executor_wrappers
                if w not in (save_note_wrapper, read_note_wrapper, list_notes_wrapper)
            ]

        # Video recording tools
        if self.ctx.video_recording_enabled and ablation_config.use_video_recording:
            executor_wrappers.extend(VIDEO_RECORDING_WRAPPERS)

        # Build the system prompt
        system_message = Template(
            Path(__file__).parent.joinpath("monolithic.md").read_text(encoding="utf-8")
        ).render(
            platform=self.ctx.device.mobile_platform.value,
            initial_goal=state.initial_goal,
            executor_tools_list=format_tools_list(ctx=self.ctx, wrappers=executor_wrappers),
            executor_feedback=executor_feedback,
            ui_hierarchy=self._format_ui_hierarchy(state),
        )

        messages = [
            SystemMessage(content=system_message),
            HumanMessage(
                content=f"Device info:\n{self.ctx.device.to_str()}"
                + (f"Device date: {state.device_date}\n" if state.device_date else "")
            ),
        ]

        # Add previous conversation context (limited)
        for msg in state.executor_messages[-10:]:  # Keep last 10 messages
            messages.append(msg)

        # Add screenshot if vision is enabled
        if state.latest_screenshot and ablation_config.use_vision:
            controller = create_device_controller(self.ctx)
            compressed_image_base64 = controller.get_compressed_b64_screenshot(
                state.latest_screenshot
            )
            messages.append(get_screenshot_message_for_llm(compressed_image_base64))

        # Get LLM with tools bound
        llm = get_llm(ctx=self.ctx, name="cortex")  # Use cortex LLM config
        llm_fallback = get_llm(ctx=self.ctx, name="cortex", use_fallback=True)

        llm_bind_tools_kwargs: dict = {
            "tools": get_tools_from_wrappers(self.ctx, executor_wrappers),
        }

        # ChatGoogleGenerativeAI does not support "parallel_tool_calls"
        if not isinstance(llm, ChatGoogleGenerativeAI | ChatVertexAI):
            # In baseline, we allow parallel tool calls (less reliable)
            llm_bind_tools_kwargs["parallel_tool_calls"] = True

        llm = llm.bind_tools(**llm_bind_tools_kwargs)
        llm_fallback = llm_fallback.bind_tools(**llm_bind_tools_kwargs)

        response = await with_fallback(
            main_call=lambda: invoke_llm_with_timeout_message(llm.ainvoke(messages)),
            fallback_call=lambda: invoke_llm_with_timeout_message(llm_fallback.ainvoke(messages)),
        )

        # Check if task is complete (agent says so without tool calls)
        is_complete = False
        if isinstance(response, AIMessage):
            tool_calls = getattr(response, "tool_calls", None)
            if not tool_calls and response.content:
                # Agent responded with text but no tools - might be done
                content_lower = str(response.content).lower()
                if any(phrase in content_lower for phrase in [
                    "task is complete",
                    "goal has been achieved",
                    "successfully completed",
                    "task has been completed",
                ]):
                    is_complete = True

        return await state.asanitize_update(
            ctx=self.ctx,
            update={
                EXECUTOR_MESSAGES_KEY: [response],
                "latest_ui_hierarchy": None,
                "latest_screenshot": None,
                "focused_app_info": None,
                "device_date": None,
                "monolithic_is_complete": is_complete,
            },
            agent="monolithic",
        )

    def _get_executor_feedback(self, state: State) -> str:
        """Get feedback from previous tool executions."""
        executor_tool_messages = [
            m for m in state.executor_messages if isinstance(m, ToolMessage)
        ]
        if not executor_tool_messages:
            return "None."
        
        # Get the last few tool messages
        recent_messages = executor_tool_messages[-3:]
        feedback_parts = []
        for msg in recent_messages:
            feedback_parts.append(f"- {msg.content[:500]}")  # Truncate long messages
        
        return "\n".join(feedback_parts)

    def _format_ui_hierarchy(self, state: State) -> str | None:
        """Format UI hierarchy for the prompt."""
        if not state.latest_ui_hierarchy:
            return None
        return json.dumps(state.latest_ui_hierarchy, indent=2, ensure_ascii=False)


class MonolithicContextorNode:
    """
    Simplified contextor for monolithic graph.
    Just captures screen state without sophisticated analysis.
    """

    def __init__(self, ctx: MobileUseContext):
        self.ctx = ctx

    @wrap_with_callbacks(
        before=lambda: logger.info("Starting Monolithic Contextor..."),
        on_success=lambda _: logger.success("Monolithic Contextor"),
        on_failure=lambda _: logger.error("Monolithic Contextor"),
    )
    async def __call__(self, state: State):
        """Capture current screen state."""
        from minitap.mobile_use.controllers.platform_specific_commands_controller import (
            get_device_date,
        )

        controller = create_device_controller(self.ctx)
        ablation_config = self.ctx.get_ablation_config()

        # Get screen data (UI hierarchy + screenshot)
        ui_hierarchy = None
        screenshot = None
        try:
            device_data = await controller.get_screen_data()
            ui_hierarchy = device_data.elements
            
            # Only include screenshot if vision is enabled
            if ablation_config.use_vision:
                screenshot = device_data.base64
            else:
                logger.warning("Vision DISABLED (ablation mode) - screenshot will not be sent to LLM")
        except Exception as e:
            logger.warning(f"Failed to get screen data: {e}")

        # Get device date
        device_date = get_device_date(self.ctx)

        return await state.asanitize_update(
            ctx=self.ctx,
            update={
                "latest_ui_hierarchy": ui_hierarchy,
                "latest_screenshot": screenshot,
                "device_date": device_date,
            },
            agent="monolithic_contextor",
        )
