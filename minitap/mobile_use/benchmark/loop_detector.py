"""Deterministic loop detector for the Cortex (flag: `use_loop_detector`).

The paper-era "meta-cognitive reasoning" is prompt-only (thought history + prompt rules, see
04 - Audit A2). This module adds a small programmatic check on top of it.

Model
-----
At every Cortex turn t we know:
  * S_t     the current screen state (UI hierarchy + focused app), observed by the Contextor;
  * A_{t-1} the action the Executor actually executed after the previous Cortex turn
            (its tool calls, read from `state.executor_messages`).
So each turn closes one transition  (S_{t-1}, A_{t-1}) -> S_t.

States and actions are reduced to short hashes:
  * state  = sha1 of the focused app + a canonical, volatile-field-free projection of every
             UI element (resource-id, class, text, content-desc, checked/selected/focused, ...;
             no bounds by default, no System UI package, clock-like strings masked);
  * action = sha1 of the executed tool calls (name + arguments, minus free-text fields such
             as `agent_thought`).

Triggers (evaluated on the transition that was just closed, after a cooldown):
  1. `repeat`:    the same (state, action) pair occurs >= `repeat_threshold` times among the
                  last `window` transitions.
  2. `no_change`: the last `no_change_threshold` transitions all left the screen unchanged
                  (S_{t-1} == S_t) although a UI action was executed.
  3. `cycle`:     the last `cycle_window` transitions visit at most `cycle_max_distinct`
                  distinct states (e.g. A -> B -> A -> B ...).

On trigger the Cortex receives an explicit "LOOP DETECTED: <evidence>" message. If
`escalate_after` > 0 and that many triggers fire without any progress in between (progress =
reaching a state never seen before in this task), the detector asks for a forced replan: the
current subgoal is marked FAILED with the evidence as completion reason and the graph routes to
the Planner. Every trigger is logged by the caller.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

# Tools that by design do not change the screen; a transition made only of these tools is not
# counted as a "no change" step.
NON_UI_TOOLS = frozenset(
    {
        "save_note",
        "read_note",
        "list_notes",
        "wait_for_delay",
        "wait",
        "start_video_recording",
        "stop_video_recording",
    }
)

# Free-text tool arguments that vary between otherwise identical actions.
IGNORED_ACTION_ARGS = frozenset({"agent_thought", "reason", "thought", "explanation", "state"})

# Element attributes that make up the canonical state.
STATE_ATTRS = (
    "resource-id",
    "class",
    "text",
    "content-desc",
    "checked",
    "selected",
    "focused",
    "enabled",
    "package",
)
IGNORED_PACKAGES = frozenset({"com.android.systemui"})

_CLOCK_RE = re.compile(r"\b\d{1,2}:\d{2}(:\d{2})?\s*(AM|PM|am|pm)?\b")
_WS_RE = re.compile(r"\s+")


class LoopDetectorConfig(BaseModel):
    """Thresholds; all values are versioned in benchmarks/configs/*.jsonc."""

    model_config = {"extra": "forbid"}

    window: int = Field(default=12, ge=2)
    repeat_threshold: int = Field(default=3, ge=2)
    no_change_threshold: int = Field(default=3, ge=2)
    cycle_window: int = Field(default=8, ge=3)
    cycle_max_distinct: int = Field(default=2, ge=1)
    cooldown: int = Field(
        default=3, ge=0, description="Transitions to wait after a trigger before re-triggering"
    )
    escalate_after: int = Field(
        default=2,
        ge=0,
        description="Force a replan after this many triggers without progress (0 = never)",
    )
    include_bounds: bool = False
    stall_rounds: int = Field(
        default=4,
        ge=0,
        description=(
            "Force a replan after this many consecutive Cortex turns that decided no device "
            "action (each one an Orchestrator round without the Executor); 0 = never"
        ),
    )


@dataclass(frozen=True)
class Transition:
    state: str
    action: str
    next_state: str
    action_tools: tuple[str, ...]
    action_desc: str


@dataclass
class LoopTrigger:
    kind: Literal["repeat", "no_change", "cycle", "stall"]
    evidence: str
    escalate: bool
    turn: int
    details: dict[str, Any] = field(default_factory=dict)

    def cortex_message(self) -> str:
        msg = (
            "⚠️ LOOP DETECTED (deterministic loop detector, not an LLM opinion).\n"
            f"Kind: {self.kind}. Evidence: {self.evidence}\n"
            "Your recent actions are not making progress on this screen. Do NOT repeat the same "
            "action. Change strategy: target a different element, scroll to reveal other "
            "options, go back, use another navigation path, or re-check your assumption about "
            "the current screen."
        )
        if self.escalate:
            msg += "\nThe current subgoal is being marked as FAILED and a replan is requested."
        return msg


def _norm_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = _CLOCK_RE.sub("<time>", text)
    return _WS_RE.sub(" ", text).strip()


def _short_hash(payload: str) -> str:
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def hash_state(
    ui_hierarchy: list[dict] | None,
    focused_app: str | None,
    include_bounds: bool = False,
) -> str:
    """Hash of the visible UI, robust to clock changes and System UI noise."""
    rows: list[str] = []
    for element in ui_hierarchy or []:
        if not isinstance(element, dict):
            continue
        if element.get("package") in IGNORED_PACKAGES:
            continue
        row = [_norm_text(element.get(attr)) for attr in STATE_ATTRS]
        if include_bounds:
            row.append(_norm_text(element.get("bounds")))
        if any(row):
            rows.append("|".join(row))
    payload = _norm_text(focused_app) + "\n" + "\n".join(rows)
    return _short_hash(payload)


def _strip_free_text(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: _strip_free_text(v) for k, v in sorted(value.items()) if k not in IGNORED_ACTION_ARGS
        }
    if isinstance(value, list):
        return [_strip_free_text(v) for v in value]
    if isinstance(value, str):
        return _WS_RE.sub(" ", value).strip()
    return value


def canonical_action(tool_calls: list[dict]) -> tuple[str, tuple[str, ...], str]:
    """Return (hash, tool names, short human description) for executed tool calls."""
    canon = [
        {"name": c.get("name"), "args": _strip_free_text(c.get("args") or {})} for c in tool_calls
    ]
    payload = json.dumps(canon, sort_keys=True, ensure_ascii=False, default=str)
    names = tuple(str(c.get("name")) for c in tool_calls)
    desc = payload if len(payload) <= 300 else payload[:300] + "..."
    return _short_hash(payload), names, desc


class LoopDetector:
    """Stateful detector, one instance per task."""

    def __init__(self, config: LoopDetectorConfig | None = None):
        self.config = config or LoopDetectorConfig()
        maxlen = max(self.config.window, self.config.cycle_window, self.config.no_change_threshold)
        self.transitions: deque[Transition] = deque(maxlen=maxlen)
        self.seen_states: set[str] = set()
        self.turn = 0
        self._prev_state: str | None = None
        self._cooldown_left = 0
        self._triggers_without_progress = 0
        self._turns_without_action = 0

    def reset_history(self) -> None:
        """Forget recent transitions (after a forced replan). Seen states are kept."""
        self.transitions.clear()
        self._prev_state = None
        self._cooldown_left = 0
        self._triggers_without_progress = 0
        self._turns_without_action = 0

    # ------------------------------------------------------------------- stall
    def note_cortex_turn(self, *, decided_action: bool) -> None:
        """Record whether this Cortex turn sent anything to the Executor."""
        self._turns_without_action = 0 if decided_action else self._turns_without_action + 1

    def check_stall(self) -> LoopTrigger | None:
        """Stall: the last `stall_rounds` Cortex turns decided no device action, so the graph
        cycled Cortex -> Orchestrator without the Executor (e.g. a plan step that can be neither
        completed nor replanned). Always escalates to a replan."""
        n, limit = self._turns_without_action, self.config.stall_rounds
        if limit <= 0 or n < limit:
            return None
        self._turns_without_action = 0
        return LoopTrigger(
            kind="stall",
            evidence=(
                f"the last {n} Cortex turns decided no device action; the plan is not advancing "
                "(a remaining step may be unnecessary, already satisfied, or blocked)"
            ),
            escalate=True,
            turn=self.turn,
            details={"turns_without_action": n},
        )

    def observe(
        self,
        *,
        ui_hierarchy: list[dict] | None,
        focused_app: str | None,
        executed_tool_calls: list[dict] | None,
    ) -> LoopTrigger | None:
        """Feed the state seen at this Cortex turn and the action executed since the last one."""
        self.turn += 1
        state = hash_state(ui_hierarchy, focused_app, self.config.include_bounds)
        prev_state = self._prev_state
        self._prev_state = state
        novel = state not in self.seen_states
        self.seen_states.add(state)

        if novel and prev_state is not None:
            # Reaching a never-seen screen counts as progress.
            self._triggers_without_progress = 0

        if prev_state is None or not executed_tool_calls:
            return None

        action, tools, desc = canonical_action(executed_tool_calls)
        self.transitions.append(
            Transition(
                state=prev_state,
                action=action,
                next_state=state,
                action_tools=tools,
                action_desc=desc,
            )
        )

        if self._cooldown_left > 0:
            self._cooldown_left -= 1
            return None

        trigger = self._evaluate()
        if trigger is None:
            return None

        self._cooldown_left = self.config.cooldown
        self._triggers_without_progress += 1
        esc = self.config.escalate_after
        trigger.escalate = esc > 0 and self._triggers_without_progress >= esc
        if trigger.escalate:
            self._triggers_without_progress = 0
        return trigger

    # ----------------------------------------------------------------- triggers
    def _evaluate(self) -> LoopTrigger | None:
        cfg = self.config
        trans = list(self.transitions)
        last = trans[-1]

        recent = trans[-cfg.window :]
        same = [t for t in recent if t.state == last.state and t.action == last.action]
        if len(same) >= cfg.repeat_threshold:
            return LoopTrigger(
                kind="repeat",
                evidence=(
                    f"the same action {last.action_desc} was executed {len(same)} times on the "
                    f"same screen (state {last.state}) within the last {len(recent)} steps"
                ),
                escalate=False,
                turn=self.turn,
                details={
                    "state_hash": last.state,
                    "action_hash": last.action,
                    "count": len(same),
                    "window": len(recent),
                },
            )

        tail = trans[-cfg.no_change_threshold :]
        if len(tail) >= cfg.no_change_threshold and all(
            t.state == t.next_state and not set(t.action_tools) <= NON_UI_TOOLS for t in tail
        ):
            return LoopTrigger(
                kind="no_change",
                evidence=(
                    f"the last {len(tail)} executed actions left the screen unchanged "
                    f"(state {last.next_state}); actions: " + "; ".join(t.action_desc for t in tail)
                ),
                escalate=False,
                turn=self.turn,
                details={"state_hash": last.next_state, "steps": len(tail)},
            )

        cyc = trans[-cfg.cycle_window :]
        if len(cyc) >= cfg.cycle_window:
            states = {t.state for t in cyc} | {cyc[-1].next_state}
            if len(states) <= cfg.cycle_max_distinct:
                return LoopTrigger(
                    kind="cycle",
                    evidence=(
                        f"the last {len(cyc)} steps only visited {len(states)} distinct screens "
                        f"({', '.join(sorted(states))}), without reaching anything new"
                    ),
                    escalate=False,
                    turn=self.turn,
                    details={"state_hashes": sorted(states), "steps": len(cyc)},
                )
        return None
