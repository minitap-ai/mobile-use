"""Matrix runner tests, against a fake harness that writes rows like P0-A's tools/run_agent.py."""

import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "matrix", ROOT / "benchmarks" / "matrix" / "matrix.py"
)
matrix = importlib.util.module_from_spec(_spec)
sys.modules["matrix"] = matrix
_spec.loader.exec_module(matrix)  # type: ignore[union-attr]

SHA = "a" * 40

FAKE_HARNESS = textwrap.dedent(
    '''
    """Fake harness: same CLI and result row shape as P0-A's tools/run_agent.py."""
    import argparse, json, os, sys, time
    ap = argparse.ArgumentParser()
    ap.add_argument("serial"); ap.add_argument("out_dir")
    ap.add_argument("--tasks"); ap.add_argument("--config"); ap.add_argument("--mobile-use")
    ap.add_argument("--expect-sha"); ap.add_argument("--seed", type=int)
    ap.add_argument("--timeout-s")
    ap.add_argument("--run-id")
    a = ap.parse_args()
    plan = json.load(open(os.environ["FAKE_PLAN"]))
    state = os.environ["FAKE_STATE"]
    os.makedirs(state, exist_ok=True)
    # concurrency probe
    marker = os.path.join(state, f"running-{os.getpid()}")
    open(marker, "w").close()
    running = len([f for f in os.listdir(state) if f.startswith("running-")])
    with open(os.path.join(state, "concurrency.log"), "a") as f:
        f.write(f"{running}\\n")
    time.sleep(float(os.environ.get("FAKE_SLEEP", "0")))
    task = a.tasks
    count_file = os.path.join(state, f"count-{task}-{a.config.replace('/', '_')}-{a.seed}")
    n = int(open(count_file).read()) if os.path.exists(count_file) else 0
    open(count_file, "w").write(str(n + 1))
    outcomes = plan.get(task, ["success"])
    outcome = outcomes[min(n, len(outcomes) - 1)]
    os.remove(marker)
    if outcome == "crash":
        sys.exit(3)
    os.makedirs(a.out_dir, exist_ok=True)
    rec = {"run_id": a.run_id, "task": task, "seed": a.seed, "mobile_use_sha": a.expect_sha,
           "config": a.config, "serial": a.serial, "init_s": 1.5, "status": "completed",
           "git_sha": a.expect_sha, "git_dirty": False, "config_resolved_sha256": "c" * 64,
           "metrics": {"wall_clock_s": 12.0, "llm": {
               "total_cost_usd": float(os.environ.get("FAKE_COST", "0.5")),
               "total_prompt_tokens": 1000, "total_completion_tokens": 50, "total_calls": 7}}}
    if outcome == "success":
        rec["score"] = 1.0
    elif outcome == "fail":
        rec["score"] = 0.0
    elif outcome == "infra":
        rec.update(status="error", error_kind="llm_api", infra_suspect=True, score=0.0)
    elif outcome == "badsha":
        rec.update(git_sha="b" * 40, score=1.0)
    elif outcome == "nometrics":
        rec.pop("metrics"); rec["score"] = 1.0
        d = os.path.join(a.out_dir, f"{task}-s{a.seed}"); os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "events.jsonl"), "w") as f:
            f.write(json.dumps({"type": "llm_call", "cost_usd": 0.25}) + "\\n")
            f.write(json.dumps({"type": "llm_call", "cost_usd": 0.5}) + "\\n")
    with open(os.path.join(a.out_dir, "results.jsonl"), "a") as f:
        f.write(json.dumps(rec) + "\\n")
    '''
)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Builds a spec + env hook + fake harness; returns a factory."""
    mu = tmp_path / "mobile-use"
    (mu / "benchmarks" / "configs").mkdir(parents=True)
    for c in ("full", "no-scratchpad"):
        (mu / "benchmarks" / "configs" / f"{c}.jsonc").write_text("{}")
    harness = tmp_path / "harness"
    harness.mkdir()
    (harness / "run_agent.py").write_text(FAKE_HARNESS)
    (tmp_path / "adbwrap").write_text(
        '#!/bin/sh\n[ "$1" = kill-server ] && exit 0\nexec adb "$@"\n'
    )
    state = tmp_path / "state"
    monkeypatch.setenv("FAKE_STATE", str(state))

    def make(
        tasks=("T1", "T2"),
        configs=("full",),
        seeds=(30,),
        devices=("d1",),
        plan=None,
        max_concurrency=1,
        budget=None,
        max_infra_attempts=3,
        sleep=0.0,
        cost=0.5,
    ):
        (tmp_path / "plan.json").write_text(json.dumps(plan or {}))
        monkeypatch.setenv("FAKE_PLAN", str(tmp_path / "plan.json"))
        monkeypatch.setenv("FAKE_SLEEP", str(sleep))
        monkeypatch.setenv("FAKE_COST", str(cost))
        (tmp_path / "devices.txt").write_text(
            "# comment\n"
            + "\n".join(devices[:1])
            + "\n"
            + "\n".join(
                json.dumps({"serial": d, "console_port": 5554 + 2 * i})
                for i, d in enumerate(devices[1:])
            )
            + "\n"
        )
        (tmp_path / "env.jsonc").write_text(
            json.dumps(
                {
                    "owner": "test",
                    "cwd": "harness",
                    "python": sys.executable,
                    "command": [
                        "{python}",
                        "run_agent.py",
                        "{serial}",
                        "{out_dir}",
                        "--tasks",
                        "{task}",
                        "--config",
                        "{config_path}",
                        "--mobile-use",
                        "{mobile_use_path}",
                        "--expect-sha",
                        "{mobile_use_sha}",
                        "--seed",
                        "{seed}",
                        "--timeout-s",
                        "{timeout_s}",
                        "--run-id",
                        "{run_id}",
                    ],
                    "result_file": "{out_dir}/results.jsonl",
                    "devices_file": "devices.txt",
                    "max_concurrency": max_concurrency,
                    "quarantine_after_infra": 99,
                    "adb_safety": {"mode": "adbwrap", "path": "adbwrap"},
                }
            )
        )
        spec = {
            "name": "test-matrix",
            "out_dir": "out",
            "mobile_use": {"path": "mobile-use", "sha": SHA},
            "configs": list(configs),
            "seeds": list(seeds),
            "task_sets": {"ts": {"tasks": list(tasks)}},
            "plan": [{"env": "fake", "task_set": "ts"}],
            "envs": {"fake": "env.jsonc"},
            "timeout_s": 60,
            "max_infra_attempts": max_infra_attempts,
            "budget": budget or {"max_usd": 0},
        }
        (tmp_path / "spec.jsonc").write_text("// test spec\n" + json.dumps(spec, indent=1))
        return matrix.Spec.load(tmp_path / "spec.jsonc")

    return make, tmp_path


def rows(path: Path) -> list[dict]:
    return (
        [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []
    )


def run(spec, **kw):
    return matrix.Runner(spec, poll_s=0.01, **kw).run()


def test_full_matrix_one_row_per_cell_with_schema(world):
    make, tmp = world
    spec = make(
        tasks=("T1", "T2"), configs=("full", "no-scratchpad"), seeds=(30, 31), plan={"T2": ["fail"]}
    )
    summary = run(spec)
    res = rows(spec.out_dir / "results.jsonl")
    assert len(res) == 8 and len({r["key"] for r in res}) == 8
    assert summary["totals"]["done"] == 8
    r = next(r for r in res if r["task"] == "T1")
    for k in (
        "task",
        "config",
        "seed",
        "env",
        "score",
        "outcome",
        "cost_usd",
        "prompt_tokens",
        "completion_tokens",
        "agent_wall_s",
        "cell_wall_s",
        "git_sha",
        "git_dirty",
        "infra_reason",
        "config_path",
        "attempts",
    ):
        assert k in r, k
    assert (
        r["outcome"] == "success"
        and r["score"] == 1.0
        and r["git_sha"] == SHA
        and r["git_dirty"] is False
    )
    assert (
        r["cost_usd"] == 0.5
        and r["prompt_tokens"] == 1000
        and r["config_path"].startswith("benchmarks/configs/")
    )
    assert {x["outcome"] for x in res if x["task"] == "T2"} == {"agent_failure"}
    groups = {(g["config"], g["seed"]): g for g in summary["by_group"]}
    assert groups[("full", 30)]["success_rate"] == 0.5


def test_rerun_is_idempotent(world):
    make, _ = world
    spec = make()
    run(spec)
    before = rows(spec.out_dir / "attempts.jsonl")
    run(matrix.Spec.load(spec.path))
    assert rows(spec.out_dir / "attempts.jsonl") == before
    assert len(rows(spec.out_dir / "results.jsonl")) == 2


def test_resume_after_partial_session(world):
    make, _ = world
    spec = make(tasks=("T1", "T2", "T3", "T4"))
    run(spec, max_cells=2)
    assert len(rows(spec.out_dir / "results.jsonl")) == 2
    run(matrix.Spec.load(spec.path))
    res = rows(spec.out_dir / "results.jsonl")
    assert sorted(r["task"] for r in res) == ["T1", "T2", "T3", "T4"]
    assert len(rows(spec.out_dir / "attempts.jsonl")) == 4


def test_infra_failure_is_retried_on_another_device(world):
    make, _ = world
    spec = make(tasks=("T1",), devices=("d1", "d2"), plan={"T1": ["infra", "success"]})
    run(spec)
    att = rows(spec.out_dir / "attempts.jsonl")
    assert [a["outcome"] for a in att] == ["infra_failure", "success"]
    assert att[0]["device"] != att[1]["device"]
    final = rows(spec.out_dir / "results.jsonl")
    assert len(final) == 1 and final[0]["outcome"] == "success" and final[0]["attempts"] == 2
    assert final[0]["total_cost_usd_all_attempts"] == 1.0


def test_agent_failure_is_not_retried_and_infra_is_capped(world):
    make, _ = world
    spec = make(
        tasks=("A", "B", "C"),
        plan={"A": ["fail", "success"], "B": ["infra"], "C": ["crash"]},
        max_infra_attempts=3,
    )
    run(spec)
    final = {r["task"]: r for r in rows(spec.out_dir / "results.jsonl")}
    assert final["A"]["outcome"] == "agent_failure" and final["A"]["attempts"] == 1
    assert final["B"]["outcome"] == "infra_exhausted" and final["B"]["attempts"] == 3
    assert final["C"]["outcome"] == "infra_exhausted" and final["C"]["infra_reason"] == "no_result"


def test_sha_mismatch_is_infra(world):
    make, _ = world
    spec = make(tasks=("T1",), plan={"T1": ["badsha"]}, max_infra_attempts=1)
    run(spec)
    r = rows(spec.out_dir / "results.jsonl")[0]
    assert r["outcome"] == "infra_exhausted" and r["infra_reason"] == "sha_mismatch"


def test_cost_falls_back_to_agent_events(world):
    make, _ = world
    spec = make(tasks=("T1",), plan={"T1": ["nometrics"]})
    run(spec)
    r = rows(spec.out_dir / "results.jsonl")[0]
    assert r["cost_usd"] == 0.75 and r["cost_source"] == "events"


def test_concurrency_is_capped_per_environment(world):
    make, tmp = world
    spec = make(
        tasks=tuple(f"T{i}" for i in range(8)),
        devices=("d1", "d2", "d3", "d4"),
        max_concurrency=2,
        sleep=0.3,
    )
    run(spec)
    seen = [int(x) for x in (tmp / "state" / "concurrency.log").read_text().split()]
    assert max(seen) <= 2
    assert max(seen) == 2  # it does run in parallel
    assert len(rows(spec.out_dir / "results.jsonl")) == 8


def test_one_task_per_device(world):
    make, tmp = world
    spec = make(
        tasks=tuple(f"T{i}" for i in range(4)), devices=("d1",), max_concurrency=4, sleep=0.2
    )
    run(spec)
    assert max(int(x) for x in (tmp / "state" / "concurrency.log").read_text().split()) == 1


def test_spend_guard_stops_launching(world):
    make, _ = world
    spec = make(
        tasks=tuple(f"T{i}" for i in range(6)),
        cost=1.0,
        budget={"max_usd": 2.5, "reserve_per_inflight_usd": 0},
    )
    summary = run(spec)
    assert summary["totals"]["done"] == 3  # 0 -> 1 -> 2 -> 3 spent; 3 > 2.5 stops
    assert summary["stop_reason"].startswith("budget")
    # the guard also holds across sessions (ledger includes earlier attempts)
    summary2 = run(matrix.Spec.load(spec.path))
    assert summary2["totals"]["done"] == 3


def test_spend_guard_reserves_for_inflight(world):
    make, _ = world
    spec = make(
        tasks=tuple(f"T{i}" for i in range(6)),
        cost=1.0,
        budget={"max_usd": 2.5, "reserve_per_inflight_usd": 1.0},
    )
    summary = run(spec)
    assert summary["totals"]["done"] == 2  # spent 2 + reserve 1 > 2.5


def test_stop_file(world):
    make, _ = world
    spec = make(tasks=("T1", "T2"))
    spec.out_dir.mkdir(parents=True, exist_ok=True)
    (spec.out_dir / "STOP").write_text("")
    summary = run(spec)
    assert summary["totals"]["done"] == 0 and summary["stop_reason"] == "STOP file"


def test_device_fields_are_template_values(world):
    make, _ = world
    spec = make(tasks=("T1",), devices=("d1", "emulator-5554"))
    env = spec.envs["fake"]
    env.command = env.command + ["--console-port", "{console_port}"]
    cell = spec.cells()[0]
    runner = matrix.Runner(spec)
    cmd = runner._command(
        cell, env, {"serial": "emulator-5554", "console_port": 5554}, Path("/x"), 1
    )
    assert cmd[-2:] == ["--console-port", "5554"] and "emulator-5554" in cmd
    with pytest.raises(ValueError, match="console_port"):
        runner._command(cell, env, {"serial": "d1"}, Path("/x"), 1)


def test_checkout_check_refuses_other_sha_or_dirty(tmp_path):
    repo = tmp_path / "mu"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "f").write_text("1")
    subprocess.run(["git", "-C", str(repo), "add", "f"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"],
        check=True,
    )
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()

    class S:
        mobile_use_path = repo
        mobile_use_sha = sha

    matrix.check_checkout(S)  # clean + right sha: ok
    (repo / "f").write_text("2")
    with pytest.raises(SystemExit, match="dirty=True"):
        matrix.check_checkout(S)
    S.mobile_use_sha = "0" * 40
    with pytest.raises(SystemExit, match="Refusing"):
        matrix.check_checkout(S)


def test_duplicate_cells_rejected(world):
    make, tmp = world
    spec = make(tasks=("T1",))
    d = matrix.load_jsonc(spec.path)
    d["plan"] = d["plan"] * 2
    (tmp / "dup.jsonc").write_text(json.dumps(d))
    with pytest.raises(ValueError, match="duplicate"):
        matrix.Spec.load(tmp / "dup.jsonc").cells()


def test_jsonc_comments_and_trailing_commas():
    assert matrix.load_jsonc.__name__ == "load_jsonc"
    text = '{\n // c\n "a": "http://x//y", /* b */ "l": [1, 2,],\n}'
    assert json.loads(matrix._strip_jsonc(text)) == {"a": "http://x//y", "l": [1, 2]}


def test_shipped_example_spec_and_hooks_parse():
    for p in (ROOT / "benchmarks" / "matrix").rglob("*.jsonc"):
        json.loads(matrix._strip_jsonc(p.read_text()))


def test_venv_python_symlink_is_not_followed(tmp_path):
    venv_bin = tmp_path / "h" / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").symlink_to(sys.executable)
    (tmp_path / "env.jsonc").write_text(
        json.dumps(
            {
                "cwd": "h",
                "python": ".venv/bin/python",
                "command": ["{python}"],
                "devices_file": "d.txt",
                "adb_safety": {"mode": "server_port", "port": 5038},
            }
        )
    )
    hook = matrix.EnvHook.load("x", tmp_path / "env.jsonc")
    assert hook.python == str(venv_bin / "python")


def test_adb_safety_is_mandatory_and_checked(tmp_path):
    base = {"cwd": ".", "command": ["x"], "devices_file": "d.txt"}
    hook = tmp_path / "e.jsonc"
    hook.write_text(json.dumps(base))
    with pytest.raises(ValueError, match="adb_safety"):
        matrix.EnvHook.load("x", hook)
    (tmp_path / "notaguard").write_text("exec adb")
    hook.write_text(json.dumps({**base, "adb_safety": {"mode": "adbwrap", "path": "notaguard"}}))
    with pytest.raises(ValueError, match="kill-server guard"):
        matrix.EnvHook.load("x", hook)
    hook.write_text(json.dumps({**base, "adb_safety": {"mode": "server_port", "port": 5037}}))
    with pytest.raises(ValueError, match="5037"):
        matrix.EnvHook.load("x", hook)
    hook.write_text(json.dumps({**base, "adb_safety": {"mode": "server_port", "port": 5038}}))
    assert matrix.EnvHook.load("x", hook).env_vars["ANDROID_ADB_SERVER_PORT"] == "5038"


def test_plan_entries_restrict_configs_and_set_phase_and_label(world):
    make, tmp = world
    spec = make(tasks=("T1", "T2"), configs=("full", "no-scratchpad"), seeds=(30, 31))
    d = matrix.load_jsonc(spec.path)
    d["task_sets"]["sub"] = {"tasks": ["T1"]}
    d["plan"] = [
        {"env": "fake", "task_set": "ts", "configs": ["full"], "phase": 0, "label": "AW-116"},
        {
            "env": "fake",
            "task_set": "sub",
            "configs": ["no-scratchpad"],
            "seeds": [30],
            "phase": 1,
            "label": "AW-Limrun-93 subset",
        },
    ]
    (tmp / "p.jsonc").write_text(json.dumps(d))
    s2 = matrix.Spec.load(tmp / "p.jsonc")
    cells = s2.cells()
    assert len(cells) == 4 + 1
    last = cells[-1]
    assert (last.config, last.task, last.seed, last.phase) == ("no-scratchpad", "T1", 30, 1)
    run(s2)
    res = {r["config"]: r for r in rows(s2.out_dir / "results.jsonl")}
    assert res["no-scratchpad"]["subset_label"] == "AW-Limrun-93 subset"
    assert res["full"]["phase"] == 0 and res["full"]["subset_label"] == "AW-116"
    d["plan"][1]["configs"] = ["not-in-spec"]
    (tmp / "bad.jsonc").write_text(json.dumps(d))
    with pytest.raises(ValueError, match="not in the spec"):
        matrix.Spec.load(tmp / "bad.jsonc")


def test_flat_rows_with_matrix_fields_are_accepted(world):
    make, tmp = world
    spec = make(tasks=("T1",))
    cell = spec.cells()[0]
    flat = {
        "task": "T1",
        "status": "completed",
        "score": 1.0,
        "git_sha": SHA,
        "git_dirty": False,
        "cost_usd": 1.25,
        "prompt_tokens": 10,
        "completion_tokens": 2,
        "llm_calls": 3,
        "agent_wall_s": 99.0,
    }
    row = matrix.build_row(
        cell,
        spec,
        flat,
        attempt=1,
        device={"serial": "d1"},
        out_dir=tmp,
        exit_code=0,
        cell_wall_s=100.0,
        started="t",
    )
    assert row["outcome"] == "success" and row["cost_usd"] == 1.25 and row["cost_source"] == "row"
    assert (row["prompt_tokens"], row["completion_tokens"], row["llm_calls"]) == (10, 2, 3)
    assert row["agent_wall_s"] == 99.0
