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
from minitap.mobile_use.agents.planner.utils import fail_current_subgoal, get_current_subgoal
from minitap.mobile_use.benchmark.runtime import get_runtime
from minitap.mobile_use.tools.text_fidelity import canonical_decisions
from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.controller_factory import create_device_controller
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.services.llm import get_llm, invoke_llm_with_timeout_message, with_fallback
from minitap.mobile_use.services.telemetry import telemetry
from minitap.mobile_use.tools.index import (
    EXECUTOR_WRAPPERS_TOOLS,
    VIDEO_RECORDING_WRAPPERS,
    format_tools_list,
)
from minitap.mobile_use.robustness import p2_flags
from minitap.mobile_use.robustness.budget import checkpoint_due, checkpoint_plan, node_runs_used
from minitap.mobile_use.robustness.calendar_context import calendar_context
from minitap.mobile_use.robustness.checklist import render_checklist
from minitap.mobile_use.robustness.failure_streak import update_streak
from minitap.mobile_use.tools.p2_tools import p2_tool_wrappers
from minitap.mobile_use.utils.conversations import get_screenshot_message_for_llm
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
        # Get ablation configuration
        ablation_config = self.ctx.get_ablation_config()
        use_vision = ablation_config.use_vision
        use_meta_reasoning = ablation_config.use_meta_reasoning
        use_data_fidelity = ablation_config.use_data_fidelity_prompts
        use_scratchpad = ablation_config.use_scratchpad

        executor_feedback = get_executor_agent_feedback(state)

        # P2 F6 (version B only): near the step limit, verify the goal instead of running out
        if ablation_config.p2_no_redo and checkpoint_due(self.ctx, state, get_runtime()):
            return await self._budget_checkpoint(state)

        current_locked_app_package = (
            self.ctx.execution_setup.get_locked_app_package() if self.ctx.execution_setup else None
        )

        executor_wrappers = list(EXECUTOR_WRAPPERS_TOOLS)
        
        # Remove scratchpad tools if disabled
        if not use_scratchpad:
            from minitap.mobile_use.tools.scratchpad import (
                list_notes_wrapper,
                read_note_wrapper,
                save_note_wrapper,
            )
            executor_wrappers = [
                w for w in executor_wrappers
                if w not in (save_note_wrapper, read_note_wrapper, list_notes_wrapper)
            ]
        
        if self.ctx.video_recording_enabled and ablation_config.use_video_recording:
            executor_wrappers.extend(VIDEO_RECORDING_WRAPPERS)
        executor_wrappers.extend(p2_tool_wrappers(ablation_config))  # P2: empty in version A

        # Render system prompt with ablation flags
        system_message = Template(
            Path(__file__).parent.joinpath("cortex.md").read_text(encoding="utf-8")
        ).render(
            platform=self.ctx.device.mobile_platform.value,
            initial_goal=state.initial_goal,
            subgoal_plan=state.subgoal_plan,
            current_subgoal=get_current_subgoal(state.subgoal_plan),
            executor_feedback=executor_feedback,
            executor_tools_list=format_tools_list(ctx=self.ctx, wrappers=executor_wrappers),
            locked_app_package=current_locked_app_package,
            # Ablation flags for conditional prompt sections
            use_vision=use_vision,
            use_meta_reasoning=use_meta_reasoning,
            use_data_fidelity=use_data_fidelity,
            **p2_flags(ablation_config),
            p2_checklist_text=render_checklist(self.ctx.p2_goal_checklist),
        )
        # KNOWN ISSUE (04 - Audit A9), deliberately NOT fixed on paper/androidworld-rework so
        # that every run of the study sees the same Cortex input as the January 2026 system:
        # because of operator precedence the expression below parses as
        #   ("device info" + device_date) if state.device_date
        #   else ("focused app info" if state.focused_app_info else "")
        # i.e. device info is sent only when device_date is set, and the focused-app line only
        # when it is not. The Contextor sets device_date on every turn (output of adb `date`),
        # so in practice the Cortex gets device info + date but never the focused-app line.
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
        
        # P2 F7 (version B only): strategy switch after repeated identical tool failures
        if ablation_config.p2_tool_fixes:
            streak_note = update_streak(self.ctx, state)
            if streak_note:
                messages.append(HumanMessage(content=streak_note))
                runtime = get_runtime()
                if runtime is not None:
                    runtime.event("p2_failure_streak", note=streak_note[:300])

        # P2 F5 (version B only): deterministic sort-settings fact
        if ablation_config.p2_disambiguation and self.ctx.p2_sort_fact:
            messages.append(HumanMessage(content=self.ctx.p2_sort_fact))

        # P2 F2 (version B only): deterministic calendar facts from the device date
        if ablation_config.p2_tally:
            calendar = calendar_context(state.device_date)
            if calendar:
                messages.append(HumanMessage(content=calendar))

        # Only include agent thoughts if meta-reasoning is enabled
        if use_meta_reasoning:
            for thought in state.agents_thoughts:
                messages.append(AIMessage(content=thought))
        else:
            logger.warning("Meta-reasoning DISABLED (ablation mode) - skipping agent thoughts")

        if state.latest_ui_hierarchy:
            ui_hierarchy_dict: list[dict] = state.latest_ui_hierarchy
            ui_hierarchy_str = json.dumps(ui_hierarchy_dict, indent=2, ensure_ascii=False)
            messages.append(HumanMessage(content="Here is the UI hierarchy:\n" + ui_hierarchy_str))

        # Only include screenshots if vision is enabled
        if use_vision and state.latest_screenshot:
            controller = create_device_controller(self.ctx)
            compressed_image_base64 = controller.get_compressed_b64_screenshot(
                state.latest_screenshot
            )
            messages.append(get_screenshot_message_for_llm(compressed_image_base64))
        elif not use_vision:
            logger.warning("Vision DISABLED (ablation mode) - TEXT-ONLY mode")

        # paper/androidworld-rework: deterministic loop detector (flag: use_loop_detector)
        loop_note: str | None = None
        if self.ctx.loop_detector is not None:
            trigger = self.ctx.loop_detector.observe(
                ui_hierarchy=state.latest_ui_hierarchy,
                focused_app=state.focused_app_info,
                executed_tool_calls=get_executed_tool_calls(state),
            )
            if trigger is not None:
                current = get_current_subgoal(state.subgoal_plan)
                can_replan = trigger.escalate and current is not None
                trigger.escalate = can_replan
                runtime = get_runtime()
                if runtime is not None:
                    runtime.record_loop_trigger(
                        kind=trigger.kind,
                        action="replan" if can_replan else "inject",
                        evidence=trigger.evidence,
                        turn=trigger.turn,
                        subgoal=current.description if current else None,
                        details=trigger.details,
                    )
                logger.warning(f"Loop detector triggered ({trigger.kind}): {trigger.evidence}")
                loop_note = f"Loop detector ({trigger.kind}): {trigger.evidence}"
                if can_replan and current is not None:
                    return await self._force_replan(state, loop_note)
                messages.append(HumanMessage(content=trigger.cortex_message()))

            # fix round: stall detector (same flag), Cortex -> Orchestrator rounds w/o the Executor
            stall = self.ctx.loop_detector.check_stall()
            current = get_current_subgoal(state.subgoal_plan)
            if stall is not None and current is not None:
                runtime = get_runtime()
                if runtime is not None:
                    runtime.record_loop_trigger(
                        kind=stall.kind,
                        action="replan",
                        evidence=stall.evidence,
                        turn=stall.turn,
                        subgoal=current.description,
                        details=stall.details,
                    )
                logger.warning(f"Stall detector triggered: {stall.evidence}")
                return await self._force_replan(state, f"Loop detector (stall): {stall.evidence}")

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
        # Fix round (M3): strict JSON for the Executor (a Python-style single-quoted literal cut
        # typed text at the first apostrophe)
        response.decisions = canonical_decisions(response.decisions)
        if response.goals_completion_reason in EMPTY_STRING_TOKENS:
            response.goals_completion_reason = None
        if self.ctx.loop_detector is not None:
            self.ctx.loop_detector.note_cortex_turn(decided_action=response.decisions is not None)

        thought_parts = []
        if response.decisions_reason:
            thought_parts.append(f"Decisions reason: {response.decisions_reason}")
        if response.goals_completion_reason:
            thought_parts.append(f"Goals completion reason: {response.goals_completion_reason}")

        agent_thought = "\n\n".join(thought_parts)

        # Capture cortex decision telemetry (only non-sensitive flags)
        telemetry.capture_cortex_decision(
            task_id=self.ctx.trace_id,
            has_decisions=response.decisions is not None,
            has_goals_completion=response.goals_completion_reason is not None,
            completed_subgoals_count=len(response.complete_subgoals_by_ids or []),
        )

        return await state.asanitize_update(
            ctx=self.ctx,
            update={
                "agents_thoughts": [loop_note, agent_thought] if loop_note else [agent_thought],
                "structured_decisions": response.decisions,
                "complete_subgoals_by_ids": response.complete_subgoals_by_ids,
                "latest_ui_hierarchy": None,
                "latest_screenshot": None,
                "focused_app_info": None,
                "device_date": None,
                # Executor related fields
                EXECUTOR_MESSAGES_KEY: [RemoveMessage(id=REMOVE_ALL_MESSAGES)],
                "cortex_last_thought": agent_thought,
            },
            agent="cortex",
        )


    async def _budget_checkpoint(self, state: State):
        """P2 F6: mark the plan done so the graph routes to the goal verifier (once per task)."""
        self.ctx.p2_budget_checkpoint_done = True
        plan = checkpoint_plan(state.subgoal_plan)
        note = "==== STEP BUDGET CHECKPOINT: verifying the goal on the device now ===="
        runtime = get_runtime()
        if runtime is not None:
            runtime.event("p2_budget_checkpoint", node_runs=node_runs_used(runtime))
        if self.ctx.on_plan_changes:
            await self.ctx.on_plan_changes(plan, False)
        return await state.asanitize_update(
            ctx=self.ctx,
            update={
                "agents_thoughts": [note],
                "subgoal_plan": plan,
                "structured_decisions": None,
                "complete_subgoals_by_ids": [],
                "latest_ui_hierarchy": None,
                "latest_screenshot": None,
                "focused_app_info": None,
                "device_date": None,
                EXECUTOR_MESSAGES_KEY: [RemoveMessage(id=REMOVE_ALL_MESSAGES)],
                "cortex_last_thought": note,
            },
            agent="cortex",
        )

    async def _force_replan(self, state: State, loop_note: str):
        """Mark the current subgoal as failed (loop evidence as reason) and skip the LLM call.

        post_cortex_gate routes a plan containing a FAILURE straight to the Planner.
        """
        assert self.ctx.loop_detector is not None
        self.ctx.loop_detector.reset_history()
        plan = [s.model_copy() for s in state.subgoal_plan]
        current = get_current_subgoal(plan)
        if current is not None:
            current.completion_reason = (
                f"{loop_note}. Marked as failed by the deterministic loop detector; replanning."
            )
        plan = fail_current_subgoal(plan)
        if self.ctx.on_plan_changes:
            await self.ctx.on_plan_changes(plan, False)
        return await state.asanitize_update(
            ctx=self.ctx,
            update={
                "agents_thoughts": [loop_note, "==== LOOP DETECTED, FORCING A REPLAN ===="],
                "subgoal_plan": plan,
                "structured_decisions": None,
                "complete_subgoals_by_ids": [],
                "latest_ui_hierarchy": None,
                "latest_screenshot": None,
                "focused_app_info": None,
                "device_date": None,
                EXECUTOR_MESSAGES_KEY: [RemoveMessage(id=REMOVE_ALL_MESSAGES)],
                "cortex_last_thought": loop_note,
            },
            agent="cortex",
        )


def get_executed_tool_calls(state: State) -> list[dict]:
    """Tool calls the Executor actually ran since the previous Cortex turn."""
    calls: list[dict] = []
    for message in state.executor_messages:
        if isinstance(message, AIMessage):
            for call in getattr(message, "tool_calls", None) or []:
                calls.append({"name": call.get("name"), "args": call.get("args") or {}})
    return calls


def get_executor_agent_feedback(state: State) -> str:
    if state.structured_decisions is None:
        return "None."
    executor_tool_messages = [m for m in state.executor_messages if isinstance(m, ToolMessage)]
    return (
        f"Latest UI decisions:\n{state.structured_decisions}"
        + "\n\n"
        + f"Executor feedback:\n{executor_tool_messages}"
    )
