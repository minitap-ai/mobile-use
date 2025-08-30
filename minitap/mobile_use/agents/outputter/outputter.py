import json
from pathlib import Path

from jinja2 import Template
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from minitap.mobile_use.config import OutputConfig
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.services.llm import get_llm
from minitap.mobile_use.utils.conversations import is_ai_message
from minitap.mobile_use.utils.logger import get_logger
from pydantic import BaseModel

logger = get_logger(__name__)


async def outputter(
    ctx: MobileUseContext, output_config: OutputConfig, graph_output: State
) -> dict:
    logger.info("Starting Outputter Agent")
    last_message = graph_output.messages[-1] if graph_output.messages else None

    system_message = (
        "You are a helpful assistant tasked with generating "
        + "the final structured output of a multi-agent reasoning process."
    )
    human_message = Template(
        Path(__file__).parent.joinpath("human.md").read_text(encoding="utf-8")
    ).render(
        initial_goal=graph_output.initial_goal,
        agents_thoughts=graph_output.agents_thoughts,
        structured_output=output_config.structured_output,
        output_description=output_config.output_description,
        last_ai_message=last_message.content
        if last_message and is_ai_message(message=last_message)
        else None,
    )

    messages: list[BaseMessage] = [
        SystemMessage(content=system_message),
        HumanMessage(content=human_message),
    ]

    if output_config.output_description:
        messages.append(HumanMessage(content=output_config.output_description))

    llm = get_llm(ctx=ctx, name="outputter", is_utils=True, temperature=1)
    structured_llm = llm

    if output_config.structured_output:
        schema: dict | type[BaseModel] | None = None
        so = output_config.structured_output

        if isinstance(so, dict):
            schema = so
        elif isinstance(so, BaseModel):
            schema = type(so)
        elif isinstance(so, type) and issubclass(so, BaseModel):
            schema = so

        if schema is not None:
            structured_llm = llm.with_structured_output(schema)

    response = await structured_llm.ainvoke(messages)  # type: ignore
    if isinstance(response, BaseModel):
        if output_config.output_description and hasattr(response, "content"):
            response = json.loads(response.content)  # type: ignore
            return response
        return response.model_dump()
    elif hasattr(response, "content"):
        return json.loads(response.content)  # type: ignore
    else:
        logger.info("Found unknown response type: " + str(type(response)))
    return response
