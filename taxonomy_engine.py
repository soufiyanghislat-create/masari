from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent
DEFAULT_TAXONOMY_DIR = ROOT / "taxonomy"

# Only EXACT/STRONG matches are placed in the user-facing search index.
STRICT_SEARCH_MIN_SCORE = 92.0
RELATED_MIN_SCORE = 70.0
HCP_SEARCH_MIN_SCORE = 96.0

STOPWORDS = {
    "a", "au", "aux", "avec", "de", "des", "du", "d", "en", "et", "la", "le", "les",
    "l", "pour", "sur", "un", "une", "dans", "ou", "autre", "autres", "assimile", "assimiles",
    "n", "c", "niveau", "cadre", "cadres", "moyen", "moyens", "specialise", "specialises",
}

LISTING_ROLE_PATTERNS = (
    re.compile(r"\brecrutement d['’]?u?n?e?\s+(?P<role>.+?)(?:\s+annonce\b|$)", re.IGNORECASE),
    re.compile(r"\brecrutement de\s+(?P<role>.+?)(?:\s+annonce\b|$)", re.IGNORECASE),
)

ACADEMIC_ROLE_MARKERS = (
    "maître de conférences",
    "maitre de conferences",
    "أستاذ محاضر",    "maître de conférence",    "maitre de conference",
)
TRAINER_ROLE_MARKERS = (
    "formateur",
    "formatrice",
)


LISTING_ENTITY_BOUNDARIES = (
    "Ministère", "Ministere", "Agence", "Université", "Universite",
    "Office", "Société", "Societe", "Province", "Préfecture",
    "Prefecture", "Région", "Region", "Institut", "École", "Ecole",
    "Centre", "Fondation", "Chambre",
)


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold().replace("’", "'")
    value = re.sub(r"[^\w+#]+", " ", value, flags=re.UNICODE).replace("_", " ")
    return re.sub(r"\s+", " ", value).strip()


def tokens(value: str) -> list[str]:
    return [t for t in normalize(value).split() if len(t) > 1 and t not in STOPWORDS]


@dataclass(frozen=True)
class Profession:
    id: str
    label: str
    sector: str
    family: str
    hcp_codes: tuple[str, ...]
    aliases: tuple[str, ...]
    diplomas: tuple[str, ...]
    source: str

    @property
    def terms(self) -> tuple[str, ...]:
        return (self.label, *self.aliases)


