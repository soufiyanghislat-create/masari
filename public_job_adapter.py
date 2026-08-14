from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Africa/Casablanca")
ANAPEC_SOURCE = "anapec"
EMPLOI_PUBLIC_SOURCE = "emploi-public"


def _iso_start_date(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:10], fmt).date().isoformat()
        except ValueError:
            pass
    return None


def normalize_anapec_job(job: dict[str, Any]) -> dict[str, Any]:
    """Adapt a verified ANAPEC v12 row to Masari's existing public-job contract.

    The Emploi-Public fields remain the core contract consumed by taxonomy/search.
    ANAPEC-specific fields are retained alongside them instead of being discarded.
    """
    source_offer_id = str(job.get("source_offer_id") or "").strip()
    if not source_offer_id:
        raise ValueError("ANAPEC job missing source_offer_id")
    global_id = str(job.get("global_id") or f"anapec:{source_offer_id}").strip()
    title = str(job.get("title") or "").strip()
    if not title:
        raise ValueError(f"ANAPEC {source_offer_id} missing title")
    source_url = str(job.get("source_url") or "").strip()
    application = deepcopy(job.get("application") or {})
    application_url = str(application.get("url") or "").strip()
    company = str(job.get("company") or "").strip()

    row = deepcopy(job)
    row.update(
        {
            # Identity / provenance
            "uuid": global_id,
            "global_id": global_id,
            "source": ANAPEC_SOURCE,
            "source_label": "ANAPEC",
            "source_offer_id": source_offer_id,
            "url": source_url,
            "source_url": source_url,
            "scope": "public",
            # Existing Masari/Emploi-Public contract
            "listing_title": str(job.get("source_title") or title).strip(),
            "administration": company or "ANAPEC",
            "publication_date": str(job.get("publication_date") or "").strip(),
            "deadline": None,  # ANAPEC does not publish a deadline; never fabricate it.
            "contest_date": _iso_start_date(job.get("start_date")),
            "job_name": title,
            "grade": "",
            "specialties": [],
            "positions": int(job.get("positions") or 0),
            "recruitment_type": str(job.get("contract_type") or "").strip(),
            "application_type": "ANAPEC",
            "application_site": application_url,
            "contest_code": str(job.get("source_reference") or "").strip(),
            "application_notice_url": "",
            "opening_order_url": "",
            # Unified public fields used by current/future UI without losing source detail.
            "company": company or None,
            "location": job.get("location"),
            "work_location_text": job.get("work_location_text"),
            "location_relation": job.get("location_relation"),
            "contract_type": job.get("contract_type"),
            "contract_options": deepcopy(job.get("contract_options") or []),
            "salary": job.get("salary"),
            "education": job.get("education"),
            "experience": job.get("experience"),
            "languages": job.get("languages"),
            "description": job.get("description"),
            "profile": job.get("profile"),
            "sector": job.get("sector"),
            "agency": job.get("agency"),
            "application": application,
            "application_url": application_url,
        }
    )
    if row["positions"] <= 0:
        raise ValueError(f"ANAPEC {source_offer_id} invalid positions")
    return row


def normalize_emploi_public_job(job: dict[str, Any]) -> dict[str, Any]:
    """Annotate the existing Emploi-Public row without changing its semantics."""
    row = deepcopy(job)
    uuid = str(row.get("uuid") or "").strip()
    if not uuid:
        raise ValueError("Emploi-Public job missing uuid")
    row.setdefault("global_id", f"emploi-public:{uuid}")
    row.setdefault("source", EMPLOI_PUBLIC_SOURCE)
    row.setdefault("source_label", "Emploi-Public.ma")
    row.setdefault("source_offer_id", uuid)
    row.setdefault("source_reference", row.get("contest_code") or uuid)
    row.setdefault("source_url", row.get("url"))
    row.setdefault("company", row.get("administration"))
    row.setdefault("location", None)
    row.setdefault("work_location_text", None)
    row.setdefault("location_relation", "primary_only")
    row.setdefault("contract_type", row.get("recruitment_type") or None)
    row.setdefault("contract_options", [])
    row.setdefault("salary", None)
    row.setdefault("application_url", row.get("application_site") or "")
    return row


def normalize_public_job(job: dict[str, Any]) -> dict[str, Any]:
    source = str(job.get("source") or "").strip().casefold()
    if source == ANAPEC_SOURCE:
        return normalize_anapec_job(job)
    return normalize_emploi_public_job(job)
