from langchain_core.messages import (
    HumanMessage,
    RemoveMessage,
    ToolMessage,
)

from minitap.mobile_use.constants import MAX_MESSAGES_IN_HISTORY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.graph.state import State


class SummarizerNode:
    def __init__(self, ctx: MobileUseContext):
        self.ctx = ctx

    async def __call__(self, state: State):
        if len(state.messages) <= MAX_MESSAGES_IN_HISTORY:
            return {}

        nb_removal_candidates = len(state.messages) - MAX_MESSAGES_IN_HISTORY

        remove_messages = []
        start_removal = False

        for msg in reversed(state.messages[:nb_removal_candidates]):
            if isinstance(msg, ToolMessage | HumanMessage):
                start_removal = True
            if start_removal and msg.id:
                remove_messages.append(RemoveMessage(id=msg.id))
            return await state.asanitize_update(
                ctx=self.ctx,
                update={
                    "messages": remove_messages,
                },
            )
