from taxonomy_engine import Taxonomy


def ids_for(job: dict) -> set[str]:
    return {row["profession_id"] for row in Taxonomy().classify_job(job)}


def test_v14_technicien_genie_civil_context_is_not_engineer():
    ids = ids_for({"job_name":"","grade":"Technicien de 3ème grade - echelle 9","specialties":["génie civil"]})
    assert "btp.technicien_genie_civil" in ids
    assert "btp.ingenieur_genie_civil" not in ids


def test_v14_ingenieur_genie_civil_context_is_not_technicien():
    ids = ids_for({"job_name":"","grade":"Ingénieur d'Etat 1er grade - echelle 11","specialties":["Génie civil"]})
    assert "btp.ingenieur_genie_civil" in ids
    assert "btp.technicien_genie_civil" not in ids


def test_v14_hydraulique_requires_engineer_grade():
    eng=ids_for({"job_name":"","grade":"Ingénieur d'Etat 1er grade","specialties":["Génie Hydraulique ou Génie Rural"]})
    tech=ids_for({"job_name":"","grade":"Technicien de 3ème grade","specialties":["Génie Hydraulique ou Génie Rural"]})
    assert "btp.ingenieur_hydraulique" in eng
    assert "btp.ingenieur_hydraulique" not in tech


def test_v14_multispecialty_technicien_safe_matches():
    ids=ids_for({"job_name":"","grade":"Technicien de 4ème grade - echelle 8","specialties":["Informatiques-Maintenance informatique-Réseaux","Urbanisme","Electricité"]})
    assert {"it.technicien_informatique","it.technicien_reseaux","it.technicien_support","btp.technicien_architecture_urbanisme","industry.technicien_electrique"}.issubset(ids)


def test_v14_generic_public_grades_stay_unclassified_without_specialty():
    t=Taxonomy()
    for grade in ["Technicien de 3ème grade - echelle 9","Technicien de 4ème grade - echelle 8","Ingénieur d'Etat 1er grade - echelle 11","Administrateur 2ème grade - echelle 11","Adjoint administratif 2ème grade"]:
        assert t.classify_job({"job_name":"","grade":grade,"specialties":[]}) == []


def test_v14_generic_market_titles_not_forced():
    t=Taxonomy()
    for title in ["Cadres et Ingénieurs","Cadres Expérimentés","Agents","Responsables et Cadres","32Cadres et 07 Agents de Maîtrise"]:
        assert t.classify_job({"job_name":title,"specialties":[],"grade":""}) == []


def test_v14_explicit_remaining_titles():
    cases=[("Superviseurs Clientèles","sales.superviseur_clientele"),("Chef de Projet Stratégie et Idéation","management.chef_projet_strategie"),("Chargés (es) de Projets Seniors","management.charge_projet"),("Technicien spécialisé en Architecture et Urbanisme","btp.technicien_architecture_urbanisme"),("Chargé(e) du suivi de la maintenance multi techniques","industry.maintenance_multitechnique"),("Chargé d’Exploitation de La gare routière","transport.responsable_exploitation_gare"),("Analyste Politique Monétaire","finance.analyste_politique_monetaire"),("Cadre en Commerce International","sales.commerce_international"),("Aide-soignant (H/F) - Bouskoura","health.aide_soignant"),("Chargé de Moyens Généraux","admin.moyens_generaux"),("Cadre Supérieur en Système d'Information ou équivalent","it.responsable_si"),("Chargé(e) de Projet Génie Civil","btp.chef_projet_genie_civil"),("CONTROLEUR TERRAIN","operations.controleur_terrain"),("Contrôleur Pratiques Commerciales Confirmé","sales.controleur_pratiques_commerciales"),("Chargé Relations avec les Bénéficiaires Confirmé","services.relations_beneficiaires"),("Cadre Technique - Pelouses et Surfaces Sportives (H/F)","sports.cadre_technique_pelouses")]
    for title,expected in cases:
        assert expected in ids_for({"job_name":title,"specialties":[],"grade":""}), title


def test_v14_arabic_lecturer():
    assert "edu.prof_universitaire" in ids_for({"job_name":"أستاذ محاضر بالمدرسة العليا للتربية والتكوين بأكادير تخصص اللغة العربية : اللسانيات","specialties":[],"grade":""})


def test_v14_formateur_gros_oeuvre():
    assert "edu.formateur_professionnel" in ids_for({"job_name":"(Formateur en Gros Œuvres (RH 72/2026","specialties":[],"grade":""})


def test_v14_agent_maitrise_finance_requires_context():
    assert "admin.agent_maitrise_gestion_finance" not in ids_for({"job_name":"Agent de maitrise","specialties":[],"grade":""})
    assert "admin.agent_maitrise_gestion_finance" in ids_for({"job_name":"Agent de maitrise","specialties":["Gestion d'entreprise, comptabilité, finance, économie"],"grade":""})
