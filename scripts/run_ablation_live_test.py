#!/usr/bin/env python3
"""
Live Ablation Test Runner

Runs a simple mobile-use task with each ablation configuration to verify
the ablation system works correctly on a real device.

Usage:
    python scripts/run_ablation_live_test.py
    python scripts/run_ablation_live_test.py --config a0  # Test specific config
    python scripts/run_ablation_live_test.py --task "Open the calculator app"
"""

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Root directory of mobile-use
PROJECT_ROOT = Path(__file__).parent.parent
ABLATION_CONFIGS_DIR = PROJECT_ROOT / "ablation-configs"
OVERRIDE_FILE = PROJECT_ROOT / "ablation-config.override.jsonc"

ABLATION_EXPERIMENTS = [
    ("a0", "a0-baseline.jsonc", "64%", "Baseline (MONOLITHIC)"),
    ("a1", "a1-multi-agent.jsonc", "70%", "+Multi-agent"),
    ("a2", "a2-sequential-validation.jsonc", "76%", "+Sequential"),
    ("a3", "a3-deterministic-text.jsonc", "79%", "+Deterministic text"),
    ("a4", "a4-vision.jsonc", "81%", "+Vision"),
    ("a5", "a5-meta-reasoning.jsonc", "84%", "+Meta-reasoning"),
    ("a7", "a7-scratchpad.jsonc", "95%", "+Scratchpad"),
    ("a8", "a8-video.jsonc", "97%", "+Video"),
    ("a9", "a9-final.jsonc", "100%", "Full system"),
]

DEFAULT_TASK = "Open the Settings app and tell me what you see"


def set_ablation_config(config_file: str) -> bool:
    """Set the ablation config override file."""
    source = ABLATION_CONFIGS_DIR / config_file
    if not source.exists():
        return False
    shutil.copy(source, OVERRIDE_FILE)
    return True


def remove_ablation_config():
    """Remove the override file."""
    if OVERRIDE_FILE.exists():
        OVERRIDE_FILE.unlink()


def run_mobile_use_task(task: str, config_key: str, timeout: int = 120) -> tuple[bool, str]:
    """
    Run a mobile-use task and capture output.
    
    Returns:
        (success, output_log)
    """
    cmd = [
        "uv", "run", "mobile-use",
        task,
        "--test-name", f"ablation-test-{config_key}",
    ]
    
    print(f"\n{'='*60}")
    print(f"Running: {' '.join(cmd[:4])}...")
    print(f"{'='*60}\n")
    
    try:
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout + "\n" + result.stderr
        success = result.returncode == 0
        return success, output
    except subprocess.TimeoutExpired:
        return False, f"Task timed out after {timeout} seconds"
    except Exception as e:
        return False, f"Error running task: {str(e)}"


def extract_ablation_info(output: str) -> dict:
    """Extract ablation-related info from the output."""
    info = {
        "graph_type": "unknown",
        "vision_mode": "unknown",
        "features_disabled": [],
    }
    
    if "MONOLITHIC graph" in output:
        info["graph_type"] = "MONOLITHIC"
    elif "MULTI-AGENT graph" in output:
        info["graph_type"] = "MULTI-AGENT"
    
    if "Vision DISABLED" in output or "TEXT-ONLY mode" in output:
        info["vision_mode"] = "DISABLED"
    elif "use_vision" in output:
        info["vision_mode"] = "ENABLED"
    
    if "Meta-reasoning DISABLED" in output:
        info["features_disabled"].append("meta_reasoning")
    if "PARALLEL mode" in output:
        info["features_disabled"].append("sequential_execution")
    if "SIMPLE text input" in output:
        info["features_disabled"].append("deterministic_text")
    
    return info


