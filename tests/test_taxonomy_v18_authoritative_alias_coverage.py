from taxonomy_engine import Taxonomy


def ids_for(job: dict) -> set[str]:
    return {row["profession_id"] for row in Taxonomy().classify_job(job)}


def test_real_formateur_developpement_informatique_bac2():
    ids = ids_for({
        "job_name": "(Formateur en Développement Informatique (Bac+2) (RH 74/2026",
        "grade": "",
        "specialties": [],
        "listing_title": "",
    })
    assert ids == {"edu.formateur_professionnel"}


def test_real_formateur_developpement_informatique_regions():
    ids = ids_for({
        "job_name": "(Formateur en Développement Informatique- Boujdour - Dakhla - Guelmim - Laâyoune - Tantan (RH 35/2026",
        "grade": "",
        "specialties": [],
        "listing_title": "",
    })
    assert ids == {"edu.formateur_professionnel"}


def test_real_formateur_genie_electrique_bac2():
    ids = ids_for({
        "job_name": "(Formateur en génie électrique (Bac+2) (RH 61/2026",
        "grade": "",
        "specialties": [],
        "listing_title": "",
    })
    assert ids == {"edu.formateur_professionnel"}


def test_real_formateur_genie_electrique_bac5():
    ids = ids_for({
        "job_name": "(Formateur en génie électrique (Bac+5) (RH 60/2026",
        "grade": "",
        "specialties": [],
        "listing_title": "",
    })
    assert ids == {"edu.formateur_professionnel"}


def test_real_formateur_genie_electrique_regions():
    ids = ids_for({
        "job_name": "(Formateur en génie électrique Dakhla – Es-Semara – Laâyoune – Tarfaya (RH 52/2026",
        "grade": "",
        "specialties": [],
        "listing_title": "",
    })
    assert ids == {"edu.formateur_professionnel"}


def test_real_formateur_qhse():
    ids = ids_for({
        "job_name": "(Formateur en Qualité, Hygiène, Sécurité et Environnement (RH 62/2026",
        "grade": "",
        "specialties": [],
        "listing_title": "",
    })
    assert ids == {"edu.formateur_professionnel"}


def test_real_formateur_qhse_guelmim():
    ids = ids_for({
        "job_name": "(Formateur en Qualité, Hygiène, Sécurité et Environnement - Guelmim (RH 40/2026",
        "grade": "",
        "specialties": [],
        "listing_title": "",
    })
    assert ids == {"edu.formateur_professionnel"}


def test_real_singular_maitre_de_conference_ensiasd():
    ids = ids_for({
        "job_name": "Maître de conférence à la ENSIASD Spécialité Informatique et sécurité informatique",
        "grade": "",
        "specialties": [],
        "listing_title": "",
    })
    assert ids == {"edu.prof_universitaire"}
