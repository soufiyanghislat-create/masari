from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from sources.public.anapec.application import build_application
from sources.public.anapec.audit import is_visible_anapec_job
from sources.public.anapec import crawler
from sources.public.anapec.parser import parse_detail, parse_listing, parse_pagination_links


@pytest.fixture(autouse=True)
def _unit_test_tls_context(monkeypatch):
    """Unit tests avoid real network/native truststore while preserving strict TLS semantics."""
    import ssl
    monkeypatch.setattr(crawler, "create_native_ssl_context", lambda: ssl.create_default_context())

DETAIL_HTML = """
<html><body>
<div>Référence de l’offre: BE1308261158866</div>
<div>Date : 13/08/2026</div>
<div>Agence : BEN MSIK / IKHOUANE</div>
<h3>(80) Concepteur CAO</h3>
<div>Description de l'entreprise</div>
<div>ALTRAN MAROC,</div>
<div>Secteur d’activité : Services fournis principalement aux entreprises</div>
<div>Type de contrat : CI</div>
<div>Lieu de travail : CASA-AIN CHOCK</div>
<div>Formation : Ingénieur</div>
<form action="https://www.anapec.org/sigec-app-rv/fr/chercheurs/postulation" method="GET">
<input type="hidden" name="ref" value="BE1308261158866">
</form>
</body></html>
"""


def detail_html(offer_id: str, ref: str, date_fr: str, title: str = "Technicien") -> str:
    return f"""<html><body>
    <div>Référence de l’offre: {ref}</div>
    <div>Date : {date_fr}</div>
    <div>Agence : TEST / AGENCY</div>
    <h3>(1) {title}</h3>
    <div>Type de contrat : CI</div>
    <div>Lieu de travail : RABAT</div>
    <form action="https://www.anapec.org/sigec-app-rv/fr/chercheurs/postulation" method="GET">
      <input type="hidden" name="ref" value="{ref}">
    </form>
    </body></html>"""


def listing_html(page: int, offer_id: str, next_page: int | None) -> str:
    next_link = (
        f'<a href="/sigec-app-rv/chercheurs/resultat_recherche/page:{next_page}/tout:all/language:fr">next</a>'
        if next_page else ""
    )
    return f"""<html><body>
    <a href="/sigec-app-rv/fr/entreprises/bloc_offre_home/{offer_id}/resultat_recherche">offer</a>
    {next_link}
    </body></html>"""


def test_parse_listing_extracts_only_canonical_offer_links():
    html = """
    <a href="/sigec-app-rv/fr/entreprises/bloc_offre_home/1158866/resultat_recherche">A</a>
    <a href="/sigec-app-rv/fr/entreprises/bloc_offre_home/1158788/resultat_recherche">B</a>
    <a href="/sigec-app-rv/chercheurs/resultat_recherche/page:2/tout:all/language:fr">2</a>
    <a href="/news/1234567">not an offer</a>
    """
    offers = parse_listing(html, "https://www.anapec.org/sigec-app-rv/fr/chercheurs/resultat_recherche/tout:all")
    assert [o.source_offer_id for o in offers] == ["1158866", "1158788"]


def test_parse_pagination_links_uses_source_links():
    html = """
    <a href="/sigec-app-rv/chercheurs/resultat_recherche/page:2/tout:all/language:fr">2</a>
    <a href="/sigec-app-rv/chercheurs/resultat_recherche/page:9/tout:all/language:fr">9</a>
    """
    links = parse_pagination_links(html, "https://www.anapec.org/sigec-app-rv/fr/chercheurs/resultat_recherche/tout:all")
    assert [x.page for x in links] == [2, 9]


