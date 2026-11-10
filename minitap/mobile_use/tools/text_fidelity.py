"""Deterministic fidelity of the text the agent types (fix round, failure class M3).

Observed in the pilot (task-agnostic mechanisms):
- the Cortex's decisions were not always strict JSON (Python-style single quotes), so the text
  reaching the Executor was cut at the first apostrophe; the Cortex then "worked around" it with a
  typographic apostrophe, which is not the character the goal asked for;
- escaped newlines (backslash + n) were typed literally instead of as line breaks.

This module never invents text: it only (1) turns the escapes \\n and \\t into the characters
they stand for, (2) restores text the Executor truncated at a quote, from the Cortex's own
decision, and (3) restores the goal's exact characters when the typed text is a span of the goal
that differs only by quote style.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field

QUOTE_MAP = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "′": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "″": '"',
    }
)
QUOTE_CHARS = set("'\"") | set("‘’‚‛“”„‟")


def canonical_decisions(decisions: str | None) -> str | None:
    """Cortex decisions as strict JSON (double quotes), when they are a JSON or Python literal."""
    if not decisions or not decisions.strip():
        return decisions
    try:
        json.loads(decisions)
        return decisions
    except (json.JSONDecodeError, TypeError):
        pass
    try:
        obj = ast.literal_eval(decisions.strip())
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return decisions
    if not isinstance(obj, dict | list):
        return decisions
    return json.dumps(obj, ensure_ascii=False)


def _strings(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _strings(v)]
    if isinstance(obj, list):
        return [s for v in obj for s in _strings(v)]
    return []


def decision_strings(decisions: str | None) -> list[str]:
    if not decisions:
        return []
    canon = canonical_decisions(decisions)
    try:
        return _strings(json.loads(canon or ""))
    except (json.JSONDecodeError, TypeError):
        return []


def unescape_controls(text: str) -> str:
    """Literal backslash-n / backslash-t (as typed by an LLM that double-escaped) -> \\n / \\t."""
    if "\\" not in text:
        return text
    return text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")


@dataclass
class FidelityResult:
    text: str
    changes: list[str] = field(default_factory=list)


def restore_text(text: str, *, goal: str | None, decisions: str | None) -> FidelityResult:
    """The text to type, with the deterministic corrections listed in `changes`."""
    out, changes = text, []

    unescaped = unescape_controls(out)
    if unescaped != out:
        changes.append("escaped_control_chars")
        out = unescaped

    # (2) truncated at a quote: the Cortex decided a longer string that continues with a quote
    for cand in sorted(decision_strings(decisions), key=len, reverse=True):
        cand = unescape_controls(cand)
        if len(cand) > len(out) and cand.startswith(out) and cand[len(out)] in QUOTE_CHARS and out:
            out = cand
            changes.append("restored_truncation_at_quote")
            break

    # (3) same span as the goal except for quote style -> the goal's exact characters
    if goal and out and out not in goal:
        norm_out, norm_goal = out.translate(QUOTE_MAP), goal.translate(QUOTE_MAP)
        idx = norm_goal.find(norm_out)
        if idx >= 0:  # QUOTE_MAP is 1:1 per character, so indices match
            out = goal[idx : idx + len(out)]
            changes.append("restored_goal_quotes")

    return FidelityResult(out, changes)
