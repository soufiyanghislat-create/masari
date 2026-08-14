from __future__ import annotations

import hashlib
from typing import Any

from taxonomy_engine import normalize, tokens

LITERAL_PREFIX = "anapec.literal."


def literal_profession_id(title: str) -> str:
    normalized = normalize(title)
    if not normalized:
        raise ValueError("literal profession title is empty")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"{LITERAL_PREFIX}{digest}"


def literal_profession_for_job(job: dict[str, Any]) -> dict[str, Any] | None:
    if str(job.get("source") or "").strip().casefold() != "anapec":
        return None
    title = str(job.get("job_name") or job.get("title") or "").strip()
    if not title:
        return None
    return {
        "profession_id": literal_profession_id(title),
        "label": title,
        "sector": "ANAPEC",
        "family": "Intitulé source vérifié",
        "source": "anapec_literal",
        "score": 1000.0,
        "confidence": "EXACT",
        "searchable": True,
        "evidence": {
            "field": "job_name",
            "value": title,
            "matched_term": title,
            "raw_score": 100.0,
        },
    }


def _literal_options(index: dict[str, Any]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for job in index.get("jobs") or []:
        literal = job.get("literal_profession")
        if not isinstance(literal, dict):
            literal = literal_profession_for_job(job)
        if not literal:
            continue
        pid = str(literal.get("profession_id") or "")
        if pid and pid not in by_id:
            by_id[pid] = dict(literal)
    return list(by_id.values())


def literal_profession_suggestions(index: dict[str, Any], query: str, *, limit: int = 8) -> list[dict[str, Any]]:
    q = normalize(query)
    if not q:
        return []
    q_tokens = set(tokens(q))
    rows: list[dict[str, Any]] = []
    for option in _literal_options(index):
        label = str(option.get("label") or "")
        nl = normalize(label)
        if not nl:
            continue
        score = 0.0
        if nl == q:
            score = 1000.0
        elif nl.startswith(q):
            score = 920.0
        elif any(word.startswith(q) for word in nl.split()):
            score = 860.0
        else:
            lt = set(tokens(nl))
            if q_tokens and q_tokens.issubset(lt):
                score = 800.0
        if score:
            row = dict(option)
            row["score"] = score
            rows.append(row)
    rows.sort(key=lambda x: (-float(x.get("score") or 0), str(x.get("label") or "").casefold()))
    return rows[:limit]


def resolve_literal_profession(index: dict[str, Any], query: str) -> dict[str, Any] | None:
    raw = str(query or "").strip()
    if not raw:
        return None
    options = _literal_options(index)
    if raw.startswith(LITERAL_PREFIX):
        for option in options:
            if option.get("profession_id") == raw:
                return option
        return None
    q = normalize(raw)
    exact = [x for x in options if normalize(str(x.get("label") or "")) == q]
    return exact[0] if len(exact) == 1 else None


def merge_profession_suggestions(canonical: list[dict[str, Any]], literal: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    canonical_labels = {
        normalize(str(x.get("label") or ""))
        for x in canonical
        if normalize(str(x.get("label") or ""))
    }
    for row in canonical:
        pid = str(row.get("profession_id") or "")
        if pid and pid not in seen_ids:
            seen_ids.add(pid)
            rows.append(dict(row))
    for row in literal:
        pid = str(row.get("profession_id") or "")
        label_norm = normalize(str(row.get("label") or ""))
        if not pid or pid in seen_ids or label_norm in canonical_labels:
            continue
        seen_ids.add(pid)
        rows.append(dict(row))
    rows.sort(key=lambda x: (-float(x.get("score") or 0), 1 if x.get("source") == "anapec_literal" else 0, str(x.get("label") or "").casefold()))
    return rows[:limit]


def search_literal_profession(index: dict[str, Any], profession_id: str, *, limit: int = 20, now=None) -> list[dict[str, Any]]:
    from search import is_job_visible_now
    rows: list[dict[str, Any]] = []
    for job in index.get("jobs") or []:
        if str(job.get("source") or "").strip().casefold() != "anapec":
            continue
        literal = job.get("literal_profession")
        if not isinstance(literal, dict):
            literal = literal_profession_for_job(job)
        if not literal or literal.get("profession_id") != profession_id:
            continue
        if not is_job_visible_now(job, now):
            continue
        title = str(job.get("job_name") or job.get("title") or literal.get("label") or "").strip()
        source_title = str(job.get("listing_title") or job.get("source_title") or title).strip()
        rows.append({
            "score": 100.0,
            "profession_match": literal,
            "uuid": job.get("uuid"),
            "global_id": job.get("global_id") or job.get("uuid"),
            "source": "anapec",
            "source_label": job.get("source_label") or "ANAPEC",
            "scope": "private",
            "employment_sector": "private",
            "title": title,
            "source_title": source_title,
            "search_title": title,
            "matched_profession_label": literal.get("label"),
            "application_type": job.get("application_type") or "ANAPEC",
            "application_site": job.get("application_site") or "",
            "application_url": job.get("application_url") or job.get("application_site") or "",
            "application_notice_url": job.get("application_notice_url") or "",
            "opening_order_url": job.get("opening_order_url") or "",
            "specialties": list(job.get("specialties") or []),
            "administration": job.get("administration"),
            "company": job.get("company"),
            "location": job.get("location"),
            "work_location_text": job.get("work_location_text"),
            "location_relation": job.get("location_relation"),
            "contract_type": job.get("contract_type") or job.get("recruitment_type"),
            "contract_options": list(job.get("contract_options") or []),
            "salary": job.get("salary"),
            "publication_date": job.get("publication_date"),
            "deadline": job.get("deadline"),
            "positions": job.get("positions"),
            "url": job.get("url"),
        })
    rows.sort(key=lambda x: (str(x.get("publication_date") or ""), str(x.get("uuid") or "")), reverse=True)
    return rows[:limit]
