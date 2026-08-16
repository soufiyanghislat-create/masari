from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from docx import Document
from pypdf import PdfReader

from search import is_job_visible_now
from taxonomy_engine import Taxonomy, normalize, tokens

TZ = ZoneInfo("Africa/Casablanca")

MAX_CV_BYTES = 5 * 1024 * 1024
MAX_CV_PAGES = 25
MAX_TEXT_CHARS = 120_000
SUPPORTED_EXTENSIONS = frozenset({".pdf", ".docx", ".txt"})

CV_STOPWORDS = frozenset({
    "curriculum", "vitae", "cv", "profil", "profile", "resume", "contact",
    "telephone", "phone", "email", "adresse", "address", "maroc", "morocco",
    "experience", "experiences", "professionnelle", "professionnelles",
    "professional", "formation", "formations", "education", "diplome",
    "diplomes", "diploma", "diplomas", "competence", "competences", "skills",
    "skill", "langue", "langues", "language", "languages", "mission", "missions",
    "poste", "postes", "travail", "work", "emploi", "job", "jobs", "societe",
    "company", "entreprise", "annee", "annees", "year", "years", "mois", "month",
    "months", "niveau", "nationalite", "nationality", "permis", "driving",
})

LANGUAGE_MARKERS = {
    "ar": ("arabe", "arabic", "العربية", "عربي"),
    "fr": ("francais", "français", "french", "الفرنسية", "فرنسي"),
    "en": ("anglais", "english", "الانجليزية", "الإنجليزية", "إنجليزي"),
    "es": ("espagnol", "spanish", "الإسبانية", "اسباني"),
    "de": ("allemand", "german", "الألمانية", "الالمانية"),
}

EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", re.I)
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)")
YEARS_RE = re.compile(
    r"(?<!\d)(\d{1,2})\s*(?:ans?|années?|annees?|years?|yrs?|سنة|سنوات)(?!\w)",
    re.I,
)


class CVAnalysisError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _safe_extension(filename: str) -> str:
    return Path(str(filename or "")).suffix.casefold()


