"""P2 F1/F5: read the details of every list row matching a text, in ONE tool call.

Observed in version B (dev rounds 2-7): comparing records whose list cards look identical (e.g.
"exact duplicates" that differ only in fields shown on the detail screen) took ~3 Cortex turns per
record (open, read, back), so a 30-row list exhausted the step budget before any decision.

This helper, for each row of the main list whose text contains `match` (identical rows are kept
apart by their occurrence order), taps the row, reads the whole detail screen (scrolling it to its
end if it scrolls), presses BACK, and checks the list is back. It never edits anything; it stops
at the first row that does not open a new screen or whose BACK does not return to the list.
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from minitap.mobile_use.robustness.list_reader import (
    Device,
    _fully_visible,
    _signature,
    _swipe_in,
    find_main_container,
    merge_page,
    page_rows,
    read_full_list,
)

MAX_ROWS = 40
MAX_PAGES = 30


@dataclass
class Inspection:
    rows: list[dict] = field(default_factory=list)  # {"n": i, "row": text, "details": [...]}
    stopped: str | None = None
    error: str | None = None

    def render(self, limit_chars: int = 14000) -> str:
        if self.error:
            return f"inspect_rows: {self.error}"
        out = [f"Inspected {len(self.rows)} matching row(s)" + (f"; STOPPED: {self.stopped}" if self.stopped else "; all matching rows done") + "."]
        used = len(out[0])
        for r in self.rows:
            block = f"#{r['n']} [{r['row']}]\n  " + "\n  ".join(r["details"])
            if used + len(block) > limit_chars:
                out.append(f"... ({len(self.rows) - r['n'] + 1} more not shown)")
                break
            out.append(block)
            used += len(block)
        return "\n".join(out)


def _tap(dev: Device, x: int, y: int):
    dev.tap(x, y)
    time.sleep(dev.settle_s * 2)


def _detail_texts(dev: Device) -> list[str]:
    res = read_full_list(dev, return_to_top=False)
    if res.error is None and res.rows:
        return res.rows
    root = ET.fromstring(dev.dump_xml())  # non-scrolling detail screen: all its texts
    out: list[str] = []
    for n in root.iter():
        for k in ("text", "content-desc"):
            v = (n.attrib.get(k) or "").strip()
            if v and v not in out:
                out.append(v)
    return out


def inspect_rows(dev: Device, match: str, max_rows: int = MAX_ROWS) -> Inspection:
    root = ET.fromstring(dev.dump_xml())
    cont = find_main_container(root, dev.screen_w * dev.screen_h)
    if cont is None:
        return Inspection(error="no scrollable list on this screen")
    rect, cid = cont.rect, (cont.node.attrib.get("resource-id") or None)
    needle = match.lower()

    # to the top
    sig = None
    for _ in range(12):
        s = _signature(page_rows(ET.fromstring(dev.dump_xml()), rect, cid))
        if s == sig:
            break
        sig = s
        _swipe_in(dev, rect, "up_content")

    result = Inspection()
    prev_all = page_rows(ET.fromstring(dev.dump_xml()), rect, cid)
    prev_vis = _fully_visible(prev_all, rect) or prev_all
    todo = list(prev_vis)
    for _page in range(MAX_PAGES):
        for row in todo:
            if needle not in row.text.lower():
                continue
            if len(result.rows) >= max_rows:
                result.stopped = f"row limit {max_rows} reached"
                return result
            before = _signature(page_rows(ET.fromstring(dev.dump_xml()), rect, cid))
            y = (max(row.top, rect.y1) + min(row.bottom, rect.y2)) // 2
            _tap(dev, (rect.x1 + rect.x2) // 2, y)
            after_root = ET.fromstring(dev.dump_xml())
            if _signature(page_rows(after_root, rect, cid)) == before:
                result.stopped = f"row '{row.text[:60]}' did not open a new screen"
                return result
            details = _detail_texts(dev)
            dev.back()
            time.sleep(dev.settle_s * 2)
            back_rows = page_rows(ET.fromstring(dev.dump_xml()), rect, cid)
            result.rows.append({"n": len(result.rows) + 1, "row": row.text, "details": details})
            if not back_rows:
                result.stopped = "BACK did not return to the list"
                return result
            if _signature(back_rows) != before:
                result.stopped = "the list moved after BACK (inspection stopped to avoid opening the wrong row)"
                return result
        # next page
        _swipe_in(dev, rect, "down_content")
        cur_all = page_rows(ET.fromstring(dev.dump_xml()), rect, cid)
        if _signature(cur_all) == _signature(prev_all):
            break
        cur_vis = _fully_visible(cur_all, rect) or cur_all
        todo = merge_page([], prev_vis, cur_vis)
        prev_all, prev_vis = cur_all, cur_vis
    return result
