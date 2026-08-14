from __future__ import annotations

from urllib.parse import urlencode

POSTULATION_URL = "https://www.anapec.org/sigec-app-rv/fr/chercheurs/postulation"


def build_application(reference: str) -> dict:
    ref = (reference or "").strip()
    if not ref:
        raise ValueError("ANAPEC application reference is required")
    return {
        "mode": "official_anapec",
        "reference": ref,
        "method": "GET",
        "url": f"{POSTULATION_URL}?{urlencode({'ref': ref})}",
        "official": True,
    }
