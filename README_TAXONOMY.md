# Masari Morocco Jobs Taxonomy v1.2 — Precision

This layer is deterministic. It does not call AI at search time.

## Architecture

1. `audit.py` keeps the verified Emploi-Public crawler unchanged and writes `output/jobs.json`.
2. `build_search_index.py` classifies each fresh open announcement against the Moroccan profession taxonomy.
3. `taxonomy/nap2014_professions.json` is the official HCP NAP-2014 backbone.
4. `taxonomy/market_professions.json` adds user-facing job-market labels and aliases such as `Dessinateur architectural`.
5. `search.py` provides autocomplete, fixed diploma mappings and ranked search.

One Emploi-Public announcement always remains one announcement even when it has several specialties. It may simply receive several `profession_ids`.

## Examples

```bash
python search.py suggest "dess"
python search.py diploma "Technicien en dessin de bâtiment"
python search.py search "Dessinateur architectural" --limit 10
```

Expected first-class choice for `dessin`:

```text
Dessinateur architectural
```

The search index is pre-built after crawling. Users never trigger crawling, AI classification or network calls when typing in the search box.

## Sources

- HCP, Nomenclature Analytique des Professions 2014: https://www.hcp.ma/file/232108/
- HCP classifications and nomenclatures: https://www.hcp.ma/Classification-et-nomenclatures_a3178.html
- OFPPT BTP training material is used as a market-language reference for building/drawing terminology.


## Precision policy v1.2

User-facing search only accepts `EXACT` or `STRONG` profession evidence.
Potential/reverse-subset similarities are stored as `RELATED` hints for taxonomy
maintenance and never appear as the selected profession in search.

Example:

```text
Technicien en Bâtiment -> Technicien bâtiment
Technicien en Bâtiment -X-> Dessinateur architectural
Dessin de bâtiment -> Dessinateur architectural
```

`precision_audit.py` enforces fixed positive/negative golden cases and fails CI if
a RELATED/low-confidence match leaks into the searchable index.
