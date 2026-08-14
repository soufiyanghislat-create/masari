from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
import unicodedata
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

BASE_URL = "https://www.anapec.org"
REF_RE = re.compile(r"\b[A-Z]{2}\d{10,16}\b")
DATE_RE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
DETAIL_PATH_RE = re.compile(
    r"/entreprises/bloc_offre_home/(?P<id>\d{6,10})/(?:resultat_recherche|display)(?:/|$)",
    re.IGNORECASE,
)
PAGE_PATH_RE = re.compile(r"/chercheurs/resultat_recherche/page:(?P<page>\d+)(?:/|$)", re.IGNORECASE)
TITLE_RE = re.compile(r"^\s*\((?P<count>\d+)\)\s*(?P<title>.+?)\s*$")


class ParseError(ValueError):
    pass


@dataclass(frozen=True)
class ListingOffer:
    source_offer_id: str
    url: str


@dataclass(frozen=True)
class PaginationLink:
    page: int
    url: str


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _lines(soup: BeautifulSoup) -> list[str]:
    return [_clean(x) for x in soup.stripped_strings if _clean(x)]


def _normalize_label_text(text: str) -> str:
    return unicodedata.normalize("NFC", _clean(text)).replace("’", "'").casefold()


def _find_labeled(lines: list[str], aliases: Iterable[str]) -> str | None:
    aliases = tuple(_normalize_label_text(a).rstrip(":").strip() for a in aliases)
    for i, line in enumerate(lines):
        normalized = _normalize_label_text(line)
        for alias in aliases:
            if normalized == alias or re.fullmatch(re.escape(alias) + r"\s*:", normalized):
                return lines[i + 1] if i + 1 < len(lines) else None
            m = re.match(re.escape(alias) + r"\s*:\s*(.*)$", normalized)
            if m:
                # Preserve original accents/casing in the extracted value.
                value = _clean(line.split(":", 1)[1])
                return value or (lines[i + 1] if i + 1 < len(lines) else None)
    return None


def _find_date(lines: list[str]) -> str | None:
    value = _find_labeled(lines, ("date", "date de publication"))
    if value:
        m = DATE_RE.search(value)
        if m:
            return datetime.strptime(m.group(1), "%d/%m/%Y").date().isoformat()
    for line in lines:
        if line.casefold().startswith("date"):
            m = DATE_RE.search(line)
            if m:
                return datetime.strptime(m.group(1), "%d/%m/%Y").date().isoformat()
    return None


def _find_title_and_positions(lines: list[str], soup: BeautifulSoup) -> tuple[str | None, int | None, str | None]:
    candidates: list[tuple[str, int, str]] = []
    for line in lines:
        m = TITLE_RE.match(line)
        if not m:
            continue
        title = _clean(m.group("title"))
        if title:
            candidates.append((title, int(m.group("count")), line))
    if candidates:
        # Prefer the richest actual title when the page repeats a shortened heading.
        return max(candidates, key=lambda x: len(x[0]))

    for tag in soup.find_all(["h1", "h2", "h3"]):
        text = _clean(tag.get_text(" ", strip=True))
        if text and text.casefold() not in {"offre d'emploi", "offre emploi"}:
            return text, None, text
    return None, None, None


_SECTION_LABELS = {
    "secteur d'activité", "secteur d’activite", "description de poste",
    "type de contrat", "lieu de travail", "date de début", "date debut",
    "caractéristiques du poste", "profil recherché", "formation",
    "expérience professionnelle", "langues", "commentaire",
}


def _label_key(text: str) -> str:
    return _clean(text).rstrip(":").strip().replace("’", "'").casefold()


def _looks_like_label(text: str) -> bool:
    folded = _label_key(text)
    normalized_labels = {x.replace("’", "'").casefold() for x in _SECTION_LABELS}
    return folded in normalized_labels


# Labels that ANAPEC can emit as standalone lines. These are metadata headings,
# never user-facing field values. Keep the list deliberately explicit so a
# legitimate sentence ending in ':' is not discarded by a broad heuristic.
_VALUE_LABELS = {
    "description du profil", "compétences requises", "competences requises",
    "compétences", "competences", "caractéristiques du poste",
    "caracteristiques du poste", "profil recherché", "profil recherche",
    "description de poste", "formation", "expérience professionnelle",
    "experience professionnelle", "langues", "langue", "commentaire",
    "commentaires", "secteur d'activité", "secteur d’activité",
    "type de contrat", "lieu de travail", "date de début", "date debut",
    "poste", "bureautiques", "bureautique",
}


