from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from taxonomy_engine import STRICT_SEARCH_MIN_SCORE, Taxonomy

TZ = ZoneInfo("Africa/Casablanca")

GOLDEN_CASES = [
    {
        "name": "generic_building_technician_is_not_drafter",
        "job": {"job_name": "Technicien en Bâtiment", "specialties": [], "listing_title": "Avis de recrutement", "grade": "Technicien"},
        "must_include": ["btp.technicien_batiment"],
        "must_exclude": ["btp.dessinateur_architectural", "btp.dessinateur_projeteur"],
    },
    {
        "name": "drawing_specialty_maps_to_architectural_drafter",
        "job": {"job_name": "", "specialties": ["Dessin de bâtiment"], "listing_title": "Avis de concours", "grade": "Technicien de 3ème grade"},
        "must_include": ["btp.dessinateur_architectural"],
        "must_exclude": [],
    },
    {
        "name": "architectural_drafter_title_maps_exactly",
        "job": {"job_name": "Dessinateur en bâtiment", "specialties": [], "listing_title": "Recrutement", "grade": "Technicien"},
        "must_include": ["btp.dessinateur_architectural"],
        "must_exclude": ["btp.technicien_batiment"],
    },
    {
        "name": "civil_engineering_technician_is_not_drafter",
        "job": {"job_name": "Technicien en génie civil", "specialties": ["Génie civil"], "listing_title": "Avis de concours", "grade": "Technicien"},
        "must_include": ["btp.technicien_genie_civil"],
        "must_exclude": ["btp.dessinateur_architectural"],
    },
    {
        "name": "developer_is_not_network_technician",
        "job": {"job_name": "Développeur informatique", "specialties": ["Développement informatique"], "listing_title": "Recrutement", "grade": ""},
        "must_include": ["it.developpeur_logiciel"],
        "must_exclude": ["it.technicien_reseaux", "it.administrateur_reseaux"],
    },
    {
        "name": "accountant_is_not_management_controller",
        "job": {"job_name": "Comptable", "specialties": ["Comptabilité"], "listing_title": "Recrutement", "grade": ""},
        "must_include": ["finance.comptable"],
        "must_exclude": ["finance.controleur_gestion"],
    },
    {
        "name": "management_controller_is_not_accountant",
        "job": {"job_name": "Contrôleur de gestion", "specialties": ["Contrôle de gestion"], "listing_title": "Recrutement", "grade": ""},
        "must_include": ["finance.controleur_gestion"],
        "must_exclude": ["finance.comptable"],
    },
    {
        "name": "nurse_is_not_doctor",
        "job": {"job_name": "Infirmier", "specialties": ["Soins infirmiers"], "listing_title": "Recrutement", "grade": ""},
        "must_include": ["health.infirmier"],
        "must_exclude": ["health.medecin_generaliste", "health.medecin_specialiste"],
    },
    {
        "name": "doctor_is_not_nurse",
        "job": {"job_name": "Médecin généraliste", "specialties": [], "listing_title": "Recrutement", "grade": ""},
        "must_include": ["health.medecin_generaliste"],
        "must_exclude": ["health.infirmier"],
    },
    {
        "name": "maitre_de_conferences_from_listing_title",
        "job": {
            "job_name": "",
            "specialties": ["Science économiques"],
            "listing_title": "Avis de concours de recrutement de Maître de conférences grade A - Echelle 11 Université Moulay Ismaïl - Meknès Annonce 1 poste Limite de dépôt : 8 Septembre 2026 Date du concours : 17 Septembre 2026",
            "grade": "Maître de conférences grade A - echelle 11",
        },
        "must_include": ["edu.prof_universitaire"],
        "must_exclude": [],
    },
    {
        "name": "generic_technicien_grade_without_specialty_stays_unclassified",
        "job": {
            "job_name": "",
            "specialties": [],
            "listing_title": "Avis de concours de recrutement de Technicien de 3ème grade - Echelle 9 Archives du Maroc Annonce Dépôt en ligne 1 poste Limite de dépôt : 28 Août 2026 Date du concours : 27 Septembre 2026",
            "grade": "Technicien de 3ème grade - echelle 9",
        },
        "must_include": [],
        "must_exclude": [],
        "allowed_ids": [],
    },
    {
        "name": "charge_contenu_is_not_hr",
        "job": {
            "job_name": "Chargé de contenu Francophone",
            "specialties": [],
            "listing_title": "Avis de concours de recrutement de Chargé de contenu Francophone Office de la Formation Professionnelle et de la Promotion du Travail Annonce 1 poste Limite de dépôt : 6 Septembre 2026",
            "grade": "",
        },
        "must_include": ["sales.charge_contenu"],
        "must_exclude": ["admin.rh"],
    },
    {
        "name": "specialized_formateur_is_not_it_operator",
        "job": {
            "job_name": "Formateur en Réseaux Informatiques-(Bac+5)",
            "specialties": [],
            "listing_title": "Avis de concours de recrutement de Formateur en Réseaux Informatiques-(Bac+5) Office de la Formation Professionnelle et de la Promotion du Travail Annonce 1 poste Limite de dépôt : 6 Septembre 2026",
            "grade": "",
        },
        "must_include": ["edu.formateur_professionnel"],
        "must_exclude": ["it.technicien_reseaux", "it.administrateur_reseaux"],
    },
]


