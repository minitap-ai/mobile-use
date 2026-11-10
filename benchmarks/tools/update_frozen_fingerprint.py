"""Re-record the frozen-system fingerprint after an INTENTIONAL agent change (fix round).

    uv run python benchmarks/tools/update_frozen_fingerprint.py [--frozen-at <sha>|--no-frozen-at]

Rewrites the golden constants of tests/mobile_use/benchmark/test_full_unchanged.py. Every agent
change must be disclosed: runs before and after it are not the same system.
"""

import argparse
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEST = ROOT / "tests" / "mobile_use" / "benchmark" / "test_full_unchanged.py"

ap = argparse.ArgumentParser()
g = ap.add_mutually_exclusive_group()
g.add_argument("--frozen-at")
g.add_argument("--no-frozen-at", action="store_true")
a = ap.parse_args()

spec = importlib.util.spec_from_file_location("tfu", TEST)
mod = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(ROOT))
spec.loader.exec_module(mod)  # type: ignore[union-attr]
from minitap.mobile_use.benchmark.config import load_benchmark_config  # noqa: E402

tree, count = mod.agent_tree_fingerprint()
full = load_benchmark_config(ROOT / "benchmarks" / "configs" / "full.jsonc").resolved_sha256
src = TEST.read_text()
src = re.sub(r'GOLDEN_AGENT_TREE = "[0-9a-f]+"', f'GOLDEN_AGENT_TREE = "{tree}"', src)
src = re.sub(r"GOLDEN_AGENT_FILES = \d+", f"GOLDEN_AGENT_FILES = {count}", src)
src = re.sub(r'GOLDEN_FULL_RESOLVED = "[0-9a-f]+"', f'GOLDEN_FULL_RESOLVED = "{full}"', src)
if a.frozen_at:
    src = re.sub(r"FROZEN_AT = .*", f'FROZEN_AT = "{a.frozen_at}"', src, count=1)
elif a.no_frozen_at:
    src = re.sub(
        r"FROZEN_AT = .*",
        "FROZEN_AT = None  # fix round in progress: set at the freeze",
        src,
        count=1,
    )
TEST.write_text(src)
print(f"tree={tree} files={count} full={full}")
