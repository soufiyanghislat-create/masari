from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter

from .parser import ListingOffer, parse_detail, parse_listing, parse_pagination_links
from .tls import create_native_ssl_context

BASE_URL = "https://www.anapec.org/sigec-app-rv"
FIRST_PAGE = f"{BASE_URL}/fr/chercheurs/resultat_recherche/tout:all"
USER_AGENT = "Masari-ANAPEC-PublicAudit/1.1"
TZ = ZoneInfo("Africa/Casablanca")
MAX_JOB_AGE_DAYS = 15
STALE_GUARD_PAGES = 3


class CrawlError(RuntimeError):
    pass


@dataclass
class CrawlResult:
    discovered: list[ListingOffer]
    jobs: list[dict]
    detail_failures: list[dict]
    pages_fetched: int
    termination_reason: str
    date_order_ok: bool
    freshness_frontier_confirmed: bool
    page_summaries: list[dict]


class NativeTLSAdapter(HTTPAdapter):
    """Requests adapter that pins every HTTPS pool to Masari's native SSLContext."""

    def __init__(self, *args, ssl_context=None, **kwargs):
        self._masari_ssl_context = ssl_context or create_native_ssl_context()
        super().__init__(*args, **kwargs)

    def build_connection_pool_key_attributes(self, request, verify, cert=None):
        if verify is False:
            raise CrawlError("TLS verification cannot be disabled for ANAPEC")
        host_params, pool_kwargs = super().build_connection_pool_key_attributes(
            request, True, cert
        )
        # Requests >=2.32 preloads its own certifi context for verify=True. Replace
        # it with the native trust context explicitly and remove alternate CA hints.
        pool_kwargs["ssl_context"] = self._masari_ssl_context
        pool_kwargs.pop("ca_certs", None)
        pool_kwargs.pop("ca_cert_dir", None)
        return host_params, pool_kwargs


def _session() -> requests.Session:
    s = requests.Session()
    s.verify = True
    s.mount("https://", NativeTLSAdapter())
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9"})
    return s


def _get(session: requests.Session, url: str, timeout: int = 25, attempts: int = 3) -> bytes:
    last = None
    for attempt in range(attempts):
        try:
            r = session.get(url, timeout=timeout)
            r.raise_for_status()
            # Preserve original bytes. BeautifulSoup/UnicodeDammit can honor the page's
            # own encoding declaration; requests.text can otherwise guess Latin-1 and
            # create mojibake such as "TÃ©lÃ©conseiller".
            return r.content
        except requests.RequestException as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(0.6 * (attempt + 1))
    raise CrawlError(f"GET failed after {attempts} attempts: {url}: {last}")


def _fetch_page_details(offers: list[ListingOffer], workers: int) -> tuple[list[dict], list[dict]]:
    jobs: list[dict] = []
    failures: list[dict] = []

    def fetch_detail(offer: ListingOffer) -> dict:
        session = _session()
        html = _get(session, offer.url)
        return parse_detail(html, offer.url, offer.source_offer_id)

    with ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as pool:
        future_map = {pool.submit(fetch_detail, offer): offer for offer in offers}
        for future in as_completed(future_map):
            offer = future_map[future]
            try:
                jobs.append(future.result())
            except Exception as exc:
                failures.append({
                    "source_offer_id": offer.source_offer_id,
                    "url": offer.url,
                    "error": f"{type(exc).__name__}: {exc}",
                })
    return jobs, failures


def _next_page_url(html: str, current_url: str, current_page: int) -> tuple[int, str] | None:
    links = parse_pagination_links(html, current_url)
    candidates = [link for link in links if link.page > current_page]
    if not candidates:
        return None
    nxt = min(candidates, key=lambda link: link.page)
    return nxt.page, nxt.url


