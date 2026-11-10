"""Fix round 2: deterministic fidelity of typed text (failure class M3)."""

import json

import pytest

from minitap.mobile_use.tools.text_fidelity import (
    canonical_decisions,
    restore_text,
    unescape_controls,
)


def test_canonical_decisions_turns_python_literals_into_json():
    py = "[{'action': 'type', 'text': \"Bob's note\"}]"
    canon = canonical_decisions(py)
    assert json.loads(canon) == [{"action": "type", "text": "Bob's note"}]
    good = '[{"action": "tap"}]'
    assert canonical_decisions(good) == good
    assert canonical_decisions("tap the OK button") == "tap the OK button"  # free text kept
    assert canonical_decisions(None) is None


def test_unescape_controls():
    assert unescape_controls("Title\\n\\nBody") == "Title\n\nBody"
    assert unescape_controls("a\\tb") == "a\tb"
    assert unescape_controls("no escapes") == "no escapes"


@pytest.mark.parametrize(
    "typed,goal,decisions,expected,changes",
    [
        # literal backslash-n typed by the LLM
        (
            "Header\\n\\nOld text",
            "Add a header",
            None,
            "Header\n\nOld text",
            ["escaped_control_chars"],
        ),
        # executor cut the text at the apostrophe; the cortex decision had the full string
        (
            "The cat",
            "Write: The cat's toy is red.",
            '[{"action": "type", "text": "The cat\'s toy is red."}]',
            "The cat's toy is red.",
            ["restored_truncation_at_quote"],
        ),
        # typographic apostrophe where the goal has an ASCII one
        (
            "The cat’s toy is red.",
            "Write: The cat's toy is red.",
            None,
            "The cat's toy is red.",
            ["restored_goal_quotes"],
        ),
        # goal itself uses typographic quotes: keep the goal's characters
        ('He said "hi"', "Type: He said “hi”", None, "He said “hi”", ["restored_goal_quotes"]),
        # text unrelated to the goal or decisions is never changed
        ("hello world", "Search for something", None, "hello world", []),
        # a prefix of a decision string NOT followed by a quote is a legitimate shorter text
        ("The cat", "x", '[{"text": "The catalog"}]', "The cat", []),
    ],
)
def test_restore_text(typed, goal, decisions, expected, changes):
    res = restore_text(typed, goal=goal, decisions=decisions)
    assert res.text == expected and res.changes == changes
