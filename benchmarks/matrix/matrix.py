#!/usr/bin/env python3
"""Experiment matrix runner: config x seed x task-set x environment.

Stdlib only, so it runs from any Python >= 3.10. It never talks to a device itself: every cell
is one call of the environment's harness (P0-A Limrun, P1-P emulator / Pixel), described by an
env hook file (see benchmarks/matrix/README.md). The harness initializes the AndroidWorld task,
runs the pinned mobile-use agent, scores it with the official evaluator and appends one JSON line
to its results file; this runner turns that line into one matrix row.

    python benchmarks/matrix/matrix.py plan   <spec.jsonc>
    python benchmarks/matrix/matrix.py run    <spec.jsonc> [--max-cells N]
    python benchmarks/matrix/matrix.py status <spec.jsonc>

Guarantees:
- resumable / idempotent: a cell whose final row is in results.jsonl is never run again; every
  attempt is in attempts.jsonl, so a restart resumes exactly where it stopped;
- one final row per (task, config, seed, env) in results.jsonl;
- infra failures are retried (other device first) up to max_infra_attempts, agent failures never;
- per-environment concurrency cap, one task per device, devices quarantined after repeated
  infra failures;
- global spend guard on the true LLM cost (ledger of all attempts, BYOK included) plus an
  optional check of the OpenRouter key's remaining limit; no new cell starts once the guard trips;
- a STOP file in the output directory stops launching new cells (running ones finish).
"""

from __future__ import annotations

import argparse
import fcntl
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROW_SCHEMA = 1
INFRA_STATUSES = {
    "init_error",
    "harness_init_error",
    "harness_agent_crash",
    "harness_crash",
    "harness_timeout",
    "rejected_sha",
    "no_result",
}


# --------------------------------------------------------------------------- jsonc
def _strip_jsonc(text: str) -> str:
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
            out.append(c)
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        else:
            out.append(c)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def load_jsonc(path: Path) -> dict:
    return json.loads(_strip_jsonc(path.read_text(encoding="utf-8")))


def now() -> str:
    return datetime.now(UTC).isoformat()


# --------------------------------------------------------------------------- spec
@dataclass(frozen=True)
class Cell:
    env: str
    task_set: str
    task: str
    config: str
    seed: int
    phase: int = 0
    label: str = ""

    @property
    def key(self) -> str:
        return f"{self.env}|{self.task}|{self.config}|{self.seed}"


@dataclass
class EnvHook:
    name: str
    path: Path
    cwd: Path
    command: list[str]
    result_file: str
    devices_file: Path
    max_concurrency: int
    env_vars: dict[str, str]
    python: str
    quarantine_after_infra: int
    harness_overhead_s: int
    adb_safety: dict[str, Any] = field(default_factory=dict)
    owner: str | None = None

    @classmethod
    def load(cls, name: str, path: Path) -> EnvHook:
        d = load_jsonc(path)
        base = path.parent
        cwd = (base / d.get("cwd", ".")).resolve()
        adb_safety = check_adb_safety(path, d.get("adb_safety"))
        env_vars = {k: str(v) for k, v in (d.get("env_vars") or {}).items()}
        if adb_safety["mode"] == "server_port":
            env_vars["ANDROID_ADB_SERVER_PORT"] = str(adb_safety["port"])
        python = d.get("python", sys.executable)
        if not os.path.isabs(python) and ("/" in python):
            # abspath, NOT resolve(): a venv's bin/python is a symlink to the base interpreter,
            # and following it would run the harness outside its venv.
            python = os.path.abspath(cwd / python)
        return cls(
            name=name,
            path=path,
            cwd=cwd,
            command=list(d["command"]),
            result_file=d.get("result_file", "{out_dir}/results.jsonl"),
            devices_file=(base / d["devices_file"]).resolve(),
            max_concurrency=int(d.get("max_concurrency", 1)),
            env_vars=env_vars,
            python=python,
            quarantine_after_infra=int(d.get("quarantine_after_infra", 2)),
            harness_overhead_s=int(d.get("harness_overhead_s", 900)),
            adb_safety=adb_safety,
            owner=d.get("owner"),
        )

    def devices(self) -> list[dict[str, Any]]:
        """Re-read on every scheduling pass, so owners can add/remove devices live."""
        if not self.devices_file.exists():
            return []
        devs = []
        for line in self.devices_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            dev = json.loads(line) if line.startswith("{") else {"serial": line}
            if "serial" not in dev:
                raise ValueError(f"{self.devices_file}: device without serial: {line}")
            devs.append(dev)
        return devs


