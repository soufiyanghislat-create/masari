#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
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


def run(cmd: list[str]) -> None:
    print("$", " ".join(str(x) for x in cmd), flush=True)
    subprocess.run(cmd, cwd=REPO, check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Refresh ANAPEC independently and promote only verified LKG")
    ap.add_argument("--runtime-dir", default="runtime/public/anapec")
    ap.add_argument("--ground-truth", action="store_true")
    ap.add_argument("--keep-runs", type=int, default=4)
    args = ap.parse_args()

    runtime = Path(args.runtime_dir)
    if not runtime.is_absolute():
        runtime = REPO / runtime
    runtime.mkdir(parents=True, exist_ok=True)
    now = datetime.now(TZ)
    run_id = now.strftime("%Y%m%d-%H%M%S")
    run_dir = runtime / "runs" / run_id
    raw_dir = run_dir / "raw"
    run_dir.mkdir(parents=True, exist_ok=False)

    try:
        run([sys.executable, "-m", "sources.public.anapec.audit", "--output", str(raw_dir)])
        audit = read_json(raw_dir / "audit.json")
        if audit.get("gate") != "PASS":
            raise RuntimeError("ANAPEC source gate failed")

        quality_path = raw_dir / "job_quality_audit.json"
        run([
            sys.executable,
            "-m",
            "sources.public.anapec.quality_audit",
            "--jobs",
            str(raw_dir / "jobs.json"),
            "--output",
            str(quality_path),
        ])
        quality = read_json(quality_path)
        if quality.get("gate") != "PASS":
            raise RuntimeError("ANAPEC job quality gate failed")

        ground_truth = None
        ground_truth_path = raw_dir / "ground_truth_audit.json"
        if args.ground_truth:
            run([
                sys.executable,
                str(REPO / "anapec_ground_truth_audit.py"),
                "--jobs",
                str(raw_dir / "jobs.json"),
                "--output",
                str(ground_truth_path),
            ])
            ground_truth = read_json(ground_truth_path)
            if ground_truth.get("gate") != "PASS":
                raise RuntimeError("ANAPEC ground-truth gate failed")

        raw_jobs = read_json(raw_dir / "jobs.json")
        normalized = [normalize_anapec_job(job) for job in raw_jobs]
        uuids = [str(j.get("uuid") or "") for j in normalized]
        urls = [str(j.get("url") or "") for j in normalized]
        if len(normalized) != len(raw_jobs):
            raise RuntimeError("ANAPEC normalization count mismatch")
        if any(not x for x in uuids) or len(uuids) != len(set(uuids)):
            raise RuntimeError("ANAPEC normalized UUID gate failed")
        if any(not x for x in urls) or len(urls) != len(set(urls)):
            raise RuntimeError("ANAPEC normalized URL gate failed")

        write_json(run_dir / "jobs.json", normalized)
        previous_manifest = {}
        current = runtime / "current"
        if (current / "manifest.json").exists():
            try:
                previous_manifest = read_json(current / "manifest.json")
            except Exception:
                previous_manifest = {}
        last_ground_truth = (
            ground_truth.get("gate") if ground_truth else previous_manifest.get("ground_truth_gate", "NOT_RUN")
        )
        manifest = {
            "source": "anapec",
            "version": "v12",
            "published_at": now.isoformat(),
            "run_id": run_id,
            "jobs": len(normalized),
            "source_gate": audit.get("gate"),
            "quality_gate": quality.get("gate"),
            "ground_truth_gate": last_ground_truth,
            "ground_truth_ran": bool(args.ground_truth),
            "ground_truth_matched": ground_truth.get("matched_count") if ground_truth else None,
            "ground_truth_mismatches": ground_truth.get("mismatch_count") if ground_truth else None,
        }
        write_json(run_dir / "manifest.json", manifest)

        previous = runtime / "previous"
        current.mkdir(parents=True, exist_ok=True)
        previous.mkdir(parents=True, exist_ok=True)
        for name in ("jobs.json", "manifest.json"):
            if (current / name).exists():
                atomic_copy(current / name, previous / name)
        atomic_copy(raw_dir / "jobs.json", current / "raw_jobs.json")
        atomic_copy(raw_dir / "audit.json", current / "audit.json")
        atomic_copy(quality_path, current / "job_quality_audit.json")
        if ground_truth_path.exists():
            atomic_copy(ground_truth_path, current / "ground_truth_audit.json")
        atomic_copy(run_dir / "jobs.json", current / "jobs.json")
        # Manifest last: readers only treat the snapshot as promoted after this point.
        atomic_copy(run_dir / "manifest.json", current / "manifest.json")

        runs = sorted([p for p in (runtime / "runs").iterdir() if p.is_dir()], reverse=True)
        for old in runs[max(args.keep_runs, 1):]:
            shutil.rmtree(old, ignore_errors=True)

        print("ANAPEC_LKG_GATE=PASS")
        print(f"ANAPEC_LKG_JOBS={len(normalized)}")
        return 0
    except Exception as exc:
        write_json(run_dir / "failure.json", {"failed_at": datetime.now(TZ).isoformat(), "error": f"{type(exc).__name__}: {exc}"})
        print(f"ANAPEC_LKG_GATE=FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
