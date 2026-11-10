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

Paper-era bugs **fixed** on this branch (decided 2026-11-09; they apply to every condition,
including `full-jan2026.jsonc`, which is therefore "January feature set + these fixes"; the
opt-in flag `legacy_v1_android_bugs` restores them, used only by `v1-as-shipped.jsonc`):
- **A10, post-validation was inert on Android.** Since the UIAutomator2 client became the
  Android screen source (730e4d7, 2025-11-26, i.e. in every paper run), the resource-id path
  could not work:
  1. `utils.ui_hierarchy.find_element_by_resource_id` matched only the Maestro key
     `resourceId`, never the `resource-id` key UIAutomator2 emits, so the post-validation
     read-back of `focus_and_input_text` / `focus_and_clear_text` was always empty and focusing
     by resource-id always fell back to coordinates;
  2. the same helper re-initialised its index counter at every match, so
     `resource_id_index >= 1` never matched;
  3. `get_bounds_for_element` parsed only the Maestro dict, not UIAutomator2's
     `"[x1,y1][x2,y2]"` string (the "move cursor to end" tap was skipped);
  4. `tools/utils.focus_element_if_needed` called the async `tap()` without `await` on the
     resource-id branch, so that tap never happened.
  All four are fixed (comments tagged `audit A10`), with regression tests
  (`tests/mobile_use/benchmark/test_paper_era_fixes.py`). The v1 paper's validator therefore
  never compared or even saw the typed text on Android.
- **A11, swipes failed when the model omitted `duration`.** `swipe_coordinates` /
  `swipe_percentages` declared `duration: int = Field(default=400)` in the tool signature, so an
  omitted duration reached the tool as a `FieldInfo` and failed validation. Now
  `Annotated[int, Field(...)] = 400`, with a regression test.

Unchanged on purpose (kept identical to January for comparability, documented):
- **A9**: operator-precedence bug in the Cortex device/focused-app message (`cortex.py`, comment
  at the message construction). The Cortex receives device info + date, never the focused app.
- Temperatures as in code: Cortex/Orchestrator/Outputter/Planner/Executor/Contextor 1,
  Hopper 0, Video analyzer 0.2 (`get_llm` default is 1).

## Flags

| Flag | Effect when false |
|---|---|
| `use_multi_agent` | monolithic single agent (Cortex model) instead of the 6-agent graph |
| `use_sequential_execution` | tool calls run in parallel, no abort-on-failure |
| `use_post_validation` | no read-back after text input (on Android the read-back only works since the A10 fix; it was always empty in January) |
| `use_deterministic_text` | simple tap + type instead of focus → cursor-to-end → type |
| `use_vision` | no screenshot to the Cortex (text-only) |
| `use_meta_reasoning` | no agent-thought history in the Cortex context, no self-monitoring prompt rules |
| `use_scratchpad` | no save/read/list note tools |
| `use_video_recording` | no start/stop video recording tools (+ video analyzer) |
| `use_data_fidelity_prompts` | no data-fidelity section in the Cortex prompt |
| `use_loop_detector` | (new) no deterministic loop detector |
| `use_text_match_check` | (new) no MATCH/MISMATCH verdict after text input |
| `legacy_v1_android_bugs` | (new, opt-in, default **false**) when **true**, restores the v1 Android bugs A10 (resource-id lookup and bounds parsing that never match UIAutomator2 elements, never-awaited focus tap) and A11 (swipe fails when `duration` is omitted). The tool schemas the LLM sees are identical either way. |

## Conditions (`benchmarks/configs/`)

| File | Plan item | Flags off | Routing |
|---|---|---|---|
| `full.jsonc` | P2 headline, P3 #2 | none | Platform Default |
| `full-jan2026.jsonc` | reference row: January features + A10/A11 fixes | loop_detector, text_match_check | Platform Default |
| `v1-as-shipped.jsonc` | extra row: what v1 actually did | as full-jan2026, plus `legacy_v1_android_bugs: true` | Platform Default (January models unavailable) |
| `full-all-frontier.jsonc` | P3 #3 | none | frontier model on all 7 agents |
| `a0-single-agent.jsonc` | P3 #1 | all (a0 flags) | Cortex model of Platform Default |
| `no-post-validation.jsonc` | P3 #4 | post_validation, text_match_check | Platform Default |
| `no-meta-reasoning.jsonc` | P3 #5 | meta_reasoning, loop_detector | Platform Default |
| `cortex-budget.jsonc` | P3 #6 | none | Platform Default, Cortex = Qwen3-VL-8B |
| `planner-budget.jsonc` | P3 #7a | none | All Frontier, Planner = Qwen3-VL-8B |
| `noncortex-budget.jsonc` | P3 #7b | none | frontier Cortex, Qwen3-VL-8B elsewhere |
| `no-data-fidelity.jsonc` | Table 2 | data_fidelity_prompts | Platform Default |
| `no-loop-detector.jsonc` | Table 2 (leave-one-out) | loop_detector | Platform Default |
| `no-text-match-check.jsonc` | Table 2 (leave-one-out) | text_match_check | Platform Default |
| `no-sequential-execution.jsonc` | Table 2 "Sequential execution" | sequential_execution | Platform Default |
| `no-hybrid-perception.jsonc` | Table 2 "Hybrid perception" | vision (text-only) | Platform Default |
| `no-scratchpad.jsonc` | Table 2 "Scratchpad memory" | scratchpad | Platform Default |
| `decomposition-only.jsonc` | WMAC: what decomposition adds | multi_agent only (monolithic agent, every other mechanism on; the loop detector is inert there because it lives in the multi-agent Cortex) | Platform Default; Cortex `require_parameters: false` (the monolithic agent sends `parallel_tool_calls`) |
| `no-video.jsonc` | stretch | video_recording | Platform Default |
| `routing/*.jsonc` | **not used in the paper** (v1 Table 4 rows on Gemini 2.5 Pro, kept for reference; each has `paper_reference: "NOT USED IN THE PAPER …"`) | none | Gemini 2.5 Pro / Qwen3-VL-8B / GPT-4o / Gemini 2.5 Flash |

