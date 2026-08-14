from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from sources.public.anapec.crawler import _get, _session

TZ = ZoneInfo("Africa/Casablanca")
TITLE_RE = re.compile(r"^\s*\((?P<count>\d+)\)\s*(?P<title>.+?)\s*$")
DATE_RE = re.compile(r"\b(?P<d>\d{2}/\d{2}/\d{4})\b")
SALARY_RE = re.compile(
    r"(?i)\b(n[ée]gociable|\d[\d\s.,]*\s*(?:dhs?|dh)(?:\s*\+\s*primes?)?)\b"
)


def clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def norm(value: str | None) -> str:
    text = unicodedata.normalize("NFC", clean(value)).replace("’", "'")
    return text.casefold()


def compact(value: str | None) -> str:
    return re.sub(r"[^a-z0-9à-ÿ]+", " ", norm(value)).strip()


def salary_key(value: str | None) -> str:
    """Compare salary semantics without caring about display spacing/case."""
    text = norm(value)
    text = re.sub(r"\s+", "", text)
    text = text.replace("mad", "dh").replace("dhs", "dh")
    return text


def html_lines(content: bytes) -> tuple[BeautifulSoup, list[str]]:
    soup = BeautifulSoup(content, "html.parser")
    lines = [clean(s) for s in soup.stripped_strings if clean(s)]
    return soup, lines


def find_label(lines: list[str], aliases: tuple[str, ...]) -> str | None:
    alias_norms = {norm(a).rstrip(":").strip() for a in aliases}
    for idx, line in enumerate(lines):
        n = norm(line)
        base = n.rstrip(":").strip()
        if base in alias_norms:
            return lines[idx + 1] if idx + 1 < len(lines) else None
        for alias in alias_norms:
            m = re.match(re.escape(alias) + r"\s*:\s*(.+)$", n)
            if m:
                original = clean(line.split(":", 1)[1]) if ":" in line else ""
                return original or (lines[idx + 1] if idx + 1 < len(lines) else None)
    return None


def extract_reference(lines: list[str]) -> str | None:
    value = find_label(lines, ("Référence de l’offre", "Référence de l'offre", "Reference de l'offre"))
    if value:
        m = re.search(r"\b[A-Za-z]{1,3}\.?\d{10,16}\b", value)
        if m:
            return m.group(0)
    blob = "\n".join(lines)
    m = re.search(r"\b[A-Za-z]{1,3}\.?\d{10,16}\b", blob)
    return m.group(0) if m else None


def extract_date(lines: list[str]) -> str | None:
    value = find_label(lines, ("Date", "Date de publication"))
    if not value:
        return None
    m = DATE_RE.search(value)
    if not m:
        return None
    return datetime.strptime(m.group("d"), "%d/%m/%Y").date().isoformat()


def extract_title_positions(lines: list[str]) -> tuple[str | None, int | None]:
    candidates: list[tuple[str, int]] = []
    for line in lines:
        m = TITLE_RE.match(line)
        if m:
            candidates.append((clean(m.group("title")), int(m.group("count"))))
    if not candidates:
        return None, None
    # A repeated heading is common. Prefer the richest title independently.
    return max(candidates, key=lambda item: len(item[0]))


def extract_location(lines: list[str]) -> str | None:
    return find_label(lines, ("Lieu de travail",))


def extract_contract(lines: list[str]) -> str | None:
    return find_label(lines, ("Type de contrat",))


def extract_start_date(lines: list[str]) -> str | None:
    return find_label(lines, ("Date de début", "Date debut"))


def extract_salary(lines: list[str]) -> str | None:
    # Prefer a dedicated monthly salary label when present.
    for aliases in (("Salaire mensuel",), ("Salaire",)):
        value = find_label(lines, aliases)
        if value:
            m = SALARY_RE.search(value)
            if m:
                return clean(m.group(1))
    # ANAPEC sometimes embeds `Salaire : ...` inside a larger characteristic line.
    for line in lines:
        if "salaire" not in norm(line):
            continue
        after = line.split(":", 1)[1] if ":" in line else line
        m = SALARY_RE.search(after)
        if m:
            return clean(m.group(1))
    return None


def extract_application_ref(soup: BeautifulSoup) -> str | None:
    node = soup.find("input", attrs={"name": "ref"})
    if node and node.get("value"):
        return clean(str(node.get("value")))
    return None


def normalize_contract(value: str | None) -> str | None:
    if not value:
        return None
    v = clean(value)
    if norm(v).startswith("choix multiple"):
        return "MULTIPLE"
    return v


def text_present(needle: str | None, haystack: str) -> bool:
    if not needle:
        return True
    n = compact(needle)
    h = compact(haystack)
    if not n:
        return True
    if n in h:
        return True
    # Long prose can differ in punctuation/spacing. Require all informative tokens.
    tokens = [t for t in n.split() if len(t) >= 3]
    return bool(tokens) and sum(1 for t in tokens if t in h) / len(tokens) >= 0.9


