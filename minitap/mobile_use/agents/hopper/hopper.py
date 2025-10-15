from pathlib import Path

from jinja2 import Template
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.services.llm import get_llm, invoke_llm_with_timeout_message


class HopperOutput(BaseModel):
    output: str = Field(description="The interesting data extracted from the input data.")
    reason: str = Field(
        description="A short explanation of what you looked for"
        + " and how you decided what to extract."
    )


async def hopper(
    ctx: MobileUseContext,
    request: str,
    data: str,
) -> HopperOutput:
    print("Starting Hopper Agent", flush=True)
    system_message = Template(
        Path(__file__).parent.joinpath("hopper.md").read_text(encoding="utf-8")
    ).render()
    messages = [
        SystemMessage(content=system_message),
        HumanMessage(content=f"{request}\nHere is the data you must dig:\n{data}"),
    ]

    llm = get_llm(ctx=ctx, name="hopper", is_utils=True, temperature=0)
    structured_llm = llm.with_structured_output(HopperOutput)
    response: HopperOutput = await invoke_llm_with_timeout_message(
        structured_llm.ainvoke(messages), agent_name="Hopper"
    )  # type: ignore
    return response
