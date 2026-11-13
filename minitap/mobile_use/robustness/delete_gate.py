"""D3: one-time verifier gate for goals that delete named items.

Observed in version B (held-out seed): the goal named one item to delete; the app's search for its
exact name returned nothing, the agents concluded it was absent and executed no delete action, and
the verifier accepted "absent" from that one empty search. Existing prompt rules (an empty search
is not proof; read the complete list) were not applied. A goal that names an item to delete
presupposes that it exists, so a "satisfied" verdict with no delete action at all is turned into
ONE rejection that asks for a complete read of the list. It fires at most once per run; if the item
is really absent, the next verdict stands.

Trigger (goal wording only): "delete"/"remove" followed by an explicit naming of the item(s):
"the following", "named", "titled", "the title", "the file".
"""

from __future__ import annotations

import re

NAMED_DELETE_RE = re.compile(
    r"\b(?:delete|remove)\b.*?\b(?:the following|named|titled|the title|the file)\b",
    re.IGNORECASE | re.DOTALL,
)

GATE_MESSAGE = (
    "This goal deletes named item(s), but the execution log shows no delete action at all. A search "
    "or filter that finds nothing is not proof that an item is absent (an app's search can mishandle "
    "punctuation or special characters). Clear any search or filter, read the full list to its end "
    "(read_full_list) and look for each named item by its exact name; delete each one that is there. "
    "Conclude that an item is absent only from that complete read."
)


def is_named_delete_goal(goal: str) -> bool:
    return bool(NAMED_DELETE_RE.search(goal or ""))


def delete_gate(ctx, goal: str) -> str | None:
    """Return the rejection text if the gate fires (and mark it used), else None."""
    if ctx.p2_delete_gate_used or ctx.p2_delete_seen or not is_named_delete_goal(goal):
        return None
    ctx.p2_delete_gate_used = True
    return GATE_MESSAGE


# --- D4 candidate (a): named items still in the verifier's complete list read ---
# Observed on D3 (held-out seed): 3 recipes named, 2 deleted; the third was not found by the app's
# search (a hyphen), the agents moved on, and the gate above did not fire because deletes existed.
# Trigger (goal wording only): "delete/remove the following <noun>: A, B, C" (a list of names).
_LIST_DELETE_RE = re.compile(
    r"\b(?:delete|remove)\b[^:]*?\bthe following\b[^:]*:\s*(?P<items>.+)$", re.IGNORECASE | re.DOTALL
)

PRESENCE_MESSAGE = (
    "The complete read of the list just now still shows these item(s) the goal names for deletion: "
    "{names}. Delete each of them. An item the app's search does not find can still be in the list: "
    "find it by reading the list, not only by searching."
)


def listed_delete_names(goal: str) -> list[str]:
    m = _LIST_DELETE_RE.search(goal or "")
    if not m:
        return []
    items = m.group("items").strip()
    if items.endswith("."):
        items = items[:-1]
    return [x.strip() for x in items.split(", ") if x.strip()]


def names_still_listed(goal: str, full_read: str | None) -> list[str]:
    """Named items equal to a whole text segment of a row of the verifier's complete list read."""
    names = listed_delete_names(goal)
    if not names or not full_read:
        return []
    segments: set[str] = set()
    for line in full_read.splitlines()[1:]:
        _, _, row = line.partition(". ")
        segments.update(s.strip() for s in row.split(" | "))
    return [n for n in names if n in segments]


def presence_gate(ctx, goal: str, full_read: str | None) -> str | None:
    if ctx.p2_delete_presence_used:
        return None
    left = names_still_listed(goal, full_read)
    if not left:
        return None
    ctx.p2_delete_presence_used = True
    return PRESENCE_MESSAGE.format(names=", ".join(f'"{n}"' for n in left))


# --- D4 candidate (b): a delete in a goal that copies records into an app from a named source ---
# Observed on D3 (held-out seed): two same-title rows looked like a failed add; the agents deleted
# their own correct record and overwrote a pre-existing one; the verifier passed ("no other item was
# added"). Backtest over all p2 runs of goals with this trigger: a delete was executed in 20 failed
# runs and in 5 passed ones, so this is ONE soft rejection, never a hard block.
# Trigger: the source-copy trigger of checklist.is_source_copy_goal plus an executed delete action.
ADD_DELETE_MESSAGE = (
    "This goal only adds records copied from a source, but a delete was executed during the run. Do "
    "not delete or edit anything more. Check, reading the list and opening records: every record that "
    "existed before this run is unchanged; every record the goal asks for is present exactly once with "
    "the source's values. Re-add one of yours only if it is missing. If all of this holds, finish."
)


def add_delete_gate(ctx, goal: str) -> str | None:
    from minitap.mobile_use.robustness.checklist import is_source_copy_goal

    if ctx.p2_add_delete_gate_used or not ctx.p2_delete_seen or not is_source_copy_goal(goal):
        return None
    ctx.p2_add_delete_gate_used = True
    return ADD_DELETE_MESSAGE
