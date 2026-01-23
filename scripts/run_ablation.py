#!/usr/bin/env python3
"""
Ablation Study Runner

This script helps run ablation experiments by copying the appropriate
ablation config as ablation-config.override.jsonc.

Usage:
    python scripts/run_ablation.py a0  # Run baseline experiment
    python scripts/run_ablation.py a5  # Run meta-reasoning experiment
    python scripts/run_ablation.py --list  # List all available configs
    python scripts/run_ablation.py --reset  # Reset to full system (no override)
"""

import argparse
import shutil
import sys
from pathlib import Path

# Root directory of mobile-use
ROOT_DIR = Path(__file__).parent.parent
ABLATION_CONFIGS_DIR = ROOT_DIR / "ablation-configs"
OVERRIDE_FILE = ROOT_DIR / "ablation-config.override.jsonc"

ABLATION_EXPERIMENTS = {
    "a0": ("a0-baseline.jsonc", "64%", "All features DISABLED"),
    "a1": ("a1-multi-agent.jsonc", "70%", "+Multi-agent graph"),
    "a2": ("a2-sequential-validation.jsonc", "76%", "+Sequential execution, +Validation"),
    "a3": ("a3-deterministic-text.jsonc", "79%", "+Deterministic text input"),
    "a4": ("a4-vision.jsonc", "81%", "+Vision (screenshots)"),
    "a5": ("a5-meta-reasoning.jsonc", "84%", "+Meta-reasoning (agent thoughts)"),
    "a7": ("a7-scratchpad.jsonc", "95%", "+Scratchpad (persistent notes)"),
    "a8": ("a8-video.jsonc", "97%", "+Video recording"),
    "a9": ("a9-final.jsonc", "100%", "All features ENABLED (full system)"),
}


def list_configs():
    """List all available ablation configurations."""
    print("\nAvailable Ablation Configurations:")
    print("-" * 60)
    for key, (filename, expected_perf, description) in ABLATION_EXPERIMENTS.items():
        print(f"  {key:4s}  {expected_perf:5s}  {description}")
    print("-" * 60)
    print("\nUsage: python scripts/run_ablation.py <config_key>")
    print("       python scripts/run_ablation.py --reset  # Remove override\n")


def set_config(config_key: str):
    """Set the ablation config override."""
    if config_key not in ABLATION_EXPERIMENTS:
        print(f"Error: Unknown config '{config_key}'")
        list_configs()
        sys.exit(1)
    
    filename, expected_perf, description = ABLATION_EXPERIMENTS[config_key]
    source = ABLATION_CONFIGS_DIR / filename
    
    if not source.exists():
        print(f"Error: Config file not found: {source}")
        sys.exit(1)
    
    # Copy the config file
    shutil.copy(source, OVERRIDE_FILE)
    
    print(f"\nAblation config set to: {config_key}")
    print(f"  Expected performance: {expected_perf}")
    print(f"  Description: {description}")
    print(f"\nConfig file copied to: {OVERRIDE_FILE}")
    print("\nNow run your AndroidWorld benchmark to test this configuration.\n")


def reset_config():
    """Remove the override file to use full system."""
    if OVERRIDE_FILE.exists():
        OVERRIDE_FILE.unlink()
        print("\nAblation override removed.")
        print("System will now use full configuration (all features enabled).\n")
    else:
        print("\nNo ablation override file found. Already using full configuration.\n")


def main():
    parser = argparse.ArgumentParser(
        description="Ablation Study Runner - Set up ablation experiments"
    )
    parser.add_argument(
        "config",
        nargs="?",
        help="Ablation config key (a0, a1, a2, a3, a4, a5, a7, a8, a9)"
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List all available ablation configurations"
    )
    parser.add_argument(
        "--reset", "-r",
        action="store_true",
        help="Reset to full system (remove override)"
    )
    
    args = parser.parse_args()
    
    if args.list:
        list_configs()
    elif args.reset:
        reset_config()
    elif args.config:
        set_config(args.config)
    else:
        list_configs()


if __name__ == "__main__":
    main()
