"""P2 F1/F5: read the details of list rows in ONE tool call (read-only).

Observed in version B (dev rounds 2-9): comparing records whose list cards look identical (exact
duplicates that differ only in fields on the detail screen), or finding the records whose DETAIL
contains a text (a search box that only searches titles), took ~2-3 Cortex turns per record and
exhausted the step budget.

For each row of the main list (all rows, or those whose card text contains `match`), the helper taps
the row, reads the whole detail screen (scrolled to its end, no truncation), presses BACK and checks
the same list page is back. Rows are identified by their POSITION in the list (identical cards stay
distinct). Optionally only rows whose details contain `detail_contains` are reported; records that
are identical on every detail field are grouped. It never edits anything; it stops at a row that does
not open, or when BACK does not return to the same list page.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from minitap.mobile_use.robustness.list_reader import (
    Device,
    _signature,
    find_main_container,
    iter_list,
    page_rows,
    parse_bounds,
    read_full_list,
)

MAX_ROWS = 60
DETAIL_TEXT_MAX = 20000


@dataclass
class Inspection:
    rows: list[dict] = field(default_factory=list)  # {"pos", "row", "details"} (reported)
    opened: list[dict] = field(default_factory=list)  # every row opened (groups use these)
    checked: int = 0
    total_seen: int = 0
    stopped: str | None = None
    error: str | None = None
    detail_contains: str | None = None
    reached_end: bool = False
    discarded: list[int] = field(default_factory=list)  # rows whose detail asked to discard on BACK

    def groups(self) -> list[list[int]]:
        by: dict[tuple, list[int]] = {}
        for r in self.opened or self.rows:
            by.setdefault(tuple(r["details"]), []).append(r["pos"])
        return [g for g in by.values() if len(g) > 1]

    def render(self, limit_chars: int = 16000) -> str:
        if self.error:
            return f"inspect_rows: {self.error}"
        scope = (
            f"{self.checked} row(s) opened; {len(self.rows)} reported"
            + (f" (details containing {self.detail_contains!r})" if self.detail_contains else "")
        )
        end = "end of list reached" if self.reached_end else "END OF LIST NOT CONFIRMED"
        head = f"inspect_rows: {scope}; {self.total_seen} list rows seen; {end}" + (
            f"; STOPPED: {self.stopped}" if self.stopped else ""
        )
        out = [head + "."]
        if self.discarded:
            out.append(
                "Note: leaving the detail of row(s) " + ", ".join(map(str, self.discarded))
                + " asked to discard changes; the tool chose DISCARD, so nothing was saved."
            )
        if self.detail_contains:
            out.append(
                "(Text match only: an attribute shown as an icon is not seen, and a match inside a "
                "title or name is not a field value. 0 reported does not prove there is none.)"
            )
        groups = self.groups()
        if groups:
            out.append(
                "Records IDENTICAL on every detail field (by list position): "
                + "; ".join(" = ".join(f"row {p}" for p in g) for g in groups)
            )
        elif len(self.opened or self.rows) > 1:
            out.append("No two opened records are identical on every detail field.")
        used = sum(len(x) for x in out)
        for r in self.rows:
            block = f"row {r['pos']} [{r['row'][:120]}]\n  " + "\n  ".join(r["details"])
            if used + len(block) > limit_chars:
                out.append(f"... (more rows not shown; see the identical-record groups above)")
                break
            out.append(block)
            used += len(block)
        return "\n".join(out)


def _detail_texts(dev: Device) -> list[str]:
    res = read_full_list(dev, return_to_top=False, text_max=DETAIL_TEXT_MAX)
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


DISCARD_RE = re.compile(r"\b(discard|don'?t save|do not save|without saving)\b", re.I)


def _discard_dialog(dev: Device) -> bool:
    """If a dialog offers to discard unsaved changes, tap that option (never the one that saves
    or keeps editing). Returns True if it did."""
    if dev.tap is None:
        return False
    root = ET.fromstring(dev.dump_xml())
    for n in root.iter():
        t = (n.attrib.get("text") or n.attrib.get("content-desc") or "").strip()
        if t and len(t) <= 30 and DISCARD_RE.search(t) and n.attrib.get("clickable") == "true":
            b = parse_bounds(n.attrib.get("bounds"))
            if b is not None:
                dev.tap((b.x1 + b.x2) // 2, (b.y1 + b.y2) // 2)
                return True
    return False


def inspect_rows(
    dev: Device, match: str = "", detail_contains: str | None = None, max_rows: int = MAX_ROWS
) -> Inspection:
    root = ET.fromstring(dev.dump_xml())
    cont = find_main_container(root, dev.screen_w * dev.screen_h)
    if cont is None:
        return Inspection(error="no scrollable list on this screen")
    if dev.home_package and cont.node.attrib.get("package") == dev.home_package:
        return Inspection(error="this is the home screen, not a list (open the app first)")
    rect, cid = cont.rect, (cont.node.attrib.get("resource-id") or None)
    needle = (match or "").lower()
    want = (detail_contains or "").lower() or None
    result = Inspection(detail_contains=detail_contains)
    state: dict = {}
    for visit in iter_list(dev, rect, cid, state):
        result.total_seen = visit.index
        row = visit.row
        if needle and needle not in row.text.lower():
            continue
        if result.checked >= max_rows:
            result.stopped = f"row limit {max_rows} reached"
            break
        before = _signature(page_rows(ET.fromstring(dev.dump_xml()), rect, cid))
        y = (max(row.top, rect.y1) + min(row.bottom, rect.y2)) // 2
        dev.tap((rect.x1 + rect.x2) // 2, y)
        time.sleep(dev.settle_s * 2)
        if _signature(page_rows(ET.fromstring(dev.dump_xml()), rect, cid)) == before:
            result.stopped = f"row {visit.index} '{row.text[:60]}' did not open a new screen"
            break
        details = _detail_texts(dev)
        dev.back()
        time.sleep(dev.settle_s * 2)
        if not page_rows(ET.fromstring(dev.dump_xml()), rect, cid) and _discard_dialog(dev):
            result.discarded.append(visit.index)  # nothing was saved: the stored record is unchanged
            time.sleep(dev.settle_s * 2)
        result.checked += 1
        rec = {"pos": visit.index, "row": row.text, "details": details}
        result.opened.append(rec)
        if want is None or any(want in d.lower() for d in details):
            result.rows.append(rec)
        back = page_rows(ET.fromstring(dev.dump_xml()), rect, cid)
        if not back:
            result.stopped = "BACK did not return to the list"
            break
        if _signature(back) != before:
            result.stopped = "the list moved after BACK (stopped to avoid opening the wrong row)"
            break
    result.reached_end = bool(state.get("reached_end")) and bool(state.get("certain", True))
    return result
