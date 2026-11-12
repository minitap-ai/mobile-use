"""P2 F2: calendar facts derived from the device date (relative-date questions).

The Contextor reads the device date with `adb shell date` (e.g. "Sun Oct 15 15:34:21 UTC 2023").
LLMs often get "next week", "yesterday" or weekdays wrong when they compute them from that raw
string; this module computes them once, deterministically.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

_FORMATS = (
    "%a %b %d %H:%M:%S %Z %Y",
    "%a %b %d %H:%M:%S %Y",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
)


def parse_device_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = " ".join(raw.strip().split())
    for fmt in _FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    # Unknown timezone abbreviation (strptime %Z only knows UTC/GMT/local): drop it.
    m = re.match(r"^(\w{3} \w{3} \d{1,2} \d{2}:\d{2}:\d{2}) \S+ (\d{4})$", text)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%a %b %d %H:%M:%S %Y")
        except ValueError:
            return None
    return None


def _d(x: date) -> str:
    return f"{x:%A} {x:%Y-%m-%d} ({x:%B} {x.day}, {x.year})"


def _span(a: date, b: date) -> str:
    return f"{a:%a} {a:%Y-%m-%d} to {b:%a} {b:%Y-%m-%d}"


def calendar_context(raw_device_date: str | None) -> str | None:
    """Text block with today, neighbours, weeks (Monday- and Sunday-based) and months."""
    now = parse_device_date(raw_device_date)
    if now is None:
        return None
    today = now.date()
    mon = today - timedelta(days=today.weekday())  # Monday-based week
    sun = today - timedelta(days=(today.weekday() + 1) % 7)  # Sunday-based week
    first = today.replace(day=1)
    next_first = (first + timedelta(days=32)).replace(day=1)
    after_next_first = (next_first + timedelta(days=32)).replace(day=1)
    prev_last = first - timedelta(days=1)
    lines = [
        "Calendar facts computed from the device date (use these, do not recompute):",
        f"- Device now: {now:%Y-%m-%d %H:%M} ({now:%A})",
        f"- Today: {_d(today)}",
        f"- Yesterday: {_d(today - timedelta(days=1))}",
        f"- Tomorrow: {_d(today + timedelta(days=1))}",
        f"- Day after tomorrow: {_d(today + timedelta(days=2))}",
        f"- This week (Mon-Sun): {_span(mon, mon + timedelta(days=6))}",
        f"- Last week (Mon-Sun): {_span(mon - timedelta(days=7), mon - timedelta(days=1))}",
        f"- Next week (Mon-Sun): {_span(mon + timedelta(days=7), mon + timedelta(days=13))}",
        f"- This week (Sun-Sat): {_span(sun, sun + timedelta(days=6))}",
        f"- Next week (Sun-Sat): {_span(sun + timedelta(days=7), sun + timedelta(days=13))}",
        f"- This month: {_span(first, next_first - timedelta(days=1))}",
        f"- Last month: {_span(prev_last.replace(day=1), prev_last)}",
        f"- Next month: {_span(next_first, after_next_first - timedelta(days=1))}",
        "- The next 14 days: "
        + ", ".join(f"{(today + timedelta(days=i)):%a %m-%d}" for i in range(1, 15)),
        "If the goal says how a week starts, use that convention; 'next week' means the whole "
        "calendar week after this one, not the next 7 days.",
    ]
    return "\n".join(lines)
