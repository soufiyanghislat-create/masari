from taxonomy_engine import Taxonomy


def ids_for(job: dict) -> set[str]:
    return {row["profession_id"] for row in Taxonomy().classify_job(job)}


def test_public_technicien_developpement_is_not_software_developer():
    ids = ids_for({
        "job_name": "",
        "grade": "Technicien de 3ème grade - echelle 9",
        "specialties": ["développement informatique"],
        "listing_title": "",
    })
    assert "it.technicien_developpement_informatique" in ids
    assert "it.developpeur_logiciel" not in ids


def test_public_technicien_multiple_it_tracks_does_not_become_developer():
    ids = ids_for({
        "job_name": "",
        "grade": "Technicien de 3ème grade - echelle 9",
        "specialties": [
            "Techniques des systèmes d'information",
            "Gestion informatique",
            "Développement technologique informatiques",
            "Développement informatique",
            "Développement Numérique",
        ],
        "listing_title": "",
    })
    assert "it.technicien_developpement_informatique" in ids
    assert "it.developpeur_logiciel" not in ids
    assert "it.technicien_informatique" in ids


def test_agriculture_70_post_tracks_are_precise_technician_roles():
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

    required = {
        "agri.technicien_technico_commercial_horticole",
        "agri.technicien_hydraulique_irrigation",
        "agri.technicien_elevage_ruminants",
        "agri.technicien_gestion_entreprises_agricoles",
        "it.technicien_developpement_informatique",
    }
    assert required <= ids

    forbidden = {
        "sales.commercial",
        "admin.gestionnaire",
        "agri.horticulture",
        "it.developpeur_logiciel",
    }
    assert not (ids & forbidden)


def test_standalone_developer_remains_developer():
    ids = ids_for({
        "job_name": "Développeur informatique",
        "grade": "",
        "specialties": [],
        "listing_title": "",
    })
    assert "it.developpeur_logiciel" in ids
    assert "it.technicien_developpement_informatique" not in ids


def test_formateur_developpement_remains_trainer():
    ids = ids_for({
        "job_name": "Formateur en Développement Informatique",
        "grade": "",
        "specialties": [],
        "listing_title": "",
    })
    assert ids == {"edu.formateur_professionnel"}


def test_engineer_hydraulic_domain_does_not_get_technician_role():
    ids = ids_for({
        "job_name": "",
        "grade": "Ingénieur d'Etat 1er grade - echelle 11",
        "specialties": ["Génie Hydraulique ou Génie Rural"],
        "listing_title": "",
    })
    assert "btp.ingenieur_hydraulique" in ids
    assert "agri.technicien_hydraulique_irrigation" not in ids


def test_generic_public_technicien_without_specialty_stays_unclassified():
    ids = ids_for({
        "job_name": "",
        "grade": "Technicien de 3ème grade - echelle 9",
        "specialties": [],
        "listing_title": "",
    })
    assert ids == set()
