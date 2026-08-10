from datetime import datetime
from zoneinfo import ZoneInfo

from precision_audit import run_golden_audit
from search import rank_job
from taxonomy_engine import Taxonomy


def ids_for(job: dict) -> set[str]:
    return {m["profession_id"] for m in Taxonomy().classify_job(job)}


def test_generic_building_technician_is_not_architectural_drafter():
    ids = ids_for({"job_name": "Technicien en Bâtiment", "specialties": [], "listing_title": "Avis", "grade": "Technicien"})
    assert "btp.technicien_batiment" in ids
    assert "btp.dessinateur_architectural" not in ids
    assert "btp.dessinateur_projeteur" not in ids


def test_dessin_de_batiment_is_architectural_drafter():
    ids = ids_for({"job_name": "", "specialties": ["Dessin de bâtiment"], "listing_title": "Avis", "grade": "Technicien"})
    assert "btp.dessinateur_architectural" in ids


def test_developer_does_not_become_network_technician():
    ids = ids_for({"job_name": "Développeur informatique", "specialties": ["Développement informatique"]})
    assert "it.developpeur_logiciel" in ids
    assert "it.technicien_reseaux" not in ids



def test_generic_recruitment_listing_does_not_become_hr_job():
    ids = ids_for({"job_name": "Développeur informatique", "specialties": ["Développement informatique"], "listing_title": "Avis de recrutement"})
    assert "it.developpeur_logiciel" in ids
    assert "admin.rh" not in ids

def test_comptable_does_not_become_controleur_de_gestion():
    ids = ids_for({"job_name": "Comptable", "specialties": ["Comptabilité"]})
    assert "finance.comptable" in ids
    assert "finance.controleur_gestion" not in ids


def test_infirmier_does_not_become_medecin():
    ids = ids_for({"job_name": "Infirmier", "specialties": ["Soins infirmiers"]})
    assert "health.infirmier" in ids
    assert "health.medecin_generaliste" not in ids
    assert "health.medecin_specialiste" not in ids


def test_related_match_is_never_searchable():
    taxonomy = Taxonomy()
    job = {"job_name": "Technicien en Bâtiment", "specialties": []}
    strong = taxonomy.classify_job(job)
    related = taxonomy.related_job_matches(job, exclude_ids={m["profession_id"] for m in strong})
    drafter = next((m for m in related if m["profession_id"] == "btp.dessinateur_architectural"), None)
    assert drafter is not None
    assert drafter["confidence"] == "RELATED"
    assert drafter["searchable"] is False


def test_rank_job_rejects_related_match_even_if_present_in_index():
    now = datetime(2026, 8, 10, 12, 0, tzinfo=ZoneInfo("Africa/Casablanca"))
    job = {
        "publication_date": "2026-08-10T00:00:00",
        "deadline": "2026-08-20T16:30:00",
        "profession_matches": [
            {
                "profession_id": "btp.dessinateur_architectural",
                "score": 88.0,
                "confidence": "RELATED",
                "searchable": False,
            }
        ],
    }
    score, match = rank_job(job, "btp.dessinateur_architectural", now)
    assert score == -1.0
    assert match is None


def test_golden_precision_gate_passes():
    report = run_golden_audit(Taxonomy())
    assert report["failed_cases"] == 0
    assert report["precision_gate_pct"] == 100.0
