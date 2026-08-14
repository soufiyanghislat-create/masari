from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from classifiability import evaluate_classifiable_coverage
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Build deterministic Masari search index from verified public jobs")
    ap.add_argument("--input", default="output/jobs.json")
    ap.add_argument("--output", default="output")
    ap.add_argument(
        "--min-coverage",
        type=float,
        default=0.0,
        help="Fail if classifiable-job searchable coverage is below this percentage",
    )
    args = ap.parse_args()

    source = Path(args.input)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        print(f"Missing input: {source}", file=sys.stderr)
        return 2

    jobs = json.loads(source.read_text(encoding="utf-8"))
    taxonomy = Taxonomy()
    indexed = []
    unclassified = []
    classified_positions = 0
    total_positions = 0
    market_classified = 0
    hcp_fallback_classified = 0
    exact_jobs = 0
    strong_jobs = 0
    related_only_jobs = 0

    for job in jobs:
        matches = taxonomy.classify_job(job)
        strong_ids = {m["profession_id"] for m in matches}
        related = taxonomy.related_job_matches(job, exclude_ids=strong_ids)

        copy = dict(job)
        copy["search_title"] = _display_title(job)
        # Only these matches are eligible for search results.
        copy["profession_matches"] = matches
        copy["profession_ids"] = [m["profession_id"] for m in matches]
        # RELATED matches are retained for taxonomy maintenance/debugging only.
        copy["related_profession_matches"] = related
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
            unclassified.append(
                {
                    "uuid": job.get("uuid"),
                    "url": job.get("url"),
                    "listing_title": job.get("listing_title"),
                    "job_name": job.get("job_name"),
                    "grade": job.get("grade"),
                    "specialties": job.get("specialties") or [],
                    "positions": positions,
                    "related_profession_matches": related,
                }
            )

    classifiability = evaluate_classifiable_coverage(
        indexed,
        minimum_coverage_pct=args.min_coverage,
    )
    classified = classifiability["classified_jobs"]
    coverage = classifiability["raw_classification_coverage_pct"]
    position_coverage = round(classified_positions / total_positions * 100, 2) if total_positions else 100.0
    gate = classifiability["gate"]

    source_counts: dict[str, int] = {}
    for job in indexed:
        source = str(job.get("source") or "emploi-public")
        source_counts[source] = source_counts.get(source, 0) + 1

    index_payload = {
        "version": 3,
        "generated_at": datetime.now(TZ).isoformat(),
        "source": "public",
        "sources": dict(sorted(source_counts.items())),
        "classification_policy": "precision_v1.2_exact_strong_only",
        "jobs": indexed,
    }
    taxonomy_audit = {
        "source": "public",
        "generated_at": datetime.now(TZ).isoformat(),
        "jobs": len(indexed),
        "classified_jobs": classified,
        "unclassified_jobs": len(unclassified),
        "classification_coverage_pct": coverage,
        "raw_classification_coverage_pct": coverage,
        "structurally_ambiguous_jobs": classifiability["structurally_ambiguous_jobs"],
        "classifiable_jobs": classifiability["classifiable_jobs"],
        "classified_classifiable_jobs": classifiability["classified_classifiable_jobs"],
        "unexplained_unclassified_jobs": classifiability["unexplained_unclassified_jobs"],
        "classifiable_coverage_pct": classifiability["classifiable_coverage_pct"],
        "ambiguous_classified_jobs": classifiability["ambiguous_classified_jobs"],
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
        "minimum_required_classifiable_coverage_pct": args.min_coverage,
        "coverage_gate_policy": "CLASSIFIABLE_COVERAGE_AND_ZERO_AMBIGUOUS_CLASSIFICATIONS",
        "searchable_match_policy": "EXACT_OR_STRONG_ONLY",
        "gate": "PASS" if gate else "FAIL",
    }

    (out / "search_index.json").write_text(json.dumps(index_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "autocomplete.json").write_text(json.dumps(taxonomy.autocomplete_payload(), ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "taxonomy_audit.json").write_text(json.dumps(taxonomy_audit, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "unclassified_jobs.json").write_text(json.dumps(unclassified, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "structurally_ambiguous_jobs.json").write_text(
        json.dumps(classifiability["structurally_ambiguous_rows"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out / "unexplained_unclassified_jobs.json").write_text(
        json.dumps(classifiability["unexplained_unclassified_rows"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out / "ambiguous_classified_jobs.json").write_text(
        json.dumps(classifiability["ambiguous_classified_rows"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("=== MASARI TAXONOMY INDEX ===")
    print(json.dumps(taxonomy_audit, ensure_ascii=False, indent=2))
    print(f"MASARI_TAXONOMY_GATE={taxonomy_audit['gate']}")
    return 0 if gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
