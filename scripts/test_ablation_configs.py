#!/usr/bin/env python3
"""
Ablation Configuration Test Script

This script tests each ablation configuration by:
1. Parsing the JSON config files directly
2. Verifying the feature flags are correctly set
3. Validating the config structure

This doesn't require the package to be installed.

Usage:
    python scripts/test_ablation_configs.py
    python scripts/test_ablation_configs.py --verbose
    python scripts/test_ablation_configs.py --config a0  # Test specific config
"""

import argparse
import json
import re
import sys
from pathlib import Path

try:
    from rich.console import Console
    from rich.table import Table
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

if RICH_AVAILABLE:
    console = Console()
else:
    class FakeConsole:
        def print(self, *args, **kwargs):
            # Strip rich formatting
            text = str(args[0]) if args else ""
            text = re.sub(r'\[.*?\]', '', text)
            print(text)
    console = FakeConsole()

# Root directory of mobile-use
PROJECT_ROOT = Path(__file__).parent.parent
ABLATION_CONFIGS_DIR = PROJECT_ROOT / "ablation-configs"

# All valid config keys
ALL_CONFIG_KEYS = [
    "use_multi_agent",
    "use_sequential_execution",
    "use_post_validation",
    "use_deterministic_text",
    "use_vision",
    "use_meta_reasoning",
    "use_scratchpad",
    "use_video_recording",
    "use_data_fidelity_prompts",
]

ABLATION_EXPERIMENTS = {
    "a0": {
        "file": "a0-baseline.jsonc",
        "expected_perf": "64%",
        "description": "Baseline - All features DISABLED",
        "expected_flags": {
            "use_multi_agent": False,
            "use_sequential_execution": False,
            "use_post_validation": False,
            "use_deterministic_text": False,
            "use_vision": False,
            "use_meta_reasoning": False,
            "use_scratchpad": False,
            "use_video_recording": False,
            "use_data_fidelity_prompts": False,
        },
    },
    "a1": {
        "file": "a1-multi-agent.jsonc",
        "expected_perf": "70%",
        "description": "+Multi-agent graph",
        "expected_flags": {
            "use_multi_agent": True,
            "use_sequential_execution": False,
            "use_post_validation": False,
            "use_deterministic_text": False,
            "use_vision": False,
            "use_meta_reasoning": False,
            "use_scratchpad": False,
            "use_video_recording": False,
            "use_data_fidelity_prompts": False,
        },
    },
    "a2": {
        "file": "a2-sequential-validation.jsonc",
        "expected_perf": "76%",
        "description": "+Sequential execution, +Validation",
        "expected_flags": {
            "use_multi_agent": True,
            "use_sequential_execution": True,
            "use_post_validation": True,
            "use_deterministic_text": False,
            "use_vision": False,
            "use_meta_reasoning": False,
            "use_scratchpad": False,
            "use_video_recording": False,
            "use_data_fidelity_prompts": False,
        },
    },
    "a3": {
        "file": "a3-deterministic-text.jsonc",
        "expected_perf": "79%",
        "description": "+Deterministic text input",
        "expected_flags": {
            "use_multi_agent": True,
            "use_sequential_execution": True,
            "use_post_validation": True,
            "use_deterministic_text": True,
            "use_vision": False,
            "use_meta_reasoning": False,
            "use_scratchpad": False,
            "use_video_recording": False,
            "use_data_fidelity_prompts": False,
        },
    },
    "a4": {
        "file": "a4-vision.jsonc",
        "expected_perf": "81%",
        "description": "+Vision (screenshots)",
        "expected_flags": {
            "use_multi_agent": True,
            "use_sequential_execution": True,
            "use_post_validation": True,
            "use_deterministic_text": True,
            "use_vision": True,
            "use_meta_reasoning": False,
            "use_scratchpad": False,
            "use_video_recording": False,
            "use_data_fidelity_prompts": False,
        },
    },
    "a5": {
        "file": "a5-meta-reasoning.jsonc",
        "expected_perf": "84%",
        "description": "+Meta-reasoning",
        "expected_flags": {
            "use_multi_agent": True,
            "use_sequential_execution": True,
            "use_post_validation": True,
            "use_deterministic_text": True,
            "use_vision": True,
            "use_meta_reasoning": True,
            "use_scratchpad": False,
            "use_video_recording": False,
            "use_data_fidelity_prompts": False,
        },
    },
    "a7": {
        "file": "a7-scratchpad.jsonc",
        "expected_perf": "95%",
        "description": "+Scratchpad",
        "expected_flags": {
            "use_multi_agent": True,
            "use_sequential_execution": True,
            "use_post_validation": True,
            "use_deterministic_text": True,
            "use_vision": True,
            "use_meta_reasoning": True,
            "use_scratchpad": True,
            "use_video_recording": False,
            "use_data_fidelity_prompts": False,
        },
    },
    "a8": {
        "file": "a8-video.jsonc",
        "expected_perf": "97%",
        "description": "+Video recording",
        "expected_flags": {
            "use_multi_agent": True,
            "use_sequential_execution": True,
            "use_post_validation": True,
            "use_deterministic_text": True,
            "use_vision": True,
            "use_meta_reasoning": True,
            "use_scratchpad": True,
            "use_video_recording": True,
            "use_data_fidelity_prompts": False,
        },
    },
    "a9": {
        "file": "a9-final.jsonc",
        "expected_perf": "100%",
        "description": "Full system - All features ENABLED",
        "expected_flags": {
            "use_multi_agent": True,
            "use_sequential_execution": True,
            "use_post_validation": True,
            "use_deterministic_text": True,
            "use_vision": True,
            "use_meta_reasoning": True,
            "use_scratchpad": True,
            "use_video_recording": True,
            "use_data_fidelity_prompts": True,
        },
    },
}


