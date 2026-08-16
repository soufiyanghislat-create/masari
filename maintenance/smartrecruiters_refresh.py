#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse
from zoneinfo import ZoneInfo

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

import requests

TZ = ZoneInfo("Africa/Casablanca")
REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from smartrecruiters_adapter import normalize_smartrecruiters_job  # noqa: E402
from search import is_job_visible_now  # noqa: E402

API_HOST = "api.smartrecruiters.com"
API_BASE = f"https://{API_HOST}/v1/companies"
SOURCE = "smartrecruiters"
PAGE_LIMIT = 100
USER_AGENT = "Masari/1.0 (SmartRecruiters official public posting refresh)"


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


def validate_official_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != API_HOST:
        raise RuntimeError(f"non-official SmartRecruiters API URL rejected: {url}")
    return url


def get_json(session: requests.Session, url: str) -> dict:
    validate_official_url(url)
    response = session.get(url, timeout=(12, 30), allow_redirects=False)
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code} for {url}: {response.text[:300]}")
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"non-object JSON from {url}")
    return data


def list_url(company_identifier: str, offset: int) -> str:
    params = urlencode({
        "country": "ma",
        "destination": "PUBLIC",
        "limit": PAGE_LIMIT,
        "offset": offset,
    })
    return validate_official_url(f"{API_BASE}/{quote(company_identifier)}/postings?{params}")


def detail_url(company_identifier: str, posting_id: str) -> str:
    return validate_official_url(
        f"{API_BASE}/{quote(company_identifier)}/postings/{quote(posting_id)}"
    )


def fetch_company(session: requests.Session, company_identifier: str) -> list[dict]:
    jobs: list[dict] = []
    offset = 0
    for _ in range(20):
        payload = get_json(session, list_url(company_identifier, offset))
        content = payload.get("content")
        if not isinstance(content, list):
            raise RuntimeError(f"{company_identifier}: missing content[]")
        rows = [x for x in content if isinstance(x, dict)]
        jobs.extend(rows)
        if len(rows) < PAGE_LIMIT:
            break
        offset += len(rows)
        try:
            if offset >= int(payload.get("totalFound")):
                break
        except Exception:
            pass
    return jobs