def compare_job(job: dict[str, Any], content: bytes) -> dict[str, Any]:
    soup, lines = html_lines(content)
    page_text = " ".join(lines)
    page_title, page_positions = extract_title_positions(lines)
    page_contract_raw = extract_contract(lines)
    page = {
        "reference": extract_reference(lines),
        "publication_date": extract_date(lines),
        "title": page_title,
        "positions": page_positions,
        "location": extract_location(lines),
        "contract_type": normalize_contract(page_contract_raw),
        "source_contract_text": clean(page_contract_raw) if page_contract_raw else None,
        "start_date": extract_start_date(lines),
        "salary": extract_salary(lines),
        "application_reference": extract_application_ref(soup),
    }

    mismatches: list[dict[str, Any]] = []

    def exact(field: str, expected: Any, actual: Any, *, normalize_text: bool = False) -> None:
        if expected in (None, "") and actual in (None, ""):
            return
        if normalize_text:
            ok = norm(str(expected)) == norm(str(actual))
        else:
            ok = expected == actual
        if not ok:
            mismatches.append({"field": field, "expected": expected, "actual": actual})

    exact("source_reference", job.get("source_reference"), page["reference"], normalize_text=True)
    exact("publication_date", str(job.get("publication_date") or "")[:10], page["publication_date"])
    exact("title", job.get("title"), page["title"], normalize_text=True)
    exact("positions", job.get("positions"), page["positions"])
    exact("location", job.get("location"), page["location"], normalize_text=True)
    exact("contract_type", job.get("contract_type"), page["contract_type"], normalize_text=True)

    # start_date in v11 is source text DD/MM/YYYY when disclosed.
    if job.get("start_date"):
        exact("start_date", job.get("start_date"), page["start_date"], normalize_text=True)

    if job.get("salary"):
        if salary_key(str(job.get("salary"))) != salary_key(page["salary"]):
            mismatches.append({"field": "salary", "expected": job.get("salary"), "actual": page["salary"]})
    elif page["salary"]:
        mismatches.append({"field": "salary_missing_in_dataset", "expected": None, "actual": page["salary"]})

    exact(
        "application.reference",
        (job.get("application") or {}).get("reference"),
        page["application_reference"],
        normalize_text=True,
    )

    # Independent evidence checks for optional source-disclosed values.
    for field in ("company", "company_description", "work_location_text"):
        value = job.get(field)
        if value and not text_present(str(value), page_text):
            mismatches.append({"field": f"{field}_not_found_on_page", "expected": value, "actual": None})

    source_url = str(job.get("source_url") or "")
    offer_id = str(job.get("source_offer_id") or "")
    if offer_id and f"/{offer_id}/" not in urlparse(source_url).path:
        mismatches.append({"field": "source_url_offer_id", "expected": offer_id, "actual": source_url})

    return {
        "source_offer_id": job.get("source_offer_id"),
        "source_url": source_url,
        "match": not mismatches,
        "mismatches": mismatches,
        "independent_extract": page,
    }


def fetch_and_compare(job: dict[str, Any], attempts: int) -> dict[str, Any]:
    url = str(job.get("source_url") or "")
    try:
        session = _session()
        content = _get(session, url, attempts=attempts)
        return compare_job(job, content)
    except Exception as exc:
        return {
            "source_offer_id": job.get("source_offer_id"),
            "source_url": url,
            "match": False,
            "fetch_error": f"{type(exc).__name__}: {exc}",
            "mismatches": [],
        }


def run(jobs_path: Path, output_path: Path, workers: int, attempts: int, pause: float) -> dict[str, Any]:
    jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
    if not isinstance(jobs, list) or not jobs:
        raise SystemExit("jobs file is empty or invalid")

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 4))) as pool:
        futures = {}
        for idx, job in enumerate(jobs):
            if pause > 0 and idx:
                time.sleep(pause)
            futures[pool.submit(fetch_and_compare, job, attempts)] = job
        done = 0
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            done += 1
            if result.get("match"):
                print(f"GROUND_TRUTH {done}/{len(jobs)} id={result.get('source_offer_id')} MATCH")
            else:
                status = "FETCH_ERROR" if result.get("fetch_error") else "MISMATCH"
                print(f"GROUND_TRUTH {done}/{len(jobs)} id={result.get('source_offer_id')} {status}")

    results.sort(key=lambda r: str(r.get("source_offer_id") or ""))
    matched = sum(1 for r in results if r.get("match"))
    fetch_failures = [r for r in results if r.get("fetch_error")]
    mismatched = [r for r in results if not r.get("match") and not r.get("fetch_error")]
    mismatch_fields: dict[str, int] = {}
    for row in mismatched:
        for item in row.get("mismatches", []):
            field = str(item.get("field"))
            mismatch_fields[field] = mismatch_fields.get(field, 0) + 1

    report = {
        "source": "anapec",
        "audit": "independent_ground_truth",
        "generated_at": datetime.now(TZ).isoformat(),
        "job_count": len(jobs),
        "matched_count": matched,
        "mismatch_count": len(mismatched),
        "fetch_failure_count": len(fetch_failures),
        "mismatch_fields": dict(sorted(mismatch_fields.items())),
        "gate": "PASS" if matched == len(jobs) else "FAIL",
        "failures": [r for r in results if not r.get("match")],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"ANAPEC_GROUND_TRUTH_GATE={report['gate']}")
    print(f"ANAPEC_GROUND_TRUTH_JOBS={len(jobs)}")
    print(f"ANAPEC_GROUND_TRUTH_MATCHED={matched}")
    print(f"ANAPEC_GROUND_TRUTH_MISMATCHES={len(mismatched)}")
    print(f"ANAPEC_GROUND_TRUTH_FETCH_FAILURES={len(fetch_failures)}")
    print("ANAPEC_GROUND_TRUTH_MISMATCH_FIELDS=" + json.dumps(report["mismatch_fields"], ensure_ascii=False, sort_keys=True))
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="Independent live ANAPEC job ground-truth audit")
    ap.add_argument("--jobs", default="output/anapec/jobs.json")
    ap.add_argument("--output", default="output/anapec/ground_truth_audit.json")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--attempts", type=int, default=3)
    ap.add_argument("--pause", type=float, default=0.03, help="delay between scheduling requests")
    args = ap.parse_args()
    report = run(Path(args.jobs), Path(args.output), args.workers, args.attempts, args.pause)
    raise SystemExit(0 if report["gate"] == "PASS" else 2)


if __name__ == "__main__":
    main()
