from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel

from minitap.mobile_use.constants import EXECUTOR_MESSAGES_KEY
from minitap.mobile_use.context import MobileUseContext
from minitap.mobile_use.controllers.mobile_command_controller import (
    erase_text as erase_text_controller,
)
from minitap.mobile_use.controllers.mobile_command_controller import get_screen_data
from minitap.mobile_use.graph.state import State
from minitap.mobile_use.tools.tool_wrapper import ToolWrapper
from minitap.mobile_use.tools.types import Target
from minitap.mobile_use.tools.utils import focus_element_if_needed, move_cursor_to_end_if_bounds
from minitap.mobile_use.utils.logger import get_logger
from minitap.mobile_use.utils.ui_hierarchy import (
    find_element_by_resource_id,
    get_element_text,
    text_input_is_empty,
)

logger = get_logger(__name__)

MAX_CLEAR_TRIES = 5
DEFAULT_CHARS_TO_ERASE = 50


class ClearTextResult(BaseModel):
    success: bool
    error_message: str | None
    chars_erased: int
    final_text: str | None


class TextClearer:
    def __init__(self, ctx: MobileUseContext, state: State):
        self.ctx = ctx
        self.state = state

    def _refresh_ui_hierarchy(self) -> None:
        screen_data = get_screen_data(screen_api_client=self.ctx.screen_api_client)
        self.state.latest_ui_hierarchy = screen_data.elements

    def _get_element_info(
        self, resource_id: str | None
    ) -> tuple[object | None, str | None, str | None]:
        if not self.state.latest_ui_hierarchy:
            self._refresh_ui_hierarchy()

        if not self.state.latest_ui_hierarchy:
            return None, None, None

        element = None
        if resource_id:
            element = find_element_by_resource_id(
                ui_hierarchy=self.state.latest_ui_hierarchy, resource_id=resource_id
            )

        if not element:
            return None, None, None

        current_text = get_element_text(element)
        hint_text = get_element_text(element, hint_text=True)

        return element, current_text, hint_text

    def _format_text_with_hint_info(self, text: str | None, hint_text: str | None) -> str | None:
        if text is None:
            return None

        is_hint_text = hint_text is not None and hint_text != "" and hint_text == text

        if is_hint_text:
            return f"{text} (which is the hint text, the input is very likely empty)"

        return text

    def _should_clear_text(self, current_text: str | None, hint_text: str | None) -> bool:
        return current_text is not None and current_text != "" and current_text != hint_text

    def _prepare_element_for_clearing(
        self,
        target: Target,
    ) -> bool:
        if not focus_element_if_needed(
            ctx=self.ctx,
            target=target,
        ):
            return False

        move_cursor_to_end_if_bounds(
            ctx=self.ctx,
            state=self.state,
            target=target,
        )
        return True

    def _erase_text_attempt(self, text_length: int) -> str | None:
        chars_to_erase = text_length + 1
        logger.info(f"Erasing {chars_to_erase} characters from the input")

        error = erase_text_controller(ctx=self.ctx, nb_chars=chars_to_erase)
        if error:
            logger.error(f"Failed to erase text: {error}")
            return str(error)

        return None

    def _clear_with_retries(
        self,
        target: Target,
        initial_text: str,
        hint_text: str | None,
    ) -> tuple[bool, str | None, int]:
        current_text = initial_text
        erased_chars = 0

        for attempt in range(1, MAX_CLEAR_TRIES + 1):
            logger.info(f"Clear attempt {attempt}/{MAX_CLEAR_TRIES}")

            chars_to_erase = len(current_text) if current_text else DEFAULT_CHARS_TO_ERASE
            error = self._erase_text_attempt(text_length=chars_to_erase)

            if error:
                return False, current_text, 0
            erased_chars += chars_to_erase

            self._refresh_ui_hierarchy()
            elt = None
            if target.resource_id:
                elt = find_element_by_resource_id(
                    ui_hierarchy=self.state.latest_ui_hierarchy or [],
                    resource_id=target.resource_id,
                )
                if elt:
                    current_text = get_element_text(elt)
                    logger.info(f"Current text: {current_text}")
                    if text_input_is_empty(text=current_text, hint_text=hint_text):
                        break

            move_cursor_to_end_if_bounds(
                ctx=self.ctx,
                state=self.state,
                target=target,
                elt=elt,
            )

        return True, current_text, erased_chars

    def _create_result(
        self,
        success: bool,
        error_message: str | None,
        chars_erased: int,
        final_text: str | None,
        hint_text: str | None,
    ) -> ClearTextResult:
        formatted_final_text = self._format_text_with_hint_info(final_text, hint_text)

        return ClearTextResult(
            success=success,
            error_message=error_message,
            chars_erased=chars_erased,
            final_text=formatted_final_text,
        )

    def _handle_no_clearing_needed(
        self, current_text: str | None, hint_text: str | None
    ) -> ClearTextResult:
        return self._create_result(
            success=True,
            error_message=None,
            chars_erased=-1,
            final_text=current_text,
            hint_text=hint_text,
        )

    def _handle_element_not_found(
        self, resource_id: str | None, hint_text: str | None
    ) -> ClearTextResult:
        error = erase_text_controller(ctx=self.ctx)
        self._refresh_ui_hierarchy()

        _, final_text, _ = self._get_element_info(resource_id)

        return self._create_result(
            success=error is None,
            error_message=str(error) if error is not None else None,
            chars_erased=0,  # Unknown since we don't have initial text
            final_text=final_text,
            hint_text=hint_text,
        )

    def clear_input_text(
        self,
        target: Target,
    ) -> ClearTextResult:
        element, current_text, hint_text = self._get_element_info(
            resource_id=target.resource_id,
        )

        if not element:
            return self._handle_element_not_found(target.resource_id, hint_text)

        if not self._should_clear_text(current_text, hint_text):
            return self._handle_no_clearing_needed(current_text, hint_text)

        if not self._prepare_element_for_clearing(
            target=target,
        ):
            return self._create_result(
                success=False,
                error_message="Failed to focus element",
                chars_erased=0,
                final_text=current_text,
                hint_text=hint_text,
            )

        success, final_text, chars_erased = self._clear_with_retries(
            target=target,
            initial_text=current_text or "",
            hint_text=hint_text,
        )

        error_message = None if success else "Failed to clear text after retries"

        return self._create_result(
            success=success,
            error_message=error_message,
            chars_erased=chars_erased,
            final_text=final_text,
            hint_text=hint_text,
        )


