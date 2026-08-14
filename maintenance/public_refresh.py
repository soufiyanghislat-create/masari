#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Africa/Casablanca")
REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from public_job_adapter import normalize_emploi_public_job  # noqa: E402
from search import is_job_visible_now  # noqa: E402


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


def call(cmd: list[str]) -> tuple[bool, str]:
    print("$", " ".join(str(x) for x in cmd), flush=True)
    try:
        subprocess.run(cmd, cwd=REPO, check=True)
        return True, ""
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _anapec_is_stale(current: Path, now: datetime, hours: float = 6.0) -> bool:
    manifest_path = current / "manifest.json"
    if not manifest_path.exists():
        return True
    try:
        published = datetime.fromisoformat(str(read_json(manifest_path).get("published_at") or ""))
        if published.tzinfo is None:
            published = published.replace(tzinfo=TZ)
        return now - published.astimezone(TZ) >= timedelta(hours=hours)
    except Exception:
        return True


def _emploi_jobs(ep_runtime: Path) -> tuple[list[dict], str]:
    current = ep_runtime / "current" / "jobs.json"
    if current.exists():
        return [normalize_emploi_public_job(j) for j in read_json(current)], "runtime"
    bootstrap = REPO / "bootstrap" / "search_index.json"
    if bootstrap.exists():
        data = read_json(bootstrap)
        rows = [
            j for j in (data.get("jobs") or [])
            if str(j.get("source") or "emploi-public").strip().casefold() != "anapec"
        ]
        return [normalize_emploi_public_job(j) for j in rows], "bootstrap"
    return [], "none"


def _anapec_jobs(runtime: Path) -> tuple[list[dict], str]:
    current = runtime / "current" / "jobs.json"
    if current.exists():
        return read_json(current), "runtime"

    bootstrap_jobs = REPO / "bootstrap" / "anapec" / "jobs.json"
    bootstrap_manifest = REPO / "bootstrap" / "anapec" / "manifest.json"
    if bootstrap_jobs.exists() and bootstrap_manifest.exists():
        manifest = read_json(bootstrap_manifest)
        jobs = read_json(bootstrap_jobs)
        if (
            manifest.get("ground_truth_gate") == "PASS"
            and int(manifest.get("ground_truth_matched") or 0) == len(jobs)
            and int(manifest.get("ground_truth_mismatches") or 0) == 0
        ):
            return jobs, "bootstrap"
    return [], "none"


