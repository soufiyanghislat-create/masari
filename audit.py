from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from crawler import SCOPES, crawl_details, crawl_scope, robots_allows

TZ = ZoneInfo("Africa/Casablanca")
MAX_AGE_DAYS = 15


def _aware_local(iso_value: str) -> datetime:
    return datetime.fromisoformat(iso_value).replace(tzinfo=TZ)


def is_fresh_and_open(job: dict, now: datetime) -> tuple[bool, str]:
    pub = _aware_local(job["publication_date"])
    deadline = _aware_local(job["deadline"])
    age = now.date() - pub.date()
    if age.days < 0:
        return False, "publication_in_future"
    if age.days > MAX_AGE_DAYS:
        return False, "older_than_15_days"
    if deadline < now:
        return False, "deadline_expired"
    return True, "accepted"


def main() -> int:
    ap = argparse.ArgumentParser(description="Independent Emploi-Public completeness audit")
    ap.add_argument("--output", default="output", help="Output directory")
    ap.add_argument("--no-gate", action="store_true", help="Write audit but do not fail on incomplete coverage")
    args = ap.parse_args()

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.now(TZ)

    robots_ok, robots_note = robots_allows()
    if not robots_ok:
        audit = {
            "source": "emploi-public.ma",
            "run_at": now.isoformat(),
            "robots_allowed": False,
            "robots_note": robots_note,
            "gate": "FAIL",
            "reason": "robots_disallow_or_unavailable",
        }
        (out / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        return 2

    scope_results = []
    for scope in SCOPES:
        result = crawl_scope(scope)
        scope_results.append(result)
        print(
            f"scope={scope} official_before={result.official_before} "
            f"official_after={result.official_after} discovered={len(set(result.discovered_urls))} "
            f"pages={result.pages_successful}/{result.pages_requested} "
            f"stable={result.stable_counter} complete={result.listing_complete}"
        )
        for err in result.errors:
            print(f"scope_error scope={scope} {err}")

    details = crawl_details(scope_results)
    all_jobs = [job.to_dict() for job in details.jobs]
    expected_urls = {u for r in scope_results for u in r.discovered_urls}
    parsed_urls = {j["url"] for j in all_jobs}
    missing_detail_urls = sorted(expected_urls - parsed_urls)

    accepted = []
    rejected = []
    reasons: dict[str, int] = {}
    for job in all_jobs:
        ok, reason = is_fresh_and_open(job, now)
        reasons[reason] = reasons.get(reason, 0) + 1
        if ok:
            accepted.append(job)
        else:
            rejected.append({"uuid": job["uuid"], "url": job["url"], "reason": reason})

    # Gate is about source completeness, not business filtering. A 15-day-old or
    # expired ad may be rejected from Masari while still needing to be crawled.
    listing_gate = all(r.listing_complete for r in scope_results)
    detail_gate = len(missing_detail_urls) == 0 and len(details.failures) == 0 and len(parsed_urls) == len(expected_urls)
    gate = robots_ok and listing_gate and detail_gate

    scope_audit = {}
    for r in scope_results:
        discovered = len(set(r.discovered_urls))
        official = r.official_after
        scope_audit[r.scope] = {
            "official_before": r.official_before,
            "official_after": official,
            "discovered": discovered,
            "missing_count": max(official - discovered, 0),
            "extra_count": max(discovered - official, 0),
            "listing_coverage_pct": round((discovered / official * 100) if official else 100.0, 2),
            "counter_stable": r.stable_counter,
            "pages_requested": r.pages_requested,
            "pages_successful": r.pages_successful,
            "errors": r.errors,
            "complete": r.listing_complete,
        }

    today_jobs = [j for j in all_jobs if _aware_local(j["publication_date"]).date() == now.date()]
    today_positions = sum(int(j.get("positions") or 0) for j in today_jobs)

    audit = {
        "source": "emploi-public.ma",
        "run_at": now.isoformat(),
        "timezone": "Africa/Casablanca",
        "robots_allowed": robots_ok,
        "robots_note": robots_note,
        "scopes": scope_audit,
        "expected_detail_pages": len(expected_urls),
        "parsed_detail_pages": len(parsed_urls),
        "detail_coverage_pct": round((len(parsed_urls) / len(expected_urls) * 100) if expected_urls else 100.0, 2),
        "detail_failures": details.failures,
        "missing_detail_urls": missing_detail_urls,
        "all_announcements_parsed": len(all_jobs),
        "fresh_open_announcements": len(accepted),
        "fresh_open_positions": sum(int(j.get("positions") or 0) for j in accepted),
        "published_today_announcements": len(today_jobs),
        "published_today_positions": today_positions,
        "rejected_announcements": len(rejected),
        "decision_counts": reasons,
        "gate": "PASS" if gate else "FAIL",
    }

    (out / "jobs.json").write_text(json.dumps(accepted, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "all_announcements.json").write_text(json.dumps(all_jobs, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "rejected.json").write_text(json.dumps(rejected, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== EMPLOI-PUBLIC AUDIT ===")
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    print(f"\nEMPLOI_PUBLIC_GATE={audit['gate']}")

    if gate or args.no_gate:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