def build_source_row(company_identifier: str, listing: dict, detail: dict) -> dict:
    posting_id = str(listing.get("uuid") or listing.get("id") or "").strip()
    if not posting_id:
        raise RuntimeError(f"{company_identifier}: missing posting id")
    company_obj = listing.get("company") if isinstance(listing.get("company"), dict) else {}
    type_obj = listing.get("typeOfEmployment") if isinstance(listing.get("typeOfEmployment"), dict) else {}
    return {
        "global_id": f"smartrecruiters:{company_identifier}:{posting_id}",
        "source": SOURCE,
        "source_label": "SmartRecruiters",
        "source_company_identifier": company_identifier,
        "source_posting_id": posting_id,
        "listing_title": listing.get("name"),
        "job_name": listing.get("name"),
        "company": company_obj.get("name"),
        "publication_date": listing.get("releasedDate"),
        "deadline": None,
        "positions": None,
        "location": listing.get("location"),
        "recruitment_type": type_obj.get("label"),
        "contract_type": type_obj.get("label"),
        "application_type": "SmartRecruiters",
        "application_site": detail.get("applyUrl"),
        "application_url": detail.get("applyUrl"),
        "source_url": detail.get("applyUrl"),
        "source_payload": {"listing": listing, "detail": detail},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Refresh SmartRecruiters Morocco independently and promote only verified LKG")
    ap.add_argument("--runtime-dir", default="runtime/public/smartrecruiters")
    ap.add_argument(
        "--companies",
        default=str(REPO / "sources" / "public" / "smartrecruiters" / "companies.json"),
    )
    ap.add_argument("--keep-runs", type=int, default=4)
    args = ap.parse_args()

    runtime = Path(args.runtime_dir)
    if not runtime.is_absolute():
        runtime = REPO / runtime
    companies_path = Path(args.companies)
    if not companies_path.is_absolute():
        companies_path = REPO / companies_path

    companies = read_json(companies_path)
    if not isinstance(companies, list) or not companies:
        raise SystemExit("SmartRecruiters company registry is empty")

    runtime.mkdir(parents=True, exist_ok=True)
    now = datetime.now(TZ)
    run_id = now.strftime("%Y%m%d-%H%M%S")
    run_dir = runtime / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    session = requests.Session()
    session.headers.update({"Accept": "application/json", "User-Agent": USER_AGENT})

    try:
        normalized: list[dict] = []
        company_status: list[dict] = []
        rejects = Counter()

        for seed in companies:
            cid = str(seed.get("identifier") or "").strip()
            label = str(seed.get("label") or cid).strip()
            if not cid:
                raise RuntimeError("SmartRecruiters registry contains empty identifier")

            try:
                listings = fetch_company(session, cid)
                accepted = 0
                for listing in listings:
                    location = listing.get("location")
                    country = ""
                    if isinstance(location, dict):
                        country = str(
                            location.get("country") or location.get("countryCode") or ""
                        ).strip().casefold()
                    if country not in {"ma", "maroc", "morocco"}:
                        rejects["not_morocco"] += 1
                        continue

                    # Cheap source-date gate before fetching detail.
                    publication = str(listing.get("releasedDate") or "").strip()
                    if not publication:
                        rejects["missing_publication_date"] += 1
                        continue
                    probe = {
                        "source": SOURCE,
                        "publication_date": publication,
                        "deadline": None,
                    }
                    if not is_job_visible_now(probe, now):
                        rejects["stale_or_future"] += 1
                        continue

                    posting_id = str(listing.get("uuid") or listing.get("id") or "").strip()
                    if not posting_id:
                        rejects["missing_posting_id"] += 1
                        continue
                    detail = get_json(session, detail_url(cid, posting_id))
                    row = normalize_smartrecruiters_job(
                        build_source_row(cid, listing, detail)
                    )
                    if not is_job_visible_now(row, now):
                        raise RuntimeError(
                            f"{row.get('global_id')}: normalized visibility gate failed"
                        )
                    normalized.append(row)
                    accepted += 1

                company_status.append({
                    "identifier": cid,
                    "label": label,
                    "gate": "PASS",
                    "listed": len(listings),
                    "accepted": accepted,
                })
            except Exception as exc:
                company_status.append({
                    "identifier": cid,
                    "label": label,
                    "gate": "FAIL",
                    "error": f"{type(exc).__name__}: {exc}",
                })

        failed = [x for x in company_status if x.get("gate") != "PASS"]
        if failed:
            raise RuntimeError(
                f"company access gate failed for {len(failed)}/{len(company_status)} companies"
            )
        if not normalized:
            raise RuntimeError("SmartRecruiters returned no fresh Morocco jobs")

        ids = [str(j.get("global_id") or "") for j in normalized]
        urls = [str(j.get("url") or "") for j in normalized]
        if any(not x for x in ids) or len(ids) != len(set(ids)):
            raise RuntimeError("SmartRecruiters global ID uniqueness gate failed")
        if any(not x for x in urls) or len(urls) != len(set(urls)):
            raise RuntimeError("SmartRecruiters URL uniqueness gate failed")
        if any(j.get("source") != SOURCE for j in normalized):
            raise RuntimeError("SmartRecruiters source identity gate failed")
        if any(j.get("employment_sector") != "private" for j in normalized):
            raise RuntimeError("SmartRecruiters private-sector gate failed")
        if any(j.get("deadline") is not None for j in normalized):
            raise RuntimeError("SmartRecruiters no-fabricated-deadline gate failed")
        if any(not j.get("publication_date") for j in normalized):
            raise RuntimeError("SmartRecruiters explicit publication-date gate failed")

        normalized.sort(
            key=lambda j: (
                str(j.get("publication_date") or ""),
                str(j.get("global_id") or ""),
            ),
            reverse=True,
        )
        write_json(run_dir / "jobs.json", normalized)
        registry_sha = hashlib.sha256(companies_path.read_bytes()).hexdigest()
        audit = {
            "source": SOURCE,
            "generated_at": now.isoformat(),
            "gate": "PASS",
            "jobs": len(normalized),
            "companies": company_status,
            "company_access": f"{len(company_status)}/{len(company_status)}",
            "registry_sha256": registry_sha,
            "rejects": dict(rejects),
            "hard_rules": {
                "official_api_only": True,
                "tls_verification": True,
                "country": "ma",
                "destination": "PUBLIC",
                "max_job_age_days": 15,
                "explicit_publication_date": True,
                "deadline_fabrication": False,
                "positions_fabrication": False,
            },
        }
        write_json(run_dir / "audit.json", audit)
        manifest = {
            "source": SOURCE,
            "version": "v1",
            "published_at": now.isoformat(),
            "run_id": run_id,
            "jobs": len(normalized),
            "source_gate": "PASS",
            "quality_gate": "PASS",
            "registry_sha256": registry_sha,
            "gate": "PASS",
        }
        write_json(run_dir / "manifest.json", manifest)

        current = runtime / "current"
        previous = runtime / "previous"
        current.mkdir(parents=True, exist_ok=True)
        previous.mkdir(parents=True, exist_ok=True)
        for name in ("jobs.json", "audit.json", "manifest.json"):
            if (current / name).exists():
                atomic_copy(current / name, previous / name)
        atomic_copy(run_dir / "jobs.json", current / "jobs.json")
        atomic_copy(run_dir / "audit.json", current / "audit.json")
        atomic_copy(run_dir / "manifest.json", current / "manifest.json")

        runs = sorted(
            [p for p in (runtime / "runs").iterdir() if p.is_dir()],
            reverse=True,
        )
        for old in runs[max(args.keep_runs, 1):]:
            shutil.rmtree(old, ignore_errors=True)

        print(f"SMARTRECRUITERS_LKG_COMPANY_ACCESS={len(company_status)}/{len(company_status)}")
        print(f"SMARTRECRUITERS_LKG_JOBS={len(normalized)}")
        print("SMARTRECRUITERS_LKG_GATE=PASS")
        return 0
    except Exception as exc:
        write_json(
            run_dir / "failure.json",
            {
                "failed_at": datetime.now(TZ).isoformat(),
                "error": f"{type(exc).__name__}: {exc}",
                "companies": company_status if "company_status" in locals() else [],
            },
        )
        print(
            f"SMARTRECRUITERS_LKG_GATE=FAIL: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
