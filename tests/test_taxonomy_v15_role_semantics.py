from taxonomy_engine import Taxonomy


def ids_for(job: dict) -> set[str]:
    return {row["profession_id"] for row in Taxonomy().classify_job(job)}


def test_academic_role_blocks_food_industry_institution_false_positive():
    ids = ids_for({
        "job_name": "Maitre de conférences au profit de l'Ecole Nationale Supérieure de l'Industrie Alimentaire et des Biotechnologies Berkane",
        "specialties": ["Toxicologie"], "grade": "", "listing_title": "",
    })
    assert ids == {"edu.prof_universitaire"}


def test_academic_role_keeps_cybersecurity_as_domain_not_second_job():
    ids = ids_for({
        "job_name": "Maitre de conférences au profit de la Faculté des Sciences et Techniques Taourirt",
        "specialties": ["Cybersécurité"], "grade": "", "listing_title": "",
    })
    assert ids == {"edu.prof_universitaire"}


def test_academic_grade_keeps_ai_as_domain_not_data_scientist_job():
    ids = ids_for({
        "job_name": "", "specialties": ["Intelligence Artificielle"],
        "grade": "Maître de conférences grade A - echelle 11",
        "listing_title": "Avis de concours de recrutement de Maître de conférences grade A - Echelle 11 Université Cadi Ayyad Annonce 1 poste",
    })
    assert ids == {"edu.prof_universitaire"}


def test_academic_grade_keeps_marketing_as_domain_not_marketing_job():
    ids = ids_for({
        "job_name": "", "specialties": ["Marketing"],
        "grade": "Maître de conférences grade A - echelle 11",
        "listing_title": "Avis de concours de recrutement de Maître de conférences grade A - Echelle 11 Université Moulay Ismaïl - Meknès Annonce 1 poste",
    })
    assert ids == {"edu.prof_universitaire"}


def test_hydraulic_agency_name_does_not_make_generic_engineer_hydraulic():
    ids = ids_for({
        "job_name": "", "specialties": [],
        "grade": "Ingénieur d'Etat 1er grade - echelle 11",
        "listing_title": "Avis de concours de recrutement de Ingénieur d'Etat 1er grade - Echelle 11 Agence du Bassin Hydraulique du Draa Oued Noun Annonce Dépôt en ligne 1 poste",
    })
    assert "btp.ingenieur_hydraulique" not in ids


def test_agriculture_ministry_name_does_not_create_agriculture_professions():
    ids = ids_for({
        "job_name": "", "specialties": ["Développement informatique"],
        "grade": "Technicien de 3ème grade - echelle 9",
        "listing_title": "Avis de concours de recrutement de Technicien de 3ème grade - Echelle 9 Ministère de l’Agriculture, de la Pêche maritime, du développement rural et des eaux et forêts - Département de l’Agriculture Annonce 1 poste",
    })
    assert "agri.technicien_agricole" not in ids
    assert "agri.eaux_forets" not in ids


def test_listing_role_is_trimmed_at_echelle():
    t = Taxonomy()
    role = t._extract_listing_role(
        "Avis de concours de recrutement de Ingénieur d'Etat 1er grade - Echelle 11 Agence du Bassin Hydraulique du Sebou Annonce 1 poste"
    )
    assert "Agence" not in role
    assert "Hydraulique" not in role
    assert "Echelle 11" in role
