from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import date, datetime, time
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

BASE_URL = "https://www.emploi-public.ma"
DETAIL_RE = re.compile(r"^/fr/concours/details/([0-9a-fA-F-]{36})/?$")
RESULTS_RE = re.compile(r"([\d.\s]+)\s+Résultats?", re.IGNORECASE)

MONTHS = {
    "janvier": 1,
    "février": 2,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "août": 8,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "décembre": 12,
    "decembre": 12,
}


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_french_datetime(value: str, *, end_of_day_if_no_time: bool = False) -> Optional[datetime]:
    value = _clean(value)
    m = re.search(
        r"(\d{1,2})\s+([A-Za-zÀ-ÿ]+)\s+(\d{4})(?:\s*-\s*(\d{1,2}):(\d{2}))?",
        value,
        re.IGNORECASE,
    )
    if not m:
        return None
    day = int(m.group(1))
    month = MONTHS.get(m.group(2).lower())
    if not month:
        return None
    year = int(m.group(3))
    if m.group(4):
        hh, mm = int(m.group(4)), int(m.group(5))
    elif end_of_day_if_no_time:
        hh, mm = 23, 59
    else:
        hh, mm = 0, 0
    return datetime(year, month, day, hh, mm)


def parse_official_count(html: str) -> int:
    # The site's result counter is rendered before the cards. We intentionally
    # inspect only the page portion before “Dernière chance pour postuler”.
    prefix = re.split(r"Dernière\s+chance\s+pour\s+postuler", html, maxsplit=1, flags=re.IGNORECASE)[0]
    soup = BeautifulSoup(prefix, "html.parser")
    text = soup.get_text(" ", strip=True)
    matches = RESULTS_RE.findall(text)
    if not matches:
        raise ValueError("Could not find the official 'Résultats' counter")
    # There should be one scoped counter. If templates add another counter,
    # the last one nearest the cards is the safest choice.
    raw = matches[-1]
    return int(re.sub(r"\D", "", raw))


def extract_listing_links(html: str) -> list[str]:
    # “Dernière chance” is cross-scope recommendation content and must not be
    # counted as part of the selected scope's official result set.
    prefix = re.split(r"Dernière\s+chance\s+pour\s+postuler", html, maxsplit=1, flags=re.IGNORECASE)[0]
    soup = BeautifulSoup(prefix, "html.parser")
    out: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        parsed = urlparse(href)
        path = parsed.path if parsed.scheme else href.split("?", 1)[0]
        if not DETAIL_RE.match(path):
            continue
        url = urljoin(BASE_URL, path)
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def extract_listing_titles(html: str) -> dict[str, str]:
    prefix = re.split(r"Dernière\s+chance\s+pour\s+postuler", html, maxsplit=1, flags=re.IGNORECASE)[0]
    soup = BeautifulSoup(prefix, "html.parser")
    out: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        parsed = urlparse(href)
        path = parsed.path if parsed.scheme else href.split("?", 1)[0]
        if DETAIL_RE.match(path):
            out[urljoin(BASE_URL, path)] = _clean(a.get_text(" ", strip=True))
    return out


def _find_heading_value(soup: BeautifulSoup, label: str) -> str:
    label_norm = _clean(label).lower()
    for tag in soup.find_all(["h2", "h3", "h4", "div", "p"]):
        text = _clean(tag.get_text(" ", strip=True))
        low = text.lower()
        if low.startswith(label_norm):
            return _clean(text[len(label):])
    return ""


