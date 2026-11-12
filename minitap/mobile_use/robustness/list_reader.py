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
ROW_TEXT_MAX = 400


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


def _vertical_stack(node: ET.Element) -> bool:
    """A generic scrollable View (e.g. a Compose list) counts as a list only if its rows form a
    vertical stack: >= 3 children, each at least half the container's width, at increasing heights.
    A filmstrip or pager (one full-size child, or side-by-side pages) does not."""
    rect = parse_bounds(node.attrib.get("bounds"))
    if rect is None:
        return False
    kids = _row_nodes(node)
    boxes = [parse_bounds(k.attrib.get("bounds")) for k in kids]
    boxes = [b for b in boxes if b is not None and (b.x2 - b.x1) >= 0.5 * (rect.x2 - rect.x1)]
    tops = [b.y1 for b in boxes]
    return len(boxes) >= 3 and all(a < b for a, b in zip(tops, tops[1:]))


def find_main_container(root: ET.Element, screen_area: int, prefer_id: str | None = None):
    best: Container | None = None
    for n in root.iter():
        if not _is_scrollable(n):
            continue
        cls = (n.attrib.get("class") or "").lower()
        if any(h in cls for h in NON_SCROLL_CLASS_HINTS):
            continue
        rid0 = n.attrib.get("resource-id") or ""
        safe = any(cls.endswith(c) for c in SAFE_SCROLL_CLASSES) or (
            cls == "android.view.view" and _vertical_stack(n)
        )
        if not (prefer_id and rid0 == prefer_id) and not safe:
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


def _iou(a: Rect, b: Rect) -> float:
    ix = max(0, min(a.x2, b.x2) - max(a.x1, b.x1))
    iy = max(0, min(a.y2, b.y2) - max(a.y1, b.y1))
    inter = ix * iy
    union = a.area + b.area - inter
    return inter / union if union else 0.0


def locate_container(root: ET.Element, container_rect: Rect, container_id: str | None):
    """The list container on a new dump: same resource-id or same bounds, else (no id, bounds
    moved, e.g. a collapsing app bar) the scrollable node overlapping the old area the most."""
    best, best_iou = None, 0.5
    for n in root.iter():
        if not _is_scrollable(n):
            continue
        r = parse_bounds(n.attrib.get("bounds"))
        if r is None:
            continue
        rid = n.attrib.get("resource-id") or ""
        if r == container_rect or (container_id and rid == container_id):
            return n, r
        iou = _iou(r, container_rect)
        if iou > best_iou:
            best, best_iou = (n, r), iou
    return best if best else (None, None)


def page_rows(
    root: ET.Element, container_rect: Rect, container_id: str | None, text_max: int = ROW_TEXT_MAX
) -> list[Row]:
    cont, _ = locate_container(root, container_rect, container_id)
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
                rows.append(Row(line[:text_max], r.y1 + i, r.y1 + i))
            continue
        rows.append(Row(" | ".join(texts)[:text_max], r.y1, r.y2))
    return rows


def _fully_visible(rows: list[Row], rect: Rect, tol: int = 2) -> list[Row]:
    return [r for r in rows if r.top >= rect.y1 - tol and r.bottom <= rect.y2 + tol]


def _signature(rows: list[Row]) -> tuple:
    return tuple((r.text, r.top) for r in rows)


def merge_page(collected: list[Row], prev: list[Row], new: list[Row]) -> list[Row]:
    """Rows of `new` not already on `prev`, by position alignment (kept for callers/tests)."""
    if not prev:
        return list(new)
    dy, _, _ = align_offset(prev, new, nominal=None)
    last_prev_top = max(r.top for r in prev)
    return [r for r in new if r.top + dy > last_prev_top + 3]