def _is_metadata_label_value(value: str | None) -> bool:
    if not value:
        return False
    key = _label_key(value)
    labels = {x.replace("’", "'").casefold() for x in _VALUE_LABELS}
    return key in labels


def _clean_optional_value(value: str | None) -> str | None:
    value = _clean(value or "")
    if not value or _is_metadata_label_value(value):
        return None
    return value


_NON_COMPANY_TEXT = {
    "partager sur", "envoyer à un ami", "annonce d’emploi", "annonce d'emploi",
    "accès employeurs", "acces employeurs", "contact", "l'entretien d'embauche",
}


_GENERIC_COMPANY_LEAD_RE = re.compile(
    r"^(?:une\s+)?(?:soci[ée]t[ée]|st[ée]|entreprise|magasin|magsin|cabinet|centre)\s+"
    r"(?:d['’]|de|du|des|dans|au|aux|op[ée]rant|active|sp[ée]cialis[ée]e?|commerciale?|industrielle?)\b",
    re.IGNORECASE,
)

_GENERIC_ENTITY_EXACT = {
    "association", "cabinet medical", "cabinet médicale", "cabinet medicale",
    "société", "societe", "entreprise", "magasin", "centre",
}

_POSTE_PREFIX_RE = re.compile(r"^poste\s*:", re.IGNORECASE)


def _looks_like_generic_company_descriptor(text: str) -> bool:
    candidate = _clean(text).rstrip(",").strip()
    if not candidate:
        return False
    return bool(_GENERIC_COMPANY_LEAD_RE.search(candidate))


def _is_plausible_company_name(text: str, *, secondary: bool = False) -> bool:
    candidate = _clean(text).rstrip(",").strip()
    if not candidate or _looks_like_label(candidate):
        return False
    folded = _label_key(candidate)
    normalized_non_company = {x.replace("’", "'").casefold() for x in _NON_COMPANY_TEXT}
    if folded in normalized_non_company:
        return False
    if folded in {x.replace("’", "'").casefold() for x in _GENERIC_ENTITY_EXACT}:
        return False
    if _POSTE_PREFIX_RE.match(candidate):
        return False
    # A disclosed company name is a label/name, not a recruitment sentence.
    # Keep this intentionally precision-first: uncertain prose is stored as
    # company_description instead of being presented as an employer name.
    if len(candidate) > 80:
        return False
    if re.search(r"\b(cherche|cherhce|recherche|recrute|recrutement|besoin de)\b", folded):
        return False
    if _looks_like_generic_company_descriptor(candidate):
        return False
    # The post-heading signal is weaker than the header-before-reference signal.
    # Keep it precision-first: a secondary candidate must also look like a short
    # brand/legal name rather than generic prose.
    if secondary:
        words = re.findall(r"[A-Za-zÀ-ÿ0-9&.'’+-]+", candidate)
        legal = bool(re.search(r"\b(SARL|S\.?A\.?|SAS|SAU|LLC|LTD|INC)\b", candidate, re.IGNORECASE))
        uppercase_brand = any(len(w) >= 2 and w.isupper() for w in words)
        title_brand = bool(words) and len(words) <= 4 and all(
            w[:1].isupper() or w.casefold() in {"de", "du", "des", "maroc", "groupe"}
            for w in words
        )
        if not (legal or uppercase_brand or title_brand):
            return False
    return True


def _find_company(lines: list[str]) -> str | None:
    # Strongest ANAPEC signal: when disclosed in the header, the employer name
    # sits immediately before the offer-reference label.
    reference_labels = {"référence de l'offre", "reference de l'offre"}
    for i, line in enumerate(lines):
        if _label_key(line) in reference_labels:
            if i > 0:
                candidate = _clean(lines[i - 1]).rstrip(",").strip()
                if _is_plausible_company_name(candidate):
                    return candidate
            break

    # Secondary strong signal: some pages repeat a short employer name as the
    # first line of the company-description section (e.g. ALTRAN MAROC). Long
    # prose/recruitment sentences are deliberately not promoted to company.
    for i, line in enumerate(lines):
        if _label_key(line) != "description de l'entreprise":
            continue
        if i + 1 < len(lines):
            candidate = _clean(lines[i + 1]).rstrip(",").strip()
            if _is_plausible_company_name(candidate, secondary=True):
                return candidate
        break
    return None