def load_jsonc(file_path: Path) -> dict:
    """Load a JSONC file (JSON with comments)."""
    content = file_path.read_text()
    # Remove single-line comments
    content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
    # Remove multi-line comments
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    return json.loads(content)


def test_config(config_key: str, verbose: bool = False) -> tuple[bool, list[str]]:
    """
    Test a specific ablation configuration.
    
    Returns:
        (success, list of error messages)
    """
    errors = []
    experiment = ABLATION_EXPERIMENTS[config_key]
    
    config_path = ABLATION_CONFIGS_DIR / experiment["file"]
    
    # Check file exists
    if not config_path.exists():
        return False, [f"Config file not found: {config_path}"]
    
    try:
        # Load the config
        config = load_jsonc(config_path)
        
        if verbose:
            console.print(f"  [dim]Loaded config: {config}[/dim]")
        
        # Check all required keys are present
        for key in ALL_CONFIG_KEYS:
            if key not in config:
                errors.append(f"Missing key: {key}")
        
        # Check no extra keys
        for key in config:
            if key not in ALL_CONFIG_KEYS:
                errors.append(f"Unknown key: {key}")
        
        # Verify each flag value
        expected_flags = experiment["expected_flags"]
        for flag_name, expected_value in expected_flags.items():
            if flag_name not in config:
                continue  # Already reported as missing
            actual_value = config[flag_name]
            if actual_value != expected_value:
                errors.append(
                    f"Flag mismatch: {flag_name} = {actual_value}, expected {expected_value}"
                )
        
        # Validate incremental progression (each config should enable one more feature)
        enabled_count = sum(1 for v in config.values() if v is True)
        expected_enabled_count = sum(1 for v in expected_flags.values() if v is True)
        
        if enabled_count != expected_enabled_count:
            errors.append(
                f"Enabled feature count mismatch: {enabled_count} vs expected {expected_enabled_count}"
            )
        
        # Display graph type
        if verbose:
            graph_type = "MULTI-AGENT" if config.get("use_multi_agent", False) else "MONOLITHIC"
            console.print(f"  [dim]Graph type: {graph_type}[/dim]")
        
    except json.JSONDecodeError as e:
        errors.append(f"JSON parse error: {str(e)}")
    except Exception as e:
        errors.append(f"Exception during config test: {str(e)}")
    
    return len(errors) == 0, errors