def get_focus_and_clear_text_tool(ctx: MobileUseContext):
    @tool
    async def focus_and_clear_text(
        tool_call_id: Annotated[str, InjectedToolCallId],
        state: Annotated[State, InjectedState],
        agent_thought: str,
        target: Target,
    ):
        """
        Clears all the text from the text field, by focusing it if needed.
        """
        clearer = TextClearer(ctx, state)
        result = clearer.clear_input_text(
            target=target,
        )

        agent_outcome = (
            focus_and_clear_text_wrapper.on_failure_fn(result.error_message)
            if not result.success
            else focus_and_clear_text_wrapper.on_success_fn(
                nb_char_erased=result.chars_erased, new_text_value=result.final_text
            )
        )

        tool_message = ToolMessage(
            tool_call_id=tool_call_id,
            content=agent_outcome,
            additional_kwargs={"error": result.error_message} if not result.success else {},
            status="error" if not result.success else "success",
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

    return focus_and_clear_text


def _format_success_message(nb_char_erased: int, new_text_value: str | None) -> str:
    if nb_char_erased == -1:
        msg = "No text clearing was needed (the input was already empty)."
    else:
        msg = f"Text erased successfully. {nb_char_erased} characters were erased."

    if new_text_value is not None:
        msg += f" New text in the input is '{new_text_value}'."

    return msg


def _format_failure_message(output: str | None) -> str:
    return "Failed to erase text. " + (str(output) if output else "")


focus_and_clear_text_wrapper = ToolWrapper(
    tool_fn_getter=get_focus_and_clear_text_tool,
    on_success_fn=_format_success_message,
    on_failure_fn=_format_failure_message,
)
