#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Africa/Casablanca")
MAX_JOB_AGE_DAYS = 15

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from crawler import SCOPES, ScopeResult, crawl_details, crawl_scope, robots_allows  # noqa: E402


def local_dt(value: object) -> datetime:
    dt = datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def fresh_and_open(job: dict, now: datetime) -> tuple[bool, str]:
    publication = job.get("publication_date")
    deadline = job.get("deadline")
    if not publication:
        return False, "missing_publication_date"
    if not deadline:
        return False, "missing_deadline"

    try:
        pub = local_dt(publication)
        end = local_dt(deadline)
    except (TypeError, ValueError):
        return False, "invalid_date"

    age_days = (now.date() - pub.date()).days
    if age_days < 0:
        return False, "publication_in_future"
    if age_days > MAX_JOB_AGE_DAYS:
        return False, "older_than_15_days"
    if end < now:
        return False, "deadline_expired"
    return True, "accepted"


def run(cmd: list[str], *, cwd: Path = REPO) -> None:
    printable = " ".join(str(x) for x in cmd)
    print(f"\n$ {printable}", flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def scope_summary(result: ScopeResult) -> dict:
    return {
        "official_before": result.official_before,
        "official_after": result.official_after,
        "discovered": len(set(result.discovered_urls)),
        "target_pages": result.target_pages,
        "pages_requested": result.pages_requested,
        "pages_successful": result.pages_successful,
        "stable_counter": result.stable_counter,
        "listing_complete": result.listing_complete,
        "errors": result.errors,
    }


def full_source_refresh(run_dir: Path, now: datetime) -> tuple[Path, dict]:
    source_dir = run_dir / "source"
    run([sys.executable, "-u", str(REPO / "audit.py"), "--output", str(source_dir)])

    audit = read_json(source_dir / "audit.json")
    if audit.get("gate") != "PASS":
        raise RuntimeError("EMPLOI_PUBLIC_GATE did not pass")

    archive = source_dir / "all_announcements.json"
    if not archive.exists():
        raise RuntimeError("Full refresh did not create all_announcements.json")

    return archive, {"mode": "full", "source_audit": audit}


def quick_source_refresh(
    run_dir: Path,
    current_dir: Path,
    now: datetime,
) -> tuple[Path, dict]:
    current_archive = current_dir / "all_announcements.json"
    if not current_archive.exists():
        raise RuntimeError(
            "Quick refresh requires an existing archive. Run --mode full first."
        )

    robots_ok, robots_note = robots_allows()
    if not robots_ok:
        raise RuntimeError(f"robots gate failed: {robots_note}")

    scope_results = [crawl_scope(scope) for scope in SCOPES]
    incomplete = [r.scope for r in scope_results if not r.listing_complete]
    if incomplete:
        raise RuntimeError(
            "Listing reconciliation incomplete for: " + ", ".join(incomplete)
        )

    old_jobs = read_json(current_archive)
    old_by_url = {str(job.get("url")): job for job in old_jobs if job.get("url")}

    current_scope_for_url: dict[str, str] = {}
    current_title_for_url: dict[str, str] = {}
    for result in scope_results:
        for url in result.discovered_urls:
            current_scope_for_url[url] = result.scope
            current_title_for_url[url] = result.titles.get(url, "")

    current_urls = set(current_scope_for_url)
    old_urls = set(old_by_url)

    removed_urls = sorted(old_urls - current_urls)
    new_urls = current_urls - old_urls
    changed_title_urls = {
        url
        for url in current_urls & old_urls
        if str(old_by_url[url].get("listing_title") or "")
        != str(current_title_for_url.get(url) or "")
    }

    recent_or_open_urls: set[str] = set()
    for url in current_urls & old_urls:
        job = old_by_url[url]
        try:
            pub = local_dt(job.get("publication_date"))
            end = local_dt(job.get("deadline"))
        except (TypeError, ValueError):
            recent_or_open_urls.add(url)
            continue

        age = (now.date() - pub.date()).days
        if age <= MAX_JOB_AGE_DAYS + 1 or end >= now:
            recent_or_open_urls.add(url)

    refresh_urls = set(new_urls) | changed_title_urls | recent_or_open_urls

    subset_results: list[ScopeResult] = []
    for original in scope_results:
        urls = [u for u in original.discovered_urls if u in refresh_urls]
        subset_results.append(
            ScopeResult(
                scope=original.scope,
                official_before=len(urls),
                official_after=len(urls),
                target_pages=0,
                discovered_urls=urls,
                titles={u: original.titles.get(u, "") for u in urls},
                pages_requested=0,
                pages_successful=0,
                stable_counter=True,
                listing_complete=True,
                errors=[],
            )
        )

    details = crawl_details(subset_results)
    if details.failures:
        raise RuntimeError(
            "Quick detail refresh had failures; refusing publish: "
            + json.dumps(details.failures, ensure_ascii=False)
        )

    retired = set(details.retired_redirects)
    if retired:
        raise RuntimeError(
            f"{len(retired)} detail URL(s) retired during listing reconciliation; "
            "refusing atomic publish"
        )

    merged = {
        url: dict(job)
        for url, job in old_by_url.items()
        if url in current_urls
    }

    for job in details.jobs:
        data = asdict(job)
        merged[data["url"]] = data

    missing = sorted(current_urls - set(merged))
    if missing:
        raise RuntimeError(
            f"Quick merge missing {len(missing)} live listing URL(s)"
        )

    archive_rows = sorted(
        merged.values(),
        key=lambda j: (str(j.get("publication_date") or ""), str(j.get("uuid") or "")),
        reverse=True,
    )

    source_dir = run_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    archive_path = source_dir / "all_announcements.json"
    write_json(archive_path, archive_rows)

    decision_counts: dict[str, int] = {}
    accepted = []
    rejected = []
    for job in archive_rows:
        ok, reason = fresh_and_open(job, now)
        decision_counts[reason] = decision_counts.get(reason, 0) + 1
        if ok:
            accepted.append(job)
        else:
            rejected.append({
                "uuid": job.get("uuid"),
                "url": job.get("url"),
                "reason": reason,
            })

    write_json(source_dir / "jobs.json", accepted)
    write_json(source_dir / "rejected.json", rejected)

    audit = {
        "source": "emploi-public.ma",
        "mode": "quick",
        "run_at": now.isoformat(),
        "timezone": "Africa/Casablanca",
        "robots_allowed": True,
        "robots_note": robots_note,
        "scopes": {r.scope: scope_summary(r) for r in scope_results},
        "previous_archive_records": len(old_jobs),
        "live_listing_records": len(current_urls),
        "new_listing_urls": len(new_urls),
        "changed_listing_titles": len(changed_title_urls),
        "removed_listing_urls": len(removed_urls),
        "details_refetched": len(refresh_urls),
        "details_parsed": len(details.jobs),
        "fresh_open_announcements": len(accepted),
        "rejected_announcements": len(rejected),
        "decision_counts": decision_counts,
        "gate": "PASS",
    }
    write_json(source_dir / "audit.json", audit)

    return archive_path, {"mode": "quick", "source_audit": audit}


def validate_runtime_index(
    index_path: Path,
    source_jobs_path: Path,
    now: datetime,
) -> dict:
    index_data = read_json(index_path)
    source_jobs = read_json(source_jobs_path)
    jobs = index_data.get("jobs") or []

    if len(jobs) != len(source_jobs):
        raise RuntimeError(
            f"Index/source count mismatch: index={len(jobs)} source={len(source_jobs)}"
        )

    uuids = [str(j.get("uuid") or "") for j in jobs]
    urls = [str(j.get("url") or "") for j in jobs]
    if any(not x for x in uuids) or len(uuids) != len(set(uuids)):
        raise RuntimeError("Runtime index UUID uniqueness gate failed")
    if any(not x for x in urls) or len(urls) != len(set(urls)):
        raise RuntimeError("Runtime index URL uniqueness gate failed")

    visibility_failures = []
    unsafe_matches = []
    for job in jobs:
        ok, reason = fresh_and_open(job, now)
        if not ok:
            visibility_failures.append({
                "uuid": job.get("uuid"),
                "reason": reason,
            })

        for match in job.get("profession_matches") or []:
            if match.get("confidence") not in {"EXACT", "STRONG"}:
                unsafe_matches.append({
                    "uuid": job.get("uuid"),
                    "profession_id": match.get("profession_id"),
                    "confidence": match.get("confidence"),
                })

    if visibility_failures:
        raise RuntimeError(
            f"Runtime visibility gate failed for {len(visibility_failures)} job(s)"
        )
    if unsafe_matches:
        raise RuntimeError(
            f"Unsafe searchable match gate failed for {len(unsafe_matches)} match(es)"
        )

    report = {
        "jobs": len(jobs),
        "unique_uuids": len(set(uuids)),
        "unique_urls": len(set(urls)),
        "visibility_failures": 0,
        "unsafe_searchable_matches": 0,
        "gate": "PASS",
    }
    return report


def run_application_cta_gate(
    run_dir: Path,
    *,
    check_network: bool,
) -> dict:
    source_jobs = run_dir / "source" / "jobs.json"
    report_path = run_dir / "application_cta_audit.json"

    cmd = [
        sys.executable,
        "-u",
        str(REPO / "application_cta_audit.py"),
        "--input",
        str(source_jobs),
        "--output",
        str(report_path),
    ]
    if check_network:
        cmd.append("--check-network")

    run(cmd)
    report = read_json(report_path)
    if report.get("gate") != "PASS":
        raise RuntimeError("MASARI_APPLICATION_CTA_GATE did not pass")
    return report


def validate_and_build(
    run_dir: Path,
    min_coverage: float,
    now: datetime,
) -> Path:
    source_dir = run_dir / "source"
    index_dir = run_dir / "index"

    run([
        sys.executable,
        "-u",
        str(REPO / "build_search_index.py"),
        "--input",
        str(source_dir / "jobs.json"),
        "--output",
        str(index_dir),
        "--min-coverage",
        str(min_coverage),
    ])

    index_path = index_dir / "search_index.json"
    if not index_path.exists():
        raise RuntimeError("Search index was not created")

    report = validate_runtime_index(
        index_path,
        source_dir / "jobs.json",
        now,
    )
    write_json(run_dir / "runtime_validation.json", report)
    print("\n=== MASARI RUNTIME INDEX VALIDATION ===")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("MASARI_RUNTIME_INDEX_GATE=PASS")

    return index_path

def atomic_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".new")
    shutil.copy2(src, tmp)
    with tmp.open("rb") as fh:
        os.fsync(fh.fileno())
    os.replace(tmp, dst)


