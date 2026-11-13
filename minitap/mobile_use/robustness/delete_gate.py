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
