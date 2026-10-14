import asyncio
import copy
from typing import Any, override

from langchain_core.messages import AnyMessage, ToolCall, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.tool_node import ToolRuntime
from langgraph.runtime import Runtime
from langgraph.types import Command
from pydantic import BaseModel

from minitap.mobile_use.services.telemetry import telemetry
from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


class ExecutorToolNode(ToolNode):
    """
    ToolNode that runs tool calls one after the other - not simultaneously.
    If one error occurs, the remaining tool calls are aborted!

    Upstream ToolNode has no public hook for sequential, abort-on-failure execution (it
    runs calls in parallel), so this overrides `_func`/`_afunc` and relies on private
    ToolNode methods (`_parse_input`, `_extract_state`, `_run_one`, `_arun_one`,
    `_combine_tool_outputs`). Their signatures change across minor releases, hence the
    minor-version cap on langgraph in pyproject.toml. When bumping it, diff upstream's
    `ToolNode._func` and run tests/mobile_use/test_executor_tool_node.py.
    """

    def __init__(self, tools, messages_key: str, trace_id: str | None = None):
        super().__init__(tools=tools, messages_key=messages_key)
        self._trace_id = trace_id

    @override
    async def _afunc(
        self,
        input: list[AnyMessage] | dict[str, Any] | BaseModel,
        config: RunnableConfig,
        runtime: Runtime,
    ):
        return await self.__func(is_async=True, input=input, config=config, runtime=runtime)

    @override
    def _func(
        self,
        input: list[AnyMessage] | dict[str, Any] | BaseModel,
        config: RunnableConfig,
        runtime: Runtime,
    ) -> Any:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(
            self.__func(is_async=False, input=input, config=config, runtime=runtime)
        )

    def _build_tool_runtime(
        self,
        call: ToolCall,
        input: list[AnyMessage] | dict[str, Any] | BaseModel,
        config: RunnableConfig,
        runtime: Runtime,
    ) -> Any:
        state = self._extract_state(input, config)
        return ToolRuntime(
            state=state,
            tool_call_id=call["id"],
            config=config,
            context=runtime.context,
            store=runtime.store,
            stream_writer=runtime.stream_writer,
            tools=list(self.tools_by_name.values()),
            execution_info=runtime.execution_info,
            server_info=runtime.server_info,
        )

    async def __func(
        self,
        is_async: bool,
        input: list[AnyMessage] | dict[str, Any] | BaseModel,
        config: RunnableConfig,
        runtime: Runtime,
    ) -> Any:
        tool_calls, input_type = self._parse_input(input)
        outputs: list[Command | ToolMessage | list[Command | ToolMessage]] = []
        failed = False
        for call in tool_calls:
            tool_runtime = self._build_tool_runtime(call, input, config, runtime)
            if failed:
                output = self._get_erroneous_command(
                    call=call,
                    message="Aborted: a previous tool call failed!",
                )
            else:
                if is_async:
                    output = await self._arun_one(call, input_type, tool_runtime)
                else:
                    output = self._run_one(call, input_type, tool_runtime)
                failed = self._has_tool_call_failed(call, output)
                if failed is None:
                    output = self._get_erroneous_command(
                        call=call,
                        message=f"Unexpected tool output type: {type(output)}",
                    )
                    failed = True

            call_without_state = copy.deepcopy(call)
            if "args" in call_without_state and "state" in call_without_state["args"]:
                del call_without_state["args"]["state"]
            if failed:
                error_msg = ""
                try:
                    if isinstance(output, ToolMessage):
                        error_msg = output.content
                    elif isinstance(output, Command):
                        error_msg = self._get_tool_message(output).content
                    elif tool_message := self._find_tool_message(output):
                        error_msg = tool_message.content
                except Exception:
                    error_msg = "Could not extract error details"

                logger.info(f"❌ Tool call failed: {call_without_state}")
                logger.info(f"   Error: {error_msg}")

                # Capture executor action telemetry
                if self._trace_id:
                    telemetry.capture_executor_action(
                        task_id=self._trace_id,
                        tool_name=call["name"],
                        success=False,
                        error=str(error_msg)[:500] if error_msg else None,
                    )
            else:
                logger.info("✅ Tool call succeeded: " + str(call_without_state))

                # Capture executor action telemetry
                if self._trace_id:
                    telemetry.capture_executor_action(
                        task_id=self._trace_id,
                        tool_name=call["name"],
                        success=True,
                    )

            outputs.append(output)
        return self._combine_tool_outputs(outputs, input_type)  # type: ignore

    def _has_tool_call_failed(
        self,
        call: ToolCall,
        output: ToolMessage | Command | list[Command | ToolMessage],
    ) -> bool | None:
        # langgraph-prebuilt >= 1.1 lets a tool return a list of ToolMessage/Command, with
        # exactly one ToolMessage for the call (others are plain state updates): judge on it.
        if isinstance(output, list):
            tool_message = self._find_tool_message(output)
            return None if tool_message is None else tool_message.status == "error"
        if isinstance(output, ToolMessage):
            return output.status == "error"
        if isinstance(output, Command):
            output_msg = self._get_tool_message(output)
            return output_msg.status == "error"
        return None

    def _find_tool_message(self, outputs: list[Command | ToolMessage]) -> ToolMessage | None:
        for item in outputs:
            if isinstance(item, ToolMessage):
                return item
            if isinstance(item, Command) and isinstance(item.update, dict):
                msg = item.update.get(self._messages_key)
                if isinstance(msg, ToolMessage):
                    return msg
                if isinstance(msg, list) and msg and isinstance(msg[-1], ToolMessage):
                    return msg[-1]
        return None

    def _get_erroneous_command(self, call: ToolCall, message: str) -> Command:
        tool_message = ToolMessage(
            name=call["name"], tool_call_id=call["id"], content=message, status="error"
        )
        return Command(update={self._messages_key: [tool_message]})

    def _get_tool_message(self, cmd: Command) -> ToolMessage:
        if isinstance(cmd.update, dict):
            msg = cmd.update.get(self._messages_key)
            if isinstance(msg, list):
                if len(msg) == 0:
                    raise ValueError("No messages found in command update")
                if not isinstance(msg[-1], ToolMessage):
                    raise ValueError("Last message in command update is not a tool message")
                return msg[-1]
            elif isinstance(msg, ToolMessage):
                return msg
            elif msg is None:
                raise ValueError(f"Missing '{self._messages_key}' in command update")
            raise ValueError(f"Unexpected message type in command update: {type(msg)}")
        raise ValueError("Command update is not a dict")
