# Benchmarks: AndroidWorld paper rework (branch `paper/androidworld-rework`)

This branch is the **agent under test** for the new runs of arXiv 2602.07787. It is
`origin/ablation/a9-final` (the January 2026 full system with ablation toggles, based on
v3.4.0) plus a measurement layer and two flag-gated mechanisms. Every condition runs on the
same commit; a condition is a file in `benchmarks/configs/`.

- Harness contract: [HARNESS_INTERFACE.md](HARNESS_INTERFACE.md)
- Model check: `uv run python benchmarks/smoke_models.py` (one real call per model id and
  capability; last result in `smoke_models.last.json`)

## What differs from the January 2026 code

| Change | Default | Where |
|---|---|---|
| Ablation config selectable by file (`run_task(config_path=…)`, or env `MOBILE_USE_ABLATION_CONFIG`); unknown flag names rejected | n/a | `config.py`, `sdk/agent.py` |
| OpenRouter client records resolved model, upstream provider, tokens, cost (incl. BYOK upstream cost); non-streamed calls in benchmark mode | benchmark only | `services/llm.py`, `benchmark/llm_callback.py` |
| Fallback models disabled in benchmark mode (each attempt logged, then the task errors with `error_kind=llm_api`) | benchmark only | `services/llm.py::with_fallback` |
| `use_loop_detector`: deterministic loop detector | **off** (on in `full.jsonc`) | `benchmark/loop_detector.py`, `agents/cortex/cortex.py`, `graph/graph.py` |
| `use_text_match_check`: MATCH/MISMATCH verdict after `focus_and_input_text` | **off** (on in `full.jsonc`) | `benchmark/text_check.py`, `tools/mobile/focus_and_input_text.py` |
| Per-task JSONL (LLM calls, tool calls, nodes, detector, validator) + `result.json` | benchmark only | `benchmark/runtime.py`, `benchmark/runner.py` |
| Trace screenshots: nanosecond, collision-checked file names (was `int(time.time())`, same-second overwrites) | always | `utils/recorder.py` |
| Trace folder suffix `_NO_ERROR`/`_ERROR` (was `_PASS`/`_FAIL`, which only meant "no exception", audit A7) | always | `sdk/agent.py` |
| Telemetry forced off | benchmark only | `benchmark/runner.py` |

Unchanged on purpose (kept identical to January for comparability, documented):
- **A9**: operator-precedence bug in the Cortex device/focused-app message (`cortex.py`, comment
  at the message construction). The Cortex receives device info + date, never the focused app.
- **A10**: `utils.ui_hierarchy.find_element_by_resource_id` matches the Maestro key
  `resourceId`, but the UIAutomator2 client emits `resource-id`, so on Android it **never
  matches**: focusing by resource-id always falls back to bounds/coordinates, and the
  post-validation read-back of `focus_and_input_text` / `focus_and_clear_text` is always empty.
  Present since 730e4d7 (2025-11-26), so in every paper run. The new text check uses its own
  lookup and is not affected. Fixing the helper is an open decision.
- **A11**: `swipe_coordinates` / `swipe_percentages` declare `duration: int = Field(default=400)`
  in the tool signature; when the model omits `duration`, the tool receives the `FieldInfo` and
  fails validation ("Input should be a valid integer"). Present at v3.4.0 and on today's main.
  The agent usually retries with an explicit duration. Fixing it is an open decision.
- Temperatures as in code: Cortex/Orchestrator/Outputter/Planner/Executor/Contextor 1,
  Hopper 0, Video analyzer 0.2 (`get_llm` default is 1).

## Flags

| Flag | Effect when false |
|---|---|
| `use_multi_agent` | monolithic single agent (Cortex model) instead of the 6-agent graph |
| `use_sequential_execution` | tool calls run in parallel, no abort-on-failure |
| `use_post_validation` | no read-back after text input (see A10: the read-back was already empty on Android) |
| `use_deterministic_text` | simple tap + type instead of focus → cursor-to-end → type |
| `use_vision` | no screenshot to the Cortex (text-only) |
| `use_meta_reasoning` | no agent-thought history in the Cortex context, no self-monitoring prompt rules |
| `use_scratchpad` | no save/read/list note tools |
| `use_video_recording` | no start/stop video recording tools (+ video analyzer) |
| `use_data_fidelity_prompts` | no data-fidelity section in the Cortex prompt |
| `use_loop_detector` | (new) no deterministic loop detector |
| `use_text_match_check` | (new) no MATCH/MISMATCH verdict after text input |

