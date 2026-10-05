#!/usr/bin/env python3
"""Verify the filebox frontend/backend contract.

Every endpoint the desktop frontend calls via ctx.rest('/...') must exist
as a @router.get/post route in dashboard/plugin_api.py. Run before any
release, and after running scripts/strip-for-catalog.py on a scratch copy
to prove the catalog build keeps the contract.

Usage: python scripts/verify-contract.py [--backend PATH] [--frontend PATH]
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

IGNORED = {
    # Provided by the Hermes plugin host, not our backend.
    "/update-check-host",
}


def backend_routes(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        d.args[0].value
        for n in ast.walk(tree)
        for d in getattr(n, "decorator_list", [])
        if getattr(getattr(d, "func", None), "attr", "") in ("get", "post")
        and d.args
        and isinstance(getattr(d.args[0], "value", None), str)
    }


def frontend_calls(path: Path) -> set[str]:
    src = path.read_text(encoding="utf-8")
    calls = set(re.findall(r"""ctx\.rest\(\s*['"](/[^'"]+)['"]""", src))
    return {c for c in calls if c not in IGNORED}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default=str(ROOT / "dashboard" / "plugin_api.py"))
    ap.add_argument("--frontend", default=str(ROOT / "desktop" / "plugin.js"))
    args = ap.parse_args()

    routes = backend_routes(Path(args.backend))
    calls = frontend_calls(Path(args.frontend))
    missing = sorted(calls - routes)
    print(f"backend routes ({len(routes)}): {sorted(routes)}")
    print(f"frontend calls ({len(calls)}): {sorted(calls)}")
    if missing:
        print(f"CONTRACT BROKEN — frontend calls with no backend route: {missing}")
        return 1
    print("contract OK — every frontend call has a backend route")
    return 0


if __name__ == "__main__":
    sys.exit(main())
