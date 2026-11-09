# Harness interface: AndroidWorld harness (P0-A) ⇄ mobile-use paper branch (P0-E)

Branch `paper/androidworld-rework`. Every run of the study uses **one commit of this branch**;
the experimental condition is selected **only** by the config file.

## Version to run

- Pin the SHA published in the P0-E report (Notion "P0-E - mobile-use paper branch (worker
  report)"); it is the head of the branch when this file was last updated. A file cannot name
  the commit that contains it, so the SHA lives in the report, and every run records
  `git_sha` + `git_dirty` in `run_start` and `result.json`. **Reject results with
  `git_dirty: true` or a different `git_sha`.**
- Since the first pin: paper-era bugs A10 (resource-id lookup / bounds / missing await: the
  text read-back now works on Android) and A11 (swipe default duration) are fixed for every
  condition; each model is pinned to one OpenRouter endpoint with no provider fallback
  (`benchmarks/README.md`, "Models and pinned providers"). `v1-as-shipped.jsonc` restores the
  A10/A11 bugs through the opt-in flag `legacy_v1_android_bugs` (one extra row).

## Entry point

```python
from minitap.mobile_use.benchmark.runner import run_task

result: dict = await run_task(
    goal,                     # str: the AndroidWorld task goal, verbatim (task.goal)
    serial,                   # str: adb serial, e.g. "127.0.0.1:53076" (Limrun tunnel) or "emulator-5554"
    config_path,              # str | Path: benchmarks/configs/<condition>.jsonc
    out_dir,                  # str | Path: one directory per (run, task, attempt), created if needed
    *,
    adb_host="127.0.0.1",     # adb server that knows `serial`
    adb_port=5037,
    task_name=None,           # e.g. "ContactsAddContact"; recorded, used as trace name
    answer_required=False,    # True for information-retrieval tasks (see below)
    max_steps=None,           # default: config agent.max_steps (400 = paper)
    timeout_s=None,           # default: config agent.timeout_s (null = none); wall-clock cap
    run_id=None,              # harness-side id (e.g. "<run>-<task>-<seed>"); uuid4 if None
    metadata=None,            # dict copied into the run_start event (seed, task params, AW SHA...)
)
```

CLI equivalent (prints the same dict as one JSON line on stdout, and writes it to
`out_dir/result.json`):

```bash
set -a; source ~/.opencode-creds/openrouter-paper.env; set +a   # OPENROUTER_API_KEY, never printed
uv run python -m minitap.mobile_use.benchmark.runner \
  --goal "<goal>" --serial 127.0.0.1:53076 --config benchmarks/configs/full.jsonc \
  --out runs/<run_id>/<task> --task-name <TaskName> [--answer-required] [--timeout-s 1800]
```

Rules:
- **One task at a time per process** (a second concurrent `run_task` in the same process raises).
  Run N devices with N processes. Sequential tasks in one process are fine.
- `run_task` does **not** reset the device. The harness owns task setup/teardown
  (`task.initialize_task(env)` before, `task.tear_down(env)` after), as with any AndroidWorld agent.
- `run_task` **never raises for task-level problems**: it returns a status. It raises only for
  harness bugs (bad config path/file, missing `OPENROUTER_API_KEY`).
- Telemetry is forced off; no call goes to the (shut down) Minitap platform.

## Result

```jsonc
{
  "run_id": "…", "task_name": "…", "goal": "…",
  "status": "completed",        // see table below
  "final_answer": "15",         // str | null (see "Answers")
  "error": null, "error_kind": null,   // error_kind: llm_api | device | agent | timeout | max_steps
  "infra_suspect": false,       // true => candidate for re-queue (init_error, llm_api, device)
  "subgoal_plan": [{"id","description","status","completion_reason"}],
  "last_thought": "…",
  "config_name": "full", "config_resolved_sha256": "…",
  "git_sha": "…", "git_dirty": false,
  "started_at": "…", "ended_at": "…",
  "metrics": {
    "wall_clock_s": 171.1, "graph_node_runs": 49, "cortex_turns": 9, "agent_thoughts": 41,
    "llm":   {"calls_by_agent", "errors_by_agent", "prompt_tokens_by_agent", "completion_tokens_by_agent",
              "cost_usd_by_agent", "latency_s_by_agent", "resolved_models_by_agent",
              "resolved_providers_by_agent", "total_calls", "total_prompt_tokens",
              "total_completion_tokens", "total_cost_usd", "calls_without_cost", "byok_calls",
              "fallback_attempts", "fallback_blocked"},
    "tools": {"calls_by_tool", "failures_by_tool", "total_calls"},
    "nodes": {"planner": 1, "cortex": 9, …},
    "loop_detector": {"triggers_by_kind", "forced_replans"},
    "text_check": {"MATCH": 1, …}
  },
  "events_path": "<out_dir>/events.jsonl"
}
```