def _find_company_description(lines: list[str]) -> str | None:
    # Preserve source prose without mislabeling it as a legal/company name.
    for i, line in enumerate(lines):
        if _label_key(line) != "description de l'entreprise":
            continue
        parts: list[str] = []
        for value in lines[i + 1:]:
            if _looks_like_label(value):
                break
            clean = _clean(value).rstrip(",").strip()
            if clean:
                parts.append(clean)
        if not parts:
            return None
        # If the first line is the already-disclosed company name, omit it from
        # the prose field and keep only the descriptive text that follows.
        company = _find_company(lines)
        if company and parts and parts[0].casefold() == company.casefold():
            parts = parts[1:]
        # ANAPEC occasionally emits a short generic descriptor followed by a
        # longer sentence that starts with the same words. Keep only the richer
        # sentence instead of duplicating the prose.
        compact: list[str] = []
        for part in parts:
            if compact and part.casefold().startswith(compact[-1].casefold()) and len(part) > len(compact[-1]):
                compact[-1] = part
            elif not compact or part.casefold() != compact[-1].casefold():
                compact.append(part)
        return " ".join(compact) or None
    return None


def _extract_postulation_reference(soup: BeautifulSoup, lines: list[str]) -> str | None:
    form = soup.find("form", action=lambda x: isinstance(x, str) and "postulation" in x)
    if form:
        hidden = form.find("input", attrs={"name": "ref"})
        if hidden and hidden.get("value"):
            return _clean(hidden["value"])
    joined = "\n".join(lines)
    m = REF_RE.search(joined)
    return m.group(0) if m else None


def parse_listing(html: str | bytes, page_url: str) -> list[ListingOffer]:
    """Extract only canonical ANAPEC offer-detail links, never arbitrary numeric links."""
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, ListingOffer] = {}
    for a in soup.find_all("a", href=True):
        href = _clean(a.get("href"))
        if not href:
            continue
        absolute = urljoin(page_url, href)
        parsed = urlparse(absolute)
        if parsed.netloc and "anapec.org" not in parsed.netloc.casefold():
            continue
        match = DETAIL_PATH_RE.search(parsed.path)
        if not match:
            continue
        offer_id = match.group("id")
        found.setdefault(offer_id, ListingOffer(source_offer_id=offer_id, url=absolute))
    return list(found.values())


def parse_pagination_links(html: str | bytes, page_url: str) -> list[PaginationLink]:
    """Extract pagination URLs advertised by ANAPEC itself."""
    soup = BeautifulSoup(html, "html.parser")
    found: dict[int, PaginationLink] = {}
    for a in soup.find_all("a", href=True):
        href = _clean(a.get("href"))
        if not href:
            continue
        absolute = urljoin(page_url, href)
        parsed = urlparse(absolute)
        if parsed.netloc and "anapec.org" not in parsed.netloc.casefold():
            continue
        match = PAGE_PATH_RE.search(parsed.path)
        if not match:
            continue
        page = int(match.group("page"))
        found.setdefault(page, PaginationLink(page=page, url=absolute))
    return [found[p] for p in sorted(found)]


MULTI_CONTRACT_RE = re.compile(r"^\s*choix\s+multiple\s*:\s*(.*)$", re.IGNORECASE)
CONTRACT_OPTION_RE = re.compile(r"\((?P<count>\d+)\)\s*(?P<type>[^,;]+)")


def _parse_contract(raw: str | None) -> tuple[str | None, list[dict], str | None]:
    if not raw:
        return None, [], None
    source_text = _clean(raw)
    match = MULTI_CONTRACT_RE.match(source_text)
    if not match:
        return source_text, [], source_text
    options: list[dict] = []
    for m in CONTRACT_OPTION_RE.finditer(match.group(1)):
        contract_type = _clean(m.group("type")).strip(" ,;:").upper()
        if contract_type:
            options.append({"type": contract_type, "positions": int(m.group("count"))})
    return "MULTIPLE", options, source_text


SALARY_MONEY_RE = re.compile(
    r"(?P<amount>\d[\d\s.,]*)\s*(?P<currency>DHS?|MAD)\b(?P<bonus>\s*\+\s*primes?)?",
    re.IGNORECASE,
)
SALARY_NEGOTIABLE_RE = re.compile(r"\b(n[ée]gociable|[àa]\s+n[ée]gocier)\b", re.IGNORECASE)
SALARY_FORBIDDEN_TAIL_RE = re.compile(
    r"\b(lieu\s+de\s+travail|logement|formation|profil|exp[ée]rience|langues?)\b",
    re.IGNORECASE,
)


