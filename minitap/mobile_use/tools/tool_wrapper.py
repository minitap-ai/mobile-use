from collections.abc import Callable

from langchain_core.tools import BaseTool
from pydantic import BaseModel

from minitap.mobile_use.context import MobileUseContext


class ToolWrapper(BaseModel):
    tool_fn_getter: Callable[[MobileUseContext], BaseTool]
    on_success_fn: Callable[..., str]
    on_failure_fn: Callable[..., str]


class CompositeToolWrapper(ToolWrapper):
    composite_tools_fn_getter: Callable[[MobileUseContext], list[BaseTool]]
