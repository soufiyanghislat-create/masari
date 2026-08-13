#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

raise SystemExit(
    subprocess.call([
        sys.executable,
        str(REPO / "maintenance" / "refresh.py"),
        "--mode",
        "auto",
        "--runtime-dir",
        "runtime/emploi_public",
        "--min-coverage",
        "90",
    ], cwd=REPO)
)