def _validate_aggregate(jobs: list[dict], now: datetime) -> dict:
    visible = [j for j in jobs if is_job_visible_now(j, now)]
    uuids = [str(j.get("uuid") or "") for j in visible]
    urls = [str(j.get("url") or "") for j in visible]
    if any(not x for x in uuids) or len(uuids) != len(set(uuids)):
        raise RuntimeError("Aggregate UUID uniqueness gate failed")
    if any(not x for x in urls) or len(urls) != len(set(urls)):
        raise RuntimeError("Aggregate URL uniqueness gate failed")
    return {
        "input_jobs": len(jobs),
        "visible_jobs": len(visible),
        "dropped_by_visibility": len(jobs) - len(visible),
        "source_counts": dict(sorted(Counter(str(j.get("source") or "unknown") for j in visible).items())),
        "jobs": visible,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Refresh public sources independently, then aggregate their LKG snapshots")
    ap.add_argument("--runtime-dir", default="runtime/public/aggregate")
    ap.add_argument("--mode", choices=("auto", "full", "quick"), default="auto")
    ap.add_argument("--min-coverage", type=float, default=90.0)
    ap.add_argument("--keep-runs", type=int, default=8)
    ap.add_argument("--no-refresh", action="store_true", help="aggregate existing LKG/bootstrap only; do not use network")
    args = ap.parse_args()

    aggregate_runtime = Path(args.runtime_dir)
    if not aggregate_runtime.is_absolute():
        aggregate_runtime = REPO / aggregate_runtime
    public_root = aggregate_runtime.parent
    ep_runtime = public_root / "emploi_public"
    anapec_runtime = public_root / "anapec"
    aggregate_runtime.mkdir(parents=True, exist_ok=True)

    lock_file = (aggregate_runtime / ".refresh.lock").open("a+")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("MASARI_PUBLIC_REFRESH_SKIPPED=LOCKED")
        return 0

    now = datetime.now(TZ)
    mode = args.mode
    if mode == "auto":
        mode = "full" if 4 <= now.hour < 8 else "quick"
    run_id = now.strftime("%Y%m%d-%H%M%S") + f"-{mode}"
    run_dir = aggregate_runtime / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    source_status: dict[str, dict] = {}

    if args.no_refresh:
        ep_ok, ep_error = True, ""
    else:
        ep_ok, ep_error = call([
            sys.executable,
            str(REPO / "maintenance" / "refresh.py"),
            "--runtime-dir",
            str(ep_runtime),
            "--mode",
            mode,
            "--min-coverage",
            str(args.min_coverage),
        ])
    source_status["emploi-public"] = {"refresh_attempted": not args.no_refresh, "refresh_ok": ep_ok, "error": ep_error}

    refresh_anapec = (not args.no_refresh) and (mode == "full" or _anapec_is_stale(anapec_runtime / "current", now))
    anapec_ok = True
    anapec_error = ""
    if refresh_anapec:
        cmd = [
            sys.executable,
            str(REPO / "maintenance" / "anapec_refresh.py"),
            "--runtime-dir",
            str(anapec_runtime),
        ]
        if mode == "full":
            cmd.append("--ground-truth")
        anapec_ok, anapec_error = call(cmd)
    source_status["anapec"] = {
        "refresh_attempted": refresh_anapec,
        "refresh_ok": anapec_ok,
        "error": anapec_error,
    }

    try:
        ep_jobs, ep_origin = _emploi_jobs(ep_runtime)
        anapec_jobs, anapec_origin = _anapec_jobs(anapec_runtime)
        source_status["emploi-public"]["snapshot_origin"] = ep_origin
        source_status["emploi-public"]["snapshot_jobs"] = len(ep_jobs)
        source_status["anapec"]["snapshot_origin"] = anapec_origin
        source_status["anapec"]["snapshot_jobs"] = len(anapec_jobs)

        if not ep_jobs and not anapec_jobs:
            raise RuntimeError("No public source snapshot available")

        validation = _validate_aggregate([*ep_jobs, *anapec_jobs], now)
        jobs = validation.pop("jobs")
        source_dir = run_dir / "source"
        index_dir = run_dir / "index"
        write_json(source_dir / "jobs.json", jobs)
        write_json(source_dir / "audit.json", {
            "gate": "PASS",
            "generated_at": now.isoformat(),
            "sources": source_status,
            **validation,
        })

        ok, error = call([
            sys.executable,
            str(REPO / "build_public_search_index.py"),
            "--input",
            str(source_dir / "jobs.json"),
            "--output",
            str(index_dir),
            "--min-coverage",
            str(args.min_coverage),
        ])
        if not ok:
            raise RuntimeError(f"aggregate taxonomy build failed: {error}")

        index = read_json(index_dir / "search_index.json")
        indexed_jobs = index.get("jobs") or []
        if len(indexed_jobs) != len(jobs):
            raise RuntimeError(f"Aggregate index count mismatch: source={len(jobs)} index={len(indexed_jobs)}")
        for job in indexed_jobs:
            if not is_job_visible_now(job, now):
                raise RuntimeError(f"Aggregate contains invisible job: {job.get('uuid')}")
            for match in job.get("profession_matches") or []:
                if match.get("confidence") not in {"EXACT", "STRONG"}:
                    raise RuntimeError(f"Unsafe aggregate profession match: {job.get('uuid')}")

        public_source_status = {
            name: {
                "refresh_attempted": bool(status.get("refresh_attempted")),
                "refresh_ok": bool(status.get("refresh_ok")),
                "snapshot_origin": status.get("snapshot_origin", "none"),
                "snapshot_jobs": int(status.get("snapshot_jobs") or 0),
            }
            for name, status in source_status.items()
        }
        manifest = {
            "source": "public",
            "published_at": now.isoformat(),
            "run_id": run_id,
            "mode": mode,
            "jobs": len(indexed_jobs),
            "source_counts": dict(sorted(Counter(str(j.get("source") or "unknown") for j in indexed_jobs).items())),
            "sources": public_source_status,
            "gate": "PASS",
        }
        write_json(run_dir / "manifest.json", manifest)

        current = aggregate_runtime / "current"
        previous = aggregate_runtime / "previous"
        current.mkdir(parents=True, exist_ok=True)
        previous.mkdir(parents=True, exist_ok=True)
        if (current / "search_index.json").exists():
            atomic_copy(current / "search_index.json", previous / "search_index.json")
        if (current / "manifest.json").exists():
            atomic_copy(current / "manifest.json", previous / "manifest.json")
        atomic_copy(source_dir / "jobs.json", current / "jobs.json")
        atomic_copy(source_dir / "audit.json", current / "audit.json")
        atomic_copy(run_dir / "manifest.json", current / "manifest.json")
        # Index last for atomic user-facing switch.
        atomic_copy(index_dir / "search_index.json", current / "search_index.json")

        runs = sorted([p for p in (aggregate_runtime / "runs").iterdir() if p.is_dir()], reverse=True)
        for old in runs[max(args.keep_runs, 1):]:
            shutil.rmtree(old, ignore_errors=True)

        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        print("MASARI_PUBLIC_AGGREGATE_GATE=PASS")
        return 0
    except Exception as exc:
        write_json(run_dir / "failure.json", {
            "run_id": run_id,
            "failed_at": datetime.now(TZ).isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
            "sources": source_status,
        })
        print(f"MASARI_PUBLIC_AGGREGATE_GATE=FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
