#!/usr/bin/env python3
from __future__ import annotations

import json
from taxonomy_engine import Taxonomy, normalize

CASES = [
    {
        "query": "assistante de direction",
        "top": "admin.assistant_direction",
        "forbidden": {"admin.secretaire"},
    },
    {
        "query": "responsable hse",
        "top": "industry.responsable_hse",
        "forbidden": {"industry.qualite"},
    },
    {
        "query": "chargé de publicité",
        "top": "sales.publicite",
        "forbidden": {"sales.marketing"},
    },
    {
        "query": "électricien",
        "forbidden": {"beauty.estheticien"},
    },
    {
        "query": "communication",
        "top": "sales.communication",
        "forbidden": {"it.telecom"},
    },
    {
        "query": "technicien",
        "top_label_prefix": "technicien",
    },
    {
        "query": "ingénieur",
        "top_label_prefix": "ingenieur",
    },
    {
        "query": "informatique",
        "top_label_contains": "informatique",
    },
    {
        "query": "comptablee",
        "top": "finance.comptable",
    },
]

taxonomy = Taxonomy()
failures = []
results = []

for case in CASES:
    rows = taxonomy.autocomplete(case["query"], limit=50)
    ids = [row["profession_id"] for row in rows]
    top = rows[0] if rows else None
    reasons = []

    if case.get("top"):
        actual = top["profession_id"] if top else None
        if actual != case["top"]:
            reasons.append(
                f"expected_top={case['top']} actual_top={actual}"
            )

    forbidden = set(case.get("forbidden") or ())
    present = sorted(forbidden & set(ids))
    if present:
        reasons.append(f"forbidden={present}")

    if case.get("top_label_prefix"):
        label = normalize(top["label"]) if top else ""
        if not label.startswith(case["top_label_prefix"]):
            reasons.append(f"unexpected_top_label={label!r}")

    if case.get("top_label_contains"):
        label = normalize(top["label"]) if top else ""
        if case["top_label_contains"] not in label:
            reasons.append(f"unexpected_top_label={label!r}")

    result = {
        "query": case["query"],
        "top": top,
        "count": len(rows),
        "pass": not reasons,
        "reasons": reasons,
    }
    results.append(result)
    if reasons:
        failures.append(result)

dev_ids = {
    row["profession_id"]
    for row in taxonomy.autocomplete(
        "développement informatique",
        limit=50,
    )
}
required_dev = {
    "it.developpeur_logiciel",
    "it.technicien_developpement_informatique",
}
missing_dev = sorted(required_dev - dev_ids)
if missing_dev:
    failures.append({
        "query": "développement informatique",
        "pass": False,
        "reasons": [f"missing={missing_dev}"],
    })

gc_ids = [
    row["profession_id"]
    for row in taxonomy.autocomplete("génie civil", limit=50)
]
if "edu.formateur_professionnel" in gc_ids:
    trainer = gc_ids.index("edu.formateur_professionnel")
    for required in (
        "btp.ingenieur_genie_civil",
        "btp.technicien_genie_civil",
    ):
        if required not in gc_ids or gc_ids.index(required) > trainer:
            failures.append({
                "query": "génie civil",
                "pass": False,
                "reasons": [f"{required} must rank before trainer"],
            })

report = {
    "cases": results,
    "failures": len(failures),
    "failure_details": failures,
    "gate": "PASS" if not failures else "FAIL",
}

print("=== MASARI AUTOCOMPLETE PRECISION AUDIT v2.3 ===")
print(json.dumps(report, ensure_ascii=False, indent=2))
print(
    "MASARI_AUTOCOMPLETE_PRECISION_GATE="
    + ("PASS" if not failures else "FAIL")
)
raise SystemExit(0 if not failures else 1)
