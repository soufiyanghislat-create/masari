from crawler import PAGE_GUARD, PAGE_SIZE_ESTIMATE
from parser import extract_listing_links, parse_detail, parse_official_count

LISTING = """
<html><body>
<div>Collectivités territoriales Annonce 42 Résultats</div>
<a href="/fr/concours/details/11111111-1111-1111-1111-111111111111">Job A Annonce</a>
<a href="/fr/concours/details/22222222-2222-2222-2222-222222222222">Job B Annonce</a>
<h2>Dernière chance pour postuler</h2>
<a href="/fr/concours/details/33333333-3333-3333-3333-333333333333">Cross-scope recommendation</a>
</body></html>
"""

DETAIL = """
<html><body>
<h3>Administration qui recrute Ministère Test</h3>
<h3>Délai de dépôt des candidatures 19 Août 2026 - 16:30</h3>
<h3>Date du concours 4 Octobre 2026</h3>
<h3>Date de publication 4 Août 2026</h3>
<h2>Description</h2>
<ul>
<li>Spécialité :<br>- Technico-commercial en production horticole<br>- Gestion et maitrise de l’eau / Hydraulique rurale et irrigation<br>- Développement informatique</li>
<li>Grade : Technicien de 3ème grade - echelle 9</li>
<li>Nombre de postes : 70</li>
<li>Type de recrutement : Recrutement régulier</li>
<li>Type de dépôt : dépôt en ligne sur le site de l'administration</li>
<li>Code du concours : C43113/26</li>
</ul>
</body></html>
"""


def test_listing_counter_and_last_chance_exclusion():
    assert parse_official_count(LISTING) == 42
    links = extract_listing_links(LISTING)
    assert len(links) == 2
    assert all("33333333" not in u for u in links)


def test_detail_parser_preserves_specialties():
    url = "https://www.emploi-public.ma/fr/concours/details/11111111-1111-1111-1111-111111111111"
    job = parse_detail(DETAIL, url, "service_etat", "Avis de concours")
    assert job.positions == 70
    assert job.administration == "Ministère Test"
    assert job.publication_date == "2026-08-04T00:00:00"
    assert job.deadline == "2026-08-19T16:30:00"
    assert job.contest_date == "2026-10-04T00:00:00"
    assert "Développement informatique" in job.specialties
    assert "Technico-commercial en production horticole" in job.specialties


def test_etab_publics_scale_requires_more_than_old_120_page_cap():
    import math
    official = 1571
    target_pages = math.ceil(official / PAGE_SIZE_ESTIMATE) + PAGE_GUARD
    assert target_pages >= 175
    assert target_pages > 120


DETAIL_WITH_SIMILAR_CONTEST_DATE = """
<html><body>

<h3>Administration qui recrute Société Test</h3>
<h3>Délai de dépôt des candidatures 27 Février 2026 - 16:30</h3>
<h3>Date de publication 12 Février 2026</h3>

<h2>Description</h2>
<ul>
<li>Nom du poste : Chef de projet SIRH</li>
<li>Nombre de postes : 1</li>
<li>Type de recrutement : Recrutement régulier</li>
</ul>

<h2>Concours similaires</h2>

<div class="similar-job">
    <h3>Autre concours</h3>
    <p>Date du concours 12 Septembre 2026</p>
</div>

</body></html>
"""


def test_detail_parser_ignores_contest_date_from_similar_announcements():
    url = (
        "https://www.emploi-public.ma/fr/concours/details/"
        "0267d6e6-eb39-4f0a-9822-9050514586a0"
    )

    job = parse_detail(
        DETAIL_WITH_SIMILAR_CONTEST_DATE,
        url,
        "etab_publics",
        "Avis de concours de recrutement de Chef de projet SIRH",
    )

    assert job.administration == "Société Test"
    assert job.publication_date == "2026-02-12T00:00:00"
    assert job.deadline == "2026-02-27T16:30:00"
    assert job.job_name == "Chef de projet SIRH"

    # Critical regression:
    # the date belongs to "Concours similaires", not this announcement.
    assert job.contest_date is None
