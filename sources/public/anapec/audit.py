from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .application import build_application
from .tls import native_tls_available

TZ = ZoneInfo("Africa/Casablanca")
MAX_JOB_AGE_DAYS = 15


def is_visible_anapec_job(job: dict, now: datetime | None = None) -> bool:
    now = now or datetime.now(TZ)
    raw = job.get("publication_date")
    if not raw:
        return False
    try:
        published = date.fromisoformat(str(raw)[:10])
    except ValueError:
        return False
    age = (now.date() - published).days
    return 0 <= age <= MAX_JOB_AGE_DAYS


def _write(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_audit(output_dir: str | Path = "output/anapec", max_pages: int = 250) -> dict:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # ANAPEC uses an explicit truststore.SSLContext in every Requests Session.
    # Refuse network I/O unless strict native TLS verification is available.
    native_truststore = native_tls_available()
    if not native_truststore:
        raise RuntimeError("ANAPEC audit requires strict native TLS trust")

    from .crawler import crawl

    # Any unverified HTTPS request is a hard source-gate failure.
    import warnings
    from urllib3.exceptions import InsecureRequestWarning
    warnings.filterwarnings("error", category=InsecureRequestWarning)

    def progress(s: dict) -> None:
        print(
            "ANAPEC_CRAWL "
            f"page={s['page']} offers={s['offer_count']} "
            f"dates={s['publication_date_min']}..{s['publication_date_max']} "
            f"stale_guard={s['stale_guard_streak']}"
        )

    result = crawl(max_pages=max_pages, progress=progress)
    all_jobs = result.jobs
    visible = []
    rejected = []
    for job in all_jobs:
        enriched = dict(job)
        enriched["application"] = build_application(job["source_reference"])
        if is_visible_anapec_job(enriched):
            visible.append(enriched)
        else:
            rejected.append({"job": enriched, "reason": "outside_15_day_publication_window"})

    discovered_ids = {o.source_offer_id for o in result.discovered}
    parsed_ids = {j["source_offer_id"] for j in all_jobs}
    identity_ok = len(parsed_ids) == len(all_jobs)
    scanned_complete = not result.detail_failures and parsed_ids == discovered_ids
    clean_termination = result.termination_reason in {"empty_page", "no_next_page", "freshness_frontier"}
    fresh_window_complete = bool(result.freshness_frontier_confirmed and result.date_order_ok and clean_termination)
    gate_pass = bool(discovered_ids) and identity_ok and scanned_complete and fresh_window_complete

    audit = {
        "source": "anapec",
        "generated_at": datetime.now(TZ).isoformat(),
        "native_truststore": native_truststore,
        "tls_policy": "explicit_truststore_sslcontext_cert_required",
        "discovery_scope": "newest_first_until_15_day_freshness_frontier",
        "policy": {
            "max_job_age_days": MAX_JOB_AGE_DAYS,
            "deadline_required": False,
            "publication_date_required": True,
            "fabricate_deadline": False,
            "stale_guard_pages": 3,
            "pagination_policy": "follow_source_advertised_links_only",
        },
        "discovered_count": len(discovered_ids),
        "parsed_count": len(all_jobs),
        "visible_count": len(visible),
        "rejected_count": len(rejected),
        "detail_failure_count": len(result.detail_failures),
        "pages_fetched": result.pages_fetched,
        "termination_reason": result.termination_reason,
        "date_order_ok": result.date_order_ok,
        "freshness_frontier_confirmed": result.freshness_frontier_confirmed,
        "page_summaries": result.page_summaries,
        "checks": {
            "identity_unique": identity_ok,
            "all_scanned_details_parsed": scanned_complete,
            "publication_date_order_verified": result.date_order_ok,
            "fresh_15_day_window_complete": fresh_window_complete,
        },
        "gate": "PASS" if gate_pass else "FAIL",
    }

    _write(out / "all_offers.json", all_jobs)
    _write(out / "jobs.json", visible)
    _write(out / "rejected.json", rejected)
    _write(out / "detail_failures.json", result.detail_failures)
    _write(out / "page_summaries.json", result.page_summaries)
    _write(out / "audit.json", audit)
    print(f"ANAPEC_GATE={audit['gate']}")
    return audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="output/anapec")
    parser.add_argument("--max-pages", type=int, default=250)
    args = parser.parse_args()
    audit = run_audit(args.output, args.max_pages)
    return 0 if audit["gate"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
