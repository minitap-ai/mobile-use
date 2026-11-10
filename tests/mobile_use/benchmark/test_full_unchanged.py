"""The system under test for full.jsonc is frozen at FROZEN_AT (the pin of the runs).

History: frozen at 4fe7ea4 for the P2 pilot and c3f77e7; changed on purpose in the fix round
(2026-11-10/11, one commit per fix, each disclosed); re-frozen at the fix-round pin.

Two independent proofs:
1. a fingerprint of every agent source file (minitap/mobile_use, prompts included, tests
   excluded) + the dependency lock + the repo-level LLM/ablation defaults, and the SHA-256 of the
   resolved full.jsonc, both equal the values computed on 4fe7ea4;
2. when git history is available, `git diff 4fe7ea4 -- <same paths>` is empty.

If an intentional agent change is ever needed, this test must be updated in the same commit, and
the change disclosed: runs before and after it are not the same system.
"""

import hashlib
import subprocess
from pathlib import Path

import pytest

from minitap.mobile_use.benchmark.config import load_benchmark_config

ROOT = Path(__file__).resolve().parents[3]
FROZEN_AT = None  # fix round in progress: set at the freeze
GOLDEN_AGENT_TREE = "68bd4e3c18500927de2a7a049255fd8c86f9b197dfae1b464ddf4a1e4f4de512"
GOLDEN_AGENT_FILES = 129
GOLDEN_FULL_RESOLVED = "1b435cb11bc8931746998da48a8f8a8046ede699bef48c158b1f42b3530096b3"
TOP_LEVEL = (
    "llm-config.defaults.jsonc",
    "ablation-config.defaults.jsonc",
    "ablation-config.override.jsonc",
    "pyproject.toml",
    "uv.lock",
)


def agent_files() -> list[Path]:
    files = []
    for p in sorted((ROOT / "minitap" / "mobile_use").rglob("*")):
        if not p.is_file() or "__pycache__" in p.parts or p.suffix == ".pyc":
            continue
        if p.name.startswith("test_") or p.name.endswith("_test.py"):
            continue
        files.append(p)
    return files + [ROOT / n for n in TOP_LEVEL]


def agent_tree_fingerprint() -> tuple[str, int]:
    h = hashlib.sha256()
    files = agent_files()
    for p in files:
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        h.update(str(p.relative_to(ROOT)).encode() + b"\0" + digest.encode() + b"\n")
    return h.hexdigest(), len(files)


def test_agent_code_fingerprint_unchanged_since_first_runs():
    tree, count = agent_tree_fingerprint()
    assert count == GOLDEN_AGENT_FILES
    assert tree == GOLDEN_AGENT_TREE


def test_full_config_resolves_to_the_same_system():
    full = load_benchmark_config(ROOT / "benchmarks" / "configs" / "full.jsonc")
    assert full.resolved_sha256 == GOLDEN_FULL_RESOLVED


def test_git_diff_against_frozen_commit_is_empty():
    if FROZEN_AT is None:
        pytest.skip("fix round in progress: no frozen commit yet (fingerprint test still applies)")
    probe = subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "-e", f"{FROZEN_AT}^{{commit}}"], capture_output=True
    )
    if probe.returncode != 0:
        pytest.skip("frozen commit not in local history (shallow clone)")
    paths = [
        "minitap/mobile_use",
        *TOP_LEVEL,
        "benchmarks/configs/_base.jsonc",
        "benchmarks/configs/full.jsonc",
    ]
    out = subprocess.run(
        ["git", "-C", str(ROOT), "diff", "--stat", FROZEN_AT, "--", *paths],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    # Only test files may differ.
    changed = [
        line.split("|")[0].strip()
        for line in out.splitlines()
        if "|" in line and not Path(line.split("|")[0].strip()).name.startswith("test_")
    ]
    assert changed == [], changed