def crawl(
    max_pages: int = 250,
    workers: int = 6,
    now: datetime | None = None,
    progress: Callable[[dict], None] | None = None,
) -> CrawlResult:
    """Crawl ANAPEC's newest-first feed only far enough to prove the 15-day window complete.

    We follow pagination links advertised by ANAPEC, never fabricate unbounded page URLs.
    Early termination is allowed only after three consecutive fully parsed pages are older
    than the freshness cutoff and observed page-date ordering stayed non-increasing.
    """
    now = now or datetime.now(TZ)
    cutoff = now.date() - timedelta(days=MAX_JOB_AGE_DAYS)

    discovered: dict[str, ListingOffer] = {}
    jobs_by_id: dict[str, dict] = {}
    failures: list[dict] = []
    page_summaries: list[dict] = []
    seen_listing_urls: set[str] = set()
    previous_page_min: date | None = None
    date_order_ok = True
    stale_streak = 0
    current_page = 1
    current_url = FIRST_PAGE

    for pages_fetched in range(1, max_pages + 1):
        if current_url in seen_listing_urls:
            raise CrawlError(f"ANAPEC pagination loop detected at page {current_page}: {current_url}")
        seen_listing_urls.add(current_url)

        listing_session = _session()
        html = _get(listing_session, current_url)
        offers = parse_listing(html, current_url)
        if pages_fetched == 1 and not offers:
            raise CrawlError("ANAPEC first listing page returned no canonical offer links")
        if not offers:
            return CrawlResult(
                discovered=list(discovered.values()), jobs=list(jobs_by_id.values()),
                detail_failures=failures, pages_fetched=pages_fetched,
                termination_reason="empty_page", date_order_ok=date_order_ok,
                freshness_frontier_confirmed=True, page_summaries=page_summaries,
            )

        page_jobs, page_failures = _fetch_page_details(offers, workers)
        failures.extend(page_failures)
        if page_failures:
            # Do not use incomplete page dates to prove a freshness frontier.
            for offer in offers:
                discovered.setdefault(offer.source_offer_id, offer)
            return CrawlResult(
                discovered=list(discovered.values()), jobs=list(jobs_by_id.values()) + page_jobs,
                detail_failures=failures, pages_fetched=pages_fetched,
                termination_reason="detail_failure", date_order_ok=date_order_ok,
                freshness_frontier_confirmed=False, page_summaries=page_summaries,
            )

        for offer in offers:
            discovered.setdefault(offer.source_offer_id, offer)
        for job in page_jobs:
            jobs_by_id.setdefault(job["source_offer_id"], job)

        dates = [date.fromisoformat(job["publication_date"][:10]) for job in page_jobs]
        page_max = max(dates)
        page_min = min(dates)
        # Newer pages must not appear after older pages. Equal dates across page boundaries are valid.
        if previous_page_min is not None and page_max > previous_page_min:
            date_order_ok = False
            raise CrawlError(
                f"ANAPEC listing publication dates are not monotonic at page {current_page}: "
                f"page_max={page_max.isoformat()} previous_page_min={previous_page_min.isoformat()}"
            )
        previous_page_min = page_min

        all_stale = all(d < cutoff for d in dates)
        stale_streak = stale_streak + 1 if all_stale else 0
        summary = {
            "page": current_page,
            "url": current_url,
            "offer_count": len(offers),
            "publication_date_max": page_max.isoformat(),
            "publication_date_min": page_min.isoformat(),
            "all_older_than_cutoff": all_stale,
            "stale_guard_streak": stale_streak,
        }
        page_summaries.append(summary)
        if progress:
            progress(summary)

        next_page = _next_page_url(html, current_url, current_page)
        if next_page is None:
            return CrawlResult(
                discovered=list(discovered.values()), jobs=list(jobs_by_id.values()),
                detail_failures=failures, pages_fetched=pages_fetched,
                termination_reason="no_next_page", date_order_ok=date_order_ok,
                freshness_frontier_confirmed=True, page_summaries=page_summaries,
            )

        if stale_streak >= STALE_GUARD_PAGES:
            return CrawlResult(
                discovered=list(discovered.values()), jobs=list(jobs_by_id.values()),
                detail_failures=failures, pages_fetched=pages_fetched,
                termination_reason="freshness_frontier", date_order_ok=True,
                freshness_frontier_confirmed=True, page_summaries=page_summaries,
            )

        current_page, current_url = next_page

    raise CrawlError(
        f"ANAPEC freshness frontier not proven within safety cap of {max_pages} listing pages"
    )