Table 2 row **"UIAutomator2 → Maestro" is dropped**: no flag can switch the Android screen source
back to Maestro on this branch: the UIAutomator2 client arrived in 730e4d7 (2025-11-26) and the
Maestro code paths were removed from the controllers on 2025-12-03 (7dd6354, eb8b899, d56698d),
so the row can't be re-measured.

`tests/mobile_use/benchmark/test_config_diffs.py` checks that every runnable config differs from
`full.jsonc` by exactly the flags (and, for routing rows, only the models) listed for it, and
`test_full_unchanged.py` proves the `full.jsonc` system is frozen since 4fe7ea4.

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

## Models and pinned providers (decided 2026-11-09)

Substitutions vs. the paper:

| Paper id | Status on OpenRouter (2026-11-09) | Used |
|---|---|---|
| `google/gemini-3-pro-preview` (Cortex; all agents in All Frontier) | 404 "no longer available" | `google/gemini-3.1-pro-preview` |
| `meta-llama/llama-3.1-70b-instruct` (Executor) | single endpoint (Bedrock) without tool calling or response_format | `meta-llama/llama-3.3-70b-instruct` |

Each model is pinned to exactly one OpenRouter endpoint, with no provider fallback
(`llm_policy.openrouter_provider_by_model` in `_base.jsonc`:
`{"order": ["<endpoint tag>"], "allow_fallbacks": false}`), except gpt-oss-120b, which has an
ordered list of two same-precision endpoints with the fallback restricted to that list
(`"only"` = `"order"`, `"allow_fallbacks": true`). A test checks that every model of every config
is pinned this way. Selection rule: unquantized (bf16/fp16) or fp8 weights, the endpoint
supports what the role sends, best 1-day uptime on the OpenRouter endpoints API (2026-11-09):

| Model | Pinned endpoint | Why |
|---|---|---|
| google/gemini-3.1-pro-preview | `google-vertex/global` | 99.93 % 1d (AI Studio 98.9 %, flex tier down) |
| google/gemini-3-flash-preview | `google-vertex/global` | same provider as the Cortex, 100 % 1d |
| meta-llama/llama-4-scout | `deepinfra/fp8` | fp8, json_schema, 100 % 1d; other endpoint (Vertex) publishes no quantization/uptime |
| openai/gpt-oss-120b | `crusoe/bf16`, then `dekallm/bf16` (fallback restricted to these two with `only`) | bf16 (most endpoints serve MXFP4), tools + json_schema; Crusoe 100 % 1d, DekaLLM 99.79 % 1d (2026-11-10). Was `deepinfra/bf16` until 2026-11-10 (no DeepInfra BYOK key); burst test: 30 concurrent Orchestrator calls x6 on Crusoe, 0 errors, 0 HTTP 429, p50 2-3 s |
| meta-llama/llama-3.3-70b-instruct | `coreweave/fp16` | no bf16 endpoint exists; unquantized fp16 with tool calling, 100 % 1d |
| meta-llama/llama-3.1-8b-instruct | `coreweave/bf16` | only bf16 endpoint and only one with json_schema, 100 % 1d |
| openai/gpt-5-nano, openai/gpt-4o | `openai` | first party (billed via the account's BYOK OpenAI key) |
| qwen/qwen3-vl-8b-instruct | `parasail/bf16` | only endpoint |
| google/gemini-2.5-pro, google/gemini-2.5-flash | `google-ai-studio` | only provider (standard tier) |

A wrong tag fails loudly (checked: `deepinfra/fp4` for gpt-oss-120b returns 404 "Every
candidate endpoint was removed during routing"). The served provider of every call is logged
(`resolved_provider`). If a pinned endpoint goes down, tasks end with `error_kind=llm_api`
(infra, re-queue) instead of silently changing provider.
