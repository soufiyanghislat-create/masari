# Masari Taxonomy Precision v1.2

- User-facing classification accepts only EXACT/STRONG evidence (>= 92).
- Reverse-subset similarity is RELATED only and never searchable.
- Generic `Technicien en Bâtiment` no longer becomes `Dessinateur architectural`.
- Adds `Technicien bâtiment` and `Contrôleur de gestion` as separate market professions.
- Removes generic `recrutement` as an RH alias; uses job-specific recruitment aliases instead.
- Listing titles are supporting context only; generic concours/recrutement text cannot establish a profession.
- Search has a safety guard against RELATED/low-confidence matches.
- Adds a deterministic precision gate with positive and negative golden cases.
- Build audit now reports EXACT, STRONG, RELATED-only and searchable coverage separately.
