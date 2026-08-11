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
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def is_development_track(value: str) -> bool:
    value = normalize(value)
    return (
        "developpement informatique" in value
        or "developpement numerique" in value
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", required=True)
    args = parser.parse_args()

    data = json.loads(Path(args.index).read_text(encoding="utf-8"))
    failures = []

    for job in data.get("jobs") or []:
        grade = normalize(job.get("grade") or "")
        if "technicien" not in grade:
            continue

        specialties = [
            normalize(x) for x in (job.get("specialties") or [])
        ]
        if not any(is_development_track(x) for x in specialties):
            continue

        ids = {
            m["profession_id"]
            for m in (job.get("profession_matches") or [])
        }

        independent_it = any(
            "informatique" in value and not is_development_track(value)
            for value in specialties
        )

        if not independent_it and "it.technicien_informatique" in ids:
            failures.append({
                "type": "REDUNDANT_GENERIC_IT_PARENT",
                "grade": job.get("grade"),
                "specialties": job.get("specialties"),
                "ids": sorted(ids),
            })

        if independent_it and "it.technicien_informatique" not in ids:
            failures.append({
                "type": "MISSING_INDEPENDENT_GENERIC_IT_TRACK",
                "grade": job.get("grade"),
                "specialties": job.get("specialties"),
                "ids": sorted(ids),
            })

    print("=== MASARI SPECIFICITY SEMANTIC AUDIT v2.1 ===")
    print(json.dumps({
        "jobs": len(data.get("jobs") or []),
        "failures": len(failures),
        "failure_details": failures,
        "gate": "PASS" if not failures else "FAIL",
    }, ensure_ascii=False, indent=2))
    print(
        "MASARI_SPECIFICITY_SEMANTIC_GATE="
        + ("PASS" if not failures else "FAIL")
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
