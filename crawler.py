from __future__ import annotations

import concurrent.futures as cf
import math
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from urllib import robotparser
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from parser import (
    BASE_URL,
    Job,
    extract_listing_links,
    extract_listing_titles,
    parse_detail,
    parse_official_count,
)

LIST_URL = f"{BASE_URL}/fr/concours-liste"
SCOPES = ("service_etat", "etab_publics", "collec")
USER_AGENT = "Masari-EmploiPublic-Audit/1.0"
PAGE_SIZE_ESTIMATE = 9
PAGE_GUARD = 12
MAX_OFFICIAL_RESULTS = 100_000
MAX_WORKERS = 8

_thread_local = threading.local()


def _session() -> requests.Session:
    sess = getattr(_thread_local, "session", None)
    if sess is None:
        sess = requests.Session()
        retry = Retry(
            total=5,
            connect=5,
            read=5,
            status=5,
            backoff_factor=0.8,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET"]),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=12, pool_maxsize=12)
        sess.mount("https://", adapter)
        sess.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept-Language": "fr-MA,fr;q=0.9,en;q=0.6",
                "Accept": "text/html,application/xhtml+xml",
                "Connection": "keep-alive",
            }
        )
        _thread_local.session = sess
    return sess


def _get(url: str, *, params: Optional[dict] = None, timeout: int = 30) -> requests.Response:
    # Small jitter keeps concurrent detail requests polite and avoids bursts.
    time.sleep(random.uniform(0.05, 0.18))
    r = _session().get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r


def robots_allows() -> tuple[bool, str]:
    url = f"{BASE_URL}/robots.txt"
    try:
        r = _get(url, timeout=20)
        if r.status_code == 404:
            return True, "robots.txt not found (allow by convention)"
        rp = robotparser.RobotFileParser()
        rp.set_url(url)
        rp.parse(r.text.splitlines())
        allowed_list = rp.can_fetch(USER_AGENT, LIST_URL)
        allowed_detail = rp.can_fetch(USER_AGENT, f"{BASE_URL}/fr/concours/details/00000000-0000-0000-0000-000000000000")
        return bool(allowed_list and allowed_detail), "robots.txt parsed"
    except Exception as exc:
        return False, f"robots check failed: {exc}"


def listing_params(scope: str, page: int) -> dict[str, str | int]:
    return {
        "corps": "0",
        "datePicker": "",
        "date_from": "",
        "date_to": "",
        "key_word": "",
        "procedure": "avis",
        "region": "0",
        "stat": scope,
        "page": page,
    }


@dataclass
class ScopeResult:
    scope: str
    official_before: int
    official_after: int
    target_pages: int
    discovered_urls: list[str]
    titles: dict[str, str]
    pages_requested: int
    pages_successful: int
    stable_counter: bool
    listing_complete: bool
    errors: list[str]


def crawl_scope_once(scope: str) -> ScopeResult:
    errors: list[str] = []
    urls: list[str] = []
    seen: set[str] = set()
    titles: dict[str, str] = {}
    pages_requested = 0
    pages_successful = 0

    first = _get(LIST_URL, params=listing_params(scope, 1))
    official_before = parse_official_count(first.text)
    first_links = extract_listing_links(first.text)
    for url in first_links:
        if url not in seen:
            seen.add(url)
            urls.append(url)
    titles.update(extract_listing_titles(first.text))
    pages_requested += 1
    pages_successful += 1

    # Derive the pagination budget from the site's own official result count.
    # A fixed page cap caused silent under-crawling when etab_publics grew past
    # 1,080 announcements (120 pages x 9 cards). The guard pages absorb small
    # template/page-size changes while the loop still exits immediately once
    # every official result has been discovered.
    if official_before < 0 or official_before > MAX_OFFICIAL_RESULTS:
        raise RuntimeError(f"Unreasonable official result count: {official_before}")
    target_pages = max(1, math.ceil(official_before / PAGE_SIZE_ESTIMATE) + PAGE_GUARD)
    stagnant = 0
    page = 2
    while len(seen) < official_before and page <= target_pages:
        pages_requested += 1
        before = len(seen)
        try:
            r = _get(LIST_URL, params=listing_params(scope, page))
            pages_successful += 1
            links = extract_listing_links(r.text)
            titles.update(extract_listing_titles(r.text))
            for url in links:
                if url not in seen:
                    seen.add(url)
                    urls.append(url)
        except Exception as exc:
            errors.append(f"page={page}: {type(exc).__name__}: {exc}")
        stagnant = stagnant + 1 if len(seen) == before else 0
        if stagnant >= 3:
            break
        page += 1

    # Re-read the official counter after crawling so an announcement published
    # during the run does not produce a false PASS.
    after = _get(LIST_URL, params=listing_params(scope, 1))
    official_after = parse_official_count(after.text)
    after_links = extract_listing_links(after.text)
    titles.update(extract_listing_titles(after.text))
    for url in after_links:
        if url not in seen:
            seen.add(url)
            urls.insert(0, url)

    stable = official_before == official_after
    complete = stable and len(seen) == official_after and not errors
    return ScopeResult(
        scope=scope,
        official_before=official_before,
        official_after=official_after,
        target_pages=target_pages,
        discovered_urls=urls,
        titles=titles,
        pages_requested=pages_requested,
        pages_successful=pages_successful,
        stable_counter=stable,
        listing_complete=complete,
        errors=errors,
    )


