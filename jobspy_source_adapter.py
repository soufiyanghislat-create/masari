from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

SOURCES = frozenset({"indeed", "linkedin"})
LABELS = {"indeed": "Indeed", "linkedin": "LinkedIn"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _https(value: Any) -> str:
    text = _text(value)
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"invalid HTTPS URL: {text!r}")
    return text


def normalize_jobspy_source_job(job: dict[str, Any], source: str | None = None) -> dict[str, Any]:
    source_key = _text(source or job.get("source")).casefold()
    if source_key not in SOURCES:
        raise ValueError(f"unsupported JobSpy source: {source_key!r}")

    title = _text(job.get("job_name") or job.get("listing_title") or job.get("title"))
    if not title:
        raise ValueError("missing title")

    global_id = _text(job.get("global_id") or job.get("uuid"))
    if not global_id:
        raise ValueError("missing global_id")
    if not global_id.startswith(source_key + ":"):
        raise ValueError(f"global_id/source mismatch: {global_id!r}")

    publication = _text(job.get("publication_date"))
    if not publication:
        raise ValueError("missing publication_date")

    url = _https(
        job.get("application_site")
        or job.get("application_url")
        or job.get("url")
        or job.get("job_url")
    )

    location_verification = job.get("location_verification")
    if not isinstance(location_verification, dict) or location_verification.get("gate") != "PASS":
        raise ValueError("Morocco location verification gate missing")

    ground_truth_status = _text(job.get("ground_truth_status")).upper()
    ground_truth_proof = _text(job.get("ground_truth_proof"))
    if ground_truth_status != "VERIFIED":
        raise ValueError("ground_truth_status must be VERIFIED")
    if not ground_truth_proof:
        raise ValueError("ground_truth_proof missing")

    company = _text(job.get("company") or job.get("administration"))
    location = _text(job.get("work_location_text") or job.get("location"))

    normalized = dict(job)
    normalized.update(
        {
            "uuid": global_id,
            "global_id": global_id,
            "source": source_key,
            "source_label": LABELS[source_key],
            "scope": "private",
            "employment_sector": "private",
            "listing_title": title,
            "job_name": title,
            "company": company or None,
            "administration": company or LABELS[source_key],
            "publication_date": publication,
            "deadline": None,
            "positions": None,
            "location": location or None,
            "work_location_text": location or None,
            "application_type": LABELS[source_key],
            "application_site": url,
            "application_url": url,
            "url": url,
            "source_url": url,
            "ground_truth_status": "VERIFIED",
            "ground_truth_proof": ground_truth_proof,
        }
    )
    return normalized