ADB_SAFETY_MODES = ("adbwrap", "shim", "server_port")


def check_adb_safety(hook_path: Path, conf: dict | None) -> dict:
    """Every env must say how `adb kill-server` (android_env retries) is kept away from the shared
    adb server that carries the Limrun tunnels. A hook that doesn't is refused.

    - adbwrap:     the harness's adb_path is a wrapper that drops `kill-server` (P1-P tools/adbwrap)
    - shim:        the harness's AdbController never calls it (P0-A aw_limrun/adb_env.py)
    - server_port: the harness gets its own adb server (ANDROID_ADB_SERVER_PORT is set for it);
                   the harness must then pass `--adb-port <port>` to the agent runner too.
    """
    if not conf or conf.get("mode") not in ADB_SAFETY_MODES:
        raise ValueError(
            f"{hook_path}: 'adb_safety' must be one of {ADB_SAFETY_MODES} "
            "(android_env's `adb kill-server` would drop every Limrun tunnel on the shared server)"
        )
    conf = dict(conf)
    if conf["mode"] in ("adbwrap", "shim"):
        guard = (hook_path.parent / conf["path"]).resolve()
        if not guard.is_file() or "kill-server" not in guard.read_text(errors="replace"):
            raise ValueError(
                f"{hook_path}: adb_safety guard {guard} missing or not a kill-server guard"
            )
        conf["path"] = str(guard)
    else:
        port = int(conf["port"])
        if port == 5037:
            raise ValueError(
                f"{hook_path}: adb_safety server_port must differ from the shared 5037"
            )
        conf["port"] = port
    return conf


