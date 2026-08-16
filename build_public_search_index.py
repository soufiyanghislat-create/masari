#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from classifiability import evaluate_classifiable_coverage
from literal_search import LITERAL_SOURCES, literal_profession_for_job
from taxonomy_engine import Taxonomy

TZ = ZoneInfo("Africa/Casablanca")


def _display_title(job: dict) -> str:
    if job.get("job_name"):
        return str(job["job_name"])
    specialties = [str(x) for x in (job.get("specialties") or []) if x]
    if specialties:
        return " / ".join(specialties[:3])
    if job.get("grade"):
        return str(job["grade"])
    return str(job.get("listing_title") or "Offre publique")


def _source(job: dict) -> str:
    return str(job.get("source") or "emploi-public").strip().casefold()


def main() -> int:
    ap = argparse.ArgumentParser(description="Build Masari multi-source search index with source-aware hard gates")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--min-coverage", type=float, default=90.0)
    args = ap.parse_args()

    source_path = Path(args.input)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    if not source_path.exists():
        print(f"Missing input: {source_path}", file=sys.stderr)
        return 2

    jobs = json.loads(source_path.read_text(encoding="utf-8"))
    taxonomy = Taxonomy()
    indexed = []
    unclassified = []
    literal_fallback = []
    classified_positions = total_positions = 0
    market_classified = hcp_fallback_classified = 0
    exact_jobs = strong_jobs = related_only_jobs = 0

    for job in jobs:
        matches = taxonomy.classify_job(job)
        strong_ids = {m["profession_id"] for m in matches}
        related = taxonomy.related_job_matches(job, exclude_ids=strong_ids)

        copy = dict(job)
        copy["search_title"] = _display_title(job)
        copy["profession_matches"] = matches
        copy["profession_ids"] = [m["profession_id"] for m in matches]
        copy["related_profession_matches"] = related
        literal = literal_profession_for_job(copy)
        if literal:
            copy["literal_profession"] = literal
            if not matches:
                literal_fallback.append({
                    "uuid": copy.get("uuid"),
                    "global_id": copy.get("global_id"),
                    "source": _source(copy),
                    "source_offer_id": copy.get("source_offer_id"),
                    "title": copy.get("job_name") or copy.get("title"),
                    "literal_profession_id": literal["profession_id"],
                })
        indexed.append(copy)
        positions = int(job.get("positions") or 0)
        total_positions += positions
        if matches:
            classified_positions += positions
            confidences = {m.get("confidence") for m in matches}
            if "EXACT" in confidences:
                exact_jobs += 1
            else:
                strong_jobs += 1
            if any(m["source"] == "masari_market" for m in matches):
                market_classified += 1
            else:
                hcp_fallback_classified += 1
        else:
            if related:
                related_only_jobs += 1
            unclassified.append({
                "uuid": job.get("uuid"),
                "global_id": job.get("global_id"),
                "source": _source(job),
                "url": job.get("url"),
                "listing_title": job.get("listing_title"),
                "job_name": job.get("job_name"),
                "grade": job.get("grade"),
                "specialties": job.get("specialties") or [],
                "positions": positions,
                "related_profession_matches": related,
                "literal_profession": literal,
            })

    aggregate_classifiability = evaluate_classifiable_coverage(
        indexed,
        minimum_coverage_pct=args.min_coverage,
    )
    emploi_public_jobs = [j for j in indexed if _source(j) == "emploi-public"]
    emploi_public_gate = evaluate_classifiable_coverage(
        emploi_public_jobs,
        minimum_coverage_pct=args.min_coverage,
    )

    source_counts = dict(sorted(Counter(_source(job) for job in indexed).items()))
    canonical_classified_by_source = dict(
        sorted(Counter(_source(job) for job in indexed if job.get("profession_matches")).items())
    )

    private_gate_rows: dict[str, dict] = {}
    missing_literal_by_source: dict[str, list[dict]] = {}
    private_source_gates: list[bool] = []

    for source_name in sorted(LITERAL_SOURCES):
        source_jobs = [j for j in indexed if _source(j) == source_name]
        missing = [
            {
                "uuid": j.get("uuid"),
                "source_offer_id": j.get("source_offer_id"),
                "title": j.get("job_name") or j.get("title"),
            }
            for j in source_jobs
            if not isinstance(j.get("literal_profession"), dict)
        ]
        missing_literal_by_source[source_name] = missing
        literal_jobs = len(source_jobs) - len(missing)
        literal_coverage = (
            round(literal_jobs / len(source_jobs) * 100, 2)
            if source_jobs
            else 100.0
        )
        source_gate = not missing and literal_coverage == 100.0
        private_source_gates.append(source_gate)
        private_gate_rows[source_name] = {
            "policy": "verified_explicit_title_literal_searchability",
            "jobs": len(source_jobs),
            "literal_searchable_jobs": literal_jobs,
            "literal_searchability_coverage_pct": literal_coverage,
            "required_pct": 100.0,
            "canonical_taxonomy_classified_jobs": canonical_classified_by_source.get(source_name, 0),
            "literal_fallback_jobs": sum(
                1 for row in literal_fallback if row.get("source") == source_name
            ),
            "missing_literal_jobs": len(missing),
            "gate": "PASS" if source_gate else "FAIL",
        }

    gate = bool(emploi_public_gate["gate"] and all(private_source_gates))

    index_payload = {
        "version": 4,
        "generated_at": datetime.now(TZ).isoformat(),
        "source": "public",
        "sources": source_counts,
        "classification_policy": "source_aware_v3_canonical_plus_verified_literal_fallback",
        "jobs": indexed,
    }

    classified = aggregate_classifiability["classified_jobs"]
    coverage = aggregate_classifiability["raw_classification_coverage_pct"]
    position_coverage = (
        round(classified_positions / total_positions * 100, 2)
        if total_positions
        else 100.0
    )

    source_gate_policy = {
        "emploi-public": {
            "policy": "existing_classifiable_taxonomy_coverage",
            "jobs": len(emploi_public_jobs),
            "classifiable_coverage_pct": emploi_public_gate["classifiable_coverage_pct"],
            "minimum_required_pct": args.min_coverage,
            "ambiguous_classified_jobs": emploi_public_gate["ambiguous_classified_jobs"],
            "gate": "PASS" if emploi_public_gate["gate"] else "FAIL",
        },
        **private_gate_rows,
    }

    taxonomy_audit = {
        "source": "public",
        "generated_at": datetime.now(TZ).isoformat(),
        "jobs": len(indexed),
        "sources": source_counts,
        "canonical_classified_by_source": canonical_classified_by_source,
        "classified_jobs": classified,
        "unclassified_jobs": len(unclassified),
        "classification_coverage_pct": coverage,
        "raw_classification_coverage_pct": coverage,
        "structurally_ambiguous_jobs": aggregate_classifiability["structurally_ambiguous_jobs"],
        "classifiable_jobs": aggregate_classifiability["classifiable_jobs"],
        "classified_classifiable_jobs": aggregate_classifiability["classified_classifiable_jobs"],
        "unexplained_unclassified_jobs": aggregate_classifiability["unexplained_unclassified_jobs"],
        "classifiable_coverage_pct": aggregate_classifiability["classifiable_coverage_pct"],
        "ambiguous_classified_jobs": aggregate_classifiability["ambiguous_classified_jobs"],
        "positions": total_positions,
        "classified_positions": classified_positions,
        "position_coverage_pct": position_coverage,
        "market_classified_jobs": market_classified,
        "hcp_fallback_classified_jobs": hcp_fallback_classified,
        "exact_jobs": exact_jobs,
        "strong_jobs": strong_jobs,
        "related_only_jobs": related_only_jobs,
        "market_professions": len(taxonomy.market),
        "hcp_professions": len(taxonomy.hcp),
        "minimum_required_coverage_pct": args.min_coverage,
        "source_gate_policy": source_gate_policy,
        "coverage_gate_policy": "SOURCE_AWARE_HARD_GATES_NO_FABRICATED_TAXONOMY",
        "searchable_match_policy": "CANONICAL_EXACT_STRONG_OR_VERIFIED_PRIVATE_LITERAL_TITLE",
        "gate": "PASS" if gate else "FAIL",
    }

    files = {
        "search_index.json": index_payload,
        "autocomplete.json": taxonomy.autocomplete_payload(),
        "taxonomy_audit.json": taxonomy_audit,
        "unclassified_jobs.json": unclassified,
        "literal_fallback_jobs.json": literal_fallback,
        "anapec_missing_literal_jobs.json": missing_literal_by_source.get("anapec", []),
        "smartrecruiters_missing_literal_jobs.json": missing_literal_by_source.get("smartrecruiters", []),
        "structurally_ambiguous_jobs.json": aggregate_classifiability["structurally_ambiguous_rows"],
        "unexplained_unclassified_jobs.json": aggregate_classifiability["unexplained_unclassified_rows"],
        "ambiguous_classified_jobs.json": aggregate_classifiability["ambiguous_classified_rows"],
    }
    for name, data in files.items():
        (out / name).write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print("=== MASARI PUBLIC SOURCE-AWARE SEARCH INDEX v3 ===")
    print(json.dumps(taxonomy_audit, ensure_ascii=False, indent=2))
    print(f"MASARI_PUBLIC_SEARCH_INDEX_GATE={taxonomy_audit['gate']}")
    return 0 if gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
