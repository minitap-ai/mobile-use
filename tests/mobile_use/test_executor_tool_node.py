"""Tests for ExecutorToolNode (regression for issue #213)."""

from unittest.mock import Mock

from langchain_core.tools import tool

from minitap.mobile_use.agents.executor.tool_node import ExecutorToolNode


@tool
def dummy_tool() -> str:
    """A no-op tool used only for constructing the node."""
    return "ok"


def _make_runtime() -> Mock:
    runtime = Mock()
    runtime.context = None
    runtime.store = None
    runtime.stream_writer = None
    return runtime


def test_build_tool_runtime_forwards_config():
    """_extract_state requires `config` on langgraph-prebuilt >= 1.1.0.

    Regression test for #213: _build_tool_runtime called
    `self._extract_state(input)` without the `config` argument, raising
    `TypeError: ToolNode._extract_state() missing 1 required positional
    argument: 'config'` on every tool execution.
    """
    node = ExecutorToolNode(tools=[dummy_tool], messages_key="messages")
    call = {"name": "dummy_tool", "args": {}, "id": "call_1", "type": "tool_call"}
    input_state = {"messages": []}
    config = {"configurable": {"thread_id": "test-thread"}}

    tool_runtime = node._build_tool_runtime(call, input_state, config, _make_runtime())

    assert tool_runtime.config == config
    assert tool_runtime.state == input_state
    assert tool_runtime.tool_call_id == "call_1"
