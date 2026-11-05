from pathlib import Path

from jinja2 import Template
from langchain_core.messages import HumanMessage, SystemMessage

from minitap.mobile_use.agents.contextor.types import AppLockVerificationOutput, ContextorOutput
from minitap.mobile_use.agents.planner.types import Subgoal
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.controller_factory import create_device_controller
from minitap.mobile_use.controllers.platform_specific_commands_controller import (
    get_current_foreground_package_async,
    get_device_date,
)
from minitap.mobile_use.errors import AppLockViolationError
from minitap.mobile_use.utils.app_lock_events import record_app_lock_event
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.services.llm import get_llm, invoke_llm_with_timeout_message, with_fallback
from minitap.mobile_use.utils.app_launch_utils import launch_app_with_retries
from minitap.mobile_use.utils.decorators import wrap_with_callbacks
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


class ContextorNode:
    def __init__(self, ctx: MobileUseContext):
        self.ctx = ctx

    @wrap_with_callbacks(
        before=lambda: logger.info("Starting Contextor Agent"),
        on_success=lambda _: logger.success("Contextor Agent"),
        on_failure=lambda _: logger.error("Contextor Agent"),
    )
    async def __call__(self, state: State):
        device_controller = create_device_controller(self.ctx)
        current_app_package = await get_current_foreground_package_async(self.ctx)
        device_date = get_device_date(self.ctx)
        agent_outcome: str | None = None

        if self.ctx.execution_setup and self.ctx.execution_setup.app_lock_status:
            app_lock_status = self.ctx.execution_setup.app_lock_status
            locked_app_package = app_lock_status.locked_app_package
            is_strict_app_lock = app_lock_status.app_lock_policy == "strict"
            should_verify_app_lock = app_lock_status.locked_app_initial_launch_success is True
            if should_verify_app_lock:
                if current_app_package:
                    try:
                        verification: AppLockVerificationOutput = (
                            await self._handle_app_lock_verification(
                                state=state,
                                current_app_package=current_app_package,
                                locked_app_package=locked_app_package,
                            )
                        )
                        agent_outcome = verification.to_optional_message()
                        if is_strict_app_lock and verification.status == "relaunched":
                            # Do not read a screenshot until a fresh foreground
                            # check confirms the deterministic relaunch held.
                            current_app_package = await get_current_foreground_package_async(
                                self.ctx
                            )
                            if current_app_package != locked_app_package:
                                record_app_lock_event(
                                    locked_app_package=locked_app_package,
                                    action="context_capture",
                                    decision="aborted",
                                    reason="restore_failed",
                                    target_package=current_app_package,
                                )
                                raise AppLockViolationError(
                                    f"Could not verify strict app lock for {locked_app_package} "
                                    "after relaunch"
                                )
                    except AppLockViolationError:
                        # A strict lock must never be downgraded to a warning.
                        raise
                    except Exception as e:
                        if is_strict_app_lock:
                            raise AppLockViolationError(
                                f"Could not verify strict app lock for {locked_app_package}"
                            ) from e
                        logger.error(f"Failed to verify app lock: {e}")
                else:
                    error = (
                        f"Could not verify strict app lock for {locked_app_package}: "
                        "foreground app is unknown"
                    )
                    if is_strict_app_lock:
                        record_app_lock_event(
                            locked_app_package=locked_app_package,
                            action="context_capture",
                            decision="aborted",
                            reason="foreground_unknown",
                        )
                        raise AppLockViolationError(error)
                    logger.warning(error)
            else:
                error = (
                    f"App lock feature is setup for {locked_app_package}, "
                    "but initial launch was not successful"
                )
                if is_strict_app_lock:
                    raise AppLockViolationError(error)
                logger.warning(f"{error}, skipping")

        # Verify the foreground before this context capture. Device focus can
        # still change between the check and capture; this is not OS isolation.
        device_data = await device_controller.get_screen_data()

        return await state.asanitize_update(
            ctx=self.ctx,
            update={
                "latest_ui_hierarchy": device_data.elements,
                "latest_screenshot": device_data.base64,
                "focused_app_info": current_app_package,
                "screen_size": (device_data.width, device_data.height),
                "device_date": device_date,
                "agents_thoughts": [agent_outcome],
            },
            agent="contextor",
        )

    async def _handle_app_lock_verification(
        self, state: State, current_app_package: str, locked_app_package: str
    ) -> AppLockVerificationOutput:
        """Verify app lock compliance and decide whether to relaunch the locked app."""
        if not self.ctx.execution_setup or not self.ctx.execution_setup.app_lock_status:
            return AppLockVerificationOutput(
                package_name=locked_app_package,
                reasoning="App lock feature is not setup",
                status="error",
            )

        app_lock_status = self.ctx.execution_setup.app_lock_status
        locked_app_package = app_lock_status.locked_app_package

        if current_app_package == locked_app_package:
            logger.info(f"App lock verified: current app matches locked app ({locked_app_package})")
            return AppLockVerificationOutput(
                package_name=locked_app_package,
                status="already_in_foreground",
            )

        logger.warning(
            f"App lock violation detected: expected '{locked_app_package}', "
            f"but current app is '{current_app_package}'"
        )

        if app_lock_status.app_lock_policy == "strict":
            # ``launch_app_with_retries`` verifies the foreground package before
            # returning success. Do not consult the LLM in strict mode: a model
            # decision must not turn an app-boundary violation into an allowed
            # deviation.
            logger.info(f"Strict app lock: relaunching {locked_app_package}")
            success, error = await launch_app_with_retries(self.ctx, app_package=locked_app_package)
            record_app_lock_event(
                locked_app_package=locked_app_package,
                action="context_capture",
                decision="restored" if success else "aborted",
                reason="foreground_mismatch" if success else "restore_failed",
                target_package=current_app_package,
            )
            if not success:
                raise AppLockViolationError(
                    f"Strict app lock could not restore {locked_app_package}: "
                    f"{error or 'foreground verification failed'}"
                )
            return AppLockVerificationOutput(
                package_name=locked_app_package,
                reasoning="Strict app lock restored the approved app.",
                status="relaunched",
            )

        decision: ContextorOutput = await self._invoke_contextor_llm(
            initial_goal=state.initial_goal,
            subgoal_plan=state.subgoal_plan,
            agents_thoughts=state.agents_thoughts,
            locked_app_package=locked_app_package,
            current_app_package=current_app_package,
        )

        if decision.should_relaunch_app:
            logger.info(f"Relaunching locked app: {locked_app_package}")
            success, error = await launch_app_with_retries(self.ctx, app_package=locked_app_package)
            if not success:
                logger.error(f"Failed to relaunch {locked_app_package}: {error}")
                return AppLockVerificationOutput(
                    package_name=locked_app_package,
                    reasoning=f"Failed to relaunch app: {error}",
                    status="error",
                )
            return AppLockVerificationOutput(
                package_name=locked_app_package,
                reasoning=decision.reasoning,
                status="relaunched",
            )

        logger.info(f"Allowing app deviation to: {current_app_package}")
        return AppLockVerificationOutput(
            package_name=locked_app_package,
            reasoning=decision.reasoning,
            status="allowed_deviation",
        )

    async def _invoke_contextor_llm(
        self,
        initial_goal: str,
        subgoal_plan: list[Subgoal],
        agents_thoughts: list[str],
        locked_app_package: str,
        current_app_package: str,
    ) -> ContextorOutput:
        """Invoke the LLM to decide whether to relaunch the locked app."""

        MAX_AGENTS_THOUGHTS = 25

        system_message = Template(
            Path(__file__).parent.joinpath("contextor.md").read_text(encoding="utf-8")
        ).render(
            task_goal=initial_goal,
            subgoal_plan="\n".join([str(subgoal) for subgoal in subgoal_plan]),
            locked_app_package=locked_app_package,
            current_app_package=current_app_package,
            agents_thoughts=agents_thoughts[:MAX_AGENTS_THOUGHTS],
        )

        messages = [
            SystemMessage(content=system_message),
            HumanMessage(content="Please make your decision."),
        ]

        llm = get_llm(ctx=self.ctx, name="contextor").with_structured_output(ContextorOutput)
        llm_fallback = get_llm(
            ctx=self.ctx, name="contextor", use_fallback=True
        ).with_structured_output(ContextorOutput)

        response: ContextorOutput = await with_fallback(
            main_call=lambda: invoke_llm_with_timeout_message(llm.ainvoke(messages)),
            fallback_call=lambda: invoke_llm_with_timeout_message(llm_fallback.ainvoke(messages)),
        )  # type: ignore

        return response