## Conditions (`benchmarks/configs/`)

| File | Plan item | Flags off | Routing |
|---|---|---|---|
| `full.jsonc` | P2 headline, P3 #2 | none | Platform Default |
| `full-jan2026.jsonc` | parity with Jan 2026 | loop_detector, text_match_check | Platform Default |
| `full-all-frontier.jsonc` | P3 #3 | none | frontier model on all 7 agents |
| `a0-single-agent.jsonc` | P3 #1 | all (a0 flags) | Cortex model of Platform Default |
| `no-post-validation.jsonc` | P3 #4 | post_validation, text_match_check | Platform Default |
| `no-meta-reasoning.jsonc` | P3 #5 | meta_reasoning, loop_detector | Platform Default |
| `cortex-budget.jsonc` | P3 #6 | none | Platform Default, Cortex = Qwen3-VL-8B |
| `planner-budget.jsonc` | P3 #7a | none | All Frontier, Planner = Qwen3-VL-8B |
| `noncortex-budget.jsonc` | P3 #7b | none | frontier Cortex, Qwen3-VL-8B elsewhere |
| `no-data-fidelity.jsonc` | stretch | data_fidelity_prompts | Platform Default |
| `no-video.jsonc` | stretch | video_recording | Platform Default |
| `routing/*.jsonc` | paper Table 4 rows | none | Gemini 2.5 Pro / Qwen3-VL-8B / GPT-4o / Gemini 2.5 Flash as in the paper |

Files starting with `_` are bases (`extends`). The resolved config and its SHA-256 are written
into every `run_start` event and `result.json`.

## Loop detector (`use_loop_detector`)

At each Cortex turn the detector closes one transition (screen before, executed action, screen
after). Screen = hash of the focused app + every UI element's resource-id, class, text,
content-desc, checked/selected/focused/enabled, package (System UI dropped, `hh:mm` strings
masked, bounds ignored). Action = hash of the Executor's tool calls (name + args, minus
`agent_thought`). Triggers, thresholds in the config:

| Trigger | Rule (defaults) |
|---|---|
| `repeat` | same (screen, action) ≥ 3 times in the last 12 transitions |
| `no_change` | 3 consecutive UI actions left the screen unchanged (note/wait tools excluded) |
| `cycle` | the last 8 transitions visited ≤ 2 distinct screens |

After a trigger: cooldown of 3 transitions. On trigger the Cortex gets an extra message
"⚠️ LOOP DETECTED (deterministic …) Kind … Evidence … change strategy", and the evidence is
added to the agent thoughts. After 2 triggers without reaching a never-seen screen, the current
subgoal is marked FAILED with the evidence as reason and the graph goes straight to the Planner
(replan). Multi-agent graph only. Every trigger is a `loop_detector` event.

## Text match check (`use_text_match_check`)

After `focus_and_input_text` succeeds, the field is read back (by resource-id, both hierarchy
formats; else the focused text field) and compared with the intended text after normalization
(NFKC, zero-width removed, NBSP → space, whitespace runs collapsed, trimmed). Verdicts: MATCH,
CONTAINS (intended text plus other content), CASE_ONLY, MISMATCH, UNVERIFIABLE (no field /
password). The verdict line is appended to the tool result the Cortex reads. With
`text_check.mismatch_as_error: true`, MISMATCH/CASE_ONLY also mark the tool call failed
(default false). Every check is a `text_check` event.

## Pending decisions (model ids, 2026-11-09)

| Paper id | Status on OpenRouter | Used now | Alternatives |
|---|---|---|---|
| `google/gemini-3-pro-preview` (Cortex; all agents in All Frontier) | **404, "no longer available"** | `google/gemini-3.1-pro-preview` | `google/gemini-2.5-pro` (paper fallback) |
| `meta-llama/llama-3.1-70b-instruct` (Executor) | listed, single endpoint (Bedrock) with **no tool calling and no response_format** → 404 for the Executor | `meta-llama/llama-3.3-70b-instruct` | `openai/gpt-5-mini` (paper fallback) |

All other ids of the configs resolve and pass a capability call (see `smoke_models.last.json`).