def validate_incremental_progression() -> list[str]:
    """Validate that configs progress incrementally (each enables one more feature)."""
    errors = []
    
    ordered_configs = ["a0", "a1", "a2", "a3", "a4", "a5", "a7", "a8", "a9"]
    prev_enabled = set()
    
    for config_key in ordered_configs:
        experiment = ABLATION_EXPERIMENTS[config_key]
        current_enabled = set(
            k for k, v in experiment["expected_flags"].items() if v
        )
        
        # Check that all previously enabled features are still enabled
        if not prev_enabled.issubset(current_enabled):
            missing = prev_enabled - current_enabled
            errors.append(f"{config_key}: Lost features from previous config: {missing}")
        
        prev_enabled = current_enabled
    
    return errors


def run_all_tests(verbose: bool = False, specific_config: str | None = None):
    """Run tests for all or specific ablation configurations."""
    
    console.print("\n[bold]Ablation Configuration Test Suite[/bold]\n")
    
    configs_to_test = [specific_config] if specific_config else list(ABLATION_EXPERIMENTS.keys())
    
    results = []
    
    for config_key in configs_to_test:
        experiment = ABLATION_EXPERIMENTS[config_key]
        console.print(f"Testing [cyan]{config_key}[/cyan] - {experiment['description']}...")
        
        success, errors = test_config(config_key, verbose)
        
        if success:
            console.print(f"  [green]✓ PASS[/green]")
        else:
            console.print(f"  [red]✗ FAIL[/red]")
            for error in errors:
                console.print(f"    [red]- {error}[/red]")
        
        results.append((config_key, success, errors))
    
    # Validate incremental progression
    if not specific_config:
        console.print("\nValidating incremental feature progression...")
        progression_errors = validate_incremental_progression()
        if progression_errors:
            console.print(f"  [red]✗ FAIL[/red]")
            for error in progression_errors:
                console.print(f"    [red]- {error}[/red]")
            results.append(("progression", False, progression_errors))
        else:
            console.print(f"  [green]✓ PASS[/green]")
            results.append(("progression", True, []))
    
    # Summary
    console.print("\n[bold]Summary[/bold]\n")
    
    if RICH_AVAILABLE:
        table = Table(show_header=True, header_style="bold")
        table.add_column("Config", style="cyan")
        table.add_column("Expected %", justify="center")
        table.add_column("Description")
        table.add_column("Status", justify="center")
        
        for config_key, success, errors in results:
            if config_key == "progression":
                continue
            experiment = ABLATION_EXPERIMENTS[config_key]
            status = "[green]PASS[/green]" if success else "[red]FAIL[/red]"
            table.add_row(
                config_key,
                experiment["expected_perf"],
                experiment["description"],
                status,
            )
        
        console.print(table)
    else:
        console.print("Config | Expected % | Description | Status")
        console.print("-" * 60)
        for config_key, success, errors in results:
            if config_key == "progression":
                continue
            experiment = ABLATION_EXPERIMENTS[config_key]
            status = "PASS" if success else "FAIL"
            console.print(f"{config_key} | {experiment['expected_perf']} | {experiment['description']} | {status}")
    
    passed = sum(1 for _, success, _ in results if success)
    failed = len(results) - passed
    
    console.print(f"\n[bold]Results:[/bold] {passed} passed, {failed} failed\n")
    
    return failed == 0


def main():
    parser = argparse.ArgumentParser(
        description="Test ablation configurations"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show verbose output"
    )
    parser.add_argument(
        "--config", "-c",
        type=str,
        choices=list(ABLATION_EXPERIMENTS.keys()),
        help="Test a specific config only"
    )
    
    args = parser.parse_args()
    
    success = run_all_tests(verbose=args.verbose, specific_config=args.config)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
