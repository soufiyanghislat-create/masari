# Masari — Emploi-Public isolated source audit

Purpose: validate **emploi-public.ma only** before it is integrated into Masari.

This repository deliberately contains no database, no Redis, no AI model, no ANAPEC, no Rekrute, and no website. It has one job: prove that the Emploi-Public source can be crawled completely and parsed accurately.

## What it verifies

The crawler audits the three official recruitment scopes:

- `service_etat`
- `etab_publics`
- `collec`

It uses `procedure=avis` so discovery targets announcement cards, then opens each `/fr/concours/details/<uuid>` page.

The listing parser excludes the cross-scope **Dernière chance pour postuler** block from source-count reconciliation.

The final gate is strict:

- robots policy allows the crawl;
- official result counter is stable during the run;
- discovered detail URLs equal the official result count for every scope;
- no listing request remains failed;
- every discovered detail page parses successfully.

Business filtering is separate from source completeness. After the full source audit, `jobs.json` keeps only announcements published within 15 days whose application deadline has not passed.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
python audit.py
```

Expected final line:

```text
EMPLOI_PUBLIC_GATE=PASS
```

If it says `FAIL`, inspect `output/audit.json`. Do not integrate this source into Masari until the gate passes consistently.

## GitHub

Open **Actions → Verify Emploi-Public → Run workflow**. No secrets or database are required.

The workflow uploads `emploi-public-audit` containing:

- `audit.json`
- `jobs.json`
- `all_announcements.json`
- `rejected.json`
