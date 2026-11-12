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

Provider routing (2026-11-10, Pilou): the gpt-oss-120b OpenRouter routing moved off DeepInfra
after the freeze. That is the ONLY allowed difference from FROZEN_AT: the agent code is
byte-identical, full.jsonc is unchanged, and the resolved full.jsonc system equals the frozen one
in every field except that one routing entry (test_resolved_full_differs_only_by_routing).

P2 (branch p2/robustness, local only, version B): the agent code gains the P2 robustness fixes,
every one behind an `AblationConfig.p2_*` flag that defaults to False and is false in every
version-A config. Version A therefore stays the frozen system; the proof moves from "no byte
changed" to: (a) only the files listed in P2_CHANGED may differ from FROZEN_AT, (b) every prompt
renders byte-identically with the flags off and full.jsonc minus the p2 keys resolves to the golden
config (tests/mobile_use/p2/test_version_a_equivalence.py), (c) every P2 code path is gated by
its flag (unit tests in tests/mobile_use/p2/).
"""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from minitap.mobile_use.benchmark.config import load_benchmark_config
from minitap.mobile_use.config import AblationConfig

ROOT = Path(__file__).resolve().parents[3]
FROZEN_AT = "982b10599ab79cf99fe4e5ccf565df8f0bf2a9f1"
GOLDEN_AGENT_TREE = "e4b0347374146f718769f4b04a44fb261d5fd2b9b24f7a396cb815fb23cc8537"
GOLDEN_AGENT_FILES = 129
GOLDEN_FULL_RESOLVED = "5f3e5a9960590bf3b0dd039f3bbe76352cc514cd966e4d1fe4a500acf5862b24"
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


P2_CHANGED = {
    "minitap/mobile_use/config.py",
    "minitap/mobile_use/context.py",
    "minitap/mobile_use/graph/graph.py",
    "minitap/mobile_use/agents/contextor/contextor.py",
    "minitap/mobile_use/agents/cortex/cortex.md",
    "minitap/mobile_use/agents/cortex/cortex.py",
    "minitap/mobile_use/agents/planner/human.md",
    "minitap/mobile_use/agents/planner/planner.md",
    "minitap/mobile_use/agents/planner/planner.py",
    "minitap/mobile_use/agents/verifier/verifier.py",
    "minitap/mobile_use/tools/mobile/tap.py",
    "minitap/mobile_use/tools/mobile/long_press_on.py",
    "minitap/mobile_use/tools/mobile/focus_and_input_text.py",
    "minitap/mobile_use/agents/video_analyzer/video_analyzer.py",
    "minitap/mobile_use/clients/ui_automator_client.py",
    "minitap/mobile_use/controllers/android_controller.py",
    "minitap/mobile_use/controllers/controller_factory.py",
}
P2_NEW_PREFIXES = (
    "minitap/mobile_use/robustness/",
    "minitap/mobile_use/tools/p2_tools.py",
    "minitap/mobile_use/agents/verifier/verifier_p2.md",
    "minitap/mobile_use/benchmark/step_screenshots.py",  # P2 recordings (measurement only)
)


def test_agent_code_changed_only_by_p2():
    """The pre-P2 golden fingerprint (FROZEN_AT) holds for every file P2 does not touch."""
    if not _frozen_available():
        pytest.skip("frozen commit not in local history (shallow clone)")
    out = subprocess.run(
        ["git", "-C", str(ROOT), "diff", "--name-status", FROZEN_AT, "--", "minitap/mobile_use",
         *TOP_LEVEL],
        capture_output=True, text=True, check=True,
    ).stdout
    for line in out.splitlines():
        status, path = line.split("\t", 1)
        if Path(path).name.startswith("test_"):
            continue
        if status == "A":
            assert path.startswith(P2_NEW_PREFIXES), path
        else:
            assert path in P2_CHANGED, path
    # untracked files would not show in git diff: fingerprint count = frozen files + P2 new files
    _, count = agent_tree_fingerprint()
    new = [p for p in agent_files() if str(p.relative_to(ROOT)).startswith(P2_NEW_PREFIXES)]
    assert count == GOLDEN_AGENT_FILES + len(new)


def test_full_config_resolves_to_the_same_system():
    full = load_benchmark_config(ROOT / "benchmarks" / "configs" / "full.jsonc")
    d = json.loads(json.dumps(full.resolved))
    assert not any(v for k, v in d["ablation"].items() if k.startswith("p2_"))
    d["ablation"] = {k: v for k, v in d["ablation"].items() if not k.startswith("p2_")}
    canon = json.dumps(d, sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(canon.encode()).hexdigest() == GOLDEN_FULL_RESOLVED


def _p2_skip_git_diff_against_frozen_commit_is_empty():
    """Superseded on p2/robustness by test_agent_code_changed_only_by_p2 (kept for history)."""
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


ROUTED_MODEL = "openai/gpt-oss-120b"  # the only post-freeze change (provider routing)


def _frozen_available() -> bool:
    probe = subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "-e", f"{FROZEN_AT}^{{commit}}"], capture_output=True
    )
    return probe.returncode == 0


def test_base_config_diff_is_only_the_routing_entry():
    if not _frozen_available():
        pytest.skip("frozen commit not in local history (shallow clone)")
    out = subprocess.run(
        ["git", "-C", str(ROOT), "diff", "-U0", FROZEN_AT, "--", "benchmarks/configs/_base.jsonc"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    changed = [
        ln[1:].strip()
        for ln in out.splitlines()
        if ln[:1] in "+-" and not ln.startswith(("+++", "---"))
    ]
    allowed_tokens = (ROUTED_MODEL, '"order"', '"only"', '"allow_fallbacks"', "}", '"p2_',
                      '"legacy_v1_android_bugs": false')
    for line in changed:
        assert line == "" or line.startswith("//") or any(t in line for t in allowed_tokens), line


def _resolve_at(rev: str, tmp_path: Path) -> dict:
    cfg_dir = tmp_path / rev / "benchmarks" / "configs"
    cfg_dir.mkdir(parents=True)
    for name in ("_base.jsonc", "full.jsonc"):
        blob = subprocess.run(
            ["git", "-C", str(ROOT), "show", f"{rev}:benchmarks/configs/{name}"],
            capture_output=True,
            check=True,
        ).stdout
        if name == "_base.jsonc":  # pre-P2 base: add the (off) p2 flags the loader now requires
            flags = ", ".join(f'"{f}": false' for f in AblationConfig.model_fields if f.startswith("p2_"))
            blob = blob.replace(
                b'"legacy_v1_android_bugs": false', b'"legacy_v1_android_bugs": false, ' + flags.encode()
            )
        (cfg_dir / name).write_bytes(blob)
    return load_benchmark_config(cfg_dir / "full.jsonc").resolved


def test_resolved_full_differs_only_by_routing(tmp_path):
    if not _frozen_available():
        pytest.skip("frozen commit not in local history (shallow clone)")
    frozen = _resolve_at(FROZEN_AT, tmp_path)
    now = load_benchmark_config(ROOT / "benchmarks" / "configs" / "full.jsonc").resolved
    old_pins = frozen["llm_policy"]["openrouter_provider_by_model"]
    new_pins = now["llm_policy"]["openrouter_provider_by_model"]
    assert old_pins[ROUTED_MODEL] != new_pins[ROUTED_MODEL]
    for d in (frozen, now):
        d["llm_policy"]["openrouter_provider_by_model"].pop(ROUTED_MODEL)
        d["ablation"] = {k: v for k, v in d["ablation"].items() if not k.startswith("p2_")}
    assert json.dumps(frozen, sort_keys=True) == json.dumps(now, sort_keys=True)
