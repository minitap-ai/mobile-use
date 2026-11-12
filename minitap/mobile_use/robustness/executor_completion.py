"""P2 (architecture-adjacent, flag p2_executor_completion, approved 2026-11-12, disclosed):
dispatch the Cortex-decided actions the Executor LLM did not emit.

Observed in version B dev rounds 2-5 (4,721 Cortex turns): the Executor model emitted at most ONE
tool call per message, even when the Cortex decided a list of predictable actions (e.g. several
form fields), and emitted NO tool call at all in 169 turns. Each lost action costs a full Cortex
turn (~6 graph steps). The Executor LLM still runs every turn; this only appends, in order, the
actions of the Cortex's own JSON that the Executor left out, and stops after the first action
that can change the screen unpredictably (the Cortex's own rule: such an action ends the turn).
Every appended call is logged (`p2_executor_completion` event) so the rate can be reported.
"""

from __future__ import annotations

import json

from minitap.mobile_use.tools.text_fidelity import canonical_decisions

# Actions that never change which screen is shown: several may run in one turn.
PREDICTABLE = {
    "focus_and_input_text",
    "focus_and_clear_text",
    "erase_one_char",
    "save_note",
    "read_note",
    "list_notes",
    "calculate",
    "read_full_list",
    "sample_colors",
    "wait_for_delay",
}


def parse_decisions(decisions: str | None) -> list[dict]:
    if not decisions:
        return []
    try:
        obj = json.loads(canonical_decisions(decisions) or "")
    except (json.JSONDecodeError, TypeError):
        return []
    if isinstance(obj, dict):
        obj = [obj]
    return [d for d in obj if isinstance(d, dict) and isinstance(d.get("action"), str)]


def completion_calls(decisions: str | None, emitted: list[dict], tools: dict) -> list[dict]:
    """Tool calls to append. `emitted`: the Executor's tool calls; `tools`: name -> BaseTool."""
    actions = parse_decisions(decisions)
    if len(emitted) >= len(actions):
        return []
    # The Executor covers a prefix of the decided list (it executes in order); complete the rest.
    rest = actions[len(emitted):]
    if emitted and emitted[-1].get("name") not in PREDICTABLE:
        return []  # the Executor already ended the turn on a screen-changing action
    out: list[dict] = []
    for i, d in enumerate(rest):
        name = d["action"]
        tool = tools.get(name)
        if tool is None:
            break  # unknown action name: leave it to the next Cortex turn
        args = {k: v for k, v in d.items() if k != "action"}
        args.setdefault("agent_thought", f"Dispatched from the Cortex decision ({name}).")
        try:
            tool.tool_call_schema.model_validate(args)
        except Exception:
            break
        out.append({"name": name, "args": args, "id": f"p2c_{len(emitted) + i}", "type": "tool_call"})
        if name not in PREDICTABLE:
            break  # a screen-changing action ends the batch
    return out
