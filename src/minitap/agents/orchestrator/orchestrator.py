import time
from pathlib import Path

from jinja2 import Template
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from minitap.graph.state import State
from minitap.services.llm import get_google_llm
from minitap.tools.index import ALL_TOOLS
from minitap.tools.maestro import get_maestro_tools
from minitap.utils.adb import get_date, get_focused_app_info, get_screen_size
from minitap.utils.recorder import record_interaction


async def orchestrator(state: State):
    start_time = time.time()
    print(f"[TIMING] Starting orchestrator at {start_time}", flush=True)
    focused_app_info = get_focused_app_info()
    screensize = get_screen_size()
    device_date = get_date()
    system_message = Template(Path(__file__).parent.joinpath("orchestrator.md").read_text()).render(
        initial_goal=state.initial_goal,
        device_id=state.device_id,
        focused_app_info=focused_app_info,
        screensize=screensize,
        latest_ui_hierarchy=state.latest_ui_hierarchy,
        subgoal_history=state.subgoal_history,
        current_subgoal=state.current_subgoal,
        device_date=device_date,
        memory=state.memory,
    )
    messages = [
        SystemMessage(content=system_message),
        HumanMessage(content=state.initial_goal),
        *state.messages,
    ]
    print(f"[TIMING] Prepared messages at {time.time() - start_time}", flush=True)
    maestro_tools = await get_maestro_tools(return_all=False)
    llm = get_google_llm().bind_tools(
        tools=ALL_TOOLS + maestro_tools,
        tool_choice="auto",
    )
    print(f"DEBUG [chatbot] - LLM invoked with {len(messages)} messages..")
    try:
        print(f"[TIMING] Invoked LLM at {time.time() - start_time}", flush=True)
        response = await llm.ainvoke(messages)
    except Exception as e:
        print(
            f"[TIMING] LLM invocation failed after {time.time() - start_time:.2f} seconds",
            flush=True,
        )
        print(
            f"LLM invocation failed for goal: '{state.initial_goal}' ",
            e,
        )
        response = AIMessage(
            content="I apologize, but I encountered an error processing your request."
            " Please try again or contact support if the issue persists."
        )
    print("Response from LLM: " + str(response.content))

    if state.trace_id:
        screenshot_tool: BaseTool | None = None
        for tool in maestro_tools:
            if tool.name == "take_screenshot":
                screenshot_tool = tool
                break
        if screenshot_tool:
            record_interaction(
                trace_id=state.trace_id,
                response=response,
            )

    return {
        "messages": [response],
    }