def align_offset(prev: list[Row], new: list[Row], nominal: int | None, tol: int = 6) -> tuple[int, int, bool]:
    """Scroll displacement between two pages, by POSITION. Each pair of equal-text rows proposes
    dy = prev.top - new.top. A candidate is scored over the overlap of the two pages: +1 for each
    new row that lands (within tol) on a prev row with the same text, -1 for each that lands where
    prev shows a DIFFERENT row, so runs of identical rows cannot pull the shift off by a row.
    With a known drag (`nominal`), candidates within a window around it are preferred.
    Returns (dy, aligned rows, certain)."""
    if not prev or not new:
        return (nominal or 0), 0, False
    cands: set[int] = set()
    by_text: dict[str, list[Row]] = {}
    for r in new:
        by_text.setdefault(r.text, []).append(r)
    for r in prev:
        for s in by_text.get(r.text, []):
            cands.add(r.top - s.top)
    lo, hi = min(r.top for r in prev), max(r.top for r in prev)

    def score(dy: int) -> tuple[int, int]:
        good = bad = 0
        for s in new:
            pos = s.top + dy
            if pos < lo - tol or pos > hi + tol:
                continue  # outside the previous page: no evidence either way
            hit = [r for r in prev if abs(r.top - pos) <= tol]
            if any(r.text == s.text for r in hit):
                good += 1
            elif hit:
                bad += 1
        return good - bad, good

    def best_of(cs):
        best = None
        for dy in sorted(cs):
            sc, good = score(dy)
            key = (sc, -(abs(dy - nominal) if nominal is not None else 0))
            if good > 0 and (best is None or key > best[0]):
                best = (key, dy, good)
        return best

    pick = None
    if nominal is not None:
        window = max(60, int(0.15 * nominal))
        pick = best_of([c for c in cands if abs(c - nominal) <= window])
    if pick is None:
        pick = best_of(cands)
    if pick is None:
        return (nominal if nominal is not None else 0), 0, False
    _, dy, good = pick
    return dy, good, True


def full_rows(rows: list[Row], rect: Rect, tol: int = 2) -> list[Row]:
    """Rows entirely on screen. UIAutomator clips bounds to the visible area, so a half-visible card
    still looks 'inside': a row also has to be (nearly) as tall as the typical row of the page."""
    inside = [r for r in rows if r.top >= rect.y1 - tol and r.bottom <= rect.y2 + tol]
    heights = sorted(r.bottom - r.top for r in inside if r.bottom > r.top)
    if len(heights) < 3:
        return inside
    typical = median(heights)
    out = []
    for r in inside:
        h = r.bottom - r.top
        clipped_edge = r.top <= rect.y1 + tol or r.bottom >= rect.y2 - tol
        if clipped_edge and h < 0.85 * typical:
            continue
        out.append(r)
    return out


def _fully_visible(rows: list[Row], rect: Rect, tol: int = 2) -> list[Row]:  # compat alias
    return full_rows(rows, rect, tol)


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
    # A drag that does NOT fling (finger held still before release): the content moves by the
    # drag distance only. Falls back to a slow swipe.
    drag: Callable[[int, int, int], None] | None = None


def _swipe_in(dev: Device, rect: Rect, direction: str):
    x = (rect.x1 + rect.x2) // 2
    top = rect.y1 + int(rect.height * 0.25)
    bottom = rect.y1 + int(rect.height * 0.80)
    if direction == "down_content":  # reveal content below: finger moves up
        dev.swipe(x, bottom, x, top, 500)
    else:  # reveal content above: fast fling down
        dev.swipe(x, rect.y1 + int(rect.height * 0.15), x, rect.y2 - 5, 250)
    time.sleep(dev.settle_s)


