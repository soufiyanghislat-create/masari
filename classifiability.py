from __future__ import annotations

import re
import unicodedata
from typing import Any


_GENERIC_AGGREGATE_JOB_NAMES = frozenset({
    "agents",
    "agents d'execution",
    "agent de maitrise",
    "agents de maitrise",
    "cadres",
    "cadres experimentes",
    "cadres et ingenieurs",
    "responsables et cadres",
})

_GENERIC_PUBLIC_GRADE_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"technicien de [34](?:eme|ème) grade(?: - echelle \d+)?",
        r"administrateur [23](?:eme|ème) grade(?: - echelle \d+)?",
        r"ingenieur d'etat 1er grade(?: - echelle \d+)?",
        r"adjoint administratif 2(?:eme|ème) grade",
        r"adjoint technique 2(?:eme|ème) grade",
    )
)


def normalize_classifiability_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[’']", "'", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def structural_ambiguity_reasons(job: dict) -> list[str]:
    name = normalize_classifiability_text(job.get("job_name"))
    grade = normalize_classifiability_text(job.get("grade"))
    specialties = [
        normalize_classifiability_text(x)
        for x in (job.get("specialties") or [])
        if normalize_classifiability_text(x)
    ]

    reasons: list[str] = []

    if (
        not specialties
        and not name
        and any(pattern.fullmatch(grade) for pattern in _GENERIC_PUBLIC_GRADE_PATTERNS)
    ):
        reasons.append("generic_public_grade_without_specialty")

    if not specialties and name in _GENERIC_AGGREGATE_JOB_NAMES:
        reasons.append("generic_aggregate_job_name")

    return reasons


def _summary(job: dict, reasons: list[str]) -> dict:
    return {
        "uuid": job.get("uuid"),
        "url": job.get("url"),
        "listing_title": job.get("listing_title"),
        "job_name": job.get("job_name"),
        "grade": job.get("grade"),
        "specialties": job.get("specialties") or [],
        "positions": int(job.get("positions") or 0),
        "reasons": reasons,
        "profession_ids": [
            m.get("profession_id")
            for m in (job.get("profession_matches") or [])
            if m.get("profession_id")
        ],
    }


def evaluate_classifiable_coverage(indexed_jobs: list[dict], *, minimum_coverage_pct: float) -> dict:
    total = len(indexed_jobs)
    classified = 0
    structurally_ambiguous = []
    ambiguous_classified = []
    unexplained_unclassified = []
    classifiable_jobs = 0
    classified_classifiable_jobs = 0

    for job in indexed_jobs:
        matches = job.get("profession_matches") or []
        if matches:
            classified += 1

        reasons = structural_ambiguity_reasons(job)

        if reasons:
            row = _summary(job, reasons)
            structurally_ambiguous.append(row)
            if matches:
                ambiguous_classified.append(row)
            continue

        classifiable_jobs += 1
        if matches:
            classified_classifiable_jobs += 1
        else:
            unexplained_unclassified.append(_summary(job, []))

    raw_coverage = round(classified / total * 100, 2) if total else 100.0
    classifiable_coverage = (
        round(classified_classifiable_jobs / classifiable_jobs * 100, 2)
        if classifiable_jobs
        else 100.0
    )

    gate = classifiable_coverage >= minimum_coverage_pct and not ambiguous_classified

    return {
        "jobs": total,
        "classified_jobs": classified,
        "unclassified_jobs": total - classified,
        "raw_classification_coverage_pct": raw_coverage,
        "structurally_ambiguous_jobs": len(structurally_ambiguous),
        "classifiable_jobs": classifiable_jobs,
        "classified_classifiable_jobs": classified_classifiable_jobs,
        "unexplained_unclassified_jobs": len(unexplained_unclassified),
        "classifiable_coverage_pct": classifiable_coverage,
        "ambiguous_classified_jobs": len(ambiguous_classified),
        "minimum_required_classifiable_coverage_pct": minimum_coverage_pct,
        "structurally_ambiguous_rows": structurally_ambiguous,
        "unexplained_unclassified_rows": unexplained_unclassified,
        "ambiguous_classified_rows": ambiguous_classified,
        "gate": gate,
    }