def run_single_test(config_key: str, config_file: str, description: str, task: str, timeout: int):
    """Run a single ablation test."""
    print(f"\n{'#'*70}")
    print(f"# ABLATION TEST: {config_key} - {description}")
    print(f"{'#'*70}")
    
    # Set the config
    if not set_ablation_config(config_file):
        print(f"ERROR: Could not set config {config_file}")
        return False, {}
    
    print(f"Config file: {OVERRIDE_FILE}")
    print(f"Task: {task}")
    
    # Run the task
    success, output = run_mobile_use_task(task, config_key, timeout)
    
    # Extract info
    info = extract_ablation_info(output)
    
    # Print relevant log excerpts
    print(f"\n--- Log Excerpts (showing ablation behavior) ---")
    
    lines = output.split('\n')
    relevant_keywords = [
        "MONOLITHIC", "MULTI-AGENT", "ablation",
        "Vision DISABLED", "Vision ENABLED",
        "Meta-reasoning DISABLED", "agent thoughts",
        "PARALLEL mode", "sequential",
        "SIMPLE text input", "deterministic",
        "scratchpad", "Starting", "Agent",
        "Graph type", "Building"
    ]
    
    shown_lines = set()
    for i, line in enumerate(lines):
        if any(kw.lower() in line.lower() for kw in relevant_keywords):
            # Show context (line before and after)
            for j in range(max(0, i-1), min(len(lines), i+2)):
                if j not in shown_lines and lines[j].strip():
                    print(lines[j])
                    shown_lines.add(j)
    
    if not shown_lines:
        # Show first 30 lines if no relevant lines found
        print("(No ablation-specific logs found, showing first 30 lines)")
        for line in lines[:30]:
            if line.strip():
                print(line)
    
    print(f"\n--- Result ---")
    print(f"Success: {success}")
    print(f"Detected graph type: {info['graph_type']}")
    print(f"Vision mode: {info['vision_mode']}")
    if info['features_disabled']:
        print(f"Disabled features detected: {info['features_disabled']}")
    
    return success, info


def main():
    parser = argparse.ArgumentParser(description="Run live ablation tests")
    parser.add_argument(
        "--config", "-c",
        type=str,
        choices=[e[0] for e in ABLATION_EXPERIMENTS],
        help="Test a specific config only"
    )
    parser.add_argument(
        "--task", "-t",
        type=str,
        default=DEFAULT_TASK,
        help=f"Task to run (default: '{DEFAULT_TASK}')"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Timeout per task in seconds (default: 120)"
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Run all configs (warning: takes a long time)"
    )
    
    args = parser.parse_args()
    
    # Determine which configs to test
    if args.config:
        configs_to_test = [(e[0], e[1], e[2], e[3]) for e in ABLATION_EXPERIMENTS if e[0] == args.config]
    elif args.all:
        configs_to_test = ABLATION_EXPERIMENTS
    else:
        # Default: test a0 (baseline) and a9 (full) to show the difference
        configs_to_test = [
            ABLATION_EXPERIMENTS[0],  # a0 - baseline
            ABLATION_EXPERIMENTS[-1],  # a9 - full
        ]
        print("Running quick test with a0 (baseline) and a9 (full system).")
        print("Use --all to test all 9 configurations.")
    
    print(f"\n{'='*70}")
    print("ABLATION LIVE TEST SUITE")
    print(f"{'='*70}")
    print(f"Task: {args.task}")
    print(f"Timeout: {args.timeout}s per config")
    print(f"Configs to test: {[c[0] for c in configs_to_test]}")
    
    results = []
    
    try:
        for config_key, config_file, expected_perf, description in configs_to_test:
            success, info = run_single_test(
                config_key, config_file, description, args.task, args.timeout
            )
            results.append((config_key, expected_perf, description, success, info))
            
            # Small delay between tests
            if len(configs_to_test) > 1:
                print("\nWaiting 3 seconds before next test...")
                time.sleep(3)
    
    finally:
        # Clean up
        remove_ablation_config()
        print(f"\nCleaned up: removed {OVERRIDE_FILE}")
    
    # Final summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    
    for config_key, expected_perf, description, success, info in results:
        status = "✓ PASS" if success else "✗ FAIL"
        graph = info.get('graph_type', 'unknown')
        print(f"{config_key} ({expected_perf}) {description}: {status} | Graph: {graph}")
    
    passed = sum(1 for r in results if r[3])
    print(f"\nTotal: {passed}/{len(results)} passed")


if __name__ == "__main__":
    main()