def publish(
    run_dir: Path,
    runtime_dir: Path,
    mode: str,
    now: datetime,
) -> dict:
    current = runtime_dir / "current"
    previous = runtime_dir / "previous"
    current.mkdir(parents=True, exist_ok=True)
    previous.mkdir(parents=True, exist_ok=True)

    current_index = current / "search_index.json"
    if current_index.exists():
        atomic_copy(current_index, previous / "search_index.json")
        if (current / "manifest.json").exists():
            atomic_copy(current / "manifest.json", previous / "manifest.json")

    source_dir = run_dir / "source"
    index_dir = run_dir / "index"

    index_data = read_json(index_dir / "search_index.json")
    source_audit = read_json(source_dir / "audit.json")
    cta_audit = read_json(run_dir / "application_cta_audit.json")

    manifest = {
        "source": "emploi-public.ma",
        "mode": mode,
        "published_at": now.isoformat(),
        "timezone": "Africa/Casablanca",
        "run_id": run_dir.name,
        "jobs": len(index_data.get("jobs") or []),
        "source_gate": source_audit.get("gate"),
        "application_cta_gate": cta_audit.get("gate"),
        "application_cta_hard_failures": cta_audit.get("hard_failure_count"),
        "application_cta_warnings": cta_audit.get("warning_count"),
        "application_cta_counts": cta_audit.get("cta_counts"),
        "application_channel_counts": cta_audit.get("application_channel_counts"),
        "application_cta_direct_or_document_pct": cta_audit.get(
            "direct_application_or_document_pct"
        ),
        "application_cta_official_detail_fallback_jobs": cta_audit.get(
            "official_detail_fallback_jobs"
        ),
        "application_cta_network_verdict_counts": cta_audit.get(
            "network_verdict_counts"
        ),
    }
    write_json(run_dir / "manifest.json", manifest)

    atomic_copy(source_dir / "all_announcements.json", current / "all_announcements.json")
    atomic_copy(source_dir / "jobs.json", current / "jobs.json")
    atomic_copy(source_dir / "audit.json", current / "audit.json")
    atomic_copy(
        run_dir / "application_cta_audit.json",
        current / "application_cta_audit.json",
    )
    atomic_copy(run_dir / "manifest.json", current / "manifest.json")
    # Search index is replaced last: users see old complete index until this point.
    atomic_copy(index_dir / "search_index.json", current_index)

    return manifest


