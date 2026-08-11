from taxonomy_engine import Taxonomy


def ids_for(job: dict) -> set[str]:
    return {row["profession_id"] for row in Taxonomy().classify_job(job)}


def test_formateur_developpement_informatique_stays_trainer():
    ids = ids_for({
        "job_name": "(Formateur en Développement Informatique (Bac+2) (RH 74/2026",
        "specialties": [],
        "grade": "",
        "listing_title": "",
    })
    assert ids == {"edu.formateur_professionnel"}


def test_formateur_genie_electrique_stays_trainer():
    ids = ids_for({
        "job_name": "(Formateur en génie électrique (Bac+5) (RH 60/2026",
        "specialties": [],
        "grade": "",
        "listing_title": "",
    })
    assert ids == {"edu.formateur_professionnel"}


def test_formateur_qhse_stays_trainer():
    ids = ids_for({
        "job_name": "(Formateur en Qualité, Hygiène, Sécurité et Environnement (RH 62/2026",
        "specialties": [],
        "grade": "",
        "listing_title": "",
    })
    assert ids == {"edu.formateur_professionnel"}


def test_singular_maitre_de_conference_stays_academic():
    ids = ids_for({
        "job_name": "Maître de conférence à la ENSIASD Spécialité Informatique et sécurité informatique",
        "specialties": [],
        "grade": "",
        "listing_title": "",
    })
    assert ids == {"edu.prof_universitaire"}


def test_responsable_hse_is_not_technicien_hse():
    ids = ids_for({
        "job_name": "Responsable HSE",
        "specialties": [],
        "grade": "",
        "listing_title": "",
    })
    assert ids == {"industry.responsable_hse"}


def test_chef_service_communication_keeps_leadership_level():
    ids = ids_for({
        "job_name": "Chef de Service Communication Offres et Services",
        "specialties": ["Bac+5 en Marketing, Communication, Management, Commerce"],
        "grade": "",
        "listing_title": "",
    })
    assert ids == {"sales.responsable_communication"}


def test_charge_publicite_is_not_generic_marketing():
    ids = ids_for({
        "job_name": "(Chargé de Publicité (RH 78/2026",
        "specialties": [],
        "grade": "",
        "listing_title": "",
    })
    assert ids == {"sales.publicite"}


def test_assistante_direction_is_not_generic_secretary():
    ids = ids_for({
        "job_name": "ASSISTANTE DE DIRECTION",
        "specialties": [],
        "grade": "",
        "listing_title": "",
    })
    assert ids == {"admin.assistant_direction"}


def test_regular_charge_communication_remains_communication():
    ids = ids_for({
        "job_name": "Chargé de communication",
        "specialties": [],
        "grade": "",
        "listing_title": "",
    })
    assert "sales.communication" in ids
    assert "sales.responsable_communication" not in ids


def test_regular_responsable_si_is_not_hijacked_by_hse_rule():
    ids = ids_for({
        "job_name": "Responsable des Systèmes d'Information",
        "specialties": [],
        "grade": "",
        "listing_title": "",
    })
    assert "it.responsable_si" in ids
    assert "industry.responsable_hse" not in ids
