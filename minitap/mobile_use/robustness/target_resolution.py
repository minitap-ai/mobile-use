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
    if not (target.resource_id or target.text):
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