def run_golden_audit(taxonomy: Taxonomy) -> dict:
    case_results = []
    for case in GOLDEN_CASES:
        matches = taxonomy.classify_job(case["job"])
        ids = {m["profession_id"] for m in matches}
        missing = [x for x in case["must_include"] if x not in ids]
        forbidden = [x for x in case["must_exclude"] if x in ids]
        allowed_ids = set(case.get("allowed_ids") or case["must_include"])
        unexpected = sorted(ids - allowed_ids)
        low_confidence = [
            m["profession_id"]
            for m in matches
            if not m.get("searchable", True) or float(m.get("score") or 0) < STRICT_SEARCH_MIN_SCORE
        ]
        passed = not missing and not forbidden and not unexpected and not low_confidence
        case_results.append(
            {
                "name": case["name"],
                "pass": passed,
                "matched_ids": sorted(ids),
                "missing_required": missing,
                "forbidden_present": forbidden,
                "unexpected_search_matches": unexpected,
                "low_confidence_search_matches": low_confidence,
            }
        )
    passed_count = sum(1 for c in case_results if c["pass"])
    pct = round(passed_count / len(case_results) * 100, 2) if case_results else 100.0
    return {
        "golden_cases": len(case_results),
        "passed_cases": passed_count,
        "failed_cases": len(case_results) - passed_count,
        "precision_gate_pct": pct,
        "cases": case_results,
    }


def audit_index(index_path: Path) -> dict:
    if not index_path.exists():
        return {"index_present": False, "unsafe_search_matches": [], "unsafe_count": 0}
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    unsafe = []
    for job in payload.get("jobs") or []:
        for match in job.get("profession_matches") or []:
            score = float(match.get("score") or 0)
            confidence = match.get("confidence")
            searchable = match.get("searchable", True)
            if not searchable or confidence == "RELATED" or score < STRICT_SEARCH_MIN_SCORE:
                unsafe.append(
                    {
                        "uuid": job.get("uuid"),
                        "profession_id": match.get("profession_id"),
                        "score": score,
                        "confidence": confidence,
                        "searchable": searchable,
                    }
                )
    return {"index_present": True, "unsafe_search_matches": unsafe[:100], "unsafe_count": len(unsafe)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Masari taxonomy precision gate")
    ap.add_argument("--index", default="output/search_index.json")
    ap.add_argument("--output", default="output/taxonomy_precision_audit.json")
    args = ap.parse_args()

    taxonomy = Taxonomy()
    golden = run_golden_audit(taxonomy)
    index_audit = audit_index(Path(args.index))
    gate = golden["failed_cases"] == 0 and index_audit["unsafe_count"] == 0
    report = {
        "generated_at": datetime.now(TZ).isoformat(),
        "policy": "exact_strong_search_related_internal_only",
        **golden,
        "index": index_audit,
        "gate": "PASS" if gate else "FAIL",
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== MASARI TAXONOMY PRECISION AUDIT ===")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"MASARI_TAXONOMY_PRECISION_GATE={report['gate']}")
    return 0 if gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
