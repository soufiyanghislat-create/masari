from taxonomy_engine import Taxonomy


def ids_for(job: dict) -> set[str]:
    return {row["profession_id"] for row in Taxonomy().classify_job(job)}


def test_single_development_track_drops_generic_it_parent():
    ids = ids_for({
        "job_name": "",
        "grade": "Technicien de 3ème grade - echelle 9",
        "specialties": ["développement informatique"],
        "listing_title": "",
    })
    assert "it.technicien_developpement_informatique" in ids
    assert "it.technicien_informatique" not in ids
    assert "it.developpeur_logiciel" not in ids


def test_agriculture_development_track_drops_generic_it_parent():
    ids = ids_for({
        "job_name": "",
        "grade": "Technicien de 3ème grade - echelle 9",
        "specialties": [
            "Technico-commercial en production horticole",
            "Gestion et maitrise de l’eau / Hydraulique rurale et irrigation / Environnement et techniques de l’eau",
            "Elevage des ruminants",
            "Gestion des entreprises agricoles",
            "Développement informatique",
        ],
        "listing_title": "",
    })
    assert "it.technicien_developpement_informatique" in ids
    assert "it.technicien_informatique" not in ids


def test_independent_gestion_informatique_keeps_generic_it_role():
    ids = ids_for({
        "job_name": "",
        "grade": "Technicien de 3ème grade - echelle 9",
        "specialties": [
            "Techniques des systèmes d'information",
            "Gestion informatique",
            "Développement informatique",
        ],
        "listing_title": "",
    })
    assert "it.technicien_developpement_informatique" in ids
    assert "it.technicien_informatique" in ids
    assert "it.technicien_systemes_information" in ids


def test_maintenance_network_track_keeps_generic_it_role():
    ids = ids_for({
        "job_name": "",
        "grade": "Technicien de 3ème grade - echelle 9",
        "specialties": ["Maintenance Informatique et réseaux"],
        "listing_title": "",
    })
    assert "it.technicien_informatique" in ids
    assert "it.technicien_reseaux" in ids
    assert "it.technicien_support" in ids