@dataclass
class Spec:
    path: Path
    name: str
    out_dir: Path
    mobile_use_path: Path
    mobile_use_sha: str
    configs: list[str]
    seeds: list[int]
    task_sets: dict[str, list[str]]
    plan: list[dict[str, str]]
    envs: dict[str, EnvHook]
    timeout_s: int
    max_infra_attempts: int
    order: list[str]
    budget_max_usd: float
    reserve_per_inflight_usd: float
    key_check: bool
    key_min_remaining_usd: float
    est_cost_per_cell_usd: float
    raw: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path, out_dir: Path | None = None) -> Spec:
        path = path.resolve()
        d = load_jsonc(path)
        base = path.parent
        task_sets = {}
        for name, ts in d["task_sets"].items():
            if "tasks" in ts:
                tasks = list(ts["tasks"])
            else:
                lines = (base / ts["file"]).read_text().splitlines()
                tasks = [x.strip() for x in lines if x.strip() and not x.startswith("#")]
            if len(set(tasks)) != len(tasks):
                raise ValueError(f"task set {name} has duplicates")
            task_sets[name] = tasks
        envs = {n: EnvHook.load(n, (base / p).resolve()) for n, p in d["envs"].items()}
        for item in d["plan"]:
            if item["env"] not in envs or item["task_set"] not in task_sets:
                raise ValueError(f"plan entry {item} refers to an unknown env or task set")
            unknown = set(item.get("configs", [])) - set(d["configs"])
            if unknown:
                raise ValueError(
                    f"plan entry {item} uses configs not in the spec's configs: {unknown}"
                )
        budget = d.get("budget") or {}
        mu = d["mobile_use"]
        return cls(
            path=path,
            name=d["name"],
            out_dir=(out_dir or (base / d.get("out_dir", f"runs/{d['name']}"))).resolve(),
            mobile_use_path=(base / mu["path"]).resolve(),
            mobile_use_sha=mu["sha"],
            configs=list(d["configs"]),
            seeds=[int(s) for s in d["seeds"]],
            task_sets=task_sets,
            plan=list(d["plan"]),
            envs=envs,
            timeout_s=int(d.get("timeout_s", 1800)),
            max_infra_attempts=int(d.get("max_infra_attempts", 3)),
            order=list(d.get("order", ["phase", "seed", "config", "task"])),
            budget_max_usd=float(budget.get("max_usd", 0)),
            reserve_per_inflight_usd=float(budget.get("reserve_per_inflight_usd", 3.0)),
            key_check=bool(budget.get("openrouter_key_check", False)),
            key_min_remaining_usd=float(budget.get("key_min_remaining_usd", 25.0)),
            est_cost_per_cell_usd=float(budget.get("est_cost_per_cell_usd", 1.5)),
            raw=d,
        )

    def cells(self) -> list[Cell]:
        # A plan entry may restrict configs/seeds (e.g. ablations on a subset only) and carry a
        # phase (launch priority) and a label (e.g. "AW-Limrun-93 subset").
        cells = [
            Cell(
                env=p["env"],
                task_set=p["task_set"],
                task=t,
                config=c,
                seed=int(s),
                phase=int(p.get("phase", 0)),
                label=p.get("label", p["task_set"]),
            )
            for p in self.plan
            for t in self.task_sets[p["task_set"]]
            for c in p.get("configs", self.configs)
            for s in p.get("seeds", self.seeds)
        ]
        keys = [c.key for c in cells]
        if len(set(keys)) != len(keys):
            dup = [k for k, v in Counter(keys).items() if v > 1][:5]
            raise ValueError(
                f"the plan produces duplicate cells (same task twice on one env): {dup}"
            )
        rank = {
            "seed": lambda c: c.seed,
            "config": lambda c: self.configs.index(c.config),
            "task": lambda c: c.task,
            "env": lambda c: c.env,
            "phase": lambda c: c.phase,
        }
        return sorted(cells, key=lambda c: tuple(rank[k](c) for k in self.order))

    def config_path(self, name: str) -> str:
        """Path relative to the mobile-use checkout (harnesses run the agent with that cwd)."""
        for rel in (f"benchmarks/configs/{name}.jsonc", f"benchmarks/configs/routing/{name}.jsonc"):
            if (self.mobile_use_path / rel).exists():
                return rel
        raise FileNotFoundError(
            f"config {name!r} not found in {self.mobile_use_path}/benchmarks/configs"
        )


