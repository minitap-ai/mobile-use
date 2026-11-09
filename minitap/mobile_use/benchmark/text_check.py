"""Deterministic text-input check (flag: `use_text_match_check`, audit A3).

The paper-era post-validation only returns the read-back field content to the LLM. This module
compares the read-back value with the intended text and returns an explicit verdict:

  MATCH         normalized field value == normalized intended text
  CONTAINS      the field contains the intended text plus other content (e.g. text that was
                already in the field before typing, since the tool appends at the end)
  CASE_ONLY     equal except for letter case (e.g. IME auto-capitalisation)
  MISMATCH      anything else (including an empty field)
  UNVERIFIABLE  no read-back possible (field not found, password field)

Normalization: Unicode NFKC, zero-width characters removed, non-breaking spaces -> spaces, every
whitespace run (spaces, tabs, newlines) collapsed to one space, leading/trailing spaces stripped.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

Verdict = Literal["MATCH", "CONTAINS", "CASE_ONLY", "MISMATCH", "UNVERIFIABLE"]

_ZERO_WIDTH_RE = re.compile("[​‌‍⁠﻿]")
_WS_RE = re.compile(r"\s+")


class TextCheckConfig(BaseModel):
    model_config = {"extra": "forbid"}

    # When true, MISMATCH / CASE_ONLY mark the tool call as failed (status="error"), which with
    # sequential execution aborts the remaining tool calls of the same Cortex decision.
    mismatch_as_error: bool = False


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value)
    text = _ZERO_WIDTH_RE.sub("", text)
    text = text.replace(" ", " ")
    return _WS_RE.sub(" ", text).strip()


@dataclass
class TextCheckResult:
    verdict: Verdict
    expected: str
    actual: str | None
    expected_normalized: str
    actual_normalized: str | None
    reason: str

    def as_feedback(self) -> str:
        if self.verdict == "MATCH":
            return (
                "Deterministic text check: MATCH "
                "(the field now contains exactly the intended text)."
            )
        if self.verdict == "UNVERIFIABLE":
            return f"Deterministic text check: UNVERIFIABLE ({self.reason}). Verify visually."
        return (
            f"Deterministic text check: {self.verdict}. Intended {self.expected!r}, "
            f"the field contains {self.actual!r}. {self.reason}"
        )


def compare_text(
    expected: str,
    actual: str | None,
    *,
    is_password: bool = False,
) -> TextCheckResult:
    exp_n = normalize_text(expected)
    if is_password:
        return TextCheckResult(
            "UNVERIFIABLE", expected, actual, exp_n, None, "password field, content is masked"
        )
    if actual is None:
        return TextCheckResult(
            "UNVERIFIABLE", expected, None, exp_n, None, "could not read the field back"
        )
    act_n = normalize_text(actual)
    if act_n == exp_n:
        return TextCheckResult("MATCH", expected, actual, exp_n, act_n, "")
    if exp_n and exp_n in act_n:
        return TextCheckResult(
            "CONTAINS",
            expected,
            actual,
            exp_n,
            act_n,
            "The field also contains other text (possibly pre-existing content); clear it if "
            "the field must contain only the intended text.",
        )
    if act_n.casefold() == exp_n.casefold():
        return TextCheckResult(
            "CASE_ONLY",
            expected,
            actual,
            exp_n,
            act_n,
            "Only letter case differs (likely keyboard auto-capitalisation).",
        )
    return TextCheckResult(
        "MISMATCH",
        expected,
        actual,
        exp_n,
        act_n,
        "Fix the field content before moving on.",
    )


def find_by_resource_id(
    ui_hierarchy: list[dict] | None, resource_id: str, index: int | None = None
) -> dict | None:
    """Resource-id lookup that accepts both hierarchy formats.

    The shared helper utils.ui_hierarchy.find_element_by_resource_id only matches the Maestro
    key `resourceId`, while the UIAutomator2 client used on Android emits `resource-id`, so it
    never matches on Android (04 - Audit A10). That helper is left untouched on purpose (it drives
    paper-era focus and post-validation behaviour); this check uses its own lookup.
    """
    wanted = index or 0
    for element in ui_hierarchy or []:
        if not isinstance(element, dict):
            continue
        rid = element.get("resource-id", element.get("resourceId"))
        if rid == resource_id:
            if wanted == 0:
                return element
            wanted -= 1
    return None


def find_focused_text_element(ui_hierarchy: list[dict] | None) -> dict | None:
    """Fallback read-back target when the Cortex gave no resource-id."""
    candidates = [
        e
        for e in ui_hierarchy or []
        if isinstance(e, dict) and str(e.get("focused", "")).lower() == "true"
    ]
    for e in candidates:
        if "EditText" in str(e.get("class", "")):
            return e
    return candidates[0] if candidates else None