def crawl_scope(scope: str) -> ScopeResult:
    # One reconciliation retry if the counter changed during the first pass or
    # if a listing request failed.
    first = crawl_scope_once(scope)
    if first.listing_complete:
        return first
    time.sleep(1.0)
    second = crawl_scope_once(scope)
    if second.listing_complete:
        return second
    # Prefer the attempt with the better discovered/official ratio.
    def score(x: ScopeResult) -> tuple[float, int, int]:
        denom = max(x.official_after, 1)
        return (len(set(x.discovered_urls)) / denom, -len(x.errors), len(x.discovered_urls))
    return max((first, second), key=score)


class RetiredDetailRedirect(RuntimeError):
    # A discovered detail URL explicitly retired by Emploi-Public to the list page.
    def __init__(self, requested_url: str, final_url: str):
        self.requested_url = requested_url
        self.final_url = final_url
        super().__init__(f"retired detail redirect: {requested_url} -> {final_url}")


def _retired_detail_redirect_target(
    requested_url: str,
    response: requests.Response,
) -> Optional[str]:
    # Only soften the verified same-site pattern:
    # /fr/concours/details/<uuid> --3xx--> /fr/concours-liste
    if not response.history:
        return None

    requested = urlparse(requested_url)
    final = urlparse(response.url)
    base = urlparse(BASE_URL)

    if requested.netloc != base.netloc or final.netloc != base.netloc:
        return None
    if not requested.path.startswith("/fr/concours/details/"):
        return None
    if final.path.rstrip("/") != "/fr/concours-liste":
        return None

    first = response.history[0]
    first_url = urlparse(first.url)
    if first.status_code not in (301, 302, 303, 307, 308):
        return None
    if first_url.netloc != requested.netloc or first_url.path != requested.path:
        return None

    return response.url


@dataclass
class DetailResult:
    jobs: list[Job]
    failures: dict[str, str]
    retired_redirects: dict[str, str] = field(default_factory=dict)


def _fetch_detail(url: str, scope: str, title: str) -> Job:
    r = _get(url, timeout=35)
    retired_target = _retired_detail_redirect_target(url, r)
    if retired_target:
        raise RetiredDetailRedirect(url, retired_target)
    return parse_detail(r.text, url, scope, title)


def crawl_details(scope_results: list[ScopeResult]) -> DetailResult:
    tasks: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for result in scope_results:
        for url in result.discovered_urls:
            if url in seen:
                continue
            seen.add(url)
            tasks.append((url, result.scope, result.titles.get(url, "")))

    jobs: list[Job] = []
    failures: dict[str, str] = {}
    retired_redirects: dict[str, str] = {}
    with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futs = {
            pool.submit(_fetch_detail, url, scope, title): (url, scope, title)
            for url, scope, title in tasks
        }
        for fut in cf.as_completed(futs):
            url, _, _ = futs[fut]
            try:
                jobs.append(fut.result())
            except RetiredDetailRedirect as exc:
                retired_redirects[url] = exc.final_url
            except Exception as exc:
                failures[url] = f"{type(exc).__name__}: {exc}"

    # Recovery pass for transient detail failures, sequential to reduce pressure.
    if failures:
        retry_failures: dict[str, str] = {}
        lookup = {url: (scope, title) for url, scope, title in tasks}
        for url in list(failures):
            scope, title = lookup[url]
            try:
                time.sleep(0.4)
                jobs.append(_fetch_detail(url, scope, title))
            except RetiredDetailRedirect as exc:
                retired_redirects[url] = exc.final_url
            except Exception as exc:
                retry_failures[url] = f"{type(exc).__name__}: {exc}"
        failures = retry_failures

    jobs.sort(key=lambda j: (j.publication_date or "", j.uuid), reverse=True)
    return DetailResult(
        jobs=jobs,
        failures=failures,
        retired_redirects=retired_redirects,
    )
