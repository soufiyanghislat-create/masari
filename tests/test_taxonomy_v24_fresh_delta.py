from taxonomy_engine import Taxonomy


def ids(job: dict) -> set[str]:
    return {m["profession_id"] for m in Taxonomy().classify_job(job)}


def test_fresh_actuaire_junior_maps_to_actuaire():
    result = ids({
        "job_name": "Actuaire Junior",
        "grade": "",
        "specialties": [],
        "listing_title": "",
    })
    assert "finance.actuaire" in result


def test_fresh_arabic_electrical_specialty_maps_public_technician():
    result = ids({
        "job_name": "",
        "grade": "Technicien de 3ème grade - echelle 9",
        "specialties": ["الهندسة الكهربائية"],
        "listing_title": "",
    })
    assert "industry.technicien_electrique" in result


def test_fresh_chef_projet_moe_maps_only_to_generic_project_role():
    result = ids({
        "job_name": "Chef de Projet MOE",
        "grade": "",
        "specialties": [],
        "listing_title": "",
    })
    assert "management.charge_projet" in result
    assert "btp.chef_projet_genie_civil" not in result
    assert "it.developpeur_logiciel" not in result


def test_fresh_technicien_gestion_maintenance_is_one_precise_role():
    result = ids({
        "job_name": "Technicien en gestion et maintenance",
        "grade": "",
        "specialties": [],
        "listing_title": "",
    })
    assert result == {"operations.technicien_gestion_maintenance"}


def test_generic_gestionnaire_still_classifies_after_alias_cleanup():
    result = ids({
        "job_name": "Gestionnaire",
        "grade": "",
        "specialties": [],
        "listing_title": "",
    })
    assert "admin.gestionnaire" in result


def test_precise_industrial_maintenance_still_classifies_after_alias_cleanup():
    result = ids({
        "job_name": "Technicien maintenance industrielle",
        "grade": "",
        "specialties": [],
        "listing_title": "",
    })
    assert "industry.maintenance_industrielle" in result


def test_mandat_de_gestion_stays_unclassified_without_domain_evidence():
    result = ids({
        "job_name": "Chargé de Pilotage du Mandat de Gestion",
        "grade": "",
        "specialties": [],
        "listing_title": "",
    })
    assert result == set()


def test_actuaire_autocomplete_is_market_first():
    rows = Taxonomy().autocomplete("actuaire", limit=10)
    assert rows
    assert rows[0]["profession_id"] == "finance.actuaire"
    assert rows[0]["source"] == "masari_market"


def test_chef_projet_moe_autocomplete_resolves_generic_project():
    rows = Taxonomy().autocomplete("chef de projet moe", limit=10)
    assert rows
    assert rows[0]["profession_id"] == "management.charge_projet"


def test_gestion_maintenance_autocomplete_resolves_precise_role():
    rows = Taxonomy().autocomplete("technicien en gestion et maintenance", limit=10)
    assert rows
    assert rows[0]["profession_id"] == "operations.technicien_gestion_maintenance"
