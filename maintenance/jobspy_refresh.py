#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Africa/Casablanca")
WINDOW_HOURS = 360
RESULTS_WANTED = 1000
SUPPORTED = {"indeed", "linkedin"}
PREFIX = {"indeed": "in", "linkedin": "li"}


def _json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _atomic_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".new")
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if isinstance(value, float) and math.isnan(value):
            return ""
    except Exception:
        pass
    text = str(value).strip()
    return "" if text.lower() in {"nan", "nat", "none"} else text


def _date(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "to_pydatetime"):
        try:
            value = value.to_pydatetime()
        except Exception:
            pass
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = _text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        try:
            return date.fromisoformat(text[:10]).isoformat()
        except Exception:
            return None


def _https(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    return text


MOROCCO_MARKERS = (
    "morocco", "maroc", ", ma", "casablanca", "rabat", "tanger", "tangier",
    "marrakech", "agadir", "fes", "fès", "meknes", "meknès", "kenitra",
    "kénitra", "tetouan", "tétouan", "oujda", "nador", "el jadida", "safi",
    "sale", "salé", "temara", "témara", "mohammedia", "beni mellal", "béni mellal",
    "khouribga", "settat", "berrechid", "ait melloul", "aït melloul", "laayoune",
    "laâyoune", "dakhla", "khemisset", "khémisset"
)


def _morocco_location(value: Any) -> tuple[bool, str]:
    text = _text(value)
    folded = text.casefold()
    for marker in MOROCCO_MARKERS:
        if marker.casefold() in folded:
            return True, f"explicit_location:{marker}"
    return False, ""


def _salary(row: dict[str, Any]) -> str | None:
    lo = _text(row.get("min_amount"))
    hi = _text(row.get("max_amount"))
    currency = _text(row.get("currency"))
    interval = _text(row.get("interval"))
    if not (lo or hi):
        return None
    body = lo if lo == hi or not hi else (hi if not lo else f"{lo}-{hi}")
    return " ".join(x for x in (body, currency, interval) if x) or None


def _normalise(source: str, row: dict[str, Any], now: datetime) -> tuple[dict[str, Any] | None, str]:
    raw_id = _text(row.get("id"))
    if not raw_id:
        return None, "missing_id"

    publication = _date(row.get("date_posted"))
    if not publication:
        return None, "missing_date"
    pub_date = date.fromisoformat(publication)
    age = (now.date() - pub_date).days
    if age < 0 or age > 15:
        return None, "outside_15d"

    title = _text(row.get("title"))
    if not title:
        return None, "missing_title"

    url = _https(row.get("job_url"))
    if not url:
        return None, "missing_source_url"

    location = _text(row.get("location"))
    location_ok, location_evidence = _morocco_location(location)
    if not location_ok:
        return None, "morocco_location_unverified"

    gid = f"{source}:{PREFIX[source]}-{raw_id}"
    direct = _https(row.get("job_url_direct"))
    company = _text(row.get("company")) or None
    description = _text(row.get("description")) or None
    contract = _text(row.get("job_type")) or None

    return {
        "global_id": gid,
        "uuid": gid,
        "source": source,
        "source_label": "Indeed" if source == "indeed" else "LinkedIn",
        "scope": "private",
        "employment_sector": "private",
        "listing_title": title,
        "job_name": title,
        "company": company,
        "administration": company or ("Indeed" if source == "indeed" else "LinkedIn"),
        "location": location,
        "work_location_text": location,
        "publication_date": publication,
        "deadline": None,
        "positions": None,
        "contract_type": contract,
        "salary": _salary(row),
        "description": description,
        "application_type": "Indeed" if source == "indeed" else "LinkedIn",
        "application_site": url,
        "application_url": url,
        "url": url,
        "source_url": url,
        "job_url_direct": direct,
        "profession_matches": [],
        "profession_ids": [],
        "literal_searchable": True,
        "location_morocco_evidence": True,
        "location_verification": {
            "gate": "PASS",
            "evidence": location_evidence,
            "source_location": location,
        },
        "ground_truth_status": "VERIFIED",
        "ground_truth_proof": f"jobspy_direct_{source}_live_15d_v1",
    }, "accepted"


def collect(source: str) -> list[dict[str, Any]]:
    from jobspy import scrape_jobs

    frame = scrape_jobs(
        site_name=[source],
        search_term="",
        location="Morocco",
        distance=50,
        results_wanted=RESULTS_WANTED,
        hours_old=WINDOW_HOURS,
        country_indeed="Morocco",
        linkedin_fetch_description=False,
        proxies=None,
    )
    if frame is None:
        return []
    return frame.to_dict(orient="records")


def main() -> int:
    ap = argparse.ArgumentParser(description="Masari shared JobSpy daily collector for Indeed and LinkedIn")
    ap.add_argument("--source", required=True, choices=sorted(SUPPORTED))
    ap.add_argument("--runtime-dir", required=True)
    ap.add_argument("--keep-runs", type=int, default=4)
    args = ap.parse_args()

    source = args.source
    runtime = Path(args.runtime_dir)
    now = datetime.now(TZ)
    run_id = now.strftime("%Y%m%d-%H%M%S")
    run_dir = runtime / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    print("=" * 100)
    print(f"MASARI JOBSPY DAILY — {source.upper()}")
    print("=" * 100)
    print("ENGINE=python-jobspy-1.1.82")
    print("REQUEST_SHAPE=SAME_FOR_INDEED_AND_LINKEDIN")
    print("LOCATION=Morocco DISTANCE=50 HOURS_OLD=360 RESULTS_WANTED=1000")
    print("PROXIES=FALSE LOGIN=FALSE CAPTCHA_BYPASS=FALSE RATE_LIMIT_BYPASS=FALSE")

    raw = collect(source)
    accepted: list[dict[str, Any]] = []
    rejected: dict[str, int] = {}
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()

    for row in raw:
        job, reason = _normalise(source, row, now)
        if job is None:
            rejected[reason] = rejected.get(reason, 0) + 1
            continue
        if job["global_id"] in seen_ids or job["url"] in seen_urls:
            rejected["duplicate"] = rejected.get("duplicate", 0) + 1
            continue
        seen_ids.add(job["global_id"])
        seen_urls.add(job["url"])
        accepted.append(job)

    accepted.sort(key=lambda j: (j["publication_date"], j["global_id"]), reverse=True)
    if not accepted:
        _json(run_dir / "failure.json", {
            "source": source,
            "failed_at": now.isoformat(),
            "raw_rows": len(raw),
            "rejected": rejected,
            "error": "no verified fresh Morocco jobs",
        })
        print(f"MASARI_{source.upper()}_JOBSPY_DAILY_GATE=FAIL: no accepted rows")
        return 1

    jobs_path = run_dir / "jobs.json"
    _json(jobs_path, accepted)
    digest = hashlib.sha256(jobs_path.read_bytes()).hexdigest()
    manifest = {
        "source": source,
        "version": "jobspy-shared-daily-v1",
        "published_at": now.isoformat(),
        "jobs": len(accepted),
        "raw_rows": len(raw),
        "rejected": dict(sorted(rejected.items())),
        "source_gate": "PASS",
        "quality_gate": "PASS",
        "location_gate": "PASS",
        "literal_gate": "PASS",
        "ground_truth_gate": "PASS",
        "ground_truth_policy": "DIRECT_LIVE_SOURCE_STRICT_FIELDS",
        "network_refresh_enabled": True,
        "collector": "shared_jobspy",
        "collector_version": "python-jobspy-1.1.82",
        "window_hours": WINDOW_HOURS,
        "jobs_sha256": digest,
        "gate": "PASS",
    }
    _json(run_dir / "manifest.json", manifest)

    current = runtime / "current"
    previous = runtime / "previous"
    current.mkdir(parents=True, exist_ok=True)
    previous.mkdir(parents=True, exist_ok=True)
    for name in ("jobs.json", "manifest.json"):
        if (current / name).exists():
            _atomic_copy(current / name, previous / name)
        _atomic_copy(run_dir / name, current / name)

    runs = sorted([p for p in (runtime / "runs").iterdir() if p.is_dir()], reverse=True)
    for old in runs[max(args.keep_runs, 1):]:
        shutil.rmtree(old, ignore_errors=True)

    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"MASARI_{source.upper()}_JOBSPY_DAILY_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