# --------------------------------------------------------------------------- rows
def _num(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def cost_from_events(out_dir: Path) -> float | None:
    """Fallback when the harness row has no metrics: sum llm_call costs of the agent events."""
    total, seen = 0.0, False
    for f in glob.glob(str(out_dir / "**" / "events.jsonl"), recursive=True):
        for line in open(f, encoding="utf-8"):
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("type") == "llm_call" and e.get("cost_usd") is not None:
                total += float(e["cost_usd"])
                seen = True
    return total if seen else None


# AndroidWorld's own rule (suite_utils._run_task, upstream @55ddaf5):
#   agent_successful = task_successful if interaction_results.done else 0.0
# i.e. a task only counts if the agent ended the episode itself. For mobile-use, "done" = the
# graph ended on its own (status completed / ended_incomplete); max_steps, timeout and errors are
# not done, so they score 0 even if the device state happens to satisfy the evaluator.
EPISODE_DONE_STATUSES = {"completed", "ended_incomplete"}
SCORE_RULE = "aw_suite_utils_done_gate"


def official_score(h: dict) -> tuple[float | None, float | None, bool]:
    """-> (official score, raw is_successful score, episode done)."""
    raw = _num(h.get("score_raw", h.get("score")))
    done = h.get("status") in EPISODE_DONE_STATUSES
    if h.get("official_score") is not None:  # harness applied the gate itself (P1-P)
        return _num(h["official_score"]), raw, done
    if raw is None:
        return None, None, done
    return (raw if done else 0.0), raw, done


def classify(h: dict) -> tuple[str, str | None]:
    """-> (outcome, infra_reason). outcome: success | agent_failure | infra_failure."""
    status = h.get("status")
    if status in INFRA_STATUSES:
        return "infra_failure", status
    if h.get("infra_suspect"):
        return "infra_failure", h.get("error_kind") or status or "infra_suspect"
    if h.get("score_error"):
        return "infra_failure", "evaluator_error"
    if h.get("git_dirty") or (
        h.get("_expected_sha") and h.get("git_sha") not in (None, h["_expected_sha"])
    ):
        return "infra_failure", "sha_mismatch"
    score, _raw, _done = official_score(h)
    if score is None:
        return "infra_failure", "no_score"
    return ("success" if score >= 1.0 else "agent_failure"), None


def official_outcome(row: dict) -> str:
    """Outcome under the official gate, also for rows written before the gate existed."""
    if row.get("score_rule") == SCORE_RULE or row.get("outcome") not in (
        "success",
        "agent_failure",
    ):
        return row["outcome"]
    score, _raw, _done = official_score(row)
    return "success" if (score or 0.0) >= 1.0 else "agent_failure"


def build_row(
    cell: Cell,
    spec: Spec,
    h: dict,
    *,
    attempt: int,
    device: dict,
    out_dir: Path,
    exit_code: int | None,
    cell_wall_s: float,
    started: str,
) -> dict:
    h = dict(h)
    h["_expected_sha"] = spec.mobile_use_sha
    outcome, infra_reason = classify(h)
    m = h.get("metrics") or {}
    llm = m.get("llm") or {}
    # Accepts the harness row shape (agent `metrics` nested, P0-A run_agent.py) and flat rows that
    # already carry the matrix fields (cost_usd, prompt_tokens, ...).
    cost = _num(llm.get("total_cost_usd"))
    cost_source = "metrics"
    if cost is None and _num(h.get("cost_usd")) is not None:
        cost, cost_source = _num(h.get("cost_usd")), "row"
    if cost is None:
        cost, cost_source = cost_from_events(out_dir), "events"
    return {
        "schema": ROW_SCHEMA,
        "matrix": spec.name,
        "key": cell.key,
        "env": cell.env,
        "task_set": cell.task_set,
        "subset_label": cell.label,
        "phase": cell.phase,
        "task": cell.task,
        "config": cell.config,
        "config_path": spec.config_path(cell.config),
        "seed": cell.seed,
        "attempt": attempt,
        "outcome": outcome,
        "infra_reason": infra_reason,
        "status": h.get("status"),
        "score": official_score(h)[0],
        "score_raw": official_score(h)[1],
        "episode_done": official_score(h)[2],
        "score_rule": SCORE_RULE,
        "error": h.get("error") or h.get("score_error"),
        "error_kind": h.get("error_kind"),
        "final_answer": h.get("final_answer"),
        "cost_usd": cost,
        "cost_source": cost_source if cost is not None else None,
        "prompt_tokens": llm.get("total_prompt_tokens", h.get("prompt_tokens")),
        "completion_tokens": llm.get("total_completion_tokens", h.get("completion_tokens")),
        "llm_calls": llm.get("total_calls", h.get("llm_calls")),
        "agent_wall_s": _num(m.get("wall_clock_s")) or _num(h.get("agent_wall_s")),
        "init_s": _num(h.get("init_s")),
        "cell_wall_s": round(cell_wall_s, 1),
        "git_sha": h.get("git_sha") or h.get("mobile_use_sha"),
        "git_dirty": h.get("git_dirty"),
        "expected_sha": spec.mobile_use_sha,
        "config_resolved_sha256": h.get("config_resolved_sha256"),
        "aw_sha": h.get("aw_sha"),
        "device": device.get("serial"),
        "harness_run_id": h.get("run_id"),
        "harness_exit_code": exit_code,
        "workarounds": h.get("workarounds"),
        "out_dir": str(out_dir),
        "started_at": started,
        "ended_at": now(),
    }


# --------------------------------------------------------------------------- runner
class Ledger:
    """attempts.jsonl (every attempt) + results.jsonl (one final row per cell) + events.jsonl.

    The files are the source of truth and may be shared by several matrix processes (e.g. one per
    environment on the same out_dir): appends are flock-ed single lines, and every read first
    picks up the lines other processes appended, so the spend guard sees the total spend.
    """

    def __init__(self, out_dir: Path):
        self.out_dir = out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        self.attempts_path = out_dir / "attempts.jsonl"
        self.results_path = out_dir / "results.jsonl"
        self.events_path = out_dir / "matrix_events.jsonl"
        self.lock = threading.Lock()
        self.attempts: dict[str, list[dict]] = defaultdict(list)
        self.final: dict[str, dict] = {}
        self._offsets = {self.attempts_path: 0, self.results_path: 0}
        self.refresh()

    def _read_new(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        with open(path, "rb") as f:
            f.seek(self._offsets[path])
            data = f.read()
        end = data.rfind(b"\n")
        if end < 0:
            return []  # nothing complete yet (a writer is mid-line)
        chunk = data[: end + 1]
        self._offsets[path] += len(chunk)
        return [json.loads(x) for x in chunk.decode("utf-8").splitlines() if x.strip()]

    def refresh(self) -> None:
        with self.lock:
            for row in self._read_new(self.attempts_path):
                self.attempts[row["key"]].append(row)
            for row in self._read_new(self.results_path):
                self.final.setdefault(row["key"], row)

    def _append(self, path: Path, row: dict):
        line = json.dumps(row, ensure_ascii=False, default=str) + "\n"
        with open(path, "a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(line)
                f.flush()
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def add_attempt(self, row: dict):
        self._append(self.attempts_path, row)
        self.refresh()

    def finalize(self, row: dict, attempts: list[dict]):
        self.refresh()
        with self.lock:
            if row["key"] in self.final:
                return
            final = dict(row)
            final["attempts"] = len(attempts)
            final["attempt_outcomes"] = [a["outcome"] for a in attempts]
            final["total_cost_usd_all_attempts"] = round(
                sum(a.get("cost_usd") or 0.0 for a in attempts), 6
            )
        self._append(self.results_path, final)
        self.refresh()

    def event(self, kind: str, **fields):
        self._append(self.events_path, {"ts": now(), "type": kind, **fields})

    def spent_usd(self) -> float:
        self.refresh()
        with self.lock:
            return sum(a.get("cost_usd") or 0.0 for rows in self.attempts.values() for a in rows)


def openrouter_key_remaining() -> float | None:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return None
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/key", headers={"Authorization": f"Bearer {key}"}
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r).get("data", {})
    rem = data.get("limit_remaining")
    return float(rem) if rem is not None else None


def check_checkout(spec: Spec) -> None:
    def git(*a):
        return subprocess.run(
            ["git", "-C", str(spec.mobile_use_path), *a], capture_output=True, text=True
        ).stdout.strip()

    sha = git("rev-parse", "HEAD")
    dirty = git("status", "--porcelain", "--untracked-files=no")
    if sha != spec.mobile_use_sha or dirty:
        raise SystemExit(
            f"mobile-use checkout {spec.mobile_use_path} is at {sha or '?'} "
            f"(dirty={bool(dirty)}); the spec pins {spec.mobile_use_sha}. Refusing to run."
        )


class Runner:
    def __init__(
        self,
        spec: Spec,
        *,
        max_cells: int | None = None,
        poll_s: float = 2.0,
        key_check_every_s: float = 120.0,
    ):
        self.spec = spec
        self.ledger = Ledger(spec.out_dir)
        self.max_cells = max_cells
        self.poll_s = poll_s
        self.key_check_every_s = key_check_every_s
        self.lock = threading.Lock()
        self.running: dict[str, int] = defaultdict(int)  # env -> running cells
        self.busy: set[tuple[str, str]] = set()  # (env, serial)
        self.inflight_keys: set[str] = set()
        self.infra_streak: Counter[tuple[str, str]] = Counter()
        self.quarantined: set[tuple[str, str]] = set()
        self.last_device: dict[str, str] = {}
        self.launched = 0
        self.stop_reason: str | None = None
        self._last_key_check = 0.0
        self.threads: list[threading.Thread] = []

    # ---------------------------------------------------------------- guards
    def _budget_ok(self) -> bool:
        spec = self.spec
        if spec.budget_max_usd > 0:
            spent = self.ledger.spent_usd()
            reserve = (sum(self.running.values()) + 1) * spec.reserve_per_inflight_usd
            if spent + reserve > spec.budget_max_usd:
                self.stop_reason = (
                    f"budget: spent ${spent:.2f} + reserve ${reserve:.2f}"
                    f" > ${spec.budget_max_usd:.2f}"
                )
                return False
        if spec.key_check and time.monotonic() - self._last_key_check > self.key_check_every_s:
            self._last_key_check = time.monotonic()
            try:
                rem = openrouter_key_remaining()
            except Exception as e:  # noqa: BLE001
                self.ledger.event("key_check_error", error=str(e)[:200])
                rem = None
            if rem is not None:
                self.ledger.event("key_check", limit_remaining_usd=rem)
                if rem < spec.key_min_remaining_usd:
                    self.stop_reason = (
                        f"openrouter key: ${rem:.2f} remaining < ${spec.key_min_remaining_usd:.2f}"
                    )
                    return False
        return True

    def _stop_file(self) -> bool:
        if (self.spec.out_dir / "STOP").exists():
            self.stop_reason = "STOP file"
            return True
        return False

    # ---------------------------------------------------------------- scheduling
    def pending(self) -> list[Cell]:
        self.ledger.refresh()
        out = []
        for c in self.spec.cells():
            if c.key in self.ledger.final or c.key in self.inflight_keys:
                continue
            out.append(c)
        return out

    def _free_device(self, env: EnvHook, cell: Cell) -> dict | None:
        devs = [
            d
            for d in env.devices()
            if (env.name, d["serial"]) not in self.busy
            and (env.name, d["serial"]) not in self.quarantined
        ]
        if not devs:
            return None
        # retry an infra failure on another device when possible
        prev = self.last_device.get(cell.key)
        devs.sort(key=lambda d: d["serial"] == prev)
        return devs[0]

    def run(self) -> dict:
        if not self.ledger.final and not self.ledger.attempts:
            self.ledger.event(
                "matrix_start", spec=str(self.spec.path), cells=len(self.spec.cells())
            )
        else:
            self.ledger.event("matrix_resume", done=len(self.ledger.final))
        while True:
            pend = self.pending()
            if not pend and not self.inflight_keys:
                break
            can_launch = not self._stop_file() and (
                self.max_cells is None or self.launched < self.max_cells
            )
            if can_launch:
                for cell in pend:
                    env = self.spec.envs[cell.env]
                    with self.lock:
                        if self.running[env.name] >= env.max_concurrency:
                            continue
                        if not self._budget_ok():
                            can_launch = False
                            break
                        dev = self._free_device(env, cell)
                        if dev is None:
                            continue
                        self.running[env.name] += 1
                        self.busy.add((env.name, dev["serial"]))
                        self.inflight_keys.add(cell.key)
                        self.launched += 1
                    t = threading.Thread(target=self._run_cell, args=(cell, env, dev), daemon=True)
                    t.start()
                    self.threads.append(t)
                    if self.max_cells is not None and self.launched >= self.max_cells:
                        break
            if not self.inflight_keys and (not can_launch or not self._any_device_available(pend)):
                break
            time.sleep(self.poll_s)
        for t in self.threads:
            t.join()
        summary = self.summary()
        self.ledger.event("matrix_stop", reason=self.stop_reason or "done", **summary["totals"])
        return summary

    def _any_device_available(self, pend: list[Cell]) -> bool:
        for env_name in {c.env for c in pend}:
            env = self.spec.envs[env_name]
            if any((env_name, d["serial"]) not in self.quarantined for d in env.devices()):
                return True
        if pend:
            self.stop_reason = self.stop_reason or "no usable device for the remaining cells"
        return False

    # ---------------------------------------------------------------- one cell
    def _command(
        self, cell: Cell, env: EnvHook, dev: dict, out_dir: Path, attempt: int
    ) -> list[str]:
        values = {
            **{k: str(v) for k, v in dev.items()},
            "python": env.python,
            "out_dir": str(out_dir),
            "task": cell.task,
            "config": cell.config,
            "config_path": self.spec.config_path(cell.config),
            "mobile_use_path": str(self.spec.mobile_use_path),
            "mobile_use_sha": self.spec.mobile_use_sha,
            "seed": str(cell.seed),
            "timeout_s": str(self.spec.timeout_s),
            "run_id": f"{self.spec.name}|{cell.key}|a{attempt}",
            "env": cell.env,
        }
        try:
            return [part.format(**values) for part in env.command]
        except KeyError as e:
            raise ValueError(
                f"env {env.name}: placeholder {e} has no value (device fields: {list(dev)})"
            ) from e

    def _run_cell(self, cell: Cell, env: EnvHook, dev: dict):
        started, t0 = now(), time.monotonic()
        attempt = len(self.ledger.attempts.get(cell.key, [])) + 1
        slug = hashlib.sha1(cell.key.encode()).hexdigest()[:8]
        out_dir = (
            self.spec.out_dir
            / "cells"
            / cell.env
            / cell.config
            / f"s{cell.seed}"
            / f"{cell.task}-{slug}"
            / f"a{attempt}"
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        exit_code, harness_row = None, None
        try:
            cmd = self._command(cell, env, dev, out_dir, attempt)
            (out_dir / "command.json").write_text(
                json.dumps({"cmd": cmd, "cwd": str(env.cwd)}, indent=1)
            )
            run_env = {**os.environ, **env.env_vars}
            with open(out_dir / "harness.log", "w") as log:
                proc = subprocess.run(
                    cmd,
                    cwd=env.cwd,
                    env=run_env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=self.spec.timeout_s + env.harness_overhead_s,
                )
            exit_code = proc.returncode
            harness_row = self._read_result(env, out_dir, cell)
            if harness_row is None:
                harness_row = {
                    "status": "no_result",
                    "error": f"harness exit {exit_code}, no result row",
                }
        except subprocess.TimeoutExpired:
            harness_row = {
                "status": "harness_timeout",
                "error": "harness exceeded timeout_s + overhead",
            }
        except Exception as e:  # noqa: BLE001
            harness_row = {"status": "harness_crash", "error": f"{type(e).__name__}: {e}"}
        row = build_row(
            cell,
            self.spec,
            harness_row,
            attempt=attempt,
            device=dev,
            out_dir=out_dir,
            exit_code=exit_code,
            cell_wall_s=time.monotonic() - t0,
            started=started,
        )
        self.ledger.add_attempt(row)
        with self.lock:
            dkey = (env.name, dev["serial"])
            self.busy.discard(dkey)
            self.running[env.name] -= 1
            self.last_device[cell.key] = dev["serial"]
            if row["outcome"] == "infra_failure":
                self.infra_streak[dkey] += 1
                if (
                    self.infra_streak[dkey] >= env.quarantine_after_infra
                    and dkey not in self.quarantined
                ):
                    self.quarantined.add(dkey)
                    self.ledger.event(
                        "device_quarantined",
                        env=env.name,
                        serial=dev["serial"],
                        infra_streak=self.infra_streak[dkey],
                    )
            else:
                self.infra_streak[dkey] = 0
            attempts = self.ledger.attempts[cell.key]
            if row["outcome"] != "infra_failure" or len(attempts) >= self.spec.max_infra_attempts:
                final = dict(row)
                if row["outcome"] == "infra_failure":
                    final["outcome"] = "infra_exhausted"
                self.ledger.finalize(final, attempts)
            self.inflight_keys.discard(cell.key)

    def _read_result(self, env: EnvHook, out_dir: Path, cell: Cell) -> dict | None:
        path = Path(env.result_file.format(out_dir=str(out_dir)))
        if not path.exists():
            return None
        rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
        rows = [r for r in rows if r.get("task") in (None, cell.task)]
        return rows[-1] if rows else None

    # ---------------------------------------------------------------- summary
    def summary(self) -> dict:
        return summarize(self.spec, self.ledger, self.stop_reason)


def summarize(spec: Spec, ledger: Ledger, stop_reason: str | None = None) -> dict:
    cells = spec.cells()
    groups: dict[tuple[str, str, int], Counter] = defaultdict(Counter)
    cost: dict[tuple[str, str, int], float] = defaultdict(float)
    for c in cells:
        g = (c.config, c.env, c.seed)
        row = ledger.final.get(c.key)
        groups[g]["cells"] += 1
        if row is None:
            groups[g]["pending"] += 1
            continue
        groups[g][official_outcome(row)] += 1
        cost[g] += row.get("total_cost_usd_all_attempts") or 0.0
    by_group = []
    for (config, env, seed), cnt in sorted(groups.items()):
        scored = cnt["success"] + cnt["agent_failure"]
        by_group.append(
            {
                "config": config,
                "env": env,
                "seed": seed,
                "cells": cnt["cells"],
                "pending": cnt["pending"],
                "success": cnt["success"],
                "agent_failure": cnt["agent_failure"],
                "infra_exhausted": cnt["infra_exhausted"],
                "success_rate": round(cnt["success"] / scored, 4) if scored else None,
                "cost_usd": round(cost[(config, env, seed)], 4),
            }
        )
    totals = {
        "cells": len(cells),
        "done": sum(1 for c in cells if c.key in ledger.final),
        "attempts": sum(len(v) for v in ledger.attempts.values()),
        "spent_usd": round(ledger.spent_usd(), 4),
    }
    return {"totals": totals, "by_group": by_group, "stop_reason": stop_reason}


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=["plan", "run", "status", "rescore"])
    ap.add_argument("spec")
    ap.add_argument("--out", help="output directory (default: spec out_dir)")
    ap.add_argument("--max-cells", type=int, help="launch at most N cells in this session")
    ap.add_argument(
        "--skip-checkout-check",
        action="store_true",
        help="tests only: don't verify the mobile-use checkout SHA",
    )
    a = ap.parse_args(argv)
    spec = Spec.load(Path(a.spec), Path(a.out) if a.out else None)
    if a.command == "plan":
        cells = spec.cells()
        per_env = Counter(c.env for c in cells)
        done = Ledger(spec.out_dir).final
        print(
            json.dumps(
                {
                    "matrix": spec.name,
                    "cells": len(cells),
                    "already_done": sum(c.key in done for c in cells),
                    "per_env": per_env,
                    "per_config": Counter(c.config for c in cells),
                    "configs": spec.configs,
                    "seeds": spec.seeds,
                    "est_cost_usd": round(len(cells) * spec.est_cost_per_cell_usd, 2),
                    "est_cost_usd_per_config": {
                        k: round(v * spec.est_cost_per_cell_usd, 2)
                        for k, v in Counter(c.config for c in cells).items()
                    },
                    "budget_max_usd": spec.budget_max_usd,
                    "devices": {n: len(e.devices()) for n, e in spec.envs.items()},
                    "max_concurrency": {n: e.max_concurrency for n, e in spec.envs.items()},
                    "config_paths": {c: spec.config_path(c) for c in spec.configs},
                },
                indent=2,
                default=str,
            )
        )
        return 0
    if a.command == "rescore":
        # Rows written before the official done-gate (mobile-use c3f77e7) stored the raw
        # is_successful score as "score". Write the official view next to the ledger (the ledger
        # itself is never rewritten).
        ledger = Ledger(spec.out_dir)
        out_path = spec.out_dir / "results.official.jsonl"
        changed = 0
        with open(out_path, "w", encoding="utf-8") as f:
            for row in ledger.final.values():
                r = dict(row)
                if r.get("score_rule") != SCORE_RULE and r.get("outcome") in (
                    "success",
                    "agent_failure",
                ):
                    score, raw, done = official_score(r)
                    r.update(
                        score=score,
                        score_raw=raw,
                        episode_done=done,
                        score_rule=SCORE_RULE,
                        outcome=official_outcome(row),
                    )
                    changed += r["outcome"] != row["outcome"]
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
        print(
            json.dumps(
                {"rows": len(ledger.final), "outcome_changed": changed, "written": str(out_path)},
                indent=2,
            )
        )
        return 0
    if a.command == "status":
        print(json.dumps(summarize(spec, Ledger(spec.out_dir)), indent=2))
        return 0
    if not a.skip_checkout_check:
        check_checkout(spec)
    for c in spec.configs:
        spec.config_path(c)
    summary = Runner(spec, max_cells=a.max_cells).run()
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
