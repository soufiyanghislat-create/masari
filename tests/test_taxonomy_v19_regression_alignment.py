from taxonomy_engine import Taxonomy


def ids_for(job: dict) -> set[str]:
    return {row["profession_id"] for row in Taxonomy().classify_job(job)}


def test_plain_charge_de_communication_maps_to_communication():
    ids = ids_for({
        "job_name": "Chargé de communication",
        "specialties": [],
        "grade": "",
        "listing_title": "",
    })
    assert ids == {"sales.communication"}


def test_plain_chargee_de_communication_maps_to_communication():
    ids = ids_for({
        "job_name": "Chargée de communication",
        "specialties": [],
        "grade": "",
        "listing_title": "",
    })
    assert ids == {"sales.communication"}


def test_chef_service_communication_remains_leadership_role():
    ids = ids_for({
        "job_name": "Chef de Service Communication Offres et Services",
        "specialties": ["Bac+5 en Marketing, Communication, Management, Commerce"],
        "grade": "",
        "listing_title": "",
    })
    assert ids == {"sales.responsable_communication"}


def test_assistante_direction_keeps_precise_canonical_role():
    ids = ids_for({
        "job_name": "assistante de Direction",
        "specialties": [],
        "grade": "",
        "listing_title": "Avis",
    })
    assert ids == {"admin.assistant_direction"}


def test_secretary_role_still_maps_to_secretary():
    ids = ids_for({
        "job_name": "Secrétaire",
        "specialties": [],
        "grade": "",
        "listing_title": "",
    })
    assert "admin.secretaire" in ids
    assert "admin.assistant_direction" not in ids
