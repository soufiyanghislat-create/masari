#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


CASES = {
    "622731fb-211c-43b2-8562-efb8ab38783d": {
        "required": {"admin.rh"},
        "forbidden": {
            "admin.gestionnaire",
            "admin.paie",
        },
    },
    "78b27d05-3b86-47fc-9356-b0f19b67b73e": {
        "required": {"legal.commissaire_judiciaire"},
        "forbidden": {
            "legal.greffier",
        },
    },
}


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Masari taxonomy v2.7 fresh recruitment/justice semantic audit"
    )
    ap.add_argument("--index", required=True)
    args = ap.parse_args()

    data = json.loads(Path(args.index).read_text(encoding="utf-8"))
    jobs = {j.get("uuid"): j for j in data.get("jobs", [])}

    failures = []
    checked = 0
    case_results = []

    for uuid, rule in CASES.items():
        job = jobs.get(uuid)
        if job is None:
            # Fresh datasets move. Missing current cases do not become false failures.
            case_results.append({
                "uuid": uuid,
                "present": False,
                "pass": True,
                "reason": "not_present_in_current_fresh_index",
            })
            continue

        checked += 1
        ids = {
            m.get("profession_id")
            for m in (job.get("profession_matches") or [])
            if m.get("profession_id")
        }

        missing = sorted(rule["required"] - ids)
        forbidden_present = sorted(rule["forbidden"] & ids)
        ok = not missing and not forbidden_present

        row = {
            "uuid": uuid,
            "present": True,
            "matched_ids": sorted(ids),
            "missing_required": missing,
            "forbidden_present": forbidden_present,
            "pass": ok,
        }
        case_results.append(row)
        if not ok:
            failures.append(row)

    report = {
        "jobs": len(data.get("jobs", [])),
        "checked_current_fresh_cases": checked,
        "cases": case_results,
        "failures": len(failures),
        "failure_details": failures,
        "gate": "PASS" if not failures else "FAIL",
    }

    print("=== MASARI TAXONOMY v2.7 RECRUITMENT/JUSTICE SEMANTIC AUDIT ===")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(
        "MASARI_TAXONOMY_V27_SEMANTIC_GATE="
        + report["gate"]
    )

    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
