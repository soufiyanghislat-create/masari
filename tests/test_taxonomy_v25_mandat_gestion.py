from taxonomy_engine import Taxonomy


def ids(job: dict) -> set[str]:
    return {m["profession_id"] for m in Taxonomy().classify_job(job)}


def test_charge_pilotage_mandat_gestion_maps_exactly():
    result = ids({
        "job_name": "Chargé de Pilotage du Mandat de Gestion",
        "grade": "",
        "specialties": [],
        "listing_title": "",
    })
    assert result == {"finance.charge_pilotage_mandat_gestion"}


def test_charge_pilotage_mandat_does_not_become_portfolio_manager():
    result = ids({
        "job_name": "Chargé de Pilotage du Mandat de Gestion",
        "grade": "",
        "specialties": [],
        "listing_title": "",
    })
    assert "finance.gerant_portefeuille" not in result


def test_mandat_gestion_autocomplete_resolves_precise_role():
    rows = Taxonomy().autocomplete(
        "chargé de pilotage du mandat de gestion",
        limit=10,
    )
    assert rows
    assert (
        rows[0]["profession_id"]
        == "finance.charge_pilotage_mandat_gestion"
    )


def test_generic_mandat_de_gestion_is_not_forced_to_precise_role():
    result = ids({
        "job_name": "Mandat de gestion",
        "grade": "",
        "specialties": [],
        "listing_title": "",
    })
    assert "finance.charge_pilotage_mandat_gestion" not in result
