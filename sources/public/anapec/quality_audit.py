from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Africa/Casablanca")
MAX_JOB_AGE_DAYS = 15
MOJIBAKE_MARKERS = ("Ã", "Â", "â€", "â€™", "â€œ", "â€\x9d", "�")
COUNT_PREFIX_RE = re.compile(r"^\s*\(\d+\)\s+")

INVALID_COMPANY_EXACT = {
    "secteur d'activité", "secteur d’activité", "description de poste",
    "type de contrat", "lieu de travail", "formation", "profil recherché",
    "partager sur", "envoyer à un ami",
}
COMPANY_PROSE_RE = re.compile(r"\b(cherche|cherhce|recherche|recrute|recrutement|besoin de)\b", re.IGNORECASE)
GENERIC_COMPANY_RE = re.compile(
    r"^(?:une\s+)?(?:soci[ée]t[ée]|st[ée]|entreprise|magasin|magsin|cabinet|centre)\s+"
    r"(?:d['’]|de|du|des|dans|au|aux|op[ée]rant|active|sp[ée]cialis[ée]e?|commerciale?|industrielle?)\b",
    re.IGNORECASE,
)
POSTE_PREFIX_RE = re.compile(r"^poste\s*:", re.IGNORECASE)
GENERIC_ENTITY_EXACT = {"association", "cabinet medical", "cabinet médicale", "cabinet medicale", "société", "societe", "entreprise", "magasin", "centre"}
SALARY_BAD_CONTEXT_RE = re.compile(r"\b(lieu\s+de\s+travail|logement|formation|profil|exp[ée]rience|langues?)\b", re.IGNORECASE)
METADATA_LABEL_VALUES = {
    "description du profil", "compétences requises", "competences requises",
    "compétences", "competences", "caractéristiques du poste",
    "caracteristiques du poste", "profil recherché", "profil recherche",
    "description de poste", "formation", "expérience professionnelle",
    "experience professionnelle", "langues", "langue", "commentaire",
    "commentaires", "secteur d'activité", "secteur d’activité",
    "type de contrat", "lieu de travail", "date de début", "date debut",
    "poste", "bureautiques", "bureautique",
}
NORMALIZED_TEXT_FIELDS = (
    "description", "profile", "education", "experience", "languages",
    "sector", "agency", "comment",
)


def _is_metadata_label_only(value) -> bool:
    if value in (None, ""):
        return False
    folded = str(value).strip().rstrip(":").strip().replace("’", "'").casefold()
    labels = {x.replace("’", "'").casefold() for x in METADATA_LABEL_VALUES}
    return folded in labels


def _invalid_company(value) -> bool:
    if value in (None, ""):
        return False
    text = str(value).strip().rstrip(",")
    folded = text.rstrip(":").strip().replace("’", "'").casefold()
    invalid_exact = {x.replace("’", "'").casefold() for x in INVALID_COMPANY_EXACT}
    if folded in invalid_exact:
        return True
    if folded in {x.replace("’", "'").casefold() for x in GENERIC_ENTITY_EXACT}:
        return True
    if POSTE_PREFIX_RE.match(text):
        return True
    if len(text) > 80:
        return True
    if GENERIC_COMPANY_RE.search(text):
        return True
    return bool(COMPANY_PROSE_RE.search(text))


def _invalid_salary(value) -> bool:
    if value in (None, ""):
        return False
    text = str(value).strip()
    return len(text) > 60 or bool(SALARY_BAD_CONTEXT_RE.search(text))


def _same_text(a, b) -> bool:
    if not a or not b:
        return False
    norm = lambda x: re.sub(r"\s+", " ", str(x)).strip().replace("’", "'").casefold()
    return norm(a) == norm(b)


