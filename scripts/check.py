#!/usr/bin/env python3
"""Check source syntax and run tests without changing system packages."""
from pathlib import Path
import os
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
for folder in ("kernelpatching", "tests", "scripts"):
    for path in (root / folder).rglob("*.py"):
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
compile((root / "fedora_vanilla_kernel.py").read_text(), str(root / "fedora_vanilla_kernel.py"), "exec")
print("Source syntax checks passed.", flush=True)
env = os.environ.copy()
env["PYTHONDONTWRITEBYTECODE"] = "1"
raise SystemExit(subprocess.call([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=root, env=env))
