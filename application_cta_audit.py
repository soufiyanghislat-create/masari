#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import time
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo("Africa/Casablanca")
EMPLOI_PUBLIC_HOSTS = {"emploi-public.ma", "www.emploi-public.ma"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

CTA_EXTERNAL = "POSTULER_EXTERNAL"
CTA_EMPLOI_PUBLIC = "POSTULER_EMPLOI_PUBLIC"
CTA_NOTICE = "APPLICATION_NOTICE"
CTA_ORDER = "OPENING_ORDER"
CTA_DETAIL = "OFFICIAL_DETAIL"

CHANNEL_EXTERNAL = "ONLINE_EXTERNAL"
CHANNEL_EMPLOI_PUBLIC = "ONLINE_EMPLOI_PUBLIC"
CHANNEL_EMAIL = "EMAIL"
CHANNEL_POSTAL = "POSTAL"
CHANNEL_PHYSICAL = "PHYSICAL_DEPOSIT"
CHANNEL_UNDECLARED = "UNDECLARED"


def compact(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalized(value: Any) -> str:
    text = unicodedata.normalize("NFKD", compact(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().replace("_", " ").replace("-", " ")
    return re.sub(r"[^a-z0-9@:/.\s]+", " ", text)


def is_http_url(value: Any) -> bool:
    try:
        p = urlparse(compact(value))
    except Exception:
        return False
    return p.scheme in {"http", "https"} and bool(p.netloc)


def is_email(value: Any) -> bool:
    v = compact(value)
    if v.lower().startswith("mailto:"):
        v = v[7:]
    return bool(EMAIL_RE.fullmatch(v))


def emploi_public_online(application_type: Any) -> bool:
    t = normalized(application_type)
    if "emploi public" not in t:
        return False
    return "depot" in t or t.startswith("sur emploi public") or "en ligne" in t


def application_channel(job: dict) -> str:
    site = compact(job.get("application_site"))
    app_type = normalized(job.get("application_type"))

    if is_http_url(site):
        return CHANNEL_EXTERNAL
    if is_email(site):
        return CHANNEL_EMAIL
    if emploi_public_online(app_type):
        return CHANNEL_EMPLOI_PUBLIC

    email_terms = ("email", "e mail", "courriel", "mail")
    if any(term in app_type for term in email_terms):
        return CHANNEL_EMAIL

    postal_terms = (
        "courrier postal",
        "voie postale",
        "par poste",
        "par courrier",
        "lettre recommandee",
        "recommande",
    )
    if any(term in app_type for term in postal_terms):
        return CHANNEL_POSTAL

    physical_terms = (
        "depot physique",
        "depot au siege",
        "depot au bureau",
        "depot sur place",
        "en personne",
    )
    if any(term in app_type for term in physical_terms):
        return CHANNEL_PHYSICAL

    return CHANNEL_UNDECLARED


def choose_cta(job: dict) -> tuple[str, str]:
    site = compact(job.get("application_site"))
    detail = compact(job.get("url"))
    notice = compact(job.get("application_notice_url"))
    order = compact(job.get("opening_order_url"))

    if is_http_url(site):
        return CTA_EXTERNAL, site
    if emploi_public_online(job.get("application_type")):
        return CTA_EMPLOI_PUBLIC, detail
    if notice:
        return CTA_NOTICE, notice
    if order:
        return CTA_ORDER, order
    return CTA_DETAIL, detail


def _expected_detail(job: dict, url: str) -> bool:
    uuid = compact(job.get("uuid")).lower()
    p = urlparse(url)
    return (
        p.hostname in EMPLOI_PUBLIC_HOSTS
        and p.path.rstrip("/")
        == f"/fr/concours/details/{uuid}"
    )


def _expected_notice(job: dict, url: str) -> bool:
    uuid = compact(job.get("uuid")).lower()
    p = urlparse(url)
    return (
        p.hostname in EMPLOI_PUBLIC_HOSTS
        and p.path.startswith(f"/fr/concours/download/fichiers_att/{uuid}/")
    )


def _expected_order(job: dict, url: str) -> bool:
    uuid = compact(job.get("uuid")).lower()
    p = urlparse(url)
    return (
        p.hostname in EMPLOI_PUBLIC_HOSTS
        and p.path.rstrip("/") == f"/fr/concours/download/arrete/{uuid}"
    )


def structural_record(job: dict) -> dict:
    uuid = compact(job.get("uuid")).lower()
    detail = compact(job.get("url"))
    site = compact(job.get("application_site"))
    notice = compact(job.get("application_notice_url"))
    order = compact(job.get("opening_order_url"))
    channel = application_channel(job)
    cta_mode, target = choose_cta(job)

    failures: list[str] = []
    warnings: list[str] = []

    if not uuid:
        failures.append("MISSING_UUID")
    if not detail or not is_http_url(detail) or not _expected_detail(job, detail):
        failures.append("INVALID_OFFICIAL_DETAIL_URL")

    if notice and (not is_http_url(notice) or not _expected_notice(job, notice)):
        failures.append("INVALID_OR_CROSS_ANNOUNCEMENT_NOTICE_URL")

    if order and (not is_http_url(order) or not _expected_order(job, order)):
        failures.append("INVALID_OR_CROSS_ANNOUNCEMENT_ORDER_URL")

    if site and not is_http_url(site) and not is_email(site):
        warnings.append("UNSTRUCTURED_APPLICATION_SITE")

    if cta_mode == CTA_EXTERNAL and not is_http_url(target):
        failures.append("INVALID_EXTERNAL_APPLICATION_TARGET")
    if cta_mode == CTA_EMPLOI_PUBLIC and not _expected_detail(job, target):
        failures.append("INVALID_EMPLOI_PUBLIC_APPLICATION_TARGET")
    if cta_mode == CTA_NOTICE and not _expected_notice(job, target):
        failures.append("INVALID_NOTICE_TARGET")
    if cta_mode == CTA_ORDER and not _expected_order(job, target):
        failures.append("INVALID_ORDER_TARGET")
    if cta_mode == CTA_DETAIL and not _expected_detail(job, target):
        failures.append("INVALID_DETAIL_FALLBACK_TARGET")

    if channel in {CHANNEL_EMAIL, CHANNEL_POSTAL, CHANNEL_PHYSICAL}:
        if cta_mode == CTA_DETAIL:
            warnings.append("NON_ONLINE_CHANNEL_WITHOUT_ATTACHED_CANDIDATURE_DOCUMENT")

    if channel == CHANNEL_UNDECLARED and cta_mode == CTA_DETAIL:
        warnings.append("OFFICIAL_DETAIL_ONLY")

    return {
        "uuid": uuid,
        "url": detail,
        "administration": compact(job.get("administration")),
        "application_type": compact(job.get("application_type")),
        "application_site": site,
        "application_notice_url": notice,
        "opening_order_url": order,
        "channel": channel,
        "cta_mode": cta_mode,
        "target": target,
        "failures": failures,
        "warnings": warnings,
    }


def _probe_once(url: str, *, expect_pdf: bool, timeout: float) -> dict:
    headers = {
        "User-Agent": "Masari-Application-CTA-Audit/1.0",
        "Accept": "application/pdf,text/html,application/xhtml+xml,*/*;q=0.8",
        "Range": "bytes=0-8191",
    }
    r = requests.get(
        url,
        headers=headers,
        timeout=timeout,
        allow_redirects=True,
        stream=True,
    )
    status = int(r.status_code)
    ctype = str(r.headers.get("Content-Type") or "").lower()
    final_url = str(r.url or url)

    first = b""
    if status < 400 and expect_pdf:
        try:
            first = next(r.iter_content(chunk_size=8192), b"")
        except StopIteration:
            first = b""

    r.close()

    if status in {404, 410}:
        verdict = "BROKEN"
    elif 400 <= status < 500:
        verdict = "RESTRICTED" if status in {401, 403, 405, 429} else "BROKEN"
    elif status >= 500:
        verdict = "TRANSIENT"
    elif expect_pdf:
        is_pdf = "application/pdf" in ctype or first.startswith(b"%PDF")
        verdict = "OK" if is_pdf else "INVALID_DOCUMENT"
    else:
        verdict = "OK"

    return {
        "url": url,
        "status": status,
        "final_url": final_url,
        "content_type": ctype,
        "expect_pdf": expect_pdf,
        "verdict": verdict,
    }


def probe(
    url: str,
    *,
    expect_pdf: bool,
    timeout: float,
    attempts: int = 3,
) -> dict:
    last: dict | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            last = _probe_once(url, expect_pdf=expect_pdf, timeout=timeout)
            last["attempts"] = attempt
            if last["verdict"] != "TRANSIENT":
                return last
        except requests.RequestException as exc:
            last = {
                "url": url,
                "status": None,
                "final_url": "",
                "content_type": "",
                "expect_pdf": expect_pdf,
                "verdict": "TRANSIENT",
                "error": f"{type(exc).__name__}: {exc}",
                "attempts": attempt,
            }
        if attempt < attempts:
            time.sleep(0.6 * attempt)
    return last or {
        "url": url,
        "status": None,
        "final_url": "",
        "content_type": "",
        "expect_pdf": expect_pdf,
        "verdict": "TRANSIENT",
        "attempts": attempts,
    }


def run_network_checks(
    records: list[dict],
    *,
    workers: int,
    timeout: float,
) -> dict[str, dict]:
    targets: dict[str, bool] = {}
    for row in records:
        mode = row["cta_mode"]
        target = row["target"]
        if mode == CTA_EXTERNAL:
            targets[target] = False
        elif mode in {CTA_NOTICE, CTA_ORDER}:
            targets[target] = True

    out: dict[str, dict] = {}
    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(
                probe,
                url,
                expect_pdf=expect_pdf,
                timeout=timeout,
            ): url
            for url, expect_pdf in targets.items()
        }
        for fut in cf.as_completed(futures):
            url = futures[fut]
            out[url] = fut.result()
    return out


def build_report(
    jobs: list[dict],
    *,
    check_network: bool = False,
    workers: int = 6,
    timeout: float = 15.0,
) -> dict:
    records = [structural_record(job) for job in jobs]

    hard_failures = [
        {"uuid": row["uuid"], "issues": row["failures"]}
        for row in records
        if row["failures"]
    ]
    warnings = [
        {"uuid": row["uuid"], "issues": row["warnings"]}
        for row in records
        if row["warnings"]
    ]

    network = {}
    if check_network:
        network = run_network_checks(records, workers=workers, timeout=timeout)
        definitive_bad = {"BROKEN", "INVALID_DOCUMENT"}

        for row in records:
            result = network.get(row["target"])
            if not result:
                continue
            row["network"] = result

            if result["verdict"] in definitive_bad:
                hard_failures.append({
                    "uuid": row["uuid"],
                    "issues": [
                        "BROKEN_CTA_TARGET"
                        if result["verdict"] == "BROKEN"
                        else "CTA_DOCUMENT_IS_NOT_PDF"
                    ],
                    "target": row["target"],
                    "network": result,
                })
            elif result["verdict"] in {"RESTRICTED", "TRANSIENT"}:
                warnings.append({
                    "uuid": row["uuid"],
                    "issues": [f"NETWORK_{result['verdict']}"],
                    "target": row["target"],
                    "network": result,
                })

    cta_counts = Counter(row["cta_mode"] for row in records)
    channel_counts = Counter(row["channel"] for row in records)
    network_counts = Counter(item.get("verdict") for item in network.values())

    actionable = sum(1 for row in records if row["target"] and not row["failures"])
    direct_or_document = sum(
        1 for row in records if row["cta_mode"] != CTA_DETAIL
    )

    report = {
        "source": "emploi-public.ma",
        "generated_at": datetime.now(TZ).isoformat(),
        "timezone": "Africa/Casablanca",
        "jobs": len(records),
        "actionable_jobs": actionable,
        "actionable_coverage_pct": (
            round(actionable / len(records) * 100, 4) if records else 100.0
        ),
        "direct_application_or_document_jobs": direct_or_document,
        "direct_application_or_document_pct": (
            round(direct_or_document / len(records) * 100, 4)
            if records
            else 100.0
        ),
        "official_detail_fallback_jobs": cta_counts.get(CTA_DETAIL, 0),
        "cta_counts": dict(sorted(cta_counts.items())),
        "application_channel_counts": dict(sorted(channel_counts.items())),
        "network_checked": bool(check_network),
        "network_unique_targets": len(network),
        "network_verdict_counts": dict(sorted(network_counts.items())),
        "hard_failure_count": len(hard_failures),
        "warning_count": len(warnings),
        "hard_failures": hard_failures,
        "warnings": warnings,
        "records": records,
        "gate": "PASS" if not hard_failures else "FAIL",
    }
    return report


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Audit every Emploi-Public job CTA and candidature destination"
    )
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--check-network", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--timeout", type=float, default=15.0)
    args = ap.parse_args()

    source = Path(args.input)
    output = Path(args.output)

    jobs = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(jobs, list):
        raise SystemExit("Input must be a JSON list of jobs")

    report = build_report(
        jobs,
        check_network=args.check_network,
        workers=args.workers,
        timeout=args.timeout,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    summary = {
        key: report[key]
        for key in [
            "jobs",
            "actionable_jobs",
            "actionable_coverage_pct",
            "direct_application_or_document_jobs",
            "direct_application_or_document_pct",
            "official_detail_fallback_jobs",
            "cta_counts",
            "application_channel_counts",
            "network_checked",
            "network_unique_targets",
            "network_verdict_counts",
            "hard_failure_count",
            "warning_count",
            "gate",
        ]
    }

    print("=== MASARI APPLICATION CTA CENSUS ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"REPORT={output}")
    print("MASARI_APPLICATION_CTA_GATE=" + report["gate"])
    return 0 if report["gate"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
