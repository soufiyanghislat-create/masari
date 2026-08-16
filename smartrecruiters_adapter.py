from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

SOURCE = "smartrecruiters"


def _location_text(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    parts = []
    for key in ("city", "region", "country"):
        item = str(value.get(key) or "").strip()
        if item:
            parts.append(item)
    return ", ".join(parts) or None


def _parse_publication(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("SmartRecruiters job missing publication_date")
    probe = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        datetime.fromisoformat(probe)
    except ValueError as exc:
        raise ValueError(f"SmartRecruiters invalid publication date: {text}") from exc
    return text


def _https(value: Any, field: str) -> str:
    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"SmartRecruiters invalid {field}")
    return text


def normalize_smartrecruiters_job(job: dict[str, Any]) -> dict[str, Any]:
    row = deepcopy(job)
    if str(row.get("source") or SOURCE).strip().casefold() != SOURCE:
        raise ValueError("unexpected SmartRecruiters source")

    posting_id = str(
        row.get("source_posting_id")
        or row.get("source_offer_id")
        or row.get("uuid")
        or ""
    ).strip()
    if posting_id.startswith("smartrecruiters:"):
        posting_id = posting_id.rsplit(":", 1)[-1]
    if not posting_id:
        raise ValueError("SmartRecruiters job missing posting id")

    company_identifier = str(row.get("source_company_identifier") or "").strip()
    if not company_identifier:
        raise ValueError(f"SmartRecruiters {posting_id} missing company identifier")

    global_id = str(row.get("global_id") or "").strip()
    if not global_id:
        global_id = f"smartrecruiters:{company_identifier}:{posting_id}"

    title = str(row.get("job_name") or row.get("listing_title") or row.get("title") or "").strip()
    if not title:
        raise ValueError(f"SmartRecruiters {posting_id} missing title")

    company = str(row.get("company") or row.get("administration") or "").strip()
    if not company:
        raise ValueError(f"SmartRecruiters {posting_id} missing company")

    publication = _parse_publication(row.get("publication_date") or row.get("releasedDate"))
    application_url = _https(
        row.get("application_url")
        or row.get("application_site")
        or row.get("source_url")
        or row.get("url"),
        "apply URL",
    )
    location = row.get("location")

    row.update({
        "uuid": global_id,
        "global_id": global_id,
        "source": SOURCE,
        "source_label": "SmartRecruiters",
        "source_offer_id": posting_id,
        "source_posting_id": posting_id,
        "source_company_identifier": company_identifier,
        "source_reference": posting_id,
        "url": application_url,
        "source_url": application_url,
        "scope": "private",
        "employment_sector": "private",
        "listing_title": title,
        "administration": company,
        "publication_date": publication,
        "deadline": None,
        "contest_date": None,
        "job_name": title,
        "grade": "",
        "specialties": list(row.get("specialties") or []),
        "positions": row.get("positions") if row.get("positions") not in ("", 0) else None,
        "recruitment_type": str(row.get("recruitment_type") or row.get("contract_type") or "").strip(),
        "application_type": "SmartRecruiters",
        "application_site": application_url,
        "application_url": application_url,
        "contest_code": posting_id,
        "application_notice_url": "",
        "opening_order_url": "",
        "company": company,
        "location": location,
        "work_location_text": row.get("work_location_text") or _location_text(location),
        "location_relation": row.get("location_relation") or "primary_only",
        "contract_type": row.get("contract_type") or row.get("recruitment_type") or None,
        "contract_options": list(row.get("contract_options") or []),
        "salary": row.get("salary"),
    })
    return row