def _parse_salary_text(raw: str) -> tuple[str | None, str | None]:
    source_text = _clean(raw)
    money = SALARY_MONEY_RE.search(source_text)
    if money:
        amount = _clean(money.group("amount"))
        currency = money.group("currency").upper()
        bonus = _clean(money.group("bonus") or "")
        normalized = f"{amount} {currency}{bonus}"
        return normalized, source_text
    negotiable = SALARY_NEGOTIABLE_RE.search(source_text)
    if negotiable:
        return "Négociable", source_text
    # Preserve short source values such as SMIG, but never let adjacent section
    # prose leak into the normalized salary field.
    if len(source_text) <= 40 and not SALARY_FORBIDDEN_TAIL_RE.search(source_text):
        return source_text, source_text
    return None, source_text


def _find_salary(lines: list[str]) -> tuple[str | None, str | None]:
    raw = _find_labeled(lines, ("salaire", "salaire mensuel", "rémunération", "remuneration"))
    if raw:
        return _parse_salary_text(raw)

    # Some ANAPEC offers embed salary inside a larger line instead of exposing
    # a standalone label/value pair. This fallback is deliberately bounded to
    # lines that explicitly contain the word 'salaire'.
    for line in lines:
        folded = _normalize_label_text(line)
        if "salaire" not in folded:
            continue
        after = line.split(":", 1)[1] if ":" in line else line
        salary, source_text = _parse_salary_text(after)
        if salary:
            return salary, source_text
    return None, None


def _find_employer_source_label(lines: list[str]) -> str | None:
    """Preserve ANAPEC's displayed employer header without claiming it is a legal company name."""
    reference_labels = {"référence de l'offre", "reference de l'offre"}
    for i, line in enumerate(lines):
        if _label_key(line) in reference_labels and i > 0:
            candidate = _clean(lines[i - 1]).rstrip(",").strip()
            if candidate and not _looks_like_label(candidate):
                folded = _label_key(candidate)
                normalized_non_company = {x.replace("’", "'").casefold() for x in _NON_COMPANY_TEXT}
                if folded not in normalized_non_company:
                    return candidate
            break
    return None


LOCATION_INLINE_RE = re.compile(
    r"\blieu\s+(?:de\s+)?travail\s*:\s*(?P<location>.+)$",
    re.IGNORECASE,
)

WORK_LOCATION_TAIL_RE = re.compile(
    r"\s*(?:[-–—]\s*)?(?:logement\b|hébergement\b|hebergement\b|"
    r"comp[ée]tences?\b|dipl[oô]me\b|formation\b|profil\b|"
    r"exp[ée]rience\b|langues?\b|commentaire\b).*$",
    re.IGNORECASE,
)


