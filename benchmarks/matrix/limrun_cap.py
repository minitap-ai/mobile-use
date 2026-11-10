#!/usr/bin/env python3
"""Global cap on live Limrun devices across ALL our agents (decision 2026-11-10: at most 35).

"Ours" = instances on the key with label sandbox=true or local-testing=true and no tenant label
(the same key also serves tenant-bound flows, which are not counted). Stdlib only; prints counts
and ids, never tokens or URLs.

    python benchmarks/matrix/limrun_cap.py check --want 4   # exit 0 if live + 4 <= cap, else 2
    python benchmarks/matrix/limrun_cap.py count            # live count + ids
Every create (matrix pool, P1-B, validation, probes) must call `check` first.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import UTC, datetime

DEFAULT_CAP = 35
BASE_URL = os.environ.get("LIMRUN_BASE_URL", "https://api.limrun.com").rstrip("/")
OUR_LABELS = ("sandbox", "local-testing")
TENANT_LABELS = ("tenant", "tenant-id", "tenant_id")


def _api_key() -> str:
    key = os.environ.get("LIMRUN_API_KEY") or os.environ.get("LIM_API_KEY")
    if not key:
        raise SystemExit("LIMRUN_API_KEY (or LIM_API_KEY) is not set")
    return key


def _get(path: str) -> object:
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        headers={"Authorization": f"Bearer {_api_key()}", "User-Agent": "matrix-limrun-cap/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def is_ours(labels: dict | None) -> bool:
    labels = labels or {}
    if any(k in labels for k in TENANT_LABELS):
        return False
    return any(str(labels.get(k, "")).lower() == "true" for k in OUR_LABELS)


def live_instances(fetch=_get) -> list[dict]:
    """Non-terminated, ours, Android + iOS."""
    out = []
    for platform in ("android", "ios"):
        items = fetch(f"/v1/{platform}_instances?limit=1000")
        for it in items if isinstance(items, list) else []:
            md, st = it.get("metadata") or {}, it.get("status") or {}
            if st.get("state") == "terminated" or not is_ours(md.get("labels")):
                continue
            out.append(
                {
                    "id": md.get("id"),
                    "state": st.get("state"),
                    "labels": md.get("labels"),
                    "created_at": md.get("createdAt"),
                }
            )
    return out


def instance_lifetime(instance_id: str, fetch=_get) -> dict:
    """created_at, terminated_at (None while live) and minutes alive so far."""
    platform = "ios" if instance_id.startswith("ios_") else "android"
    d = fetch(f"/v1/{platform}_instances/{instance_id}")
    md = d.get("metadata") or {}
    created, terminated = md.get("createdAt"), md.get("terminatedAt")

    def parse(ts):
        return datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None

    start, end = parse(created), parse(terminated) or datetime.now(UTC)
    minutes = (end - start).total_seconds() / 60 if start else None
    return {
        "instance_id": instance_id,
        "created_at": created,
        "terminated_at": terminated,
        "minutes": round(minutes, 1) if minutes is not None else None,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=["check", "count"])
    ap.add_argument("--want", type=int, default=1, help="instances about to be created")
    ap.add_argument("--cap", type=int, default=int(os.environ.get("LIMRUN_MAX_LIVE", DEFAULT_CAP)))
    a = ap.parse_args(argv)
    live = live_instances()
    if a.command == "count":
        print(json.dumps({"live": len(live), "cap": a.cap, "ids": [i["id"] for i in live]}))
        return 0
    ok = len(live) + a.want <= a.cap
    print(json.dumps({"live": len(live), "want": a.want, "cap": a.cap, "allowed": ok}))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
