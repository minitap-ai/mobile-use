"""P2 F5: order-based targets (newest, oldest, largest...), made deterministic.

Observed in version B (6/6 attempts of one task, 4 prompt layers): the models assume "sorted by
date = newest first" and delete the top row, even when the sort menu on screen shows the reverse
option OFF (an ascending sort: newest LAST) and every row shows the same displayed time. Prompt
rules were paraphrased away by the Planner and ignored by the Cortex and the verifier. Two
deterministic aids, both app-agnostic:

1. `sort_fact`: when the UI tree shows a checkable option labelled reverse/descending/ascending/
   newest-first/oldest-first, record the selected sort key and that option's state, and show the
   fact to the Cortex and the verifier for the rest of the task.
2. `order_subgoal`: for goals with a superlative, insert a literal "establish the order first"
   subgoal into the first plan (the Planner model drops such rules when paraphrasing).
"""

from __future__ import annotations

import re

from minitap.mobile_use.utils.ui_hierarchy import ElementBounds, get_bounds_for_element

DIRECTION_RE = re.compile(
    r"\b(reverse(d)?( order)?|descending|ascending|newest first|oldest first|latest first|"
    r"most recent first|smallest first|largest first)\b",
    re.I,
)
SUPERLATIVE_RE = re.compile(
    r"\b(newest|oldest|latest|earliest|most recent|least recent|largest|smallest|biggest|"
    r"longest|shortest|highest|lowest|first created|last created|last modified)\b",
    re.I,
)


def _iter(elements):
    for el in elements or []:
        if isinstance(el, dict):
            yield el
            yield from _iter(el.get("children") or [])


def _label_for(check: dict, texts: list[tuple[str, ElementBounds]]) -> str | None:
    own = (check.get("text") or check.get("content-desc") or "").strip()
    if own:
        return own
    b = get_bounds_for_element(check)
    if b is None:
        return None
    cy = b.y + b.height // 2
    row = [t for t, tb in texts if tb.y <= cy <= tb.y + tb.height]
    return row[0] if row else None


def sort_fact(elements) -> str | None:
    """A one-line fact about the sort settings visible on screen, or None."""
    els = list(_iter(elements))
    texts = []
    for e in els:
        t = (e.get("text") or "").strip()
        b = get_bounds_for_element(e)
        if t and b is not None and len(t) <= 40:
            texts.append((t, b))
    checks = [e for e in els if e.get("checkable") == "true"]
    direction, key = None, None
    for c in checks:
        label = _label_for(c, texts)
        if not label:
            continue
        if DIRECTION_RE.search(label):
            direction = (label, c.get("checked") == "true")
        elif c.get("checked") == "true" and len(label) <= 25:
            key = label
    if direction is None:
        return None
    label, on = direction
    low = label.lower()
    if "reverse" in low:
        meaning = (
            "the order is REVERSED: newest/largest FIRST, oldest/smallest LAST"
            if on
            else "the order is ascending: oldest/smallest FIRST, newest/largest LAST"
        )
    elif any(w in low for w in ("descending", "newest first", "latest first", "most recent first", "largest first")):
        meaning = (
            "newest/largest FIRST" if on else "this option is off: oldest/smallest FIRST, newest/largest LAST"
        )
    else:  # ascending / oldest first / smallest first
        meaning = (
            "oldest/smallest FIRST, newest/largest LAST" if on else "this option is off: newest/largest FIRST"
        )
    by = f"sorted by '{key}', " if key else ""
    return (
        f"Sort settings seen on screen: {by}'{label}' is {'ON' if on else 'OFF'}, so {meaning} "
        "(convention for a separate direction option; if the list shows DISTINCT values of the "
        "sort attribute, those values decide)."
    )


def record_sort_fact(ctx, elements) -> None:
    fact = sort_fact(elements)
    if fact:
        ctx.p2_sort_fact = fact


ORDER_SUBGOAL = (
    "Establish the order BEFORE choosing the item: open the sort/order options and note the sort "
    "key and whether a reverse/descending option is on (with a separate reverse option OFF the "
    "order is ascending: newest/largest LAST), or compare the items' actual values; do not act "
    "on any item in this subgoal"
)


def needs_order_subgoal(goal: str) -> bool:
    return bool(SUPERLATIVE_RE.search(goal or ""))


def insert_order_subgoal(goal: str, subgoals: list, make_subgoal) -> list:
    """Insert ORDER_SUBGOAL after a leading 'open/launch' subgoal (else first), once."""
    if not needs_order_subgoal(goal):
        return subgoals
    if any("establish the order" in (s.description or "").lower() for s in subgoals):
        return subgoals
    pos = 1 if subgoals and re.search(r"\b(open|launch|start)\b", subgoals[0].description, re.I) else 0
    return subgoals[:pos] + [make_subgoal(ORDER_SUBGOAL)] + subgoals[pos:]
