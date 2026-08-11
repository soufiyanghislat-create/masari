from taxonomy_engine import Taxonomy


def ids_for(job: dict) -> set[str]:
    return {row["profession_id"] for row in Taxonomy().classify_job(job)}


def test_rssi_keeps_cybersecurity_not_generic_si_manager():
    ids = ids_for({
        "job_name": "Responsable de la Sécurité des Systèmes d'Information(RSSI)",
        "specialties": [],
        "grade": "",
        "listing_title": "",
    })
    assert "it.cybersecurite" in ids
    assert "it.responsable_si" not in ids


def test_dba_keeps_database_admin_not_generic_system_admin():
    ids = ids_for({
        "job_name": "Administrateur des Systèmes de Gestion des Bases de Données (DBA)",
        "specialties": ["ingénieur d'Etat en génie Informatique"],
        "grade": "",
        "listing_title": "",
    })
    assert "it.base_donnees" in ids
    assert "it.administrateur_systemes" not in ids


def test_data_performance_analyst_title_dominates_data_science_domain():
    ids = ids_for({
        "job_name": "Data Performance Analyst - Rabat",
        "specialties": ["data science"],
        "grade": "",
        "listing_title": "",
    })
    assert "it.data_analyst" in ids
    assert "it.data_scientist" not in ids


def test_communication_project_keeps_specialized_role_not_generic_project():
    ids = ids_for({
        "job_name": "(Chargé de projet en communication (RH 75/2026",
        "specialties": [],
        "grade": "",
        "listing_title": "",
    })
    assert "sales.communication" in ids
    assert "management.charge_projet" not in ids


def test_civil_engineering_project_keeps_specialized_role_not_generic_project():
    ids = ids_for({
        "job_name": "Chargé(e) de Projet Génie Civil",
        "specialties": ["génie civil"],
        "grade": "",
        "listing_title": "",
    })
    assert "btp.chef_projet_genie_civil" in ids
    assert "management.charge_projet" not in ids


def test_public_multispecialty_competition_is_not_collapsed():
    ids = ids_for({
        "job_name": "",
        "grade": "Technicien de 4ème grade - echelle 8",
        "specialties": ["Génie Civil- Travaux", "Développement des Systèmes d'information"],
        "listing_title": "",
    })
    assert "btp.technicien_genie_civil" in ids
    assert "it.technicien_systemes_information" in ids


def test_explicit_automotive_alternatives_are_not_collapsed():
    ids = ids_for({
        "job_name": "Adjoint technique de 3ᵉ grade, spécialité mécanique automobile ou mécanique de maintenance ou électricité automobile",
        "specialties": [],
        "grade": "",
        "listing_title": "",
    })
    assert "auto.mecanicien" in ids
    assert "auto.electricien" in ids
    assert "industry.technicien_mecanique" in ids
