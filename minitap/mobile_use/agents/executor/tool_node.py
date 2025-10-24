import asyncio
import copy
from typing import Any, override

from langchain_core.messages import AnyMessage, ToolCall, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import ToolNode
from langgraph.store.base import BaseStore
from langgraph.types import Command
from pydantic import BaseModel

from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


class ExecutorToolNode(ToolNode):
    """
    ToolNode that runs tool calls one after the other - not simultaneously.
    If one error occurs, the remaining tool calls are aborted!
    """

    @override
    async def _afunc(
        self,
        input: list[AnyMessage] | dict[str, Any] | BaseModel,
        config: RunnableConfig,
        *,
        store: BaseStore | None,
    ):
        return await self.__func(is_async=True, input=input, config=config, store=store)

    @override
    def _func(
        self,
        input: list[AnyMessage] | dict[str, Any] | BaseModel,
        config: RunnableConfig,
        *,
        store: BaseStore | None,
    ) -> Any:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(
            self.__func(is_async=False, input=input, config=config, store=store)
        )

    async def __func(
        self,
        is_async: bool,
        input: list[AnyMessage] | dict[str, Any] | BaseModel,
        config: RunnableConfig,
        *,
        store: BaseStore | None,
    ) -> Any:
        tool_calls, input_type = self._parse_input(input, store)
        outputs: list[Command | ToolMessage] = []
        failed = False
        for call in tool_calls:
            if failed:
                output = self._get_erroneous_command(
                    call=call,
                    message="Aborted: a previous tool call failed!",
                )
            else:
                if is_async:
                    output = await self._arun_one(call, input_type, config)
                else:
                    output = self._run_one(call, input_type, config)
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
                        tool_msg = self._get_tool_message(output)
                        error_msg = tool_msg.content
                except Exception:
                    error_msg = "Could not extract error details"

                logger.info(f"❌ Tool call failed: {call_without_state}")
                logger.info(f"   Error: {error_msg}")
            else:
                logger.info("✅ Tool call succeeded: " + str(call_without_state))

            outputs.append(output)
        return self._combine_tool_outputs(outputs, input_type)  # type: ignore

    def _has_tool_call_failed(
        self,
        call: ToolCall,
        output: ToolMessage | Command,
    ) -> bool | None:
        if isinstance(output, ToolMessage):
            return output.status == "error"
        if isinstance(output, Command):
            output_msg = self._get_tool_message(output)
            return output_msg.status == "error"
        return None

    def _get_erroneous_command(self, call: ToolCall, message: str) -> Command:
        tool_message = ToolMessage(
            name=call["name"], tool_call_id=call["id"], content=message, status="error"
        )
        return Command(update={self.messages_key: [tool_message]})

    def _get_tool_message(self, cmd: Command) -> ToolMessage:
        if isinstance(cmd.update, dict):
            msg = cmd.update.get(self.messages_key)
            if isinstance(msg, list):
                if len(msg) == 0:
                    raise ValueError("No messages found in command update")
                if not isinstance(msg[-1], ToolMessage):
                    raise ValueError("Last message in command update is not a tool message")
                return msg[-1]
            elif isinstance(msg, ToolMessage):
                return msg
            elif msg is None:
                raise ValueError(f"Missing '{self.messages_key}' in command update")
            raise ValueError(f"Unexpected message type in command update: {type(msg)}")
        raise ValueError("Command update is not a dict")