def test_parse_detail_required_and_optional_fields():
    job = parse_detail(DETAIL_HTML, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1158866/resultat_recherche", "1158866")
    assert job["global_id"] == "anapec:1158866"
    assert job["source_reference"] == "BE1308261158866"
    assert job["title"] == "Concepteur CAO"
    assert job["source_title"] == "(80) Concepteur CAO"
    assert job["positions"] == 80
    assert job["company"] == "ALTRAN MAROC"
    assert job["publication_date"] == "2026-08-13"
    assert job["location"] == "CASA-AIN CHOCK"
    assert job["deadline"] is None


def test_visibility_is_15_days_without_deadline():
    now = datetime(2026, 8, 14, 12, tzinfo=ZoneInfo("Africa/Casablanca"))
    assert is_visible_anapec_job({"publication_date": "2026-08-13", "deadline": None}, now)
    assert is_visible_anapec_job({"publication_date": "2026-07-30", "deadline": None}, now)
    assert not is_visible_anapec_job({"publication_date": "2026-07-29", "deadline": None}, now)
    assert not is_visible_anapec_job({"publication_date": "2026-08-15", "deadline": None}, now)


def test_application_is_official_anapec_only():
    app = build_application("BE1308261158866")
    assert app["method"] == "GET"
    assert app["official"] is True
    assert app["reference"] == "BE1308261158866"
    assert "anapec.org" in app["url"]


def test_crawl_stops_at_verified_freshness_frontier(monkeypatch):
    pages = {
        crawler.FIRST_PAGE: listing_html(1, "1159001", 2),
        "https://www.anapec.org/sigec-app-rv/chercheurs/resultat_recherche/page:2/tout:all/language:fr": listing_html(2, "1159002", 3),
        "https://www.anapec.org/sigec-app-rv/chercheurs/resultat_recherche/page:3/tout:all/language:fr": listing_html(3, "1159003", 4),
        "https://www.anapec.org/sigec-app-rv/chercheurs/resultat_recherche/page:4/tout:all/language:fr": listing_html(4, "1159004", 5),
        "https://www.anapec.org/sigec-app-rv/chercheurs/resultat_recherche/page:5/tout:all/language:fr": listing_html(5, "1159005", 6),
    }
    details = {
        "1159001": detail_html("1159001", "AA1308261159001", "13/08/2026"),
        "1159002": detail_html("1159002", "AA0108261159002", "01/08/2026"),
        "1159003": detail_html("1159003", "AA2907261159003", "29/07/2026"),
        "1159004": detail_html("1159004", "AA2807261159004", "28/07/2026"),
        "1159005": detail_html("1159005", "AA2707261159005", "27/07/2026"),
    }

    def fake_get(_session, url, timeout=25, attempts=3):
        if url in pages:
            return pages[url]
        for offer_id, html in details.items():
            if f"/{offer_id}/" in url:
                return html
        raise AssertionError(url)

    monkeypatch.setattr(crawler, "_get", fake_get)
    result = crawler.crawl(
        max_pages=20,
        workers=1,
        now=datetime(2026, 8, 14, 12, tzinfo=ZoneInfo("Africa/Casablanca")),
    )
    assert result.termination_reason == "freshness_frontier"
    assert result.pages_fetched == 5
    assert result.date_order_ok is True
    assert result.freshness_frontier_confirmed is True


def test_crawl_stops_when_source_has_no_next_page(monkeypatch):
    first = listing_html(1, "1159001", None)
    detail = detail_html("1159001", "AA1308261159001", "13/08/2026")

    def fake_get(_session, url, timeout=25, attempts=3):
        return detail if "/1159001/" in url else first

    monkeypatch.setattr(crawler, "_get", fake_get)
    result = crawler.crawl(max_pages=20, workers=1, now=datetime(2026, 8, 14, 12, tzinfo=ZoneInfo("Africa/Casablanca")))
    assert result.termination_reason == "no_next_page"
    assert result.freshness_frontier_confirmed is True


def test_crawl_rejects_date_order_violation_before_frontier(monkeypatch):
    pages = {
        crawler.FIRST_PAGE: listing_html(1, "1159001", 2),
        "https://www.anapec.org/sigec-app-rv/chercheurs/resultat_recherche/page:2/tout:all/language:fr": listing_html(2, "1159002", 3),
        "https://www.anapec.org/sigec-app-rv/chercheurs/resultat_recherche/page:3/tout:all/language:fr": listing_html(3, "1159003", 4),
        "https://www.anapec.org/sigec-app-rv/chercheurs/resultat_recherche/page:4/tout:all/language:fr": listing_html(4, "1159004", 5),
    }
    details = {
        "1159001": detail_html("1159001", "AA1308261159001", "13/08/2026"),
        "1159002": detail_html("1159002", "AA2907261159002", "29/07/2026"),
        "1159003": detail_html("1159003", "AA2807261159003", "28/07/2026"),
        # Newer date after stale pages -> ordering violation.
        "1159004": detail_html("1159004", "AA0508261159004", "05/08/2026"),
    }

    def fake_get(_session, url, timeout=25, attempts=3):
        if url in pages:
            return pages[url]
        for offer_id, html in details.items():
            if f"/{offer_id}/" in url:
                return html
        raise AssertionError(url)

    monkeypatch.setattr(crawler, "_get", fake_get)
    with pytest.raises(crawler.CrawlError, match="not monotonic"):
        crawler.crawl(max_pages=10, workers=1, now=datetime(2026, 8, 14, 12, tzinfo=ZoneInfo("Africa/Casablanca")))


def test_title_parser_prefers_full_title_over_count_only():
    html = '''
      <h2>(8)</h2>
      <div>(8) Téléconseiller</div>
      <div>Date : 13/08/2026</div>
      <div>Lieu : FES</div>
      <form action="/postulation"><input name="ref" value="FE1308261158926"></form>
    '''
    job = parse_detail(html, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1158926/resultat_recherche", "1158926")
    assert job["title"] == "Téléconseiller"
    assert job["positions"] == 8


def test_missing_explicit_publication_date_is_rejected():
    from sources.public.anapec.parser import ParseError

    html = '''
      <div>(1) Technicien Topographe</div>
      <div>Lieu : AL HOCEIMA</div>
      <form action="/postulation"><input name="ref" value="AL1308261158927"></form>
    '''
    with pytest.raises(ParseError, match="publication_date"):
        parse_detail(html, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1158927/resultat_recherche", "1158927")


def test_anapec_package_does_not_preimport_audit():
    import importlib
    import sys
    import sources.public.anapec as pkg

    sys.modules.pop("sources.public.anapec.audit", None)
    importlib.reload(pkg)
    assert "sources.public.anapec.audit" not in sys.modules


def test_tls_helper_never_disables_certificate_verification():
    from pathlib import Path
    from sources.public.anapec import tls

    source = Path(tls.__file__).read_text(encoding="utf-8")
    assert "verify=False" not in source
    assert "ssl.CERT_REQUIRED" in source
    assert "truststore.SSLContext" in source
    assert "inject_into_ssl" not in source


def test_audit_requires_explicit_native_tls_and_rejects_insecure_warning():
    from pathlib import Path

    source = Path("sources/public/anapec/audit.py").read_text(encoding="utf-8")
    assert "native_tls_available()" in source
    assert "warnings.filterwarnings(\"error\", category=InsecureRequestWarning)" in source
    assert "explicit_truststore_sslcontext_cert_required" in source


def test_native_tls_context_is_strict(monkeypatch):
    import ssl
    import sys
    import types
    from sources.public.anapec import tls

    fake = types.SimpleNamespace(SSLContext=lambda _protocol: ssl.create_default_context())
    monkeypatch.setitem(sys.modules, "truststore", fake)
    ctx = tls.create_native_ssl_context()
    assert ctx.check_hostname is True
    assert ctx.verify_mode == ssl.CERT_REQUIRED


def test_requests_session_uses_native_tls_adapter_and_verify_true(monkeypatch):
    import ssl
    from sources.public.anapec import crawler

    ctx = ssl.create_default_context()
    monkeypatch.setattr(crawler, "create_native_ssl_context", lambda: ctx)
    session = crawler._session()
    assert session.verify is True
    adapter = session.get_adapter("https://www.anapec.org/")
    assert isinstance(adapter, crawler.NativeTLSAdapter)
    assert adapter._masari_ssl_context is ctx
    assert adapter._masari_ssl_context.check_hostname is True
    assert adapter._masari_ssl_context.verify_mode == ssl.CERT_REQUIRED


def test_native_tls_adapter_refuses_verify_false():
    import ssl
    import requests
    from sources.public.anapec.crawler import CrawlError, NativeTLSAdapter

    adapter = NativeTLSAdapter(ssl_context=ssl.create_default_context())
    prepared = requests.Request("GET", "https://www.anapec.org/").prepare()
    with pytest.raises(CrawlError, match="cannot be disabled"):
        adapter.build_connection_pool_key_attributes(prepared, False, None)


def test_parser_accepts_utf8_bytes_without_mojibake():
    html = DETAIL_HTML.replace("Concepteur CAO", "Téléconseiller").replace("CI", "CDD").encode("utf-8")
    job = parse_detail(html, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1158866/resultat_recherche", "1158866")
    assert job["title"] == "Téléconseiller"
    assert "Ã" not in job["title"]


def test_company_is_optional_when_anapec_does_not_disclose_it():
    html = detail_html("1158927", "AL1308261158927", "13/08/2026", "Technicien Topographe")
    job = parse_detail(html, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1158927/resultat_recherche", "1158927")
    assert job["company"] is None


def test_job_quality_gate_detects_mojibake_and_accepts_clean_job():
    from sources.public.anapec.quality_audit import audit_jobs
    now = datetime(2026, 8, 14, 12, tzinfo=ZoneInfo("Africa/Casablanca"))
    clean = parse_detail(DETAIL_HTML.encode("utf-8"), "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1158866/resultat_recherche", "1158866")
    clean["application"] = build_application(clean["source_reference"])
    report = audit_jobs([clean], now=now)
    assert report["gate"] == "PASS"
    bad = dict(clean)
    bad["title"] = "TÃ©lÃ©conseiller"
    report = audit_jobs([bad], now=now)
    assert report["gate"] == "FAIL"
    assert report["problem_counts"]["mojibake_detected"] == 1


def test_company_label_is_never_emitted_as_company():
    html = '''<html><body>
      <div>Référence de l’offre:</div><div>AG1308261158957</div>
      <div>Date :</div><div>13/08/2026</div>
      <div>Agence :</div><div>AGADIR / SNOUSSI</div>
      <div>(2) PATISSIER</div><div>sur AGADIR</div>
      <div>Description de l'entreprise</div>
      <div>Secteur d’activité :</div><div>Autres</div>
      <div>Type de contrat :</div><div>CDD</div>
      <div>Lieu de travail :</div><div>AGADIR</div>
      <form action="/postulation"><input name="ref" value="AG1308261158957"></form>
    </body></html>'''
    job = parse_detail(html, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1158957/resultat_recherche", "1158957")
    assert job["company"] is None
    assert job["company_description"] is None


def test_company_description_is_not_misrepresented_as_company_name():
    html = '''<html><body>
      <div>Référence de l’offre:</div><div>EL1308261158788</div>
      <div>Date :</div><div>13/08/2026</div>
      <div>(10) Vendeurs / Vendeuses / Livreurs (H/F)</div>
      <div>Description de l'entreprise</div>
      <div>Société de distribution des produits d'hygiène, beauté et cosmétique à ELJADIDA Cherhce 10 commerciaux et livreurs (H/F)</div>
      <div>Secteur d’activité :</div><div>Commerce</div>
      <div>Type de contrat :</div><div>CI</div>
      <div>Lieu de travail :</div><div>EL JADIDA</div>
      <form action="/postulation"><input name="ref" value="EL1308261158788"></form>
    </body></html>'''
    job = parse_detail(html, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1158788/resultat_recherche", "1158788")
    assert job["company"] is None
    assert "Société de distribution" in job["company_description"]


def test_disclosed_company_name_remains_strict_name_only():
    job = parse_detail(DETAIL_HTML, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1158866/resultat_recherche", "1158866")
    assert job["company"] == "ALTRAN MAROC"


def test_quality_gate_rejects_section_label_or_recruitment_prose_as_company():
    from sources.public.anapec.quality_audit import audit_jobs
    now = datetime(2026, 8, 14, 12, tzinfo=ZoneInfo("Africa/Casablanca"))
    clean = parse_detail(DETAIL_HTML, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1158866/resultat_recherche", "1158866")
    clean["application"] = build_application(clean["source_reference"])
    for bad_company in ("Secteur d’activité :", "Société X cherche 10 opérateurs"):
        bad = dict(clean)
        bad["company"] = bad_company
        report = audit_jobs([bad], now=now)
        assert report["gate"] == "FAIL"
        assert report["problem_counts"]["invalid_company_semantics"] == 1


def test_generic_pharma_descriptor_is_not_employer_name():
    html = '''<html><body>
      <div>Référence de l’offre:</div><div>EL1308261158852</div>
      <div>Date :</div><div>13/08/2026</div>
      <div>(5) Opérateur De Production (H)</div>
      <div>Description de l'entreprise</div>
      <div>Société opérant dans l'industrie pharmaceutique</div>
      <div>Société opérant dans l'industrie pharmaceutique cherche 5 Opérateurs de production (H)</div>
      <div>Secteur d’activité :</div><div>Industrie pharmaceutique</div>
      <div>Type de contrat :</div><div>CDD</div>
      <div>Lieu de travail :</div><div>EL JADIDA</div>
      <form action="/postulation"><input name="ref" value="EL1308261158852"></form>
    </body></html>'''
    job = parse_detail(html, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1158852/resultat_recherche", "1158852")
    assert job["company"] is None
    assert job["company_description"] == "Société opérant dans l'industrie pharmaceutique cherche 5 Opérateurs de production (H)"


def test_salary_mensuel_is_extracted_without_fabrication():
    html = '''<html><body>
      <div>Référence de l’offre:</div><div>FE1308261158926</div>
      <div>Date :</div><div>13/08/2026</div>
      <div>(8) Téléconseiller</div>
      <div>Type de contrat :</div><div>CI</div>
      <div>Lieu de travail :</div><div>FES</div>
      <div>Salaire mensuel :</div><div>2000 DHS</div>
      <form action="/postulation"><input name="ref" value="FE1308261158926"></form>
    </body></html>'''
    job = parse_detail(html, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1158926/resultat_recherche", "1158926")
    assert job["salary"] == "2000 DHS"


def test_curly_apostrophe_sector_label_is_extracted():
    html = '''<html><body>
      <div>Référence de l’offre:</div><div>AG1308261158957</div>
      <div>Date :</div><div>13/08/2026</div>
      <div>(2) PATISSIER</div>
      <div>Secteur d’activité :</div><div>Autres</div>
      <div>Type de contrat :</div><div>CDD</div>
      <div>Lieu de travail :</div><div>AGADIR</div>
      <form action="/postulation"><input name="ref" value="AG1308261158957"></form>
    </body></html>'''
    job = parse_detail(html, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1158957/resultat_recherche", "1158957")
    assert job["sector"] == "Autres"


def test_multiple_contract_is_structured_and_matches_positions():
    html = '''<html><body>
      <div>Référence de l’offre:</div><div>BE1308261158507</div>
      <div>Date :</div><div>13/08/2026</div>
      <div>(25) Employé Libre Service</div>
      <div>Type de contrat :</div><div>Choix Multiple: (5) CDI, (20) CI,</div>
      <div>Lieu de travail :</div><div>BERKANE</div>
      <form action="/postulation"><input name="ref" value="BE1308261158507"></form>
    </body></html>'''
    job = parse_detail(html, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1158507/resultat_recherche", "1158507")
    assert job["contract_type"] == "MULTIPLE"
    assert job["source_contract_text"] == "Choix Multiple: (5) CDI, (20) CI,"
    assert job["contract_options"] == [
        {"type": "CDI", "positions": 5},
        {"type": "CI", "positions": 20},
    ]
    job["application"] = build_application(job["source_reference"])
    from sources.public.anapec.quality_audit import audit_jobs
    report = audit_jobs([job], now=datetime(2026, 8, 14, 12, tzinfo=ZoneInfo("Africa/Casablanca")))
    assert report["gate"] == "PASS"


def test_quality_gate_rejects_multiple_contract_position_mismatch():
    html = '''<html><body>
      <div>Référence de l’offre:</div><div>BE1308261158585</div>
      <div>Date :</div><div>13/08/2026</div>
      <div>(2) Cariste</div>
      <div>Type de contrat :</div><div>Choix Multiple: (1) CDI, (1) CI,</div>
      <div>Lieu de travail :</div><div>BERKANE</div>
      <form action="/postulation"><input name="ref" value="BE1308261158585"></form>
    </body></html>'''
    job = parse_detail(html, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1158585/resultat_recherche", "1158585")
    job["contract_options"][0]["positions"] = 9
    job["application"] = build_application(job["source_reference"])
    from sources.public.anapec.quality_audit import audit_jobs
    report = audit_jobs([job], now=datetime(2026, 8, 14, 12, tzinfo=ZoneInfo("Africa/Casablanca")))
    assert report["gate"] == "FAIL"
    assert report["problem_counts"]["contract_positions_mismatch"] == 1


def test_quality_gate_rejects_generic_company_descriptor():
    from sources.public.anapec.quality_audit import audit_jobs
    clean = parse_detail(DETAIL_HTML, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1158866/resultat_recherche", "1158866")
    clean["company"] = "Société opérant dans l'industrie pharmaceutique"
    clean["application"] = build_application(clean["source_reference"])
    report = audit_jobs([clean], now=datetime(2026, 8, 14, 12, tzinfo=ZoneInfo("Africa/Casablanca")))
    assert report["gate"] == "FAIL"
    assert report["problem_counts"]["invalid_company_semantics"] == 1


def test_company_equal_to_job_title_is_not_emitted_as_company():
    html = '''<html><body>
      <div>Employé Administratif D'assurances</div>
      <div>Référence de l’offre:</div><div>BE0608261155489</div>
      <div>Date :</div><div>06/08/2026</div>
      <div>(2) Employé Administratif D'assurances</div>
      <div>Type de contrat :</div><div>CI</div>
      <div>Lieu de travail :</div><div>CASA-AIN CHOCK</div>
      <div>Salaire mensuel :</div><div>2500 DHS</div>
      <form action="/postulation"><input name="ref" value="BE0608261155489"></form>
    </body></html>'''
    job = parse_detail(html, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1155489/resultat_recherche", "1155489")
    assert job["company"] is None
    assert job["employer_source_label"] == "Employé Administratif D'assurances"


def test_poste_prefix_is_never_company_name():
    html = '''<html><body>
      <div>Poste : VENDEUR DANS UNE AGENCE DE TELECOMMUNICATION</div>
      <div>Référence de l’offre:</div><div>AG0308261153765</div>
      <div>Date :</div><div>03/08/2026</div>
      <div>(1) VENDEUR DANS UNE AGENCE DE TELECOMMUNICATION</div>
      <div>Type de contrat :</div><div>CI</div>
      <div>Lieu de travail :</div><div>AGADIR</div>
      <form action="/postulation"><input name="ref" value="AG0308261153765"></form>
    </body></html>'''
    job = parse_detail(html, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1153765/resultat_recherche", "1153765")
    assert job["company"] is None
    assert job["employer_source_label"].startswith("Poste :")


def test_anonymized_generic_employer_label_is_preserved_but_not_company():
    html = '''<html><body>
      <div>une société au QI Ben souda</div>
      <div>Référence de l’offre:</div><div>FE0508261155050</div>
      <div>Date :</div><div>05/08/2026</div>
      <div>(2) Technicien De Production</div>
      <div>Type de contrat :</div><div>CDI</div>
      <div>Lieu de travail :</div><div>FES</div>
      <form action="/postulation"><input name="ref" value="FE0508261155050"></form>
    </body></html>'''
    job = parse_detail(html, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1155050/resultat_recherche", "1155050")
    assert job["company"] is None
    assert job["employer_source_label"] == "une société au QI Ben souda"


def test_salary_is_bounded_when_source_text_contains_benefits_and_location():
    html = '''<html><body>
      <div>Référence de l’offre:</div><div>ER0408261154293</div>
      <div>Date :</div><div>04/08/2026</div>
      <div>(3) Enseignant Des écoles</div>
      <div>Type de contrat :</div><div>CDI</div>
      <div>Lieu de travail :</div><div>ERRACHIDIA</div>
      <div>Salaire mensuel :</div><div>Négociable Logement est assuré dans la limite du disponible Lieu de travail : Nador - DEROUICH</div>
      <form action="/postulation"><input name="ref" value="ER0408261154293"></form>
    </body></html>'''
    job = parse_detail(html, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1154293/resultat_recherche", "1154293")
    assert job["salary"] == "Négociable"
    assert "Logement" in job["source_salary_text"]


def test_salary_money_is_bounded_when_adjacent_prose_leaks_into_source_node():
    html = '''<html><body>
      <div>Référence de l’offre:</div><div>NA1308261158832</div>
      <div>Date :</div><div>13/08/2026</div>
      <div>(60) OPERATEUR AU TERMINAL</div>
      <div>Type de contrat :</div><div>CI</div>
      <div>Lieu de travail :</div><div>NADOR</div>
      <div>Salaire mensuel :</div><div>3750 DHS Formation : Technicien</div>
      <form action="/postulation"><input name="ref" value="NA1308261158832"></form>
    </body></html>'''
    job = parse_detail(html, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1158832/resultat_recherche", "1158832")
    assert job["salary"] == "3750 DHS"
    assert job["source_salary_text"] == "3750 DHS Formation : Technicien"


def test_quality_gate_rejects_company_equal_to_title_and_bad_salary_context():
    from sources.public.anapec.quality_audit import audit_jobs
    clean = parse_detail(DETAIL_HTML, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1158866/resultat_recherche", "1158866")
    clean["application"] = build_application(clean["source_reference"])
    bad = dict(clean)
    bad["company"] = bad["title"]
    bad["salary"] = "Négociable Logement est assuré Lieu de travail : Nador"
    report = audit_jobs([bad], now=datetime(2026, 8, 14, 12, tzinfo=ZoneInfo("Africa/Casablanca")))
    assert report["gate"] == "FAIL"
    assert report["problem_counts"]["company_equals_title"] == 1
    assert report["problem_counts"]["invalid_salary_semantics"] == 1


def test_semantic_duplicate_groups_are_review_warnings_not_auto_deduplication():
    from sources.public.anapec.quality_audit import audit_jobs
    a = parse_detail(DETAIL_HTML, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1158866/resultat_recherche", "1158866")
    a["application"] = build_application(a["source_reference"])
    b = dict(a)
    b["source_offer_id"] = "1159999"
    b["source_reference"] = "BE1308261159999"
    b["global_id"] = "anapec:1159999"
    b["source_url"] = "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1159999/resultat_recherche"
    b["application"] = build_application(b["source_reference"])
    report = audit_jobs([a, b], now=datetime(2026, 8, 14, 12, tzinfo=ZoneInfo("Africa/Casablanca")))
    assert report["gate"] == "PASS"
    assert report["summary"]["semantic_duplicate_review_group_count"] == 1
    assert set(report["semantic_duplicate_review_groups"][0]) == {"1158866", "1159999"}


def test_metadata_heading_is_never_exposed_as_profile_or_description():
    html = '''<html><body>
      <div>Référence de l’offre:</div><div>SI0608261155353</div>
      <div>Date :</div><div>06/08/2026</div>
      <div>(600) Des Opératrices En Câblage</div>
      <div>Type de contrat :</div><div>CI</div>
      <div>Lieu de travail :</div><div>SIDI YAHYA (M)</div>
      <div>Caractéristiques du poste :</div><div>sans niveau , spécialisation, qualification et autre</div>
      <div>Profil recherché</div><div>Description du profil :</div>
      <div>Formation :</div><div>Diplôme de qualification professionnelle</div>
      <form action="/postulation"><input name="ref" value="SI0608261155353"></form>
    </body></html>'''
    job = parse_detail(html, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1155353/resultat_recherche", "1155353")
    assert job["description"] == "sans niveau , spécialisation, qualification et autre"
    assert job["profile"] is None


def test_quality_gate_rejects_metadata_heading_leaking_into_normalized_field():
    from sources.public.anapec.quality_audit import audit_jobs
    job = parse_detail(DETAIL_HTML, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1158866/resultat_recherche", "1158866")
    job["application"] = build_application(job["source_reference"])
    job["profile"] = "Description du profil :"
    report = audit_jobs([job], now=datetime(2026, 8, 14, 12, tzinfo=ZoneInfo("Africa/Casablanca")))
    assert report["gate"] == "FAIL"
    assert report["problem_counts"]["metadata_label_leaked_into_value"] == 1


def test_conflicting_free_text_work_location_is_preserved_not_overwritten():
    html = '''<html><body>
      <div>Référence de l’offre:</div><div>ER0408261154293</div>
      <div>Date :</div><div>04/08/2026</div>
      <div>(3) Enseignant Des écoles</div>
      <div>Type de contrat :</div><div>CDI</div>
      <div>Lieu de travail :</div><div>ERRACHIDIA</div>
      <div>Salaire mensuel :</div><div>Négociable Logement est assuré dans la limite du disponible Lieu de travail : Nador - DEROUICH</div>
      <form action="/postulation"><input name="ref" value="ER0408261154293"></form>
    </body></html>'''
    job = parse_detail(html, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1154293/resultat_recherche", "1154293")
    assert job["location"] == "ERRACHIDIA"
    assert job["source_location"] == "ERRACHIDIA"
    assert job["work_location_text"] == "Nador - DEROUICH"
    assert job["alternate_work_location"] == "Nador - DEROUICH"
    assert job["location_relation"] == "different_source_location"
    assert job["location_variation"] is True
    assert job["location_conflict"] is True


def test_quality_gate_accepts_structured_source_location_conflict():
    from sources.public.anapec.quality_audit import audit_jobs
    html = '''<html><body>
      <div>Référence de l’offre:</div><div>ER0408261154293</div>
      <div>Date :</div><div>04/08/2026</div>
      <div>(3) Enseignant Des écoles</div>
      <div>Type de contrat :</div><div>CDI</div>
      <div>Lieu de travail :</div><div>ERRACHIDIA</div>
      <div>Salaire mensuel :</div><div>Négociable Lieu de travail : Nador - DEROUICH</div>
      <form action="/postulation"><input name="ref" value="ER0408261154293"></form>
    </body></html>'''
    job = parse_detail(html, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1154293/resultat_recherche", "1154293")
    job["application"] = build_application(job["source_reference"])
    report = audit_jobs([job], now=datetime(2026, 8, 14, 12, tzinfo=ZoneInfo("Africa/Casablanca")))
    assert report["gate"] == "PASS"
    assert report["summary"]["location_variation_count"] == 1
    assert report["summary"]["different_source_location_count"] == 1


def test_semantic_review_fingerprint_distinguishes_different_positions_or_requirements():
    from sources.public.anapec.quality_audit import audit_jobs
    a = parse_detail(DETAIL_HTML, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1158866/resultat_recherche", "1158866")
    a["application"] = build_application(a["source_reference"])
    b = dict(a)
    b["source_offer_id"] = "1159999"
    b["source_reference"] = "BE1308261159999"
    b["global_id"] = "anapec:1159999"
    b["source_url"] = "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1159999/resultat_recherche"
    b["positions"] = a["positions"] + 1
    b["application"] = build_application(b["source_reference"])
    report = audit_jobs([a, b], now=datetime(2026, 8, 14, 12, tzinfo=ZoneInfo("Africa/Casablanca")))
    assert report["gate"] == "PASS"
    assert report["summary"]["semantic_duplicate_review_group_count"] == 0



def test_work_location_tail_is_cleaned_before_storage():
    html = '''<html><body>
      <div>Référence de l’offre:</div><div>OU0408261154436</div>
      <div>Date :</div><div>04/08/2026</div>
      <div>(3) Conducteur D'engins</div>
      <div>Type de contrat :</div><div>CDD</div>
      <div>Lieu de travail :</div><div>OUARZAZATE</div>
      <div>Caractéristiques du poste :</div><div>Lieu de travail: ville de TATA Logement assuré par l'employeur</div>
      <form action="/postulation"><input name="ref" value="OU0408261154436"></form>
    </body></html>'''
    job = parse_detail(html, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1154436/resultat_recherche", "1154436")
    assert job["work_location_text"] == "TATA"
    assert job["location_relation"] == "different_source_location"


def test_work_location_double_slash_tail_is_removed():
    html = '''<html><body>
      <div>Référence de l’offre:</div><div>TI1208261158026</div>
      <div>Date :</div><div>12/08/2026</div>
      <div>(1) Technicien Gestion Commerciale</div>
      <div>Type de contrat :</div><div>CI</div>
      <div>Lieu de travail :</div><div>TIZNIT</div>
      <div>Caractéristiques du poste :</div><div>Lieu de travail : Tafraout //Compétences Professionnelles : facturation</div>
      <form action="/postulation"><input name="ref" value="TI1208261158026"></form>
    </body></html>'''
    job = parse_detail(html, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1158026/resultat_recherche", "1158026")
    assert job["work_location_text"] == "Tafraout"
    assert job["location_relation"] == "different_source_location"


def test_related_location_detail_is_not_called_conflict():
    html = '''<html><body>
      <div>Référence de l’offre:</div><div>AG0308261153765</div>
      <div>Date :</div><div>03/08/2026</div>
      <div>(1) Vendeur</div>
      <div>Type de contrat :</div><div>CI</div>
      <div>Lieu de travail :</div><div>AGADIR</div>
      <div>Description du profil :</div><div>Lieu Travail : QUARTIER LES AMICALES AGADIR</div>
      <form action="/postulation"><input name="ref" value="AG0308261153765"></form>
    </body></html>'''
    job = parse_detail(html, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1153765/resultat_recherche", "1153765")
    assert job["work_location_text"] == "QUARTIER LES AMICALES AGADIR"
    assert job["location_relation"] == "related_detail"
    assert job["location_conflict"] is False


def test_multi_location_offer_is_structured_separately():
    html = '''<html><body>
      <div>Référence de l’offre:</div><div>TA0408261154196</div>
      <div>Date :</div><div>04/08/2026</div>
      <div>(6) AGENT COMMARCIAUX</div>
      <div>Type de contrat :</div><div>CI</div>
      <div>Lieu de travail :</div><div>TANGER-ASSILAH</div>
      <div>Caractéristiques du poste :</div><div>Lieu de travail : TANGER / LARACHE / AL HOCEIMA</div>
      <form action="/postulation"><input name="ref" value="TA0408261154196"></form>
    </body></html>'''
    job = parse_detail(html, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1154196/resultat_recherche", "1154196")
    assert job["location_relation"] == "multi_location"
    assert job["location_conflict"] is False


def test_quality_gate_rejects_dirty_work_location_tail():
    from sources.public.anapec.quality_audit import audit_jobs
    job = parse_detail(DETAIL_HTML, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1158866/resultat_recherche", "1158866")
    job["application"] = build_application(job["source_reference"])
    job["work_location_text"] = "TATA Logement assuré"
    job["alternate_work_location"] = job["work_location_text"]
    job["location_relation"] = "different_source_location"
    job["location_variation"] = True
    job["location_conflict"] = True
    report = audit_jobs([job], now=datetime(2026, 8, 14, 12, tzinfo=ZoneInfo("Africa/Casablanca")))
    assert report["gate"] == "FAIL"
    assert report["problem_counts"]["work_location_contains_non_location_tail"] == 1


def test_salary_embedded_in_larger_characteristics_line_is_extracted():
    html = '''<html><body>
      <div>Référence de l’offre:</div><div>KE0308261153788</div>
      <div>Date :</div><div>03/08/2026</div>
      <div>(8) Acheteuses</div>
      <div>Type de contrat :</div><div>CDI</div>
      <div>Lieu de travail :</div><div>KENITRA</div>
      <div>Caractéristiques du poste : Salaire : 5000dhs</div>
      <form action="/postulation"><input name="ref" value="KE0308261153788"></form>
    </body></html>'''
    job = parse_detail(html, "https://www.anapec.org/sigec-app-rv/fr/entreprises/bloc_offre_home/1153788/resultat_recherche", "1153788")
    assert job["salary"] == "5000 DHS"
    assert "5000dhs" in job["source_salary_text"].casefold()
