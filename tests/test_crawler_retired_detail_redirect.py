from types import SimpleNamespace

import pytest

import crawler


DETAIL_URL = (
    "https://www.emploi-public.ma/fr/concours/details/"
    "374beffe-58c3-11ef-810d-506b8df7d43c"
)
LIST_URL = "https://www.emploi-public.ma/fr/concours-liste"


def redirected_response(final_url=LIST_URL, status_code=302):
    first = SimpleNamespace(
        status_code=status_code,
        url=DETAIL_URL,
    )
    return SimpleNamespace(
        history=[first],
        url=final_url,
        text="<html><body>Liste des concours</body></html>",
    )


def test_verified_detail_to_list_redirect_is_retired():
    response = redirected_response()
    assert (
        crawler._retired_detail_redirect_target(DETAIL_URL, response)
        == LIST_URL
    )


def test_external_redirect_is_not_softened():
    response = redirected_response("https://example.com/fr/concours-liste")
    assert crawler._retired_detail_redirect_target(DETAIL_URL, response) is None


def test_same_final_page_without_redirect_history_is_not_softened():
    response = SimpleNamespace(
        history=[],
        url=LIST_URL,
        text="<html></html>",
    )
    assert crawler._retired_detail_redirect_target(DETAIL_URL, response) is None


def test_non_redirect_history_status_is_not_softened():
    response = redirected_response(status_code=200)
    assert crawler._retired_detail_redirect_target(DETAIL_URL, response) is None


def test_fetch_detail_raises_typed_retired_redirect(monkeypatch):
    response = redirected_response()
    monkeypatch.setattr(crawler, "_get", lambda *args, **kwargs: response)

    with pytest.raises(crawler.RetiredDetailRedirect) as exc_info:
        crawler._fetch_detail(DETAIL_URL, "etab_publics", "Old listing")

    assert exc_info.value.requested_url == DETAIL_URL
    assert exc_info.value.final_url == LIST_URL


def test_crawl_details_records_retired_redirect_not_failure(monkeypatch):
    def fake_fetch(url, scope, title):
        raise crawler.RetiredDetailRedirect(url, LIST_URL)

    monkeypatch.setattr(crawler, "_fetch_detail", fake_fetch)

    scope = SimpleNamespace(
        scope="etab_publics",
        discovered_urls=[DETAIL_URL],
        titles={DETAIL_URL: "Old listing"},
    )

    result = crawler.crawl_details([scope])

    assert result.jobs == []
    assert result.failures == {}
    assert result.retired_redirects == {DETAIL_URL: LIST_URL}
