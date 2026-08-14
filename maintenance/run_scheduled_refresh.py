#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

raise SystemExit(
    subprocess.call([
        sys.executable,
        str(REPO / "maintenance" / "public_refresh.py"),
        "--mode",
        "auto",
        "--runtime-dir",
        "runtime/public/aggregate",
        "--min-coverage",
        "90",
    ], cwd=REPO)
)
