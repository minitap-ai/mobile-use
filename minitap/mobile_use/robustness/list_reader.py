"""P2 F1: deterministic scroll-to-end reader for lists and long documents.

Version A answered list questions and declared multi-item goals done from ONE screen of a list
(the rest below the fold, or above it). This module reads the main scrollable container of the
current screen completely: scroll to the top, then page down until the content stops changing,
and return every row in order, once, with its position.

Task-agnostic: it only uses the UI tree (`scrollable="true"`, bounds, text, content-desc).
Never scrolls maps, web views or canvases (they pan instead of scrolling), never taps.

Row identity across pages uses the measured scroll displacement (rows that appear once on both
pages anchor it), so identical rows (true duplicates) are counted correctly; without an anchor,
it falls back to the longest page overlap.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from statistics import median

_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
NON_SCROLL_CLASS_HINTS = ("webview", "mapview", "surfaceview", "textureview", "glsurface", "canvas")
# Only standard list / scroll containers are scrolled automatically. A custom scrollable view can
# give a swipe another meaning: in a camera filmstrip a vertical swipe DELETES the photo (the
# verifier's automatic full read deleted the photo it was checking, dev round p1p-emu s46).
SAFE_SCROLL_CLASSES = (
    "recyclerview.widget.recyclerview",
    "android.widget.listview",
    "android.widget.gridview",
    "android.widget.expandablelistview",
    "android.widget.scrollview",
    "androidx.core.widget.nestedscrollview",
    "android.support.v4.widget.nestedscrollview",
    "android.support.v7.widget.recyclerview",
)
MIN_AREA_FRACTION = 0.20
MAX_PAGES = 30
MAX_TOP_SWIPES = 12
MAX_ROWS = 400
ROW_TEXT_MAX = 300


@dataclass(frozen=True)
class Rect:
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def area(self) -> int:
        return max(0, self.x2 - self.x1) * max(0, self.y2 - self.y1)

    @property
    def height(self) -> int:
        return self.y2 - self.y1


def parse_bounds(s: str | None) -> Rect | None:
    if not s:
        return None
    m = _BOUNDS_RE.match(s.strip())
    if not m:
        return None
    return Rect(*(int(v) for v in m.groups()))


@dataclass
class Row:
    text: str
    top: int
    bottom: int


@dataclass
class Container:
    node: ET.Element
    rect: Rect
    label: str


@dataclass
class ReadResult:
    rows: list[str] = field(default_factory=list)
    reached_end: bool = False
    pages: int = 0
    container: str | None = None
    error: str | None = None

    def render(self, limit_chars: int = 12000) -> str:
        if self.error:
            return f"read_full_list: {self.error}"
        head = (
            f"Read {len(self.rows)} rows from {self.container} in {self.pages} page(s); "
            + ("END OF LIST REACHED (this is the complete content)." if self.reached_end
               else "END NOT CONFIRMED (stopped at the page limit; there may be more rows).")
        )
        lines, used = [head], len(head)
        for i, r in enumerate(self.rows, 1):
            line = f"{i}. {r}"
            if used + len(line) > limit_chars:
                lines.append(f"... ({len(self.rows) - i + 1} more rows not shown)")
                break
            lines.append(line)
            used += len(line) + 1
        return "\n".join(lines)


def _node_text(node: ET.Element) -> list[str]:
    out: list[str] = []
    for n in node.iter():
        t = (n.attrib.get("text") or "").strip()
        d = (n.attrib.get("content-desc") or "").strip()
        for v in (t, d):
            if v and v not in out:
                out.append(v)
    return out


def _is_scrollable(n: ET.Element) -> bool:
    return n.attrib.get("scrollable") == "true"


def find_main_container(root: ET.Element, screen_area: int, prefer_id: str | None = None):
    best: Container | None = None
    for n in root.iter():
        if not _is_scrollable(n):
            continue
        cls = (n.attrib.get("class") or "").lower()
        if any(h in cls for h in NON_SCROLL_CLASS_HINTS):
            continue
        rid0 = n.attrib.get("resource-id") or ""
        if not (prefer_id and rid0 == prefer_id) and not any(cls.endswith(c) for c in SAFE_SCROLL_CLASSES):
            continue
        rect = parse_bounds(n.attrib.get("bounds"))
        if rect is None or rect.height < 100:
            continue
        rid = n.attrib.get("resource-id") or ""
        label = rid or (n.attrib.get("class") or "scrollable")
        if prefer_id and rid == prefer_id:
            return Container(n, rect, label)
        if screen_area and rect.area < MIN_AREA_FRACTION * screen_area:
            continue
        if best is None or rect.area > best.rect.area:
            best = Container(n, rect, label)
    return best


def _row_nodes(container: ET.Element) -> list[ET.Element]:
    """Children that are the list's rows: descend through single-child wrappers."""
    node = container
    for _ in range(6):
        kids = list(node)
        if len(kids) != 1:
            break
        node = kids[0]
    kids = list(node)
    return kids if kids else [node]


def page_rows(root: ET.Element, container_rect: Rect, container_id: str | None) -> list[Row]:
    cont = None
    for n in root.iter():
        if not _is_scrollable(n):
            continue
        r = parse_bounds(n.attrib.get("bounds"))
        rid = n.attrib.get("resource-id") or ""
        if r == container_rect or (container_id and rid == container_id and r is not None):
            cont = n
            break
    if cont is None:
        return []
    rows: list[Row] = []
    for kid in _row_nodes(cont):
        r = parse_bounds(kid.attrib.get("bounds"))
        texts = _node_text(kid)
        if r is None or not texts:
            continue
        # Single text block taller than the container (a document): split it into lines.
        if len(texts) == 1 and "\n" in texts[0]:
            for i, line in enumerate(texts[0].split("\n")):
                rows.append(Row(line[:ROW_TEXT_MAX], r.y1 + i, r.y1 + i))
            continue
        rows.append(Row(" | ".join(texts)[:ROW_TEXT_MAX], r.y1, r.y2))
    return rows


