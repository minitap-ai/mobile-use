"""P2 F7: the Cortex's decided text is what gets typed.

Observed in version A: the Executor (a smaller model) copied the Cortex's text into the
`focus_and_input_text` call with corruption ("Sauté" -> "Sã©", mojibake of a non-ASCII
character), and the corrupted text was typed and saved. The Cortex decision is available in
the state, so when the typed text is a near-copy of one string of that decision (but not equal
to it), the decision's string is typed instead.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from minitap.mobile_use.tools.text_fidelity import decision_strings, unescape_controls

MIN_RATIO = 0.85
MIN_LEN = 4


def restore_from_decision(text: str, decisions: str | None) -> str | None:
    """The decision string the Executor meant to copy, if `text` is a corrupted copy of it."""
    if not text or len(text) < MIN_LEN:
        return None
    cands = [unescape_controls(s) for s in decision_strings(decisions)]
    cands = [c for c in cands if len(c) >= MIN_LEN]
    if text in cands:
        return None
    best, best_ratio = None, 0.0
    for c in cands:
        if abs(len(c) - len(text)) > max(8, 0.2 * len(c)):
            continue
        r = SequenceMatcher(None, text, c, autojunk=False).ratio()
        if r > best_ratio:
            best, best_ratio = c, r
    if best is not None and best_ratio >= MIN_RATIO:
        return best
    return None


def trailing_newlines_missing(intended: str, read_back: str | None) -> int:
    """D3: how many of the intended text's trailing newlines the field's raw readback lacks.

    0 when nothing was read back (no evidence), when the readback has at least as many, or when the
    field is not shown to be multi-line: both the text body and the readback must already contain a
    line break. A single-line field (a search box) never keeps a newline, and there the first Enter
    submitted; pressing it again would submit twice."""
    if not read_back:
        return 0
    if "\n" not in intended.rstrip("\n") or "\n" not in read_back.rstrip("\n"):
        return 0
    want = len(intended) - len(intended.rstrip("\n"))
    have = len(read_back) - len(read_back.rstrip("\n"))
    return max(0, want - have)
