# Masari Daily Sync v1

Policy:
- Public search always enforces publication age <= 15 days and an unexpired deadline.
- Missing/invalid dates are hidden.
- 05:30 Africa/Casablanca: full authoritative refresh.
- 10:30, 14:30, 18:30: quick reconciliation and refetch of the active/recent window.
- Refresh is atomic: failure never replaces the currently served index.
- Historical source records are retained internally; stale jobs simply disappear from search.

First local run:

```bash
python3 maintenance/refresh.py --mode full
```

On success the website should read:

`runtime/emploi_public/current/search_index.json`

Do not install the scheduler until the first full local run and browser test pass.

Runtime refresh uses the live build/classifiability gate plus a non-mutating runtime validation gate. The full GitHub semantic CI remains the release gate.
