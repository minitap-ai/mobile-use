"""P2 (version B): route/track goals through named places (BORDERLINE-GENERAL, disclosed).

Map apps whose route planner adds a point at the map centre need a strict per-place procedure
(search the place, centre the view on the place itself, go back to the planner, add once);
free exploration of the place card's other buttons creates favourites, markers, waypoints or a
second planner, and an add while the view is still elsewhere misplaces the point. The procedure
text is rendered into the Planner, Cortex and verifier prompts ONLY for goals that ask to create
or save a track or route with/through given places (goal wording; no app or task names), so every
other goal's prompts stay byte-identical.
"""

from __future__ import annotations

import re

# create/save/make/plan/build/draw ... a track|route ... waypoints|through|via|stops|passing
_MAP_ROUTE_RE = re.compile(
    r"\b(?:save|create|make|plan|build|draw)\b[^.]*?\b(?:track|route)s?\b[^.]*?"
    r"\b(?:waypoints?|through|via|stops?|passing)\b",
    re.IGNORECASE,
)


def is_map_route_goal(goal: str | None) -> bool:
    """True for goals that ask to create or save a track/route with or through given places."""
    return bool(goal) and _MAP_ROUTE_RE.search(goal) is not None


def map_route_flag(ablation, goal: str | None) -> bool:
    """Template variable `p2_map_route`: version B (p2_coverage) and a route/track goal."""
    return bool(getattr(ablation, "p2_coverage", False)) and is_map_route_goal(goal)
