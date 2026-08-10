from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from taxonomy_engine import Taxonomy

TZ = ZoneInfo("Africa/Casablanca")


def _days_since(iso_value: str, now: datetime) -> int:
    try:
        value = datetime.fromisoformat(iso_value).replace(tzinfo=TZ)
        return max((now.date() - value.date()).days, 0)
    except Exception:
        return 99


def _days_until(iso_value: str, now: datetime) -> int:
    try:
        value = datetime.fromisoformat(iso_value).replace(tzinfo=TZ)
        return max((value.date() - now.date()).days, 0)
    except Exception:
        return 0


def rank_job(job: dict, profession_id: str, now: datetime | None = None) -> tuple[float, dict | None]:
    now = now or datetime.now(TZ)
    match = next((m for m in job.get("profession_matches") or [] if m.get("profession_id") == profession_id), None)
    if not match:
        return -1.0, None
    # Precision safety net: RELATED/internal hints must never become user-facing
    # search results, even if a malformed/stale index accidentally contains one.
    if match.get("searchable") is False:
        return -1.0, None
    if match.get("confidence") == "RELATED":
        return -1.0, None
    if match.get("confidence") is None and float(match.get("score") or 0) < 92.0:
        return -1.0, None
    match_component = float(match.get("score") or 0) * 0.82
    age = _days_since(str(job.get("publication_date") or ""), now)
    freshness_component = max(10.0 - min(age, 15) * (10.0 / 15.0), 0.0)
    days_left = _days_until(str(job.get("deadline") or ""), now)
    deadline_component = min(days_left, 10) * 0.3
    source_component = 5.0  # verified official source
    final = min(match_component + freshness_component + deadline_component + source_component, 100.0)
    return round(final, 2), match


def search_by_profession(index: dict, profession_id: str, limit: int = 20) -> list[dict]:
    now = datetime.now(TZ)
    rows = []
    for job in index.get("jobs") or []:
        score, match = rank_job(job, profession_id, now)
        if score < 0:
            continue
        rows.append(
            {
                "score": score,
                "profession_match": match,
                "uuid": job.get("uuid"),
                "title": job.get("search_title") or job.get("listing_title"),
                "administration": job.get("administration"),
                "publication_date": job.get("publication_date"),
                "deadline": job.get("deadline"),
                "positions": job.get("positions"),
                "url": job.get("url"),
            }
        )
    rows.sort(key=lambda x: (-x["score"], str(x.get("publication_date") or ""), str(x.get("uuid") or "")), reverse=False)
    # The primary score is already descending via negative score; for ties we
    # want newer publication dates first, so do a stable second sort.
    rows.sort(key=lambda x: str(x.get("publication_date") or ""), reverse=True)
    rows.sort(key=lambda x: x["score"], reverse=True)
    return rows[:limit]


def main() -> int:
    ap = argparse.ArgumentParser(description="Masari deterministic profession search")
    sub = ap.add_subparsers(dest="cmd", required=True)

    suggest = sub.add_parser("suggest", help="Autocomplete a profession")
    suggest.add_argument("query")
    suggest.add_argument("--limit", type=int, default=10)

    diploma = sub.add_parser("diploma", help="List fixed professions for a diploma")
    diploma.add_argument("query")

    search = sub.add_parser("search", help="Search ranked jobs by profession label/alias or ID")
    search.add_argument("query")
    search.add_argument("--index", default="output/search_index.json")
    search.add_argument("--limit", type=int, default=20)

    args = ap.parse_args()
    taxonomy = Taxonomy()

    if args.cmd == "suggest":
        print(json.dumps(taxonomy.autocomplete(args.query, args.limit), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "diploma":
        rows = [
            {"profession_id": p.id, "label": p.label, "sector": p.sector, "family": p.family}
            for p in taxonomy.diploma_professions(args.query)
        ]
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    index_path = Path(args.index)
    if not index_path.exists():
        raise SystemExit(f"Search index not found: {index_path}. Run build_search_index.py first.")
    index = json.loads(index_path.read_text(encoding="utf-8"))

    if args.query in taxonomy.by_id:
        profession_id = args.query
    else:
        exact = taxonomy.exact_profession_ids(args.query)
        if len(exact) == 1:
            profession_id = exact[0]
        else:
            suggestions = taxonomy.autocomplete(args.query, limit=8)
            print(json.dumps({"selection_required": True, "suggestions": suggestions}, ensure_ascii=False, indent=2))
            return 3

    profession = taxonomy.profession(profession_id)
    results = search_by_profession(index, profession_id, args.limit)
    print(
        json.dumps(
            {
                "profession": {
                    "profession_id": profession_id,
                    "label": profession.label if profession else profession_id,
                    "sector": profession.sector if profession else "",
                    "family": profession.family if profession else "",
                },
                "count": len(results),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