def _fully_visible(rows: list[Row], rect: Rect, tol: int = 2) -> list[Row]:
    return [r for r in rows if r.top >= rect.y1 - tol and r.bottom <= rect.y2 + tol]


def _signature(rows: list[Row]) -> tuple:
    return tuple((r.text, r.top) for r in rows)


def merge_page(collected: list[Row], prev: list[Row], new: list[Row]) -> list[Row]:
    """Rows of `new` that were not already on `prev` (displacement-anchored)."""
    prev_counts = Counter(r.text for r in prev)
    new_counts = Counter(r.text for r in new)
    anchors = [t for t in prev_counts if prev_counts[t] == 1 and new_counts.get(t) == 1]
    if anchors:
        prev_top = {r.text: r.top for r in prev}
        new_top = {r.text: r.top for r in new}
        dy = median(prev_top[t] - new_top[t] for t in anchors)
        last_prev_top = max(r.top for r in prev) if prev else -(10**9)
        return [r for r in new if r.top + dy > last_prev_top + 3]
    # Fallback: longest suffix of prev texts equal to a prefix of new texts.
    pt, nt = [r.text for r in prev], [r.text for r in new]
    for k in range(min(len(pt), len(nt)), 0, -1):
        if pt[-k:] == nt[:k]:
            return new[k:]
    return new


@dataclass
class Device:
    """What the reader needs from a device (injected; tests use a fake)."""

    dump_xml: Callable[[], str]
    swipe: Callable[[int, int, int, int, int], None]
    screen_w: int
    screen_h: int
    settle_s: float = 0.6
    tap: Callable[[int, int], None] | None = None
    back: Callable[[], None] | None = None


def _swipe_in(dev: Device, rect: Rect, direction: str):
    x = (rect.x1 + rect.x2) // 2
    top = rect.y1 + int(rect.height * 0.25)
    bottom = rect.y1 + int(rect.height * 0.80)
    if direction == "down_content":  # reveal content below: finger moves up
        dev.swipe(x, bottom, x, top, 500)
    else:  # reveal content above: fast fling down
        dev.swipe(x, rect.y1 + int(rect.height * 0.15), x, rect.y2 - 5, 250)
    time.sleep(dev.settle_s)


def read_full_list(dev: Device, prefer_id: str | None = None, return_to_top: bool = True) -> ReadResult:
    try:
        root = ET.fromstring(dev.dump_xml())
    except ET.ParseError as e:
        return ReadResult(error=f"cannot parse the UI tree ({e})")
    cont = find_main_container(root, dev.screen_w * dev.screen_h, prefer_id)
    if cont is None:
        return ReadResult(error="no scrollable list or document on this screen (nothing to read)")
    rect, cid = cont.rect, (cont.node.attrib.get("resource-id") or None)

    # 1. to the top
    sig = None
    for _ in range(MAX_TOP_SWIPES):
        rows = page_rows(ET.fromstring(dev.dump_xml()), rect, cid)
        s = _signature(rows)
        if s == sig:
            break
        sig = s
        _swipe_in(dev, rect, "up_content")

    # 2. page down to the end
    root = ET.fromstring(dev.dump_xml())
    prev = page_rows(root, rect, cid)
    collected = list(prev if len(prev) <= 2 else _fully_visible(prev, rect) or prev)
    prev_vis = collected[:]
    reached_end, pages = False, 1
    for _ in range(MAX_PAGES):
        _swipe_in(dev, rect, "down_content")
        cur_all = page_rows(ET.fromstring(dev.dump_xml()), rect, cid)
        pages += 1
        if _signature(cur_all) == _signature(prev):
            reached_end = True
            break
        cur = _fully_visible(cur_all, rect) or cur_all
        new = merge_page(collected, prev_vis, cur)
        collected.extend(new)
        prev, prev_vis = cur_all, cur
        if len(collected) >= MAX_ROWS:
            break
    if reached_end:
        # Rows only partly visible at the bottom of the last page were never fully visible.
        tail = [r for r in prev if r.bottom > rect.y2 + 2]
        collected.extend(merge_page(collected, prev_vis, tail) if tail else [])

    if return_to_top:
        sig = None
        for _ in range(MAX_TOP_SWIPES):
            _swipe_in(dev, rect, "up_content")
            s = _signature(page_rows(ET.fromstring(dev.dump_xml()), rect, cid))
            if s == sig:
                break
            sig = s

    return ReadResult(
        rows=[r.text for r in collected],
        reached_end=reached_end,
        pages=pages,
        container=cont.label,
    )


def android_device(ctx) -> Device:
    """Device adapter over mobile-use's Android clients (UIAutomator2 dump + adb swipe)."""
    from minitap.mobile_use.controllers.platform_specific_commands_controller import (
        get_adb_device,
    )

    ui = ctx.ui_adb_client
    device = get_adb_device(ctx)

    def swipe(x1, y1, x2, y2, ms):
        device.shell(f"input touchscreen swipe {x1} {y1} {x2} {y2} {ms}")

    return Device(
        dump_xml=lambda: ui.get_hierarchy(),
        swipe=swipe,
        screen_w=ctx.device.device_width,
        screen_h=ctx.device.device_height,
        tap=lambda x, y: device.shell(f"input tap {x} {y}"),
        back=lambda: device.shell("input keyevent 4"),
    )
