# Ablation Study Setup for ICML 2026

## Overview

This document describes the ablation study infrastructure for measuring the contribution of each architectural innovation in mobile-use, demonstrating the path from 64% → 100% on AndroidWorld.

## Architecture

### Graph Structures

**A0 - MONOLITHIC Baseline (3 nodes):**
```
START → contextor → monolithic ─┬─[invoke_tools]→ tools ─┐
                                ├─[complete]───→ END      │
                                └─[continue]──────────────┴→ contextor
```

**A1+ - MULTI-AGENT Full System (8 nodes):**
```
START → planner → orchestrator → convergence ─┬─[continue]→ contextor → cortex
                                              ├─[replan]──→ planner
                                              └─[end]─────→ END

cortex ─┬─[review_subgoals]──→ orchestrator
        └─[execute_decisions]→ executor ─┬─[tools]→ executor_tools → summarizer
                                         └─[skip]─→ summarizer
                                                           ↓
                                                    convergence ←──┘
```

---

## Feature Toggles

| Toggle | Description | Impact |
|--------|-------------|--------|
| `use_multi_agent` | Multi-agent graph (6 agents) vs MonolithicNode | Architecture complexity |
| `use_sequential_execution` | Sequential abort-on-failure vs parallel tool execution | Reliability |
| `use_post_validation` | Verify text input results after typing | Text accuracy |
| `use_deterministic_text` | State machine (focus→clear→type→verify) vs simple tap+type | Text reliability |
| `use_vision` | Screenshots sent to Cortex LLM | Visual understanding |
| `use_meta_reasoning` | Agent thoughts injection in prompts | Context awareness |
| `use_scratchpad` | save_note/read_note/list_notes tools | Persistent memory |
| `use_video_recording` | Video recording tools | Complex UI understanding |
| `use_data_fidelity_prompts` | Data fidelity instructions in Cortex prompt | Accuracy |

---

## Ablation Matrix

| Branch | Config | Expected % | Features Added | Cumulative Features |
|--------|--------|------------|----------------|---------------------|
| `ablation/a0-baseline` | a0 | 64% | None | MONOLITHIC baseline |
| `ablation/a1-multi-agent` | a1 | 70% | +multi_agent | Multi-agent graph |
| `ablation/a2-sequential` | a2 | 76% | +sequential_execution, +post_validation | + Reliable execution |
| `ablation/a3-deterministic-text` | a3 | 79% | +deterministic_text | + Reliable text input |
| `ablation/a4-vision` | a4 | 81% | +vision | + Screenshot understanding |
| `ablation/a5-meta-reasoning` | a5 | 84% | +meta_reasoning | + Agent context |
| `ablation/a7-scratchpad` | a7 | 95% | +scratchpad | + Persistent memory |
| `ablation/a8-video-recording` | a8 | 97% | +video_recording | + Video understanding |
| `ablation/a9-final` | a9 | 100% | +data_fidelity_prompts | ALL FEATURES |

---

## Running Experiments

### Quick Setup

```bash
# Set ablation config (creates override file)
python scripts/run_ablation.py a0   # Baseline
python scripts/run_ablation.py a9   # Full system

# Run mobile-use with current config
uv run mobile-use "Your task here"

# Reset to full system (remove override)
python scripts/run_ablation.py --reset
```

### Validate All Configs

```bash
python scripts/test_ablation_configs.py
```

### Run AndroidWorld Benchmark

```bash
# For each configuration:
python scripts/run_ablation.py a0
# Run AndroidWorld benchmark suite
# Record results

python scripts/run_ablation.py a1
# Run AndroidWorld benchmark suite
# Record results

# ... repeat for a2-a9
```

---

## File Structure

```
mobile-use/
├── ablation-config.defaults.jsonc          # Default config (all enabled)
├── ablation-config.override.jsonc          # Active override (gitignored)
├── ablation-configs/                       # Experiment configurations
│   ├── a0-baseline.jsonc
│   ├── a1-multi-agent.jsonc
│   ├── a2-sequential-execution.jsonc
│   ├── a3-deterministic-text.jsonc
│   ├── a4-vision.jsonc
│   ├── a5-meta-reasoning.jsonc
│   ├── a7-scratchpad.jsonc
│   ├── a8-video-recording.jsonc
│   └── a9-final.jsonc
├── scripts/
│   ├── run_ablation.py                     # Set config helper
│   └── test_ablation_configs.py            # Validate configs
└── minitap/mobile_use/
    ├── config.py                           # AblationConfig class
    ├── context.py                          # MobileUseContext with ablation
    ├── graph/graph.py                      # Conditional graph building
    └── agents/monolithic/                  # Baseline single-agent
```

---

## Key Implementation Details

### Config Loading Priority

1. `ablation-config.override.jsonc` (if exists)
2. `ablation-config.defaults.jsonc` (fallback)

### Log Indicators

| Feature State | Log Message |
|---------------|-------------|
| Monolithic mode | `Building MONOLITHIC graph (ablation baseline mode)` |
| Multi-agent mode | `Building MULTI-AGENT graph (full system)` |
| Vision disabled | `Vision DISABLED (ablation mode) - screenshot not sent to LLM` |
| Meta-reasoning disabled | `Meta-reasoning DISABLED (ablation mode) - skipping agent thoughts` |
| Parallel execution | `Running tools in PARALLEL mode (ablation baseline)` |
| All features enabled | `✓ Ablation config: All features enabled (full system)` |
| N features disabled | `⚠ Ablation mode: N features DISABLED: [list]` |

---

## Branch Strategy

Each ablation configuration has a dedicated branch for reproducibility:

```
feature/ablation-system          # Main development branch
  ├── ablation/a0-baseline       # Monolithic baseline
  ├── ablation/a1-multi-agent    # +Multi-agent
  ├── ablation/a2-sequential     # +Sequential execution
  ├── ablation/a3-deterministic-text
  ├── ablation/a4-vision
  ├── ablation/a5-meta-reasoning
  ├── ablation/a7-scratchpad
  ├── ablation/a8-video-recording
  └── ablation/a9-final          # Full system (100%)
```

---

## Expected Results Chart

```
Performance (%)
100 ┤                                                    ████ a9 (100%)
 97 ┤                                              ████ a8
 95 ┤                                        ████ a7
 84 ┤                                  ████ a5
 81 ┤                            ████ a4
 79 ┤                      ████ a3
 76 ┤                ████ a2
 70 ┤          ████ a1
 64 ┤    ████ a0
    └────────────────────────────────────────────────────────
         Baseline → Multi-agent → Execution → Text → Vision → Reasoning → Memory → Video → Prompts
```

---

## Notes

- The `launch_app` tool has a temperature bug with certain fallback models - tasks complete via tap fallback
- Monolithic baseline uses explicit `task_complete` tool for termination
- Video analyzer must be configured in llm-config for a8 to have full effect
