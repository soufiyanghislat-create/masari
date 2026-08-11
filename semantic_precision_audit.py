#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold()
    value = value.replace("’", "'")
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


ACADEMIC_MARKERS = (
    "maître de conférences",
    "maitre de conferences",
    "maître de conférence",
    "maitre de conference",
    "أستاذ محاضر",
)

TRAINER_MARKERS = (
    "formateur",
    "formatrice",
)

DOMINANCE = {
    "it.cybersecurite": {"it.responsable_si"},
    "it.base_donnees": {"it.administrateur_systemes"},
    "it.data_analyst": {"it.data_scientist"},
    "sales.communication": {"management.charge_projet"},
    "btp.chef_projet_genie_civil": {"management.charge_projet"},
    "industry.responsable_hse": {"industry.qualite"},
    "sales.responsable_communication": {"sales.communication"},
    "sales.publicite": {"sales.marketing"},
    "admin.assistant_direction": {"admin.secretaire"},
}

ROLE_EXPECTATIONS = (
    ("responsable hse", "industry.responsable_hse"),
    ("chef de service communication", "sales.responsable_communication"),
    ("charge de publicite", "sales.publicite"),
    ("chargee de publicite", "sales.publicite"),
    ("assistant de direction", "admin.assistant_direction"),
    ("assistante de direction", "admin.assistant_direction"),
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit real Masari search-index role semantics"
    )
    parser.add_argument("--index", required=True)
    args = parser.parse_args()

    path = Path(args.index)
    if not path.exists():
        print(f"MASARI_REAL_SEMANTIC_PRECISION_GATE=FAIL missing index: {path}")
        return 2

    data = json.loads(path.read_text(encoding="utf-8"))
    failures = []
    classified = 0
    multi = 0

    for job in data.get("jobs") or []:
        matches = job.get("profession_matches") or []
        if not matches:
            continue

        classified += 1
        if len(matches) > 1:
            multi += 1

        ids = {m["profession_id"] for m in matches}
        job_name = str(job.get("job_name") or "")
        grade = str(job.get("grade") or "")
        listing_title = str(job.get("listing_title") or "")
        role_text = " ".join([job_name, grade, listing_title])
        n_role = normalize(role_text)
        n_job_name = normalize(job_name)

        if any(normalize(marker) in n_role for marker in ACADEMIC_MARKERS):
            if ids != {"edu.prof_universitaire"}:
                failures.append({
                    "type": "academic_role_leak",
                    "job": job_name or grade or listing_title,
                    "ids": sorted(ids),
                })

        if any(re.search(rf"(?:^| ){re.escape(normalize(marker))}(?:$| )", n_job_name)
               for marker in TRAINER_MARKERS):
            if ids != {"edu.formateur_professionnel"}:
                failures.append({
                    "type": "trainer_role_leak",
                    "job": job_name,
                    "ids": sorted(ids),
                })

        for phrase, expected_id in ROLE_EXPECTATIONS:
            if phrase in n_job_name and ids != {expected_id}:
                failures.append({
                    "type": "explicit_role_mismatch",
                    "job": job_name,
                    "expected": expected_id,
                    "ids": sorted(ids),
                })

        for specific, generics in DOMINANCE.items():
            if specific in ids:
                bad = sorted(ids & generics)
                if bad:
                    failures.append({
                        "type": "generic_specific_duplicate",
                        "job": job_name or grade or listing_title,
                        "specific": specific,
                        "unexpected": bad,
                    })

        fields = [(m.get("evidence") or {}).get("field") for m in matches]
        if job_name and "job_name" in fields and "specialty" in fields:
            failures.append({
                "type": "explicit_title_specialty_competition",
                "job": job_name,
                "ids": sorted(ids),
            })

        for match in matches:
            ev = match.get("evidence") or {}
            if ev.get("field") == "listing_role":
                value = str(ev.get("value") or "")
                n_value = f" {normalize(value)} "
                for marker in (
                    " agence ",
                    " ministere ",
                    " universite ",
                    " chambre ",
                    " province ",
                    " institut ",
                ):
                    if marker in n_value:
                        failures.append({
                            "type": "listing_role_entity_contamination",
                            "job": listing_title or grade,
                            "profession": match["profession_id"],
                            "evidence": value,
                        })
                        break

    print("=== MASARI REAL SEMANTIC PRECISION AUDIT v1.7 ===")
    print(json.dumps({
        "jobs": len(data.get("jobs") or []),
        "classified_jobs": classified,
        "multi_match_jobs": multi,
        "failures": len(failures),
        "failure_details": failures,
        "gate": "PASS" if not failures else "FAIL",
    }, ensure_ascii=False, indent=2))
    print(
        "MASARI_REAL_SEMANTIC_PRECISION_GATE="
        + ("PASS" if not failures else "FAIL")
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
