"""P2 F7: resolve a tap target against the LIVE UI hierarchy.

Observed in version A (many tasks): the Cortex copies an element's CENTRE (often the previous tap
point) into `bounds.x/y`, which the tool reads as the top-left corner, so the tap lands half an
element off (a corner, a neighbour, a floating button). When the target also names the element
(resource_id and/or text), the live element is authoritative:

- if the centre of the given bounds lies inside ANY live element matching the given resource_id/
  text, the bounds are trusted (the model may have picked a different index on purpose);
- otherwise, the indexed live match replaces the bounds.

No match at all (or no selector): the bounds are kept unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

from minitap.mobile_use.utils.ui_hierarchy import ElementBounds, get_bounds_for_element


@dataclass
class Resolution:
    bounds: ElementBounds | None
    corrected: bool
    reason: str


def _contains(b: ElementBounds, x: int, y: int) -> bool:
    return b.x <= x < b.x + max(b.width, 1) and b.y <= y < b.y + max(b.height, 1)


def _iter(elements: list[dict]):
    for el in elements:
        if isinstance(el, dict):
            yield el
            yield from _iter(el.get("children") or [])


def _rid(el: dict) -> str | None:
    return el.get("resourceId", el.get("resource-id"))


def _text(el: dict) -> str | None:
    return el.get("text") or None


def _desc(el: dict) -> str | None:
    return el.get("content-desc") or el.get("accessibilityText") or None


def target_exists(elements: list[dict], resource_id: str | None, text: str | None) -> bool:
    """True if the live screen has an element with that resource-id, or with that text,
    content description or hint (an empty input field often shows only its hint)."""
    for el in _iter(elements):
        if resource_id and _rid(el) == resource_id:
            return True
        if text and text in (_text(el), _desc(el), el.get("hint"), el.get("hintText")):
            return True
    return False


def matching_elements(
    elements: list[dict], resource_id: str | None, text: str | None
) -> tuple[list[dict], str]:
    """Live elements matching the selectors: resource_id+text, then resource_id, then text."""
    flat = [e for e in _iter(elements) if get_bounds_for_element(e) is not None]
    if resource_id and text:
        both = [e for e in flat if _rid(e) == resource_id and text in (_text(e), _desc(e))]
        if both:
            return both, "resource_id+text"
    if resource_id:
        by_id = [e for e in flat if _rid(e) == resource_id]
        if by_id:
            return by_id, "resource_id"
    if text:
        by_text = [e for e in flat if _text(e) == text] or [e for e in flat if _desc(e) == text]
        if by_text:
            return by_text, "text"
    return [], "none"


def snap_centre_written_as_top_left(
    elements: list[dict], bounds: ElementBounds | None, screen_w: int, screen_h: int
) -> Resolution:
    """No usable selector: detect the centre-as-top-left error from the geometry alone.
    1. A live element whose centre is (bounds.x, bounds.y) (±4 px) and whose size equals the given
       size (±4 px): that element is meant.
    2. Otherwise, if the given box runs off-screen while (x, y) is on-screen, (x, y) is the centre.
    """
    if bounds is None or bounds.width <= 0 or bounds.height <= 0:
        return Resolution(bounds, False, "no bounds")
    for e in _iter(elements):
        b = get_bounds_for_element(e)
        if b is None or b.width <= 0:
            continue
        c = b.get_center()
        if (
            abs(c.x - bounds.x) <= 4
            and abs(c.y - bounds.y) <= 4
            and abs(b.width - bounds.width) <= 4
            and abs(b.height - bounds.height) <= 4
        ):
            return Resolution(b, True, "given x/y is the centre of a live element of that size")
    c = bounds.get_center()
    off = not (0 <= c.x < screen_w and 0 <= c.y < screen_h)
    if off and 0 <= bounds.x < screen_w and 0 <= bounds.y < screen_h:
        fixed = ElementBounds(
            x=bounds.x - bounds.width // 2,
            y=bounds.y - bounds.height // 2,
            width=bounds.width,
            height=bounds.height,
        )
        return Resolution(fixed, True, "box off-screen while x/y is on-screen: x/y used as centre")
    return Resolution(bounds, False, "geometry consistent")


def resolve_target_bounds(
    elements: list[dict],
    bounds: ElementBounds | None,
    resource_id: str | None,
    resource_id_index: int | None,
    text: str | None,
    text_index: int | None,
) -> Resolution:
    resource_id = resource_id or None
    text = text or None
    if not resource_id and not text:
        return Resolution(bounds, False, "no selector")
    matches, how = matching_elements(elements, resource_id, text)
    if not matches:
        return Resolution(bounds, False, "no live match")
    live = [get_bounds_for_element(e) for e in matches]
    live = [b for b in live if b is not None and b.width > 0 and b.height > 0]
    if not live:
        return Resolution(bounds, False, "no live bounds")
    if bounds is not None:
        c = bounds.get_center()
        if any(_contains(b, c.x, c.y) for b in live):
            return Resolution(bounds, False, "given bounds inside a live match")
    idx = (resource_id_index if how.startswith("resource_id") else text_index) or 0
    if idx < 0 or idx >= len(live):
        idx = 0
    if bounds is not None and len(live) > 1:
        # Ambiguous index: prefer the live match nearest to where the model aimed.
        c = bounds.get_center()
        idx = min(
            range(len(live)),
            key=lambda i: (live[i].get_center().x - c.x) ** 2 + (live[i].get_center().y - c.y) ** 2,
        )
    chosen = live[idx]
    reason = (
        f"given bounds missed every live element matching {how}; using the live element"
        if bounds is not None
        else f"no bounds given; using the live element matching {how}"
    )
    return Resolution(chosen, True, reason)


async def p2_resolve_target(ctx, target, controller) -> str | None:
    """Correct `target.bounds` in place from the live hierarchy (P2 F7, version B only).
    Returns a short note for the tool output when a correction was made."""
    if not ctx.get_ablation_config().p2_tool_fixes:
        return None
    if not (target.resource_id or target.text or target.bounds):
        return None
    try:
        elements = await controller.get_ui_elements()
    except Exception:
        return None
    res = resolve_target_bounds(
        elements,
        target.bounds,
        target.resource_id,
        target.resource_id_index,
        target.text,
        target.text_index,
    )
    if not res.corrected and res.reason in ("no selector", "no live match", "no live bounds"):
        res = snap_centre_written_as_top_left(
            elements, target.bounds, ctx.device.device_width, ctx.device.device_height
        )
    if not res.corrected or res.bounds is None:
        return None
    old = target.bounds
    target.bounds = res.bounds
    from minitap.mobile_use.benchmark.runtime import get_runtime

    runtime = get_runtime()
    if runtime is not None:
        runtime.event(
            "p2_target_corrected",
            given=old.model_dump() if old is not None else None,
            live=res.bounds.model_dump(),
            reason=res.reason,
        )
    return f"(bounds corrected from the live screen: {res.reason})"


def _inside(inner: ElementBounds, outer: ElementBounds) -> bool:
    return (
        inner.x >= outer.x
        and inner.y >= outer.y
        and inner.x + inner.width <= outer.x + outer.width
        and inner.y + inner.height <= outer.y + outer.height
    )


def _label(el: dict) -> str:
    return (_text(el) or _desc(el) or _rid(el) or el.get("class") or "element").strip()


def covering_element(elements: list[dict], target_el: dict, x: int, y: int) -> dict | None:
    """The topmost clickable element drawn over (x, y) on top of `target_el`, or None.

    The hierarchy is in drawing order (pre-order): an element listed AFTER the target that contains
    the point and is not inside the target's own bounds (not one of its children) is drawn on top
    of it and receives the touch."""
    flat = [e for e in _iter(elements)]
    try:
        start = next(i for i, e in enumerate(flat) if e is target_el)
    except StopIteration:
        return None
    tb = get_bounds_for_element(target_el)
    if tb is None:
        return None
    top = None
    for e in flat[start + 1 :]:
        b = get_bounds_for_element(e)
        if b is None or b.width <= 0 or b.height <= 0 or not _contains(b, x, y):
            continue
        if _inside(b, tb):
            continue  # the target's own children
        if e.get("clickable") == "true":
            top = e
    return top


def p2_covered_check(ctx, target, elements: list[dict] | None) -> tuple[str | None, str | None]:
    """(refusal, warning) for a tap whose target is covered by another clickable element.
    Refuse only when the cover is a labelled control (text or description); warn otherwise."""
    if not ctx.get_ablation_config().p2_tool_fixes or not elements:
        return None, None
    if not (target.resource_id or target.text):
        return None, None
    matches, _ = matching_elements(elements, target.resource_id or None, target.text or None)
    if not matches:
        return None, None
    if target.bounds is not None:
        c = target.bounds.get_center()
    else:
        b0 = get_bounds_for_element(matches[(target.resource_id_index or 0) if (target.resource_id_index or 0) < len(matches) else 0])
        if b0 is None:
            return None, None
        c = b0.get_center()
    hit = [m for m in matches if (b := get_bounds_for_element(m)) is not None and _contains(b, c.x, c.y)]
    if not hit:
        return None, None
    cover = covering_element(elements, hit[0], c.x, c.y)
    if cover is None:
        return None, None
    name = _label(cover)
    from minitap.mobile_use.benchmark.runtime import get_runtime

    runtime = get_runtime()
    cb, tb = get_bounds_for_element(cover), get_bounds_for_element(hit[0])
    wraps = cb is not None and tb is not None and _inside(tb, cb)  # may be the target's own wrapper
    labelled = bool(_text(cover) or _desc(cover)) and not wraps
    if runtime is not None:
        runtime.event("p2_tap_covered", x=c.x, y=c.y, cover=name[:80], refused=labelled)
    if labelled:
        return (
            f"Not tapped: at ({c.x}, {c.y}) the target is covered by another control '{name[:60]}' "
            "drawn on top of it (a popup, sheet or overlay), so the tap would hit that control. "
            "Close or move the covering element first (BACK, its close/dismiss button, or scroll), "
            "or use the control that is actually visible.",
            None,
        )
    return None, (
        f"(warning: at ({c.x}, {c.y}) an overlay '{name[:60]}' is drawn over the target; check the "
        "next screen to see what the tap actually hit)"
    )
