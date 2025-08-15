import asyncio
import uuid
from pathlib import Path

from jinja2 import Template
from langchain_core.messages import AIMessage, SystemMessage, ToolCall, ToolMessage
from pydantic import BaseModel, Field

from minitap.agents.executor.utils import is_last_tool_message_take_screenshot
from minitap.agents.planner.types import Subgoal, SubgoalStatus
from minitap.agents.planner.utils import get_current_subgoal
from minitap.config import get_default_llm_config
from minitap.context import DeviceContext
from minitap.controllers.mobile_command_controller import get_screen_data
from minitap.controllers.platform_specific_commands_controller import (
    get_device_date,
    get_focused_app_info,
)
from minitap.graph.state import State
from minitap.llm_config_context import LLMConfigContext, set_llm_config_context
from minitap.services.llm import get_llm
from minitap.utils.conversations import get_screenshot_message_for_llm
from minitap.utils.decorators import wrap_with_callbacks
from minitap.utils.logger import get_logger

logger = get_logger(__name__)


class KeyValuePair(BaseModel):
    key: str
    value: str


class PathOp(BaseModel):
    index: int
    key_value_pairs: list[KeyValuePair] = Field(
        description="Key-value pairs to add to the element at the given index"
    )


class ContextorOutput(BaseModel):
    patch_operations: list[PathOp]


@wrap_with_callbacks(
    before=lambda: logger.info("Starting Contextor Agent"),
    on_success=lambda _: logger.success("Contextor Agent"),
    on_failure=lambda _: logger.error("Contextor Agent"),
)
async def contextor_node(state: State):
    device_data = get_screen_data()
    focused_app_info = get_focused_app_info()
    device_date = get_device_date()

    latest_ui_hierarchy = device_data.elements

    should_add_screenshot_context = is_last_tool_message_take_screenshot(list(state.messages))

    if should_add_screenshot_context:
        focus_on_guidelines: str | None = (
            state.agents_thoughts[-1] if state.agents_thoughts else None
        )
        current_subgoal = get_current_subgoal(subgoals=state.subgoal_plan)
        system_message = Template(
            Path(__file__).parent.joinpath("contextor.md").read_text(encoding="utf-8")
        ).render(
            initial_goal=state.initial_goal,
            plan="\n".join(str(s) for s in state.subgoal_plan),
            current_subgoal=current_subgoal,
            ui_hierarchy=latest_ui_hierarchy,
            focused_app_info=focused_app_info,
            focus_on_guidelines=focus_on_guidelines,
        )
        messages = [
            SystemMessage(content=system_message),
            get_screenshot_message_for_llm(device_data.base64),
        ]

        llm = get_llm(agent_node="contextor")
        llm = llm.with_structured_output(ContextorOutput)
        response: ContextorOutput = await llm.ainvoke(messages)  # type: ignore
        if response and response.patch_operations:
            for op in response.patch_operations:
                patch = {kv.key: kv.value for kv in op.key_value_pairs}
                if op.index == -1:
                    latest_ui_hierarchy.append(patch)
                else:
                    try:
                        latest_ui_hierarchy[op.index].update(patch)
                    except IndexError:
                        logger.warning(f"Index {op.index} out of bounds for UI hierarchy")
            logger.success(
                "Enriched UI hierarchy with screenshot."
                f"Updated {len(response.patch_operations)} keys"
            )

    return {
        "latest_ui_hierarchy": latest_ui_hierarchy,
        "focused_app_info": focused_app_info,
        "screen_size": (device_data.width, device_data.height),
        "device_date": device_date,
    }


if __name__ == "__main__":
    random_id = str(uuid.uuid4())
    set_llm_config_context(llm_config_context=LLMConfigContext(llm_config=get_default_llm_config()))
    DeviceContext(
        host_platform="WINDOWS",
        mobile_platform="ANDROID",
        device_id="1234567890",
        device_width=1080,
        device_height=2340,
    ).set()
    mock_state = State(
        messages=[
            AIMessage(
                content="",
                tool_calls=[ToolCall(name="take_screenshot", id=random_id, args={})],
            ),
            ToolMessage(
                tool_call_id=random_id,
                name="take_screenshot",
                content="",
            ),
        ],
        initial_goal="Go on task.tml, and draw on the canvas anything using the colors displayed.",
        subgoal_plan=[
            Subgoal(
                description="Go in the files app",
                status=SubgoalStatus.SUCCESS,
                completion_reason="I successfully went in the files app",
            ),
            Subgoal(
                description="Open the file task.tml",
                status=SubgoalStatus.SUCCESS,
                completion_reason="I successfully opened the file task.tml",
            ),
            Subgoal(
                description="Draw on the canvas anything using the colors displayed",
                status=SubgoalStatus.PENDING,
                completion_reason=None,
            ),
        ],
        latest_ui_hierarchy=[],
        focused_app_info="com.google.chrome",
        device_date="",
        structured_decisions=None,
        executor_retrigger=False,
        executor_failed=False,
        executor_messages=[],
        cortex_last_thought="",
        agents_thoughts=[],
    )
    asyncio.run(contextor_node(mock_state))