def _clean_text(text: str) -> str:
    text = str(text or "").replace("\x00", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()[:MAX_TEXT_CHARS]


def _extract_pdf(data: bytes) -> tuple[str, dict[str, Any]]:
    try:
        reader = PdfReader(BytesIO(data))
    except Exception as exc:
        raise CVAnalysisError("CV_PDF_INVALID", "Impossible de lire ce fichier PDF.") from exc

    if len(reader.pages) > MAX_CV_PAGES:
        raise CVAnalysisError(
            "CV_TOO_MANY_PAGES",
            f"Le CV dépasse la limite de {MAX_CV_PAGES} pages.",
        )

    if getattr(reader, "is_encrypted", False):
        try:
            result = reader.decrypt("")
        except Exception as exc:
            raise CVAnalysisError("CV_PDF_ENCRYPTED", "Le PDF est protégé par mot de passe.") from exc
        if result == 0:
            raise CVAnalysisError("CV_PDF_ENCRYPTED", "Le PDF est protégé par mot de passe.")

    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")

    return _clean_text("\n".join(pages)), {"pages": len(reader.pages)}


def _extract_docx(data: bytes) -> tuple[str, dict[str, Any]]:
    try:
        document = Document(BytesIO(data))
    except Exception as exc:
        raise CVAnalysisError("CV_DOCX_INVALID", "Impossible de lire ce fichier DOCX.") from exc

    blocks = [p.text for p in document.paragraphs if p.text]
    for table in document.tables:
        for row in table.rows:
            values = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if values:
                blocks.append(" | ".join(values))

    return _clean_text("\n".join(blocks)), {"paragraphs": len(document.paragraphs)}


def _extract_txt(data: bytes) -> tuple[str, dict[str, Any]]:
    text = ""
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    return _clean_text(text), {}


def extract_cv_text(filename: str, data: bytes) -> tuple[str, dict[str, Any]]:
    if not isinstance(data, (bytes, bytearray)):
        raise CVAnalysisError("CV_INVALID_BYTES", "Fichier CV invalide.")
    if not data:
        raise CVAnalysisError("CV_EMPTY_FILE", "Le fichier CV est vide.")
    if len(data) > MAX_CV_BYTES:
        raise CVAnalysisError(
            "CV_TOO_LARGE",
            f"Le CV dépasse la limite de {MAX_CV_BYTES // (1024 * 1024)} Mo.",
        )

    ext = _safe_extension(filename)
    if ext not in SUPPORTED_EXTENSIONS:
        raise CVAnalysisError(
            "CV_UNSUPPORTED_FORMAT",
            "Formats acceptés : PDF, DOCX et TXT.",
        )

    if ext == ".pdf":
        text, meta = _extract_pdf(bytes(data))
    elif ext == ".docx":
        text, meta = _extract_docx(bytes(data))
    else:
        text, meta = _extract_txt(bytes(data))

    if len(normalize(text)) < 60:
        raise CVAnalysisError(
            "CV_TEXT_TOO_SHORT",
            "Le CV ne contient pas assez de texte exploitable. "
            "Pour un PDF scanné, utilisez une version contenant du texte.",
        )

    return text, {"extension": ext, "bytes": len(data), **meta}


def _analysis_text(text: str) -> str:
    text = EMAIL_RE.sub(" ", text)
    text = PHONE_RE.sub(" ", text)
    return text


def detect_language_mentions(text: str) -> list[str]:
    normalized = normalize(text)
    padded = f" {normalized} "
    found = []
    for code, markers in LANGUAGE_MARKERS.items():
        for marker in markers:
            n = normalize(marker)
            if n and f" {n} " in padded:
                found.append(code)
                break
    return found


def infer_explicit_experience_years(text: str) -> int | None:
    values = []
    for match in YEARS_RE.finditer(text):
        value = int(match.group(1))
        if 0 < value <= 50:
            values.append(value)
    return max(values) if values else None


def _profession_candidates(
    text: str,
    taxonomy: Taxonomy,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    analysis = _analysis_text(text)
    normalized = normalize(analysis)
    padded = f" {normalized} "
    line_candidates = Counter()
    evidence_by_id: dict[str, set[str]] = {}

    for raw_line in analysis.splitlines()[:100]:
        line = raw_line.strip()
        if not line or len(line) > 120:
            continue
        suggestions = taxonomy.autocomplete(line, limit=3)
        for suggestion in suggestions:
            score = float(suggestion.get("score") or 0.0)
            pid = str(suggestion.get("profession_id") or "")
            if pid and score >= 800:
                line_candidates[pid] += 12
                matched = str(suggestion.get("matched_term") or suggestion.get("label") or "").strip()
                if matched:
                    evidence_by_id.setdefault(pid, set()).add(matched)

    rows = []
    for profession in taxonomy.market:
        best = 0.0
        matched_terms: set[str] = set(evidence_by_id.get(profession.id, set()))

        for term in taxonomy.query_terms(profession):
            nt = normalize(term)
            term_tokens = tokens(nt)
            if not nt or len(nt) < 3 or not term_tokens:
                continue

            count = padded.count(f" {nt} ")
            if not count:
                continue

            base = 76.0 if len(term_tokens) >= 2 else 62.0
            length_bonus = min(14.0, len(term_tokens) * 3.5)
            frequency_bonus = min(8.0, count * 2.0)
            label_bonus = 4.0 if normalize(term) == normalize(profession.label) else 0.0
            score = base + length_bonus + frequency_bonus + label_bonus
            if score > best:
                best = score
            matched_terms.add(term)

        if line_candidates.get(profession.id):
            best = max(best, 64.0) + min(24.0, line_candidates[profession.id])

        if best >= 64.0:
            rows.append(
                {
                    "profession_id": profession.id,
                    "label": profession.label,
                    "sector": profession.sector,
                    "family": profession.family,
                    "score": round(min(best, 100.0), 1),
                    "evidence": sorted(matched_terms, key=lambda x: (-len(x), x.casefold()))[:5],
                }
            )

    rows.sort(key=lambda x: (-x["score"], x["label"].casefold()))
    return rows[:limit]


def _content_tokens(value: str) -> list[str]:
    result = []
    for token in tokens(value):
        if token in CV_STOPWORDS:
            continue
        if token.isdigit():
            continue
        if len(token) < 3 and token not in {"c++", "c#", "r"}:
            continue
        result.append(token)
    return result


def _flatten(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        return " ".join(_flatten(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten(v) for v in value)
    return str(value)


def _job_text(job: dict[str, Any]) -> str:
    fields = (
        "title",
        "job_name",
        "listing_title",
        "search_title",
        "specialties",
        "description",
        "profile",
        "education",
        "experience",
        "languages",
        "sector",
        "contract_type",
    )
    return " ".join(_flatten(job.get(field)) for field in fields)


def _job_profession_ids(job: dict[str, Any]) -> set[str]:
    ids = {
        str(x).strip()
        for x in (job.get("profession_ids") or [])
        if str(x).strip()
    }
    for match in job.get("profession_matches") or []:
        pid = str((match or {}).get("profession_id") or "").strip()
        if not pid:
            continue
        if (match or {}).get("searchable") is False:
            continue
        if (match or {}).get("confidence") == "RELATED":
            continue
        ids.add(pid)
    return ids


def _publication_age_days(job: dict[str, Any], now: datetime) -> int:
    raw = str(job.get("publication_date") or "")
    if not raw:
        return 99
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        else:
            dt = dt.astimezone(TZ)
        return max((now.date() - dt.date()).days, 0)
    except Exception:
        return 99


def _public_job_match(job: dict[str, Any], score: float, reasons: list[dict[str, Any]]) -> dict[str, Any]:
    gid = str(job.get("global_id") or job.get("uuid") or "")
    return {
        "global_id": gid,
        "title": str(job.get("job_name") or job.get("title") or job.get("search_title") or "").strip(),
        "company": str(job.get("company") or job.get("administration") or "").strip(),
        "source": str(job.get("source") or "").strip(),
        "source_label": str(job.get("source_label") or job.get("source") or "").strip(),
        "employment_sector": str(job.get("employment_sector") or job.get("scope") or "").strip(),
        "location": _flatten(job.get("location") or job.get("work_location_text")).strip(),
        "publication_date": job.get("publication_date"),
        "deadline": job.get("deadline"),
        "contract_type": job.get("contract_type") or job.get("recruitment_type"),
        "match_score": round(score, 1),
        "reasons": reasons,
        "detail_url": f"/job/{gid}",
    }


def _match_jobs(
    text: str,
    index: dict[str, Any],
    profession_rows: list[dict[str, Any]],
    *,
    limit: int,
    now: datetime,
) -> tuple[list[dict[str, Any]], list[str]]:
    visible_jobs = [
        job
        for job in (index.get("jobs") or [])
        if isinstance(job, dict) and is_job_visible_now(job, now)
    ]
    if not visible_jobs:
        return [], []

    cv_counts = Counter(_content_tokens(_analysis_text(text)))
    if not cv_counts:
        return [], []

    job_token_sets: list[tuple[dict[str, Any], set[str]]] = []
    df: Counter[str] = Counter()
    cv_token_set = set(cv_counts)

    for job in visible_jobs:
        job_tokens = set(_content_tokens(_job_text(job)))
        job_token_sets.append((job, job_tokens))
        for token in job_tokens & cv_token_set:
            df[token] += 1

    n_jobs = max(len(visible_jobs), 1)
    idf = {
        token: math.log((n_jobs + 1) / (count + 1)) + 1.0
        for token, count in df.items()
        if 0 < count / n_jobs <= 0.35
    }

    cv_weights = {
        token: min(float(cv_counts[token]), 3.0) * weight
        for token, weight in idf.items()
    }
    strongest_cv_tokens = dict(
        sorted(cv_weights.items(), key=lambda x: (-x[1], x[0]))[:80]
    )
    denominator = sum(strongest_cv_tokens.values()) or 1.0

    profession_score = {
        row["profession_id"]: float(row["score"])
        for row in profession_rows
    }
    profession_label = {
        row["profession_id"]: str(row["label"])
        for row in profession_rows
    }

    scored = []
    for job, job_tokens in job_token_sets:
        pids = _job_profession_ids(job)
        matching_professions = [
            (pid, profession_score[pid])
            for pid in pids
            if pid in profession_score
        ]
        best_prof = max((score for _pid, score in matching_professions), default=0.0)
        profession_component = best_prof * 0.45

        matched = [token for token in strongest_cv_tokens if token in job_tokens]
        matched_weight = sum(strongest_cv_tokens[t] for t in matched)
        coverage = min(matched_weight / denominator, 1.0)
        keyword_component = min(
            35.0,
            (min(len(matched), 6) * 2.5) + (coverage * 20.0),
        )

        title_tokens = set(_content_tokens(str(job.get("job_name") or job.get("title") or "")))
        title_hits = title_tokens & set(matched)
        title_component = min(10.0, len(title_hits) * 2.5)

        age = _publication_age_days(job, now)
        recency_component = max(0.0, 5.0 * (15 - min(age, 15)) / 15.0)

        if best_prof <= 0 and len(matched) < 2:
            continue

        score = min(
            100.0,
            profession_component
            + keyword_component
            + title_component
            + recency_component,
        )
        if score < 18.0:
            continue

        reasons: list[dict[str, Any]] = []
        if matching_professions:
            matching_professions.sort(key=lambda x: (-x[1], x[0]))
            pid = matching_professions[0][0]
            reasons.append(
                {
                    "type": "profession",
                    "label": profession_label.get(pid, pid),
                }
            )

        if matched:
            matched_sorted = sorted(
                matched,
                key=lambda t: (-strongest_cv_tokens.get(t, 0.0), t),
            )[:6]
            reasons.append({"type": "keywords", "terms": matched_sorted})

        if age <= 3:
            reasons.append({"type": "recent", "days": age})

        scored.append(
            (
                score,
                str(job.get("publication_date") or ""),
                str(job.get("global_id") or job.get("uuid") or ""),
                _public_job_match(job, score, reasons),
                job,
            )
        )

    scored.sort(key=lambda x: x[1], reverse=True)
    scored.sort(key=lambda x: x[0], reverse=True)
    matches = [row[3] for row in scored[:limit]]

    cv_tokens_all = set(_content_tokens(_analysis_text(text)))
    review_counts: Counter[str] = Counter()
    for _score, _date, _gid, _public, job in scored[:10]:
        requirement_text = " ".join(
            _flatten(job.get(field))
            for field in ("specialties", "profile", "education", "experience")
        )
        for token in set(_content_tokens(requirement_text)):
            if token not in cv_tokens_all and len(token) >= 4:
                review_counts[token] += 1

    review_terms = [
        token
        for token, count in review_counts.most_common(20)
        if count >= 2
    ][:8]

    return matches, review_terms


def analyze_cv(
    filename: str,
    data: bytes,
    index: dict[str, Any],
    taxonomy: Taxonomy,
    *,
    limit: int = 15,
    now: datetime | None = None,
) -> dict[str, Any]:
    limit = max(1, min(int(limit), 15))
    now = now or datetime.now(TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    else:
        now = now.astimezone(TZ)

    text, file_meta = extract_cv_text(filename, data)
    safe_text = _analysis_text(text)

    professions = _profession_candidates(safe_text, taxonomy, limit=5)
    matches, review_terms = _match_jobs(
        safe_text,
        index,
        professions,
        limit=limit,
        now=now,
    )

    keyword_counts = Counter(_content_tokens(safe_text))
    keywords = [
        token
        for token, _count in keyword_counts.most_common(30)
        if len(token) >= 3
    ][:15]

    top_prof_score = float(professions[0]["score"]) if professions else 0.0
    if len(safe_text) >= 700 and top_prof_score >= 85:
        confidence = "high"
    elif len(safe_text) >= 300 and (top_prof_score >= 70 or matches):
        confidence = "medium"
    else:
        confidence = "low"

    warnings = []
    if len(safe_text) < 300:
        warnings.append("CV_TEXT_SHORT")
    if not professions:
        warnings.append("NO_STRONG_PROFESSION_DETECTED")
    if not matches:
        warnings.append("NO_JOB_MATCHES")

    source_counts = Counter(match["source"] for match in matches)

    return {
        "version": "cv-matching-v1",
        "file": {
            "name": Path(filename or "cv").name,
            **file_meta,
        },
        "profile": {
            "analysis_confidence": confidence,
            "professions": professions,
            "keywords": keywords,
            "language_mentions": detect_language_mentions(safe_text),
            "explicit_experience_years": infer_explicit_experience_years(safe_text),
        },
        "matches": matches,
        "match_count": len(matches),
        "source_counts": dict(sorted(source_counts.items())),
        "suggestions": {
            "terms_to_review": review_terms,
            "note": (
                "Ces termes apparaissent dans plusieurs offres correspondantes "
                "mais pas dans le texte du CV. Ils ne signifient pas que la compétence manque."
            ),
        },
        "warnings": warnings,
        "privacy": {
            "stored": False,
            "raw_text_returned": False,
            "processing": "memory_only",
        },
    }
