#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Africa/Casablanca")
REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from public_job_adapter import normalize_anapec_job  # noqa: E402


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def atomic_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".new")
    shutil.copy2(src, tmp)
    with tmp.open("rb") as fh:
        os.fsync(fh.fileno())
    os.replace(tmp, dst)


def main() -> int:
    ap = argparse.ArgumentParser(description="Import an already verified ANAPEC v12 snapshot into Masari LKG")
    ap.add_argument("--input-dir", required=True)
    ap.add_argument("--runtime-dir", default="runtime/public/anapec")
    args = ap.parse_args()

    src = Path(args.input_dir).expanduser().resolve()
    runtime = Path(args.runtime_dir)
    if not runtime.is_absolute():
        runtime = REPO / runtime

    required = {
        "jobs": src / "jobs.json",
        "source_audit": src / "audit.json",
        "quality": src / "job_quality_audit.json",
        "ground_truth": src / "ground_truth_audit.json",
    }
    missing = [name for name, path in required.items() if not path.exists()]
    if missing:
        raise SystemExit("Missing verified ANAPEC artifacts: " + ", ".join(missing))

    jobs = read_json(required["jobs"])
    source_audit = read_json(required["source_audit"])
    quality = read_json(required["quality"])
    ground_truth = read_json(required["ground_truth"])

    if source_audit.get("gate") != "PASS":
        raise SystemExit("ANAPEC source audit is not PASS")
    if quality.get("gate") != "PASS":
        raise SystemExit("ANAPEC quality audit is not PASS")
    if ground_truth.get("gate") != "PASS":
        raise SystemExit("ANAPEC ground-truth audit is not PASS")
    if int(ground_truth.get("job_count", -1)) != len(jobs):
        raise SystemExit("Ground-truth job count does not match jobs.json")
    if int(ground_truth.get("matched_count", -1)) != len(jobs):
        raise SystemExit("Ground-truth matched_count is not complete")
    if int(ground_truth.get("mismatch_count", -1)) != 0:
        raise SystemExit("Ground-truth mismatches are not zero")
    if int(ground_truth.get("fetch_failure_count", -1)) != 0:
        raise SystemExit("Ground-truth fetch failures are not zero")

    normalized = [normalize_anapec_job(job) for job in jobs]
    uuids = [str(j.get("uuid") or "") for j in normalized]
    if any(not x for x in uuids) or len(uuids) != len(set(uuids)):
        raise SystemExit("Normalized ANAPEC UUID gate failed")

    current = runtime / "current"
    previous = runtime / "previous"
    current.mkdir(parents=True, exist_ok=True)
    previous.mkdir(parents=True, exist_ok=True)
    for name in ("jobs.json", "manifest.json"):
        if (current / name).exists():
            atomic_copy(current / name, previous / name)

    normalized_path = runtime / ".import-jobs.json"
    write_json(normalized_path, normalized)
    manifest_path = runtime / ".import-manifest.json"
    manifest = {
        "source": "anapec",
        "version": "v12",
        "published_at": datetime.now(TZ).isoformat(),
        "jobs": len(normalized),
        "source_gate": "PASS",
        "quality_gate": "PASS",
        "ground_truth_gate": "PASS",
        "ground_truth_matched": len(normalized),
        "ground_truth_mismatches": 0,
        "imported_verified_snapshot": True,
        "origin": str(src),
    }
    write_json(manifest_path, manifest)

    atomic_copy(required["jobs"], current / "raw_jobs.json")
    atomic_copy(required["source_audit"], current / "audit.json")
    atomic_copy(required["quality"], current / "job_quality_audit.json")
    atomic_copy(required["ground_truth"], current / "ground_truth_audit.json")
    atomic_copy(normalized_path, current / "jobs.json")
    atomic_copy(manifest_path, current / "manifest.json")
    normalized_path.unlink(missing_ok=True)
    manifest_path.unlink(missing_ok=True)

    print("ANAPEC_VERIFIED_IMPORT_GATE=PASS")
    print(f"ANAPEC_VERIFIED_IMPORT_JOBS={len(normalized)}")
    print("ANAPEC_VERIFIED_IMPORT_GROUND_TRUTH=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