| status | meaning | harness action (proposal) |
|---|---|---|
| `completed` | graph ended, every subgoal SUCCESS | score with the AndroidWorld evaluator |
| `ended_incomplete` | graph ended without all subgoals SUCCESS | score (the agent stopped) |
| `max_steps` | LangGraph recursion limit (`max_steps`) hit | score (agent failure) |
| `timeout` | `timeout_s` wall-clock cap hit | score (agent failure); report the rate |
| `error` + `error_kind=agent` | exception inside the agent code | score as failure; report |
| `error` + `error_kind=llm_api` | OpenRouter error after retries (model and provider fallbacks are disabled; a pinned endpoint being down lands here) | infra: re-queue, log |
| `error` + `error_kind=device` | adb / uiautomator2 error | infra: re-queue, log |
| `init_error` | agent could not attach to the device | infra: re-queue, log |

**Scoring is never done here.** `status` says how the agent run ended, not whether the task
succeeded. Always score with the official evaluator (`task.is_successful(env)`).

## Answers (information-retrieval tasks)

For AndroidWorld tasks that expect an answer, pass `answer_required=True`. The agent then ends
with the Outputter producing `{"answer": "<string>"}` (schema `BenchmarkAnswer`, model =
config `llm.utils.outputter`), returned as `final_answer`. The harness hands it to AndroidWorld
the way the official agents do, i.e. as the final `answer` action / interaction cache, e.g.

```python
env.interaction_cache = result["final_answer"] or ""
success = task.is_successful(env)
```

(The January runner did the same: "the agent's final answer is sent as an `answer` action",
local/archaeology/aw-fork-modifications.md.) With `answer_required=False`, `final_answer` is the
last agent thought (free text, informational only).

## Files written in `out_dir`

- `events.jsonl`: one JSON object per line, schema below.
- `result.json`: the dict above.
- `traces/` only if the config sets `agent.record_trace: true` (GIF + steps per task).

### events.jsonl schema (version 1)

Common fields: `schema` (1), `run_id`, `seq` (1..n), `ts` (UTC ISO), `t_rel_s` (since run
start, monotonic), `type`. Strings longer than 4000 chars are truncated (marked).

| type | fields |
|---|---|
| `run_start` | goal, task_name, serial, adb_server, answer_required, max_steps, timeout_s, config_name, config_files [{path, sha256}], config_resolved_sha256, config_resolved (full resolved config), openrouter_key_source, code {git_sha, git_branch, git_dirty, python, platform, packages}, metadata |
| `node` | node (LangGraph node that just ran: planner, orchestrator, contextor, cortex, executor, executor_tools, summarizer, convergence) |
| `llm_call` | agent, requested_model, provider_kind, is_fallback, status (ok/error), resolved_model, resolved_provider, generation_id, prompt_tokens, completion_tokens, reasoning_tokens, cached_tokens, cost_usd, openrouter_cost_usd, upstream_cost_usd, is_byok, finish_reason, latency_s, error |
| `llm_fallback` | blocked (true in benchmark configs), reason |
| `tool_call` | tool, args (minus injected state), status (success/error), latency_s, output |
| `loop_detector` | kind (repeat/no_change/cycle), action (inject/replan), evidence, turn, subgoal, details (state/action hashes, counts) |
| `text_check` | verdict (MATCH/CONTAINS/CASE_ONLY/MISMATCH/UNVERIFIABLE), expected, actual, expected_normalized, actual_normalized, match, readback_method, focus_method, target_resource_id, marked_as_error |
| `error` / `warning` | phase (init/task/clean), error, traceback |
| `run_end` | the result dict (minus events_path) |

Notes:
- `cost_usd` = OpenRouter credits + upstream provider cost when the call used a BYOK key
  (`is_byok`). `latency_s` includes HTTP retries of the same model (`llm_policy.max_retries`).
- `generation_id` can be looked up later on OpenRouter (`GET /api/v1/generation?id=`).

## Device requirements

Any adb-reachable Android device: Limrun tunnel serial (`lim android connect --id <id>` →
`127.0.0.1:<port>`) or an emulator serial. The agent uses uiautomator2 (installs its helper APK
on first connect) and `adb shell`. Root, emulator console and gRPC are not needed by the agent
(AndroidWorld itself may need them, see 04 - Audit B). The video tools (configs with
`use_video_recording`) need `ffmpeg` on the harness machine.
