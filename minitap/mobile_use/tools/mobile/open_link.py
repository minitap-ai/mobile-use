from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.unified_controller import UnifiedMobileController
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.tools.tool_wrapper import ToolWrapper
from minitap.mobile_use.utils.app_launch_utils import get_strict_locked_app_package
from minitap.mobile_use.utils.app_lock_events import record_app_lock_event


def get_open_link_tool(ctx: MobileUseContext):
    @tool
    async def open_link(
        agent_thought: str,
        url: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
    ) -> Command:
        """
        Open a link on a device (i.e. a deep link).
        """
        locked_app_package = get_strict_locked_app_package(ctx)
        if locked_app_package:
            # A deep link delegates its handler to the operating system. The
            # strict policy cannot prove which app will receive it, so it must
            # not permit that foreground-app handoff. The URL is not recorded.
            record_app_lock_event(
                locked_app_package=locked_app_package,
                action="open_link",
                decision="blocked",
                reason="os_routed_deep_link",
            )
            has_failed = True
            output = (
                "Strict app lock blocks deep links because their destination "
                "package cannot be verified before launch."
            )
            agent_outcome = open_link_wrapper.on_failure_fn()
        else:
            controller = UnifiedMobileController(ctx)
            success = await controller.open_url(url)
            has_failed = not success
            output = "Failed to open URL" if has_failed else None
            agent_outcome = (
                open_link_wrapper.on_failure_fn()
                if has_failed
                else open_link_wrapper.on_success_fn(url)
            )

        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=agent_outcome,
            additional_kwargs={"error": output} if has_failed else {},
            status="error" if has_failed else "success",
        )
        return Command(
            update=await state.asanitize_update(
                ctx=ctx,
                update={
                    "agents_thoughts": [agent_thought, agent_outcome],
                    EXECUTOR_MESSAGES_KEY: [tool_message],
                },
                agent="executor",
            ),
        )

    return open_link


open_link_wrapper = ToolWrapper(
    tool_fn_getter=get_open_link_tool,
    on_success_fn=lambda url: f"Link {url} opened successfully.",
    on_failure_fn=lambda: "Failed to open link.",
)
