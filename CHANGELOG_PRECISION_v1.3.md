# Masari Taxonomy Precision v1.3

- Keeps the EXACT/STRONG-only search policy unchanged.
- Extracts the advertised role from Emploi-Public listing-title boilerplate before scoring.
- Adds conservative market coverage for `Maître de conférences`, OFPPT `Formateur en ...` roles, content roles, topography, HSE, customs, portfolio/risk/control jobs, and school transport drivers.
- Preserves the no-go rule for generic titles such as `Cadres`, `Agents`, `Administrateur` and bare `Technicien de ... grade` postings without a defining specialty.
- Adds regression tests for listing-title extraction and false-positive prevention (`RH`, generic grades, network-vs-formateur, nurse-vs-doctor).
