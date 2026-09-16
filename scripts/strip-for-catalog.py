#!/usr/bin/env python3
"""Produce the catalog build: identical to main minus the self-updater.

The Hermes plugin catalog forbids self-updating code (rule 3: the SHA pin
is the trust model), but explicitly blesses keeping the updater in the
standalone distribution. So:

  git checkout catalog && git merge main
  python scripts/strip-for-catalog.py   # edits in place, verifies
  git commit -am "..." && git push

then open a catalog SHA-bump PR against the new catalog-branch commit.
Standalone users (this repo, direct installs) keep the UpdateChip.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "dashboard" / "plugin_api.py"
FRONTEND = ROOT / "desktop" / "plugin.js"
README = ROOT / "README.md"


def strip_backend() -> None:
    src = BACKEND.read_text(encoding="utf-8")
    # Updater block runs from the UPDATE_REPO constant to end of file.
    idx = src.find('UPDATE_REPO = os.environ.get("FILEBOX_UPDATE_REPO"')
    if idx < 0:
        print("backend: no updater block (already stripped?)")
        return
    src = src[:idx].rstrip() + "\n"
    # Imports only the updater used.
    src = re.sub(r"^import json\n", "", src, flags=re.M)
    src = re.sub(r"^import time\n", "", src, flags=re.M)
    BACKEND.write_text(src, encoding="utf-8")
    tree = ast.parse(src)
    routes = [d.args[0].value for n in ast.walk(tree)
              for d in getattr(n, "decorator_list", [])
              if getattr(getattr(d, "func", None), "attr", "") in ("get", "post")]
    assert "/update-check" not in routes and "/update" not in routes, routes
    assert "UPDATE_REPO" not in src and "tarfile" not in src
    print(f"backend: stripped, {len(routes)} routes left")


def strip_frontend() -> None:
    src = FRONTEND.read_text(encoding="utf-8")
    m = re.search(r"\nfunction UpdateChip\(\{ ctx, t \}\).*?\n\}\n\nfunction Explorer",
                  src, flags=re.S)
    assert m, "UpdateChip block not found"
    src = src[:m.start()] + "\nfunction Explorer" + src[m.end():]
    src = src.replace("      jsx(UpdateChip, { ctx, t }),\n", "")
    for line in ("  updateTo: v => `Update to v${v}`,\n",
                 "  checkingUpdate: 'Checking for updates…',\n",
                 "  upToDate: v => `v${v} · up to date`,\n",
                 "  updateDone: 'Updated — restart the gateway and reload the window to apply.',\n",
                 "  aheadV: v => `Unpushed v${v}`,\n",
                 "  aheadTip: (l, r) => `Local v${l} is ahead of GitHub v${r} — push to publish it. Click to re-check.`,\n"):
        assert line in src, line
        src = src.replace(line, "")
    FRONTEND.write_text(src, encoding="utf-8")
    assert "UpdateChip" not in src and "update-check" not in src
    r = subprocess.run(["node", "--check", str(FRONTEND)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    print("frontend: stripped, node --check OK")


def strip_readme() -> None:
    src = README.read_text(encoding="utf-8")
    m = re.search(r"\n## Self-updates\n.*?\n(?=## )", src, flags=re.S)
    assert m, "Self-updates section not found"
    src = src[:m.start()] + "\n" + src[m.end() - len("## "):]
    README.write_text(src, encoding="utf-8")
    assert "Self-updates" not in src and "update-check" not in src
    print("readme: Self-updates section removed")


if __name__ == "__main__":
    strip_backend()
    strip_frontend()
    strip_readme()
    print("catalog build ready — verify with git diff, then commit")