def drag_lanes(root: ET.Element, rect: Rect, cid: str | None) -> list[tuple[int, int, int]]:
    """Drag paths (x, y_from, y_to) inside the list whose START point is not under an element drawn
    on top of the list (a floating button, a bottom bar, a snackbar): a drag started there moves
    nothing, and an unchanged page would wrongly look like the end of the list."""
    cont, _ = locate_container(root, rect, cid)
    overlays: list[Rect] = []
    if cont is not None:
        nodes = list(root.iter())
        idx = next((i for i, n in enumerate(nodes) if n is cont), None)
        own = {id(n) for n in cont.iter()}
        for n in nodes[(idx + 1) if idx is not None else len(nodes):]:
            if id(n) in own:
                continue
            r = parse_bounds(n.attrib.get("bounds"))
            if r is None or r.area == 0 or r.area >= 0.6 * rect.area:
                continue
            if r.x2 <= rect.x1 or r.x1 >= rect.x2 or r.y2 <= rect.y1 or r.y1 >= rect.y2:
                continue
            overlays.append(r)
    width = rect.x2 - rect.x1
    lanes: list[tuple[int, int, int]] = []
    for fx in (0.5, 0.3, 0.7, 0.15, 0.85):
        x = rect.x1 + int(width * fx)
        y_from = rect.y1 + int(rect.height * 0.75)
        y_to = rect.y1 + int(rect.height * 0.30)
        for _ in range(3):  # move the start above overlays that cover it
            cover = [o for o in overlays if o.x1 <= x < o.x2 and o.y1 <= y_from < o.y2]
            if not cover:
                break
            y_from = min(o.y1 for o in cover) - 8
        if any(o.x1 <= x < o.x2 and o.y1 <= y_from < o.y2 for o in overlays):
            continue
        if y_from - y_to < 0.2 * rect.height:
            continue
        lanes.append((x, y_from, y_to))
    return lanes or [(rect.x1 + width // 2, rect.y1 + int(rect.height * 0.75), rect.y1 + int(rect.height * 0.30))]


def _drag_page(dev: Device, rect: Rect, lane: tuple[int, int, int] | None = None) -> int:
    """Reveal content below with a no-fling drag (default ~45 % of the container); returns the
    nominal content displacement in pixels."""
    if lane is None:
        lane = (
            (rect.x1 + rect.x2) // 2,
            rect.y1 + int(rect.height * 0.75),
            rect.y1 + int(rect.height * 0.30),
        )
    x, y_from, y_to = lane
    if dev.drag is not None:
        dev.drag(x, y_from, y_to)
    else:
        dev.swipe(x, y_from, x, y_to, 1500)
    time.sleep(dev.settle_s)
    return y_from - y_to


def scroll_to_top(dev: Device, rect: Rect, cid: str | None):
    sig = None
    for _ in range(MAX_TOP_SWIPES):
        s = _signature(page_rows(ET.fromstring(dev.dump_xml()), rect, cid))
        if s == sig:
            break
        sig = s
        _swipe_in(dev, rect, "up_content")


@dataclass
class Visit:
    """A row first seen in full on the current page, with its position in the whole list."""

    row: Row
    index: int  # 1-based position in the list


def iter_list(dev: Device, rect: Rect, cid: str | None, state: dict, text_max: int = ROW_TEXT_MAX):
    """Yield every row of the list once, top to bottom, while the page that shows it is on screen
    (consumers may tap it, read a detail screen and come BACK before resuming). Sets
    state['reached_end'], state['certain'], state['pages']."""
    scroll_to_top(dev, rect, cid)
    page = page_rows(ET.fromstring(dev.dump_xml()), rect, cid, text_max)
    vis = full_rows(page, rect) or page
    state.update(reached_end=False, certain=True, pages=1)
    offset, last_abs, n = 0, None, 0
    for r in vis:
        n += 1
        last_abs = r.top
        yield Visit(r, n)
    root = ET.fromstring(dev.dump_xml())
    for _ in range(MAX_PAGES):
        lanes = drag_lanes(root, rect, cid)
        nominal = _drag_page(dev, rect, lanes[0])
        root = ET.fromstring(dev.dump_xml())
        _, new_rect = locate_container(root, rect, cid)
        if new_rect is not None and new_rect != rect:
            nominal -= new_rect.y1 - rect.y1  # the list itself moved (collapsing header)
            rect = new_rect
        cur = page_rows(root, rect, cid, text_max)
        state["pages"] += 1
        if _signature(cur) == _signature(page):
            # Unchanged: the end, or a drag that did not move the list. Confirm with a second drag
            # from another free point before calling it the end.
            other = [ln for ln in drag_lanes(root, rect, cid) if ln[0] != lanes[0][0]] or lanes
            nominal = _drag_page(dev, rect, other[0])
            root = ET.fromstring(dev.dump_xml())
            cur = page_rows(root, rect, cid, text_max)
            if _signature(cur) == _signature(page):
                state["reached_end"] = True
                return
        cur_vis = full_rows(cur, rect) or cur
        dy, aligned, certain = align_offset(vis, cur_vis, nominal)
        if not certain:
            state["certain"] = False
        offset += dy
        for r in cur_vis:
            abs_top = r.top + offset
            if last_abs is None or abs_top > last_abs + 3:
                n += 1
                last_abs = abs_top
                yield Visit(r, n)
                if n >= MAX_ROWS:
                    return
        page, vis = cur, cur_vis


def read_full_list(
    dev: Device, prefer_id: str | None = None, return_to_top: bool = True, text_max: int = ROW_TEXT_MAX
) -> ReadResult:
    try:
        root = ET.fromstring(dev.dump_xml())
    except ET.ParseError as e:
        return ReadResult(error=f"cannot parse the UI tree ({e})")
    cont = find_main_container(root, dev.screen_w * dev.screen_h, prefer_id)
    if cont is None:
        return ReadResult(error="no scrollable list or document on this screen (nothing to read)")
    rect, cid = cont.rect, (cont.node.attrib.get("resource-id") or None)
    state: dict = {}
    rows = [v.row.text for v in iter_list(dev, rect, cid, state, text_max)]
    if return_to_top:
        scroll_to_top(dev, rect, cid)
    res = ReadResult(
        rows=rows,
        reached_end=state.get("reached_end", False) and state.get("certain", True),
        pages=state.get("pages", 1),
        container=cont.label,
    )
    if state.get("reached_end") and not state.get("certain", True):
        res.container = f"{cont.label} (ROWS MAY BE MISSING: two pages could not be aligned)"
    return res


def android_device(ctx) -> Device:
    """Device adapter over mobile-use's Android clients (UIAutomator2 dump + adb swipe)."""
    from minitap.mobile_use.controllers.platform_specific_commands_controller import (
        get_adb_device,
    )

    ui = ctx.ui_adb_client
    device = get_adb_device(ctx)

    def swipe(x1, y1, x2, y2, ms):
        device.shell(f"input touchscreen swipe {x1} {y1} {x2} {y2} {ms}")

    def drag(x, y_from, y_to):
        """No-fling drag: DOWN, MOVEs, hold still, UP (release velocity ~0, so no momentum)."""
        steps = max(4, abs(y_from - y_to) // 60)
        ys = [y_from + (y_to - y_from) * i // steps for i in range(1, steps + 1)]
        cmd = " && ".join(
            [f"input motionevent DOWN {x} {y_from}"]
            + [f"input motionevent MOVE {x} {y}" for y in ys]
            + [f"input motionevent MOVE {x} {y_to}", "sleep 0.4", f"input motionevent UP {x} {y_to}"]
        )
        out = str(device.shell(cmd + " ; echo __rc=$?"))
        if "__rc=0" not in out:  # motionevent unsupported: slow swipe instead
            device.shell(f"input touchscreen swipe {x} {y_from} {x} {y_to} 1500")

    return Device(
        dump_xml=lambda: ui.get_hierarchy(),
        swipe=swipe,
        screen_w=ctx.device.device_width,
        screen_h=ctx.device.device_height,
        tap=lambda x, y: device.shell(f"input tap {x} {y}"),
        back=lambda: device.shell("input keyevent 4"),
        drag=drag,
    )