def _load(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _has_mojibake(value) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        return any(_has_mojibake(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_mojibake(v) for v in value)
    text = str(value)
    return any(marker in text for marker in MOJIBAKE_MARKERS)


def audit_jobs(jobs: list[dict], now: datetime | None = None) -> dict:
    now = now or datetime.now(TZ)
    problems: list[dict] = []
    required = ("source_offer_id", "source_reference", "global_id", "title", "positions", "publication_date", "location", "source_url")

    def problem(job, code, detail=None):
        problems.append({
            "source_offer_id": job.get("source_offer_id"),
            "code": code,
            "detail": detail,
        })

    for job in jobs:
        for field in required:
            if job.get(field) in (None, "", []):
                problem(job, "missing_required_field", field)

        if _has_mojibake(job):
            problem(job, "mojibake_detected")

        if _invalid_company(job.get("company")):
            problem(job, "invalid_company_semantics", job.get("company"))
        if _same_text(job.get("company"), job.get("title")):
            problem(job, "company_equals_title", job.get("company"))
        if _invalid_salary(job.get("salary")):
            problem(job, "invalid_salary_semantics", job.get("salary"))
        for field in NORMALIZED_TEXT_FIELDS:
            if _is_metadata_label_only(job.get(field)):
                problem(job, "metadata_label_leaked_into_value", {"field": field, "value": job.get(field)})
        source_location = job.get("source_location")
        work_location = job.get("work_location_text")
        relation = job.get("location_relation")
        variation = bool(job.get("location_variation"))
        conflict = bool(job.get("location_conflict"))
        if not _same_text(source_location, job.get("location")):
            problem(job, "source_location_mismatch", {"location": job.get("location"), "source_location": source_location})
        allowed_relations = {"primary_only", "related_detail", "multi_location", "different_source_location"}
        if relation not in allowed_relations:
            problem(job, "invalid_location_relation", relation)
        if work_location and not variation:
            problem(job, "work_location_without_variation_flag", work_location)
        if variation and not work_location:
            problem(job, "variation_missing_work_location")
        if not work_location and relation != "primary_only":
            problem(job, "location_relation_without_work_location", relation)
        if work_location and relation == "primary_only":
            problem(job, "work_location_marked_primary_only", work_location)
        if conflict != (relation == "different_source_location"):
            problem(job, "location_conflict_relation_mismatch", {"relation": relation, "conflict": conflict})
        if work_location and _same_text(work_location, job.get("location")):
            problem(job, "redundant_work_location", work_location)
        if work_location and re.search(r"//|\blogement\b|\bcomp[ée]tences?\b|\bdipl[oô]me\b", str(work_location), re.IGNORECASE):
            problem(job, "work_location_contains_non_location_tail", work_location)
        # Legacy alias must remain identical while the source package is isolated.
        if job.get("alternate_work_location") != work_location:
            problem(job, "legacy_alternate_location_mismatch")

        title = str(job.get("title") or "")
        if COUNT_PREFIX_RE.match(title):
            problem(job, "title_still_contains_position_count", title)

        positions = job.get("positions")
        if not isinstance(positions, int) or positions < 1:
            problem(job, "invalid_positions", positions)

        contract_type = job.get("contract_type")
        contract_options = job.get("contract_options") or []
        source_contract_text = job.get("source_contract_text")
        if contract_type == "MULTIPLE":
            if not contract_options:
                problem(job, "multiple_contract_options_missing", source_contract_text)
            else:
                option_total = 0
                option_types = set()
                options_valid = True
                for option in contract_options:
                    if not isinstance(option, dict):
                        options_valid = False
                        continue
                    opt_type = str(option.get("type") or "").strip()
                    opt_positions = option.get("positions")
                    if not opt_type or not isinstance(opt_positions, int) or opt_positions < 1:
                        options_valid = False
                    else:
                        option_total += opt_positions
                        if opt_type in option_types:
                            options_valid = False
                        option_types.add(opt_type)
                if not options_valid:
                    problem(job, "invalid_contract_options", contract_options)
                if isinstance(positions, int) and option_total != positions:
                    problem(job, "contract_positions_mismatch", {"positions": positions, "contract_total": option_total})
            if not str(source_contract_text or "").casefold().startswith("choix multiple"):
                problem(job, "multiple_contract_source_text_missing", source_contract_text)
        else:
            if contract_options:
                problem(job, "unexpected_contract_options", contract_options)
            if source_contract_text and contract_type != source_contract_text:
                problem(job, "simple_contract_normalization_mismatch", {"contract_type": contract_type, "source": source_contract_text})

        offer_id = str(job.get("source_offer_id") or "")
        ref = str(job.get("source_reference") or "")
        if offer_id and ref and not ref.endswith(offer_id):
            problem(job, "reference_offer_id_mismatch", ref)

        gid = str(job.get("global_id") or "")
        if offer_id and gid != f"anapec:{offer_id}":
            problem(job, "global_id_mismatch", gid)

        url = str(job.get("source_url") or "")
        if offer_id and f"/{offer_id}/" not in url:
            problem(job, "source_url_offer_id_mismatch", url)

        raw_date = job.get("publication_date")
        try:
            published = date.fromisoformat(str(raw_date)[:10])
            age = (now.date() - published).days
            if not 0 <= age <= MAX_JOB_AGE_DAYS:
                problem(job, "outside_15_day_window", age)
        except Exception:
            problem(job, "invalid_publication_date", raw_date)

        app = job.get("application") or {}
        if app.get("reference") != job.get("source_reference"):
            problem(job, "application_reference_mismatch", app.get("reference"))
        if app and not app.get("official"):
            problem(job, "application_not_official")

    ids = [j.get("source_offer_id") for j in jobs]
    refs = [j.get("source_reference") for j in jobs]
    gids = [j.get("global_id") for j in jobs]
    urls = [j.get("source_url") for j in jobs]

    duplicate_counts = {
        "source_offer_id": [x for x, n in Counter(ids).items() if x and n > 1],
        "source_reference": [x for x, n in Counter(refs).items() if x and n > 1],
        "global_id": [x for x, n in Counter(gids).items() if x and n > 1],
        "source_url": [x for x, n in Counter(urls).items() if x and n > 1],
    }
    duplicate_ok = not any(duplicate_counts.values())

    # Distinct official IDs are not auto-deduplicated. Surface same-day semantic
    # lookalikes for review rather than deleting legitimate offers.
    semantic_groups = {}
    for job in jobs:
        key = (
            str(job.get("title") or "").strip().casefold(),
            int(job.get("positions") or 0),
            str(job.get("location") or "").strip().casefold(),
            str(job.get("publication_date") or ""),
            str(job.get("start_date") or "").strip().casefold(),
            str(job.get("company") or "").strip().casefold(),
            str(job.get("salary") or "").strip().casefold(),
            str(job.get("contract_type") or "").strip().casefold(),
            str(job.get("education") or "").strip().casefold(),
            str(job.get("experience") or "").strip().casefold(),
            str(job.get("languages") or "").strip().casefold(),
        )
        semantic_groups.setdefault(key, []).append(job)
    semantic_duplicate_groups = [
        [j.get("source_offer_id") for j in group]
        for group in semantic_groups.values() if len(group) > 1
    ]

    field_completeness = {}
    optional = ("company", "employer_source_label", "company_description", "agency", "start_date", "contract_type", "contract_options", "source_contract_text", "salary", "source_salary_text", "sector", "description", "profile", "education", "experience", "languages", "comment", "source_location", "work_location_text", "location_relation")
    for field in optional:
        present = sum(1 for j in jobs if j.get(field) not in (None, "", []))
        field_completeness[field] = {
            "present": present,
            "missing": len(jobs) - present,
            "percent": round((present / len(jobs) * 100), 2) if jobs else 0.0,
        }

    codes = Counter(p["code"] for p in problems)
    checks = {
        "nonempty": bool(jobs),
        "no_duplicate_identity": duplicate_ok,
        "required_fields_complete": codes["missing_required_field"] == 0,
        "no_mojibake": codes["mojibake_detected"] == 0,
        "company_semantics_clean": codes["invalid_company_semantics"] == 0 and codes["company_equals_title"] == 0,
        "salary_semantics_clean": codes["invalid_salary_semantics"] == 0,
        "normalized_fields_free_of_labels": codes["metadata_label_leaked_into_value"] == 0,
        "location_metadata_consistent": all(codes[x] == 0 for x in (
            "source_location_mismatch", "invalid_location_relation", "work_location_without_variation_flag",
            "variation_missing_work_location", "location_relation_without_work_location",
            "work_location_marked_primary_only", "location_conflict_relation_mismatch",
            "redundant_work_location", "work_location_contains_non_location_tail",
            "legacy_alternate_location_mismatch",
        )),
        "title_positions_normalized": codes["title_still_contains_position_count"] == 0 and codes["invalid_positions"] == 0,
        "contract_semantics_consistent": all(codes[x] == 0 for x in (
            "multiple_contract_options_missing", "invalid_contract_options", "contract_positions_mismatch",
            "multiple_contract_source_text_missing", "unexpected_contract_options", "simple_contract_normalization_mismatch",
        )),
        "reference_identity_consistent": codes["reference_offer_id_mismatch"] == 0 and codes["global_id_mismatch"] == 0 and codes["source_url_offer_id_mismatch"] == 0,
        "publication_window_valid": codes["outside_15_day_window"] == 0 and codes["invalid_publication_date"] == 0,
        "official_application_consistent": codes["application_reference_mismatch"] == 0 and codes["application_not_official"] == 0,
    }
    passed = all(checks.values())
    contract_distribution = Counter(str(j.get("contract_type") or "MISSING") for j in jobs)
    summary = {
        "positions_total": sum(j.get("positions", 0) for j in jobs if isinstance(j.get("positions"), int)),
        "company_name_count": sum(1 for j in jobs if j.get("company")),
        "company_description_count": sum(1 for j in jobs if j.get("company_description")),
        "salary_count": sum(1 for j in jobs if j.get("salary")),
        "multiple_contract_job_count": sum(1 for j in jobs if j.get("contract_type") == "MULTIPLE"),
        "semantic_duplicate_review_group_count": len(semantic_duplicate_groups),
        "location_variation_count": sum(1 for j in jobs if j.get("location_variation")),
        "different_source_location_count": sum(1 for j in jobs if j.get("location_relation") == "different_source_location"),
        "related_location_detail_count": sum(1 for j in jobs if j.get("location_relation") == "related_detail"),
        "multi_location_job_count": sum(1 for j in jobs if j.get("location_relation") == "multi_location"),
        "location_relation_distribution": dict(sorted(Counter(str(j.get("location_relation") or "MISSING") for j in jobs).items())),
        "contract_distribution": dict(sorted(contract_distribution.items())),
    }
    return {
        "source": "anapec",
        "generated_at": now.isoformat(),
        "job_count": len(jobs),
        "checks": checks,
        "problem_counts": dict(sorted(codes.items())),
        "duplicate_values": duplicate_counts,
        "semantic_duplicate_review_groups": semantic_duplicate_groups,
        "field_completeness": field_completeness,
        "summary": summary,
        "problems": problems,
        "gate": "PASS" if passed else "FAIL",
    }


def run(jobs_path: str | Path = "output/anapec/jobs.json", output_path: str | Path = "output/anapec/job_quality_audit.json") -> dict:
    jobs = _load(jobs_path)
    report = audit_jobs(jobs)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ANAPEC_JOB_QUALITY_GATE={report['gate']}")
    print(f"ANAPEC_JOB_COUNT={report['job_count']}")
    print(f"ANAPEC_POSITIONS_TOTAL={report['summary']['positions_total']}")
    print(f"ANAPEC_COMPANY_NAME_COUNT={report['summary']['company_name_count']}")
    print(f"ANAPEC_COMPANY_DESCRIPTION_COUNT={report['summary']['company_description_count']}")
    print(f"ANAPEC_SALARY_COUNT={report['summary']['salary_count']}")
    print(f"ANAPEC_MULTIPLE_CONTRACT_JOB_COUNT={report['summary']['multiple_contract_job_count']}")
    print(f"ANAPEC_SEMANTIC_DUPLICATE_REVIEW_GROUPS={report['summary']['semantic_duplicate_review_group_count']}")
    print(f"ANAPEC_LOCATION_VARIATIONS={report['summary']['location_variation_count']}")
    print(f"ANAPEC_DIFFERENT_SOURCE_LOCATIONS={report['summary']['different_source_location_count']}")
    print(f"ANAPEC_RELATED_LOCATION_DETAILS={report['summary']['related_location_detail_count']}")
    print(f"ANAPEC_MULTI_LOCATION_JOBS={report['summary']['multi_location_job_count']}")
    print("ANAPEC_LOCATION_RELATIONS=" + json.dumps(report['summary']['location_relation_distribution'], ensure_ascii=False, sort_keys=True))
    print("ANAPEC_CONTRACT_DISTRIBUTION=" + json.dumps(report['summary']['contract_distribution'], ensure_ascii=False, sort_keys=True))
    if report["problem_counts"]:
        print("ANAPEC_JOB_QUALITY_PROBLEMS=" + json.dumps(report["problem_counts"], ensure_ascii=False, sort_keys=True))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", default="output/anapec/jobs.json")
    parser.add_argument("--output", default="output/anapec/job_quality_audit.json")
    args = parser.parse_args()
    report = run(args.jobs, args.output)
    return 0 if report["gate"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
