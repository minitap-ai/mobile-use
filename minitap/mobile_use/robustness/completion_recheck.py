"""D7a: completion-question verifier re-check (deterministic scrolling, one extra verification).

Observed (D5 and D6 held-out seeds, completion questions): the verifier rejected correct titles as "not
completed" while their rows were not on its screen, judging from list position or a screenshot of another part
of the list; the agents then gave up correct answers. The UI tree carries no checked state for those rows, so
completion can only be judged visually from a row that is on screen. When a rejection names titles that are not
among the screen's texts, the first one is scrolled fully into view and the verification runs once more with
that screen. Trigger: completion / incomplete question goals (checklist.is_completion_question), at most once.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET

RECHECK_INSTRUCTION = (
    "Re-check on a fresh screen: the list was just scrolled so that the row titled {title!r} is fully visible. "
    "Judge each row's completion ONLY from what this screenshot shows for that row (a ticked checkbox or a "
    "struck-through title means completed), never from where the row sits in the list. Re-read the whole list "
    "content above for every row whose date matches the goal, and give your verdict again."
)

_QUOTED = re.compile(r"['\"\u2018\u2019\u201c\u201d]([^'\"\u2018\u2019\u201c\u201d]{3,80})['\"\u2018\u2019\u201c\u201d]")
_NOT_TITLE = re.compile(
    r"^\s*(?:\d[\d\s:/.,-]*|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{1,2}(?:,?\s*\d{4})?|none|"
    r"show completed|show unstarted|completed|incomplete)\s*$",
    re.IGNORECASE,
)
_BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def missing_titles(verdict_text: str, visible_text: str) -> list[str]:
    """Quoted names in the verdict that are not on the current screen (dates, numbers, menu words excluded)."""
    vis = (visible_text or "").lower()
    out: list[str] = []
    for m in _QUOTED.finditer(verdict_text or ""):
        t = m.group(1).strip()
        if _NOT_TITLE.match(t) or t.lower() in vis or t in out:
            continue
        out.append(t)
    return out


def _node_rect(root: ET.Element, title: str):
    for n in root.iter():
        if (n.attrib.get("text") or "").strip().lower() == title.lower():
            m = _BOUNDS.match(n.attrib.get("bounds") or "")
            if m:
                return tuple(int(v) for v in m.groups())
    return None


def scroll_title_into_view(ctx, title: str, max_drags: int = 30) -> bool:
    """Scroll the main list until the row titled `title` is fully on screen, away from the bottom bar."""
    from minitap.mobile_use.robustness.list_reader import android_device, find_main_container

    dev = android_device(ctx)
    root = ET.fromstring(dev.dump_xml())
    cont = find_main_container(root, dev.screen_w * dev.screen_h, None, exclude_forms=True)
    if cont is None:
        return False
    r = cont.rect
    x = (r.x1 + r.x2) // 2
    top_ok, bottom_ok = r.y1 + int(r.height * 0.05), r.y2 - int(r.height * 0.18)

    def visible_ok() -> bool:
        b = _node_rect(ET.fromstring(dev.dump_xml()), title)
        return bool(b) and b[1] >= top_ok and b[3] <= bottom_ok

    if visible_ok():
        return True
    for _ in range(12):  # back to the top of the list (fast flings down)
        before = dev.dump_xml()
        dev.swipe(x, r.y1 + int(r.height * 0.15), x, r.y2 - 5, 250)
        time.sleep(dev.settle_s)
        if dev.dump_xml() == before:
            break
    drag = dev.drag or (lambda xx, a, b: dev.swipe(xx, a, xx, b, 1500))
    for _ in range(max_drags):
        if visible_ok():
            return True
        b = _node_rect(ET.fromstring(dev.dump_xml()), title)
        if b and b[3] > bottom_ok:  # on screen but under the bottom bar: a short drag up centres it
            drag(x, r.y1 + int(r.height * 0.6), r.y1 + int(r.height * 0.35))
        else:
            before = dev.dump_xml()
            drag(x, r.y1 + int(r.height * 0.75), r.y1 + int(r.height * 0.20))
            time.sleep(dev.settle_s)
            if dev.dump_xml() == before:  # end of list
                return visible_ok()
        time.sleep(dev.settle_s)
    return visible_ok()
