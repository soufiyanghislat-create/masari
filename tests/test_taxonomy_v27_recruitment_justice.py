from taxonomy_engine import Taxonomy


def ids(job):
    return {
        m["profession_id"]
        for m in Taxonomy().classify_job(job)
    }


def test_gestionnaire_recrutement_maps_only_to_existing_hr_profession():
    result = ids({
        "job_name": "Gestionnaire Recrutement",
        "grade": "",
        "specialties": [],
        "listing_title": "",
    })
    assert result == {"admin.rh"}


def test_gestionnaire_de_recrutement_variant_maps_only_to_hr():
    result = ids({
        "job_name": "Gestionnaire de recrutement",
        "grade": "",
        "specialties": [],
        "listing_title": "",
    })
    assert result == {"admin.rh"}


def test_gestionnaire_recrutement_autocomplete_is_market_exact():
    rows = Taxonomy().autocomplete("gestionnaire recrutement", limit=10)
    assert rows
    assert rows[0]["profession_id"] == "admin.rh"
    assert rows[0]["source"] == "masari_market"
    assert rows[0]["score"] == 1000


def test_generic_gestionnaire_does_not_gain_hr_from_new_alias():
    result = ids({
        "job_name": "Gestionnaire",
        "grade": "",
        "specialties": [],
        "listing_title": "",
    })
    assert "admin.rh" not in result


def test_gestionnaire_de_paie_stays_payroll_not_hr_recruitment():
    result = ids({
        "job_name": "Gestionnaire de paie",
        "grade": "",
        "specialties": [],
        "listing_title": "",
    })
    assert "admin.paie" in result
    assert "admin.rh" not in result


def test_commissaire_judiciaire_public_grade_maps_only_to_new_canonical():
    result = ids({
        "job_name": "",
        "grade": "Commissaire Judiciaire 3ème grade - echelle 10",
        "specialties": ["Etudes portugaises ou traduction (portugais)"],
        "listing_title": (
            "Avis de concours de recrutement de Commissaire Judiciaire "
            "3ème grade - Echelle 10 Ministère de la justice "
            "Annonce 12 postes"
        ),
    })
    assert result == {"legal.commissaire_judiciaire"}


def test_commissaire_judiciaire_autocomplete_is_exact():
    rows = Taxonomy().autocomplete("commissaire judiciaire", limit=10)
    assert rows
    assert rows[0]["profession_id"] == "legal.commissaire_judiciaire"
    assert rows[0]["source"] == "masari_market"
    assert rows[0]["score"] == 1000


def test_generic_commissaire_does_not_force_judicial_profession():
    result = ids({
        "job_name": "Commissaire",
        "grade": "",
        "specialties": [],
        "listing_title": "",
    })
    assert "legal.commissaire_judiciaire" not in result


def test_greffier_stays_distinct_from_commissaire_judiciaire():
    result = ids({
        "job_name": "Greffier",
        "grade": "",
        "specialties": [],
        "listing_title": "",
    })
    assert "legal.greffier" in result
    assert "legal.commissaire_judiciaire" not in result