def _normalize_location_compare(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", _clean(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _clean_work_location_candidate(value: str) -> str | None:
    candidate = _clean(value)
    # ANAPEC sometimes appends the rest of the job description after // on the
    # same line. That text is not part of the workplace.
    candidate = candidate.split("//", 1)[0].strip()
    candidate = re.split(
        r"\s+(?:Formation|Profil|Exp[ée]rience|Langues?|Commentaire)\s*:\s*",
        candidate,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    candidate = WORK_LOCATION_TAIL_RE.sub("", candidate).strip(" ,;.-")
    # 'ville de TATA' is prose around the place name, not part of the place.
    candidate = re.sub(r"^(?:ville\s+de|ville\s+d['’])\s+", "", candidate, flags=re.IGNORECASE).strip()
    return candidate or None


def _find_work_location_text(lines: list[str], primary_location: str | None) -> str | None:
    """Return a clean explicit workplace mentioned in ANAPEC free text.

    The structured `Lieu de travail` field remains authoritative source metadata.
    This second value is preserved as source-provided detail and is never used to
    silently overwrite the structured value.
    """
    primary_norm = _normalize_location_compare(primary_location)
    candidates: list[str] = []
    for line in lines:
        m = LOCATION_INLINE_RE.search(_clean(line))
        if not m:
            continue
        candidate = _clean_work_location_candidate(m.group("location"))
        if not candidate:
            continue
        norm = _normalize_location_compare(candidate)
        if norm and norm != primary_norm and candidate not in candidates:
            candidates.append(candidate)
    return candidates[0] if candidates else None


def _location_relation(primary_location: str | None, work_location_text: str | None) -> str:
    if not work_location_text:
        return "primary_only"
    primary_norm = _normalize_location_compare(primary_location)
    work_norm = _normalize_location_compare(work_location_text)
    # Explicit lists such as 'TANGER / LARACHE / AL HOCEIMA' represent a
    # multi-location offer. Do not call this a conflict.
    if "/" in work_location_text and len([x for x in work_location_text.split("/") if x.strip()]) >= 2:
        return "multi_location"
    primary_tokens = {t for t in primary_norm.split() if len(t) >= 4}
    work_tokens = {t for t in work_norm.split() if len(t) >= 4}
    if primary_tokens & work_tokens:
        return "related_detail"
    return "different_source_location"


def parse_detail(html: str | bytes, source_url: str, source_offer_id: str | None = None) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    lines = _lines(soup)

    inferred_id = source_offer_id
    if not inferred_id:
        m = DETAIL_PATH_RE.search(urlparse(source_url).path)
        inferred_id = m.group("id") if m else None

    title, positions, source_title = _find_title_and_positions(lines, soup)
    publication_date = _find_date(lines)
    reference = _extract_postulation_reference(soup, lines)
    location = _find_labeled(lines, ("lieu de travail", "lieu", "ville", "localisation"))

    required = {
        "source_offer_id": inferred_id,
        "source_reference": reference,
        "title": title,
        "source_title": source_title,
        "positions": positions,
        "publication_date": publication_date,
        "location": location,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise ParseError("missing required ANAPEC field(s): " + ", ".join(missing))

    raw_contract = _find_labeled(lines, ("type de contrat", "contrat"))
    contract_type, contract_options, source_contract_text = _parse_contract(raw_contract)
    salary, source_salary_text = _find_salary(lines)
    company = _find_company(lines)
    if company and _normalize_label_text(company) == _normalize_label_text(title):
        company = None

    job = {
        "source": "anapec",
        "source_label": "ANAPEC",
        "source_offer_id": inferred_id,
        "source_reference": reference,
        "global_id": f"anapec:{inferred_id}",
        "title": title,
        "source_title": source_title,
        "positions": positions,
        "publication_date": publication_date,
        "location": location,
        "source_url": source_url,
        "company": company,
        "employer_source_label": _find_employer_source_label(lines),
        "company_description": _clean_optional_value(_find_company_description(lines)),
        "agency": _clean_optional_value(_find_labeled(lines, ("agence",))),
        "start_date": _clean_optional_value(_find_labeled(lines, ("date de début", "date debut", "date de début du contrat"))),
        "contract_type": contract_type,
        "contract_options": contract_options,
        "source_contract_text": source_contract_text,
        "salary": salary,
        "source_salary_text": source_salary_text,
        "sector": _clean_optional_value(_find_labeled(lines, ("secteur d'activité", "secteur d’activité", "secteur d’activite", "secteur"))),
        # Precision-first: do not expose ANAPEC section headings as values.
        # Richer section parsing can be added later, but false data is worse
        # than an optional None.
        "description": _clean_optional_value(_find_labeled(lines, ("caractéristiques du poste", "caracteristiques du poste", "compétences", "competences", "description", "descriptif du poste"))),
        "profile": _clean_optional_value(_find_labeled(lines, ("description du profil", "profil recherché", "profil recherche", "profil"))),
        "education": _clean_optional_value(_find_labeled(lines, ("formation", "diplôme", "diplome"))),
        "experience": _clean_optional_value(_find_labeled(lines, ("expérience professionnelle", "experience professionnelle", "expérience", "experience"))),
        "languages": _clean_optional_value(_find_labeled(lines, ("langues", "langue"))),
        "comment": _clean_optional_value(_find_labeled(lines, ("commentaire", "commentaires"))),
    }
    work_location_text = _find_work_location_text(lines, location)
    relation = _location_relation(location, work_location_text)
    job["source_location"] = location
    job["work_location_text"] = work_location_text
    job["location_relation"] = relation
    job["location_variation"] = bool(work_location_text)
    # Backward-compatible aliases for the isolated source package. New code
    # should use work_location_text/location_relation.
    job["alternate_work_location"] = work_location_text
    job["location_conflict"] = relation == "different_source_location"
    job["deadline"] = None
    return job