def prune_runs(runtime_dir: Path, keep: int) -> None:
    runs = runtime_dir / "runs"
    if not runs.exists():
        return
    dirs = sorted([p for p in runs.iterdir() if p.is_dir()], reverse=True)
    for old in dirs[max(keep, 1):]:
        shutil.rmtree(old, ignore_errors=True)


def choose_auto_mode(current_dir: Path, now: datetime) -> str:
    if not (current_dir / "manifest.json").exists():
        return "full"
    if 4 <= now.hour < 8:
        return "full"
    return "quick"


def main() -> int:
    ap = argparse.ArgumentParser(description="Masari atomic daily/quick source refresh")
    ap.add_argument("--runtime-dir", default="runtime/emploi_public")
    ap.add_argument("--mode", choices=("auto", "full", "quick"), default="auto")
    ap.add_argument("--min-coverage", type=float, default=90.0)
    ap.add_argument("--keep-runs", type=int, default=8)
    args = ap.parse_args()

    runtime_dir = Path(args.runtime_dir)
    if not runtime_dir.is_absolute():
        runtime_dir = REPO / runtime_dir
    runtime_dir.mkdir(parents=True, exist_ok=True)

    lock_path = runtime_dir / ".refresh.lock"
    lock_file = lock_path.open("a+")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("MASARI_REFRESH_SKIPPED=LOCKED")
        return 0

    now = datetime.now(TZ)
    mode = args.mode if args.mode != "auto" else choose_auto_mode(runtime_dir / "current", now)

    run_id = now.strftime("%Y%m%d-%H%M%S") + f"-{mode}"
    run_dir = runtime_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    print("=" * 72)
    print("MASARI DAILY SYNC v1")
    print("MODE       :", mode)
    print("TIME       :", now.isoformat())
    print("RUNTIME    :", runtime_dir)
    print("RUN        :", run_dir)
    print("=" * 72)

    try:
        if mode == "full":
            full_source_refresh(run_dir, now)
        else:
            quick_source_refresh(run_dir, runtime_dir / "current", now)

        run_application_cta_gate(
            run_dir,
            check_network=(mode == "full"),
        )
        validate_and_build(run_dir, args.min_coverage, now)
        manifest = publish(run_dir, runtime_dir, mode, now)
        prune_runs(runtime_dir, args.keep_runs)

        print("\n" + json.dumps(manifest, ensure_ascii=False, indent=2))
        print("CURRENT_INDEX:", runtime_dir / "current" / "search_index.json")
        print("MASARI_DAILY_SYNC_GATE=PASS")
        return 0
    except Exception as exc:
        failure = {
            "run_id": run_id,
            "mode": mode,
            "failed_at": datetime.now(TZ).isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
        }
        write_json(run_dir / "failure.json", failure)
        print("\n" + json.dumps(failure, ensure_ascii=False, indent=2), file=sys.stderr)
        print("MASARI_DAILY_SYNC_GATE=FAIL", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