def _description_fields(soup: BeautifulSoup) -> dict[str, object]:
    fields: dict[str, object] = {}
    label_map = {
        "spécialité": "specialties",
        "specialite": "specialties",
        "grade": "grade",
        "nombre de postes": "positions",
        "type de recrutement": "recruitment_type",
        "type de dépôt": "application_type",
        "type de depot": "application_type",
        "site de dépôt": "application_site",
        "site de depot": "application_site",
        "code du concours": "contest_code",
        "nom du poste": "job_name",
    }
    for li in soup.find_all("li"):
        raw = li.get_text("\n", strip=True)
        lines = [_clean(x).lstrip("-• ") for x in raw.splitlines() if _clean(x)]
        if not lines:
            continue
        first = lines[0]
        if ":" not in first:
            continue
        label, first_value = first.split(":", 1)
        key = label_map.get(_clean(label).lower())
        if not key:
            continue
        values: list[str] = []
        if _clean(first_value):
            values.append(_clean(first_value).lstrip("-• "))
        values.extend(x for x in lines[1:] if x)
        # Some templates render all specialties on one line separated by " - ".
        if key == "specialties":
            expanded: list[str] = []
            for value in values:
                expanded.extend(
                    _clean(x) for x in re.split(r"\s+-\s+", value) if _clean(x)
                )
            fields[key] = list(dict.fromkeys(expanded))
        elif key == "positions":
            joined = " ".join(values)
            m = re.search(r"\d+", joined)
            fields[key] = int(m.group(0)) if m else None
        else:
            fields[key] = _clean(" ".join(values))

    # "Site de dépôt" can also be a non-li line with an anchor.
    if not fields.get("application_site"):
        for node in soup.find_all(string=re.compile(r"Site de dépôt\s*:", re.IGNORECASE)):
            parent = node.parent
            anchor = parent.find_next("a", href=True) if parent else None
            if anchor:
                fields["application_site"] = anchor.get("href")
                break
    return fields


@dataclass
class Job:
    uuid: str
    url: str
    scope: str
    listing_title: str
    administration: str
    publication_date: Optional[str]
    deadline: Optional[str]
    contest_date: Optional[str]
    job_name: str
    grade: str
    specialties: list[str]
    positions: Optional[int]
    recruitment_type: str
    application_type: str
    application_site: str
    contest_code: str

    def to_dict(self) -> dict:
        return asdict(self)


def parse_detail(html: str, url: str, scope: str, listing_title: str = "") -> Job:
    soup = BeautifulSoup(html, "html.parser")
    path = urlparse(url).path
    m = DETAIL_RE.match(path)
    if not m:
        raise ValueError(f"Not an Emploi-Public detail URL: {url}")

    administration = _find_heading_value(soup, "Administration qui recrute")
    deadline_raw = _find_heading_value(soup, "Délai de dépôt des candidatures")
    contest_date_raw = _find_heading_value(soup, "Date du concours")
    publication_raw = _find_heading_value(soup, "Date de publication")
    fields = _description_fields(soup)

    publication_dt = parse_french_datetime(publication_raw)
    deadline_dt = parse_french_datetime(deadline_raw, end_of_day_if_no_time=True)
    contest_dt = parse_french_datetime(contest_date_raw)

    if not administration:
        raise ValueError("Missing administration")
    if not publication_dt:
        raise ValueError("Missing or invalid publication date")
    if not deadline_dt:
        raise ValueError("Missing or invalid deadline")
    if not fields.get("positions"):
        raise ValueError("Missing or invalid number of positions")
    if not (fields.get("specialties") or fields.get("job_name") or fields.get("grade")):
        raise ValueError("Missing classification fields (specialty/job name/grade)")

    return Job(
        uuid=m.group(1).lower(),
        url=url,
        scope=scope,
        listing_title=listing_title,
        administration=administration,
        publication_date=publication_dt.isoformat(),
        deadline=deadline_dt.isoformat(),
        contest_date=contest_dt.isoformat() if contest_dt else None,
        job_name=str(fields.get("job_name") or ""),
        grade=str(fields.get("grade") or ""),
        specialties=list(fields.get("specialties") or []),
        positions=fields.get("positions") if isinstance(fields.get("positions"), int) else None,
        recruitment_type=str(fields.get("recruitment_type") or ""),
        application_type=str(fields.get("application_type") or ""),
        application_site=str(fields.get("application_site") or ""),
        contest_code=str(fields.get("contest_code") or ""),
    )
