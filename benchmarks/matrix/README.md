# Experiment matrix runner

`matrix.py` (stdlib only) runs **config × seed × task set × environment** for the AndroidWorld
paper rework. It never touches a device: each cell is one call of the environment's harness
(P0-A's Limrun harness, P1-P's stock emulator and Pixel harnesses), which initializes the task,
runs the pinned mobile-use agent (`minitap.mobile_use.benchmark.runner`), scores it with the
**official AndroidWorld evaluator** and appends one JSON line to its results file.

```bash
set -a; source ~/.opencode-creds/openrouter-paper.env; set +a   # the agent and the key guard need it
python benchmarks/matrix/matrix.py plan   local/matrix/specs/aw-rework.jsonc   # cell count, cost estimate, devices
python benchmarks/matrix/matrix.py run    local/matrix/specs/aw-rework.jsonc   # resumable
python benchmarks/matrix/matrix.py status local/matrix/specs/aw-rework.jsonc   # per config/env/seed
python benchmarks/matrix/matrix.py rescore local/matrix/specs/aw-rework.jsonc  # official view of old rows
touch <out_dir>/STOP                                                            # stop launching, let running cells finish
```

The live specs, env hooks, device lists and task sets are in the umbrella's `local/matrix/`
(owned by the environment owners); `examples/` holds copies of them as templates.

## Spec (`specs/*.jsonc`)

| Key | Meaning |
|---|---|
| `name`, `out_dir` | matrix id; output directory (relative to the spec) |
| `mobile_use.path`, `mobile_use.sha` | the checkout the harnesses run; `run` refuses to start unless it is at `sha` and clean |
| `configs` | names in `benchmarks/configs/` (or `routing/`) |
| `seeds` | AndroidWorld `task_random_seed` values (passed to the harness `--seed`) |
| `task_sets` | `{"file": "...txt"}` (one task per line, `#` comments) or `{"tasks": [...]}` |
| `plan` | list of `{env, task_set, configs?, seeds?, phase?, label?}`: which tasks run on which environment, optionally only for some configs/seeds (e.g. ablations on a subset), with a launch `phase` and a `label` copied into every row (`subset_label`, e.g. "AW-Limrun-93 subset") |
| `envs` | env name → env hook file |
| `timeout_s` | agent wall-clock cap per task |
| `max_infra_attempts` | attempts per cell when the failure is infra (agent failures are never retried) |
| `order` | launch order, default `["phase", "seed", "config", "task"]` (phase 0 first, then complete seed 1 first) |
| `budget.max_usd` | **spend guard**: no new cell starts once ledger cost (all attempts, all sessions, BYOK included) + `reserve_per_inflight_usd` × (running + 1) would exceed it |
| `budget.openrouter_key_check`, `key_min_remaining_usd` | also stop when the OpenRouter key's `limit_remaining` (GET /api/v1/key, every 2 min) drops below the floor |

## Env hook (`envs/*.jsonc`)

| Key | Meaning |
|---|---|
| `cwd`, `python` | where and with which interpreter the harness runs (`python` relative to `cwd`; venv symlinks are not followed) |
| `command` | argv template. Placeholders: `{python} {serial} {out_dir} {task} {config} {config_path} {mobile_use_path} {mobile_use_sha} {seed} {timeout_s} {run_id} {env}` plus any extra field of the device line (e.g. `{console_port}`) |
| `result_file` | the harness's JSONL output (`{out_dir}/results.jsonl`); the last row for the task is used |
| `devices_file` | one device per line (serial, or a JSON object with `serial` + extra fields); re-read on every pass |
| `max_concurrency` | cap of running cells for this environment (also: one cell per device) |
| `quarantine_after_infra` | consecutive infra failures before a device is skipped for the rest of the session |
| `harness_overhead_s` | extra time on top of `timeout_s` before the harness process is killed |
| `env_vars` | added to the harness environment (e.g. `GRPC_VERBOSITY=ERROR`) |
| `adb_safety` | **mandatory**. How android_env's `adb kill-server` retries are kept off the shared adb server that carries the Limrun tunnels: `{"mode": "adbwrap", "path": <wrapper that drops kill-server>}`, `{"mode": "shim", "path": <controller that never calls it>}` (the file must mention `kill-server`), or `{"mode": "server_port", "port": <≠5037>}` (sets `ANDROID_ADB_SERVER_PORT` for the harness; the harness must then pass `--adb-port` to the agent runner). A hook without it is refused |

## Outputs (`out_dir/`)

- `results.jsonl`: **one final row per (task, config, seed, env)**. Written once; a cell with a
  final row is never run again (idempotent, resumable).
