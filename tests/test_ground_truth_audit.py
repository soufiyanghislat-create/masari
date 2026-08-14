from anapec_ground_truth_audit import compare_job

HTML = b'''<!doctype html><html><body>
<div>ALTRAN MAROC</div>
<div>R\xc3\xa9f\xc3\xa9rence de l\xe2\x80\x99offre:</div><div>BE1308261158866</div>
<div>Date :</div><div>13/08/2026</div>
<h2>(80) Concepteur CAO</h2>
<div>Description de l'entreprise</div><div>ALTRAN MAROC,</div>
<div>Grande entreprise, Leader en solution d'ing\xc3\xa9nierie et conseil industriel cherche des Concepteurs CAO</div>
<div>Secteur d\xe2\x80\x99activit\xc3\xa9 :</div><div>Services fournis principalement aux entreprises</div>
<div>Description de Poste</div>
<div>Type de contrat :</div><div>CI</div>
<div>Lieu de travail :</div><div>CASA-AIN CHOCK</div>
<form><input name="ref" type="hidden" value="BE1308261158866"></form>
</body></html>'''

JOB = {
    "source_offer_id": "1158866",
    "source_reference": "BE1308261158866",
    "publication_date": "2026-08-13",
    "title": "Concepteur CAO",
    "positions": 80,
    "location": "CASA-AIN CHOCK",
    "contract_type": "CI",
    "start_date": None,
    "salary": None,
    "company": "ALTRAN MAROC",
    "company_description": "Grande entreprise, Leader en solution d'ing\xc3\xa9nierie et conseil industriel cherche des Concepteurs CAO".encode().decode("utf-8"),
    "work_location_text": None,
    "source_url": "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1158866/resultat_recherche",
    "application": {"reference": "BE1308261158866"},
}


def test_independent_ground_truth_match():
    result = compare_job(JOB, HTML)
    assert result["match"] is True, result


def test_independent_ground_truth_detects_wrong_title():
    bad = dict(JOB)
    bad["title"] = "Wrong"
    result = compare_job(bad, HTML)
    assert result["match"] is False
    assert any(x["field"] == "title" for x in result["mismatches"])


def test_independent_ground_truth_detects_wrong_reference():
    bad = dict(JOB)
    bad["source_reference"] = "BE1308260000000"
    result = compare_job(bad, HTML)
    assert result["match"] is False
    assert any(x["field"] == "source_reference" for x in result["mismatches"])


def test_independent_ground_truth_accepts_dotted_single_letter_reference():
    html = b'''<html><body>
    <div>R\xc3\xa9f\xc3\xa9rence de l\xe2\x80\x99offre:</div><div>H.0308261153583</div>
    <div>Date :</div><div>03/08/2026</div>
    <div>(1) TECHNICIEN INSTALLATEUR MATERIEL DE LABORATOIRE</div>
    <div>Type de contrat :</div><div>CI</div>
    <div>Lieu de travail :</div><div>CASA HAY HASSANI</div>
    <form><input name="ref" value="H.0308261153583"></form>
    </body></html>'''
    job = dict(JOB)
    job.update({
        "source_offer_id": "1153583",
        "source_reference": "H.0308261153583",
        "publication_date": "2026-08-03",
        "title": "TECHNICIEN INSTALLATEUR MATERIEL DE LABORATOIRE",
        "positions": 1,
        "location": "CASA HAY HASSANI",
        "contract_type": "CI",
        "company": None,
        "company_description": None,
        "source_url": "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1153583/resultat_recherche",
        "application": {"reference": "H.0308261153583"},
    })
    result = compare_job(job, html)
    assert result["match"] is True, result


def test_independent_ground_truth_salary_bonus_is_semantically_equal():
    html = b'''<html><body>
    <div>R\xc3\xa9f\xc3\xa9rence de l\xe2\x80\x99offre:</div><div>TE0508261155177</div>
    <div>Date :</div><div>05/08/2026</div>
    <div>(100) Op\xc3\xa9rateurs De Production</div>
    <div>Type de contrat :</div><div>CDD</div>
    <div>Lieu de travail :</div><div>TANGER-FAHS-ANJRA</div>
    <div>Salaire mensuel :</div><div>3700dh+primes</div>
    <form><input name="ref" value="TE0508261155177"></form>
    </body></html>'''
    job = dict(JOB)
    job.update({
        "source_offer_id": "1155177",
        "source_reference": "TE0508261155177",
        "publication_date": "2026-08-05",
        "title": "Opérateurs De Production",
        "positions": 100,
        "location": "TANGER-FAHS-ANJRA",
        "contract_type": "CDD",
        "salary": "3700 DH+primes",
        "company": None,
        "company_description": None,
        "source_url": "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1155177/resultat_recherche",
        "application": {"reference": "TE0508261155177"},
    })
    result = compare_job(job, html)
    assert result["match"] is True, result
