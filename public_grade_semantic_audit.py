#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import unicodedata
import re
from pathlib import Path


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold()
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", required=True)
    args = parser.parse_args()

    path = Path(args.index)
    data = json.loads(path.read_text(encoding="utf-8"))
    failures = []

    for job in data.get("jobs") or []:
        grade = normalize(job.get("grade") or "")
        if "technicien" not in grade:
            continue

        specialties = " | ".join(
            normalize(x) for x in (job.get("specialties") or [])
        )
        ids = {
            m["profession_id"]
            for m in (job.get("profession_matches") or [])
        }

        if "developpement informatique" in specialties:
            if "it.developpeur_logiciel" in ids:
                failures.append({
                    "type": "TECHNICIEN_BECAME_DEVELOPER",
                    "grade": job.get("grade"),
                    "specialties": job.get("specialties"),
                    "ids": sorted(ids),
                })
            if "it.technicien_developpement_informatique" not in ids:
                failures.append({
                    "type": "MISSING_TECHNICIEN_DEVELOPPEMENT",
                    "grade": job.get("grade"),
                    "specialties": job.get("specialties"),
                    "ids": sorted(ids),
                })

        if "technico commercial en production horticole" in specialties:
            required = {
                "agri.technicien_technico_commercial_horticole",
                "agri.technicien_hydraulique_irrigation",
                "agri.technicien_elevage_ruminants",
                "agri.technicien_gestion_entreprises_agricoles",
                "it.technicien_developpement_informatique",
            }
            missing = sorted(required - ids)
            forbidden = sorted(ids & {
                "sales.commercial",
                "admin.gestionnaire",
                "agri.horticulture",
                "it.developpeur_logiciel",
            })
            if missing or forbidden:
                failures.append({
                    "type": "AGRICULTURE_MULTI_SPECIALTY_SEMANTICS",
                    "grade": job.get("grade"),
                    "specialties": job.get("specialties"),
                    "missing": missing,
                    "forbidden": forbidden,
                    "ids": sorted(ids),
                })

    print("=== MASARI PUBLIC GRADE SEMANTIC AUDIT v2.0 ===")
    print(json.dumps({
        "jobs": len(data.get("jobs") or []),
        "failures": len(failures),
        "failure_details": failures,
        "gate": "PASS" if not failures else "FAIL",
    }, ensure_ascii=False, indent=2))

    print(
        "MASARI_PUBLIC_GRADE_SEMANTIC_GATE="
        + ("PASS" if not failures else "FAIL")
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