- `attempts.jsonl`: every attempt (same schema); the source of the spend ledger.
- `matrix_events.jsonl`: start/resume/stop, quarantines, key checks.
- `cells/<env>/<config>/s<seed>/<task>-<hash>/a<n>/`: the harness output of each attempt
  (`command.json`, `harness.log`, the harness's results file, agent `events.jsonl`/`result.json`).

Row fields: `key env task_set subset_label phase task config score score_raw episode_done
score_def seeding instance_seed expected_instance_seed protocol_reason config_path seed attempt outcome infra_reason status
score error error_kind final_answer cost_usd cost_source prompt_tokens completion_tokens llm_calls
agent_wall_s init_s cell_wall_s git_sha git_dirty expected_sha config_resolved_sha256 aw_sha
device harness_run_id harness_exit_code workarounds out_dir started_at ended_at`, and in
`results.jsonl` also `attempts attempt_outcomes total_cost_usd_all_attempts`.

**Official score (done-gate).** AndroidWorld's own runner counts a task only if the agent ended
the episode itself: `agent_successful = task_successful if interaction_results.done else 0.0`
(`suite_utils._run_task`, upstream @55ddaf5). The matrix applies the same rule to every row,
whatever the harness: `score` = official score, `score_raw` = the harness's `is_successful`,
`episode_done` = agent status `completed` or `ended_incomplete` (max_steps, timeout and errors
are not done), `score_def = "official_done_gated"`. A harness `official_score` field, if present,
is cross-checked (must agree). Rows written by c3f77e7 (before the gate) stored the raw score as
`score`; `status` and `rescore` re-apply the gate to them (`matrix.py rescore <spec>` writes
`results.official.jsonl`; the ledger is never rewritten).

**Study protocol (enforced).** Spec `protocol` = `{"seeding": "upstream_suite", "score_def":
"official_done_gated"}` (the only accepted values, also the default). Every scored harness row
must prove upstream suite seeding: `instance_seed` must equal `sha256(f"{seed}_{task}_0") %
2**32` (upstream `suite_utils._get_instance_seed`, i=0), and `seeding` must be absent,
`"official"` or `"upstream_suite"` (`"legacy"`/`"random"`/`"direct"` = direct `random.seed(seed)`,
P0-A's pilot). A harness-side official score (`official_score` or `score_official`) must agree with
the matrix's own done-gate. A violating row is `outcome = "protocol_rejected"` (with
`protocol_reason`): it is not a result, it is not retried, and it **halts its environment** for
the session (event `env_halted_protocol`); the cell stays pending and runs again once the harness
is fixed. Row fields: `seeding` (`"upstream_suite"` when verified), `instance_seed`,
`expected_instance_seed`, `score_def` (`"official_done_gated"`), `protocol_reason`.

**Several processes, one ledger.** Two matrix processes may share an `out_dir` (e.g. one per
environment, with disjoint cells): appends are flock-ed single lines and every read picks up the
other process's lines first, so the spend guard sees the total spend.

`outcome`:
- `success`: official score 1.0;
- `agent_failure`: the agent ran and the official score is < 1.0 (including agent `timeout`,
  `max_steps`, `ended_incomplete`);
- `infra_failure` (attempt) / `infra_exhausted` (final): harness init error, harness crash or
  timeout, no result row, evaluator exception, agent `infra_suspect` (OpenRouter error, device
  error, init error), or a SHA mismatch / dirty checkout. Retried up to `max_infra_attempts`,
  on another device when one is free.

`cost_usd` comes from the agent's metrics (true cost incl. BYOK), or, if the harness row has no
metrics, from the agent `events.jsonl` under the attempt directory.

## Cost estimate

```bash
uv run python benchmarks/matrix/estimate_cost.py <spec.jsonc> --profile '<glob of harness results.jsonl>'
```

Per config: mean per-agent tokens of measured runs × today's price of the endpoint each config
pins. Assumes every config has the measured token profile (only prices change), so it is
UNVERIFIED for configs that change behaviour; `status` reports the measured cost once cells ran.

## Harness row accepted

The harness row of P0-A's `run_agent.py` (agent `metrics` nested) or a flat row carrying the
matrix fields (`cost_usd`, `prompt_tokens`, `completion_tokens`, `llm_calls`, `agent_wall_s`).
Required in both: `task`, `status`, `score` (official evaluator), `git_sha`, `git_dirty`;
`infra_suspect: true` (or an infra status: `harness_init_error`, `harness_agent_crash`,
`init_error`, `rejected_sha`) for anything that is not the agent's fault; `score_error` if the
evaluator raised.