class Taxonomy:
    def __init__(self, taxonomy_dir: Path | str = DEFAULT_TAXONOMY_DIR):
        self.taxonomy_dir = Path(taxonomy_dir)
        market_data = json.loads((self.taxonomy_dir / "market_professions.json").read_text(encoding="utf-8"))
        nap_data = json.loads((self.taxonomy_dir / "nap2014_professions.json").read_text(encoding="utf-8"))

        self.market: list[Profession] = []
        for item in market_data["professions"]:
            self.market.append(
                Profession(
                    id=item["id"],
                    label=item["label"],
                    sector=item["sector"],
                    family=item["family"],
                    hcp_codes=tuple(item.get("hcp_codes") or ()),
                    aliases=tuple(item.get("aliases") or ()),
                    diplomas=tuple(item.get("diplomas") or ()),
                    source="masari_market",
                )
            )

        self.hcp: list[Profession] = []
        for item in nap_data["records"]:
            self.hcp.append(
                Profession(
                    id=f"hcp.{item['code']}",
                    label=item["label"],
                    sector=item.get("major_group_label") or item.get("grand_group_label") or "HCP",
                    family=item.get("subgroup_label") or "",
                    hcp_codes=(item["code"],),
                    aliases=(),
                    diplomas=(),
                    source="hcp_nap2014",
                )
            )

        self.by_id = {p.id: p for p in [*self.market, *self.hcp]}
        rules_path = self.taxonomy_dir / 'context_rules.json'
        self.context_rules = []
        if rules_path.exists():
            rules_data = json.loads(rules_path.read_text(encoding='utf-8'))
            self.context_rules = list(rules_data.get('rules') or [])
        self._normalized_terms: dict[str, list[tuple[Profession, str]]] = {}
        for profession in [*self.market, *self.hcp]:
            for term in profession.terms:
                n = normalize(term)
                if n:
                    self._normalized_terms.setdefault(n, []).append((profession, term))

    def profession(self, profession_id: str) -> Profession | None:
        return self.by_id.get(profession_id)

    def diploma_professions(self, diploma: str) -> list[Profession]:
        q = normalize(diploma)
        out: list[Profession] = []
        for profession in self.market:
            if any(normalize(d) == q for d in profession.diplomas):
                out.append(profession)
        return sorted(out, key=lambda p: (p.sector, p.label))

    def autocomplete(self, query: str, limit: int = 10) -> list[dict]:
        """Return clean user-facing profession choices.

        Curated Moroccan market professions are authoritative in the default UX.
        HCP/NAP is exposed only when the curated market layer has no suggestion.
        """
        q = normalize(query)
        if not q:
            return []
        q_tokens = set(tokens(q))

        def collect(professions: Iterable[Profession]) -> list[dict]:
            best: dict[str, dict] = {}
            for profession in professions:
                best_term_score = -1.0
                best_term = profession.label
                for term in profession.terms:
                    nt = normalize(term)
                    if not nt:
                        continue
                    score = self._autocomplete_term_score(q, q_tokens, nt)
                    if score > best_term_score:
                        best_term_score = score
                        best_term = term
                if best_term_score < 0:
                    continue
                if "n c a" in normalize(profession.label):
                    best_term_score -= 90
                best[profession.id] = {
                    "profession_id": profession.id,
                    "label": profession.label,
                    "sector": profession.sector,
                    "family": profession.family,
                    "hcp_codes": list(profession.hcp_codes),
                    "source": profession.source,
                    "matched_term": best_term,
                    "score": round(best_term_score, 2),
                }
            return sorted(best.values(), key=lambda x: (-x["score"], x["label"].casefold()))

        market_rows = collect(self.market)
        if market_rows:
            return market_rows[:limit]
        return collect(self.hcp)[:limit]

    @staticmethod
    def _autocomplete_term_score(q: str, q_tokens: set[str], term: str) -> float:
        if q == term:
            return 1000
        if term.startswith(q):
            return 920
        if any(word.startswith(q) for word in term.split()):
            return 860
        if q in term:
            return 820
        t_tokens = set(tokens(term))
        if q_tokens and q_tokens.issubset(t_tokens):
            return 780 + min(len(q_tokens), 5)
        ratio = SequenceMatcher(None, q, term).ratio()
        if ratio >= 0.72:
            return 500 + ratio * 100
        return -1

    def exact_profession_ids(self, query: str) -> list[str]:
        q = normalize(query)
        matches = [p for p, _ in self._normalized_terms.get(q, [])]
        market = sorted({p.id for p in matches if p.source == "masari_market"})
        if market:
            return market
        return sorted({p.id for p in matches})

    def classify_job(self, job: dict, *, max_matches: int = 8) -> list[dict]:
        """Return only search-safe EXACT/STRONG profession matches.

        A generic job title is never allowed to become a more specific profession
        merely because some of its words are contained in a longer alias. Example:
        `Technicien en Bâtiment` must not become `Dessinateur architectural` from
        the alias `technicien dessin bâtiment`.
        """
        fields = self._job_fields(job)
        context_matches = self._context_rule_matches(job)
        market_matches = self._classify_against(
            self.market,
            fields,
            min_score=STRICT_SEARCH_MIN_SCORE,
            scoring="strict",
            searchable=True,
        )
        if context_matches or market_matches:
            merged = {}
            for row in [*context_matches, *market_matches]:
                current = merged.get(row["profession_id"])
                if current is None or row["score"] > current["score"]:
                    merged[row["profession_id"]] = row
            rows = sorted(merged.values(), key=lambda x: (-x["score"], x["label"].casefold()))
            rows = self._apply_authoritative_role_policy(job, rows)
            return rows[:max_matches]

        # HCP remains a long-tail fallback, but only for very strong phrase
        # evidence. Reverse/subset inference is intentionally forbidden here.
        return self._classify_against(
            self.hcp,
            fields,
            min_score=HCP_SEARCH_MIN_SCORE,
            scoring="strict",
            searchable=True,
        )[:max_matches]

    def related_job_matches(
        self,
        job: dict,
        *,
        exclude_ids: set[str] | None = None,
        max_matches: int = 8,
    ) -> list[dict]:
        """Return non-searchable RELATED hints for internal use only."""
        exclude_ids = exclude_ids or set()
        fields = self._job_fields(job)
        rows = self._classify_against(
            self.market,
            fields,
            min_score=RELATED_MIN_SCORE,
            max_score=STRICT_SEARCH_MIN_SCORE - 0.01,
            scoring="related",
            searchable=False,
        )
        return [row for row in rows if row["profession_id"] not in exclude_ids][:max_matches]

    def _apply_authoritative_role_policy(self, job: dict, rows: list[dict]) -> list[dict]:
        role_parts = [
            str(job.get("job_name") or ""),
            str(job.get("grade") or ""),
        ]
        listing_title = str(job.get("listing_title") or "")
        if listing_title:
            role_parts.append(self._extract_listing_role(listing_title))
        role_text = " ".join(role_parts)

        # Academic titles are authoritative occupations. Their specialty remains
        # a domain/discipline and must not become a second searchable profession.
        if any(self._context_contains(role_text, marker) for marker in ACADEMIC_ROLE_MARKERS):
            academic = [row for row in rows if row["profession_id"] == "edu.prof_universitaire"]
            if academic:
                return academic

        # A trainer remains a trainer. The subject after "Formateur en ..." is
        # the teaching domain and must not become the searchable occupation.
        if any(self._context_contains(role_text, marker) for marker in TRAINER_ROLE_MARKERS):
            trainer = [row for row in rows if row["profession_id"] == "edu.formateur_professionnel"]
            if trainer:
                return trainer

        # When the source gives an explicit job title and that title produces a
        # profession match, the title is authoritative. A specialty may describe
        # the domain of that job (e.g. Data Performance Analyst / data science),
        # not a second occupation. Conjunctive context rules are kept because
        # they intentionally combine role/grade + specialty.
        job_name = str(job.get("job_name") or "").strip()
        if job_name:
            title_rows = [
                row for row in rows
                if (row.get("evidence") or {}).get("field") == "job_name"
            ]
            context_rows = [
                row for row in rows
                if (row.get("evidence") or {}).get("field") == "context_rule"
            ]
            if title_rows:
                keep_ids = {
                    row["profession_id"]
                    for row in [*title_rows, *context_rows]
                }
                rows = [row for row in rows if row["profession_id"] in keep_ids]

        rows = self._apply_public_technician_semantics(job, rows)
        rows = self._prune_generic_title_matches(rows)
        return rows

    @staticmethod
    def _apply_public_technician_semantics(job: dict, rows: list[dict]) -> list[dict]:
        role_text = " ".join([
            str(job.get("job_name") or ""),
            str(job.get("grade") or ""),
        ])
        role_norm = normalize(role_text)

        precise_technician_ids = {
            "it.technicien_developpement_informatique",
            "agri.technicien_technico_commercial_horticole",
            "agri.technicien_hydraulique_irrigation",
            "agri.technicien_elevage_ruminants",
            "agri.technicien_gestion_entreprises_agricoles",
        }

        is_technician_role = "technicien" in role_norm

        if not is_technician_role:
            return [
                row for row in rows
                if row["profession_id"] not in precise_technician_ids
            ]

        present = {row["profession_id"] for row in rows}
        drop_ids: set[str] = set()

        if "it.technicien_developpement_informatique" in present:
            drop_ids.add("it.developpeur_logiciel")

            # Drop the broad parent only when it has no independent specialty
            # evidence. Example: a single "développement informatique" track
            # should not be indexed twice as both development-technician and
            # generic IT-technician. If another specialty such as "Gestion
            # informatique" or "Maintenance informatique et réseaux" exists,
            # the broad IT technician link remains legitimate.
            specialties = [
                normalize(str(value or ""))
                for value in (job.get("specialties") or [])
            ]

            def is_development_track(value: str) -> bool:
                return (
                    "developpement informatique" in value
                    or "developpement numerique" in value
                )

            independent_it_track = any(
                "informatique" in value and not is_development_track(value)
                for value in specialties
            )

            if not independent_it_track:
                drop_ids.add("it.technicien_informatique")

        if "agri.technicien_technico_commercial_horticole" in present:
            drop_ids.update({
                "sales.commercial",
                "agri.horticulture",
            })

        if "agri.technicien_gestion_entreprises_agricoles" in present:
            drop_ids.add("admin.gestionnaire")

        return [
            row for row in rows
            if row["profession_id"] not in drop_ids
        ]

    @staticmethod
    def _prune_generic_title_matches(rows: list[dict]) -> list[dict]:
        """Prefer a specific title match over a generic parent match.

        This only prunes searchable duplicates inside one advertisement. It does
        not collapse genuinely different specialties in public multi-specialty
        competitions.
        """
        drop_ids: set[str] = set()

        # Explicit semantic dominance for titles whose wording is not a simple
        # token subset of the generic profession.
        dominance = {
            "it.cybersecurite": {"it.responsable_si"},
            "it.base_donnees": {"it.administrateur_systemes"},
            "it.data_analyst": {"it.data_scientist"},
            "sales.communication": {"management.charge_projet"},
            "btp.chef_projet_genie_civil": {"management.charge_projet"},
            "admin.assistant_direction": {"admin.secretaire"},
            "sales.publicite": {"sales.marketing"},
            "sales.responsable_communication": {"sales.communication"},
            "industry.responsable_hse": {"industry.qualite"},
        }

        present = {row["profession_id"] for row in rows}
        for specific_id, generic_ids in dominance.items():
            if specific_id in present:
                drop_ids.update(generic_ids & present)

        # Generic phrase pruning: "chargé de projet" is dominated by
        # "chargé de projet génie civil" when both matched the same job title.
        for left in rows:
            left_ev = left.get("evidence") or {}
            if left_ev.get("field") != "job_name":
                continue
            left_tokens = set(tokens(str(left_ev.get("matched_term") or "")))
            if not left_tokens:
                continue

            for right in rows:
                if left is right:
                    continue
                right_ev = right.get("evidence") or {}
                if right_ev.get("field") != "job_name":
                    continue
                if normalize(str(left_ev.get("value") or "")) != normalize(str(right_ev.get("value") or "")):
                    continue

                right_tokens = set(tokens(str(right_ev.get("matched_term") or "")))
                if (
                    left_tokens
                    and right_tokens
                    and left_tokens < right_tokens
                    and float(right.get("score") or 0) >= float(left.get("score") or 0)
                ):
                    drop_ids.add(left["profession_id"])

        return [row for row in rows if row["profession_id"] not in drop_ids]

    @staticmethod
    def _context_contains(value: str, phrase: str) -> bool:
        nv = normalize(value)
        np = normalize(phrase)
        if not nv or not np:
            return False
        return bool(re.search(rf"(?:^| ){re.escape(np)}(?:$| )", nv))

    def _context_rule_matches(self, job: dict) -> list[dict]:
        if not self.context_rules:
            return []
        job_name = str(job.get("job_name") or "")
        grade = str(job.get("grade") or "")
        specialties = [str(x) for x in (job.get("specialties") or []) if x]
        def any_match(values: list[str], phrases: list[str]) -> bool:
            return any(self._context_contains(value, phrase) for value in values for phrase in phrases)
        rows = []
        for rule in self.context_rules:
            profession = self.by_id.get(rule.get("profession_id"))
            if profession is None or profession.source != "masari_market":
                continue
            if rule.get("job_name_any") and not any_match([job_name], list(rule["job_name_any"])):
                continue
            if rule.get("grade_any") and not any_match([grade], list(rule["grade_any"])):
                continue
            if rule.get("specialty_any") and not any_match(specialties, list(rule["specialty_any"])):
                continue
            score = float(rule.get("score") or 99.0)
            rows.append({"profession_id": profession.id, "label": profession.label, "sector": profession.sector, "family": profession.family, "hcp_codes": list(profession.hcp_codes), "source": profession.source, "score": round(min(score,100.0),2), "confidence": self._confidence(score), "searchable": True, "evidence": {"field": "context_rule", "value": rule.get("id") or "context", "matched_term": rule.get("id") or "context", "raw_score": round(score,2)}})
        rows.sort(key=lambda x: (-x["score"], x["label"].casefold()))
        return rows

    @staticmethod
    def _job_fields(job: dict) -> list[tuple[str, str, float]]:
        fields: list[tuple[str, str, float]] = []
        if job.get("job_name"):
            fields.append(("job_name", str(job["job_name"]), 1.0))
        for specialty in job.get("specialties") or []:
            if specialty:
                fields.append(("specialty", str(specialty), 1.0))
        if job.get("listing_title"):
            listing_title = str(job["listing_title"])
            role = Taxonomy._extract_listing_role(listing_title)
            if role:
                fields.append(("listing_role", role, 1.0))
            fields.append(("listing_title", listing_title, 0.90))
        # Grade is useful context, but is too generic to establish a searchable
        # profession by itself (Technicien 3ème grade, Administrateur, etc.).
        if job.get("grade"):
            fields.append(("grade", str(job["grade"]), 0.72))
        return fields

    @staticmethod
    def _extract_listing_role(listing_title: str) -> str:
        """Extract the advertised role from boilerplate-heavy Emploi-Public titles.

        Example:
        `Avis de concours de recrutement de Maître de conférences ...`
        -> `Maître de conférences ...`

        This keeps exact phrase evidence on the profession part of the title while
        avoiding false positives from the generic `avis/recrutement/concours`
        boilerplate that surrounds many public-sector listings.
        """
        text = re.sub(r"\s+", " ", str(listing_title or "")).strip()
        if not text:
            return ""
        for pattern in LISTING_ROLE_PATTERNS:
            match = pattern.search(text)
            if match:
                role = match.group("role").strip(" -–:()[]")
                role = Taxonomy._sanitize_listing_role(role)
                if normalize(role) and normalize(role) != normalize(text):
                    return role
        return ""

    @staticmethod
    def _sanitize_listing_role(role: str) -> str:
        value = re.sub(r"\s+", " ", str(role or "")).strip()
        if not value:
            return ""

        scale = re.search(r"\b(?:echelle|échelle)\s*\d+\b", value, re.IGNORECASE)
        if scale:
            return value[: scale.end()].strip(" -–:()[]")

        best = None
        for marker in LISTING_ENTITY_BOUNDARIES:
            m = re.search(rf"\s+{re.escape(marker)}\b", value, re.IGNORECASE)
            if m and (best is None or m.start() < best):
                best = m.start()
        if best is not None:
            value = value[:best]

        return value.strip(" -–:()[]")

    def _classify_against(
        self,
        professions: Iterable[Profession],
        fields: list[tuple[str, str, float]],
        *,
        min_score: float,
        scoring: str,
        searchable: bool,
        max_score: float | None = None,
    ) -> list[dict]:
        results: list[dict] = []
        scorer = self._strict_phrase_match_score if scoring == "strict" else self._related_phrase_match_score
        for profession in professions:
            best_score = 0.0
            best_evidence = None
            for term in profession.terms:
                for field_name, field_value, field_weight in fields:
                    raw = scorer(term, field_value)
                    score = raw * field_weight
                    if score > best_score:
                        best_score = score
                        best_evidence = {
                            "field": field_name,
                            "value": field_value,
                            "matched_term": term,
                            "raw_score": round(raw, 2),
                        }
            if best_score < min_score or not best_evidence:
                continue
            if max_score is not None and best_score > max_score:
                continue
            results.append(
                {
                    "profession_id": profession.id,
                    "label": profession.label,
                    "sector": profession.sector,
                    "family": profession.family,
                    "hcp_codes": list(profession.hcp_codes),
                    "source": profession.source,
                    "score": round(min(best_score, 100.0), 2),
                    "confidence": self._confidence(best_score),
                    "searchable": searchable,
                    "evidence": best_evidence,
                }
            )
        results.sort(key=lambda x: (-x["score"], 0 if x["source"] == "masari_market" else 1, x["label"].casefold()))
        return results

    @staticmethod
    def _confidence(score: float) -> str:
        if score >= 98.0:
            return "EXACT"
        if score >= STRICT_SEARCH_MIN_SCORE:
            return "STRONG"
        if score >= RELATED_MIN_SCORE:
            return "RELATED"
        return "NONE"

    @staticmethod
    def _strict_phrase_match_score(term: str, field: str) -> float:
        """High-precision scorer used for user-facing classification.

        It permits exact phrase evidence and forward containment only. Crucially,
        it never treats a shorter/generic field as proof of a longer/more specific
        profession alias.
        """
        nt = normalize(term)
        nf = normalize(field)
        if not nt or not nf:
            return 0.0
        if nt == nf:
            return 100.0

        tt = set(tokens(nt))
        ft = set(tokens(nf))
        if not tt or not ft:
            return 0.0

        # A multi-token profession term can safely appear inside a more verbose
        # official title/specialty, e.g. "développement informatique" inside a
        # longer specialty. One-word terms are intentionally exact-only.
        if len(tt) >= 2 and len(nt) >= 4 and re.search(rf"(?:^| ){re.escape(nt)}(?:$| )", nf):
            return 98.0
        if len(tt) >= 2 and tt.issubset(ft):
            return 94.0
        return 0.0

    @staticmethod
    def _related_phrase_match_score(term: str, field: str) -> float:
        """Conservative similarity scorer for non-searchable internal hints."""
        nt = normalize(term)
        nf = normalize(field)
        if not nt or not nf:
            return 0.0
        if nt == nf:
            return 100.0
        tt = set(tokens(nt))
        ft = set(tokens(nf))
        if not tt or not ft:
            return 0.0
        if len(tt) >= 2 and tt.issubset(ft):
            return 91.0
        # Reverse subset is exactly the dangerous case for search precision; it
        # is kept only as a RELATED hint and capped below the searchable gate.
        if len(ft) >= 2 and ft.issubset(tt):
            return 88.0
        inter = len(tt & ft)
        union = len(tt | ft)
        if inter >= 2 and union:
            jaccard = inter / union
            coverage = inter / min(len(tt), len(ft))
            if coverage >= 0.80 and jaccard >= 0.45:
                return 84.0
            if coverage >= 0.67 and jaccard >= 0.35:
                return 78.0
        return 0.0

    def autocomplete_payload(self) -> dict:
        options = []
        for profession in [*self.market, *self.hcp]:
            options.append(
                {
                    "profession_id": profession.id,
                    "label": profession.label,
                    "sector": profession.sector,
                    "family": profession.family,
                    "hcp_codes": list(profession.hcp_codes),
                    "aliases": list(profession.aliases),
                    "source": profession.source,
                }
            )
        return {
            "version": 2,
            "market_professions": len(self.market),
            "hcp_professions": len(self.hcp),
            "options": options,
        }
