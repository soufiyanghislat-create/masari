from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent
DEFAULT_TAXONOMY_DIR = ROOT / "taxonomy"

STOPWORDS = {
    "a", "au", "aux", "avec", "de", "des", "du", "d", "en", "et", "la", "le", "les",
    "l", "pour", "sur", "un", "une", "dans", "ou", "autre", "autres", "assimile", "assimiles",
    "n", "c", "niveau", "cadre", "cadres", "moyen", "moyens", "specialise", "specialises",
}


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold().replace("’", "'")
    value = re.sub(r"[^a-z0-9+#]+", " ", value)
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
        """Return user-facing profession choices.

        Curated Moroccan market professions are authoritative for the default
        UX. HCP/NAP remains a long-tail fallback, but is only exposed when the
        curated market taxonomy has no match at all. This prevents generic
        queries such as "dessin" from mixing architectural job choices with
        unrelated administrative labels such as caricaturists or drawing
        teachers.
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
        fields = self._job_fields(job)
        market_matches = self._classify_against(self.market, fields, min_score=70.0)
        if market_matches:
            return market_matches[:max_matches]
        # HCP fallback keeps long-tail Moroccan occupations searchable without
        # inventing a market label when no curated Masari profession exists yet.
        return self._classify_against(self.hcp, fields, min_score=82.0)[:max_matches]

    @staticmethod
    def _job_fields(job: dict) -> list[tuple[str, str, float]]:
        fields: list[tuple[str, str, float]] = []
        if job.get("job_name"):
            fields.append(("job_name", str(job["job_name"]), 1.0))
        for specialty in job.get("specialties") or []:
            if specialty:
                fields.append(("specialty", str(specialty), 1.0))
        if job.get("listing_title"):
            fields.append(("listing_title", str(job["listing_title"]), 0.95))
        if job.get("grade"):
            fields.append(("grade", str(job["grade"]), 0.72))
        return fields

    def _classify_against(
        self,
        professions: Iterable[Profession],
        fields: list[tuple[str, str, float]],
        *,
        min_score: float,
    ) -> list[dict]:
        results: list[dict] = []
        for profession in professions:
            best_score = 0.0
            best_evidence = None
            for term in profession.terms:
                for field_name, field_value, field_weight in fields:
                    raw = self._phrase_match_score(term, field_value)
                    score = raw * field_weight
                    if score > best_score:
                        best_score = score
                        best_evidence = {
                            "field": field_name,
                            "value": field_value,
                            "matched_term": term,
                            "raw_score": round(raw, 2),
                        }
            if best_score >= min_score and best_evidence:
                results.append(
                    {
                        "profession_id": profession.id,
                        "label": profession.label,
                        "sector": profession.sector,
                        "family": profession.family,
                        "hcp_codes": list(profession.hcp_codes),
                        "source": profession.source,
                        "score": round(min(best_score, 100.0), 2),
                        "evidence": best_evidence,
                    }
                )
        results.sort(key=lambda x: (-x["score"], 0 if x["source"] == "masari_market" else 1, x["label"].casefold()))
        return results

    @staticmethod
    def _phrase_match_score(term: str, field: str) -> float:
        nt = normalize(term)
        nf = normalize(field)
        if not nt or not nf:
            return 0.0
        if nt == nf:
            return 100.0
        # Avoid using tiny abbreviations as substring triggers. They remain
        # available for autocomplete but require an exact field match here.
        if len(nt) >= 4 and re.search(rf"(?:^| ){re.escape(nt)}(?:$| )", nf):
            return 96.0
        tt = set(tokens(nt))
        ft = set(tokens(nf))
        if len(tt) >= 2 and tt.issubset(ft):
            return 91.0
        # A concise specialty such as "génie civil" can legitimately identify
        # an official HCP label that is much longer. Require at least two useful
        # tokens to avoid generic one-word matches such as "gestion".
        if len(ft) >= 2 and ft.issubset(tt):
            return 88.0
        if tt and ft:
            inter = len(tt & ft)
            union = len(tt | ft)
            jaccard = inter / union
            coverage = inter / min(len(tt), len(ft))
            if inter >= 2 and coverage >= 0.80 and jaccard >= 0.45:
                return 84.0
            if inter >= 2 and coverage >= 0.67 and jaccard >= 0.35:
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
            "version": 1,
            "market_professions": len(self.market),
            "hcp_professions": len(self.hcp),
            "options": options,
        }
