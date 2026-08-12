#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

EXPECTED = {
    "9643ae15-0c73-49c7-b69e-d4c6347549ef": {
        "required": {"finance.actuaire"},
        "forbidden": set(),
    },
    "0b660a5c-18e4-42a9-b35a-96cd32f86b53": {
        "required": {"industry.technicien_electrique"},
        "forbidden": set(),
    },
    "c5871c7d-a63d-437b-95e1-bae28349595d": {
        "required": {"management.charge_projet"},
        "forbidden": {
            "btp.chef_projet_genie_civil",
            "it.developpeur_logiciel",
        },
    },
    "089e1b81-21f8-4b8b-b929-f1cc76ede259": {
        "required": {"operations.technicien_gestion_maintenance"},
        "forbidden": {
            "admin.gestionnaire",
            "industry.maintenance_industrielle",
        },
    },
    "8d831b6d-e9e6-4c8d-915b-05854c488ed4": {
        "required": {"finance.charge_pilotage_mandat_gestion"},
        "forbidden": {
            "finance.gerant_portefeuille",
            "admin.gestionnaire",
            "management.charge_projet",
        },
    },
}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", required=True)
    args = parser.parse_args()

    path = Path(args.index)
    data = json.loads(path.read_text(encoding="utf-8"))
    jobs = data["jobs"]

    by_uuid = {str(j.get("uuid")): j for j in jobs}
    failures = []
    details = []

    for uuid, rule in EXPECTED.items():
        job = by_uuid.get(uuid)
        if job is None:
            details.append({
                "uuid": uuid,
                "status": "NOT_PRESENT_IN_CURRENT_WINDOW",
            })
            continue

        actual = {
            m["profession_id"]
            for m in (job.get("profession_matches") or [])
        }

        missing = sorted(rule["required"] - actual)
        forbidden = sorted(rule["forbidden"] & actual)
        reasons = []

        if missing:
            reasons.append(f"missing={missing}")
        if forbidden:
            reasons.append(f"forbidden={forbidden}")

        row = {
            "uuid": uuid,
            "job_name": job.get("job_name"),
            "actual": sorted(actual),
            "pass": not reasons,
            "reasons": reasons,
        }
        details.append(row)
        if reasons:
            failures.append(row)

    report = {
        "jobs": len(jobs),
        "checked_current_fresh_cases": sum(
            1 for row in details
            if row.get("status") != "NOT_PRESENT_IN_CURRENT_WINDOW"
        ),
        "failures": len(failures),
        "failure_details": failures,
        "gate": "PASS" if not failures else "FAIL",
    }

    print("=== MASARI FRESH DELTA SEMANTIC AUDIT v2.5 ===")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(
        "MASARI_FRESH_DELTA_SEMANTIC_GATE="
        + ("PASS" if not failures else "FAIL")
    )
    return 0 if not failures else 1

if __name__ == "__main__":
    raise SystemExit(main())
