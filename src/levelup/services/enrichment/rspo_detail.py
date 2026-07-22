"""Fetches a school's detail record from RSPO's own live API.

Confirmed directly (not assumed from the other tool's README): the bulk
SIO/RSPO CSV export has no director field, and rspo.gov.pl's HTML search
frontend is geo-blocked to Polish IP addresses -- but this specific JSON
API path (the one the rspo.gov.pl frontend itself calls) is reachable from
here, fast (~50ms/request), and not rate-limited at a modest concurrency.
It returns `directorName`/`directorSurname` directly from the official
registry -- authoritative, no regex/table-format ambiguity at all -- plus
a `languageList` (confirms which languages the school actually teaches)
and `dataTransmittingAuthority` (the gmina/powiat operating authority,
a fallback contact source when the school itself has no usable website).

This is best-effort exactly like the website scraper: a missing or
unreachable detail record leaves fields None, never guessed.
"""

from __future__ import annotations

import time

import requests

RSPO_API_BASE = "https://rspo.gov.pl/api"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "application/json",
}
TIMEOUT_SECONDS = 20
MAX_ATTEMPTS = 3


def fetch_rspo_detail(rspo_id: str | int) -> dict | None:
    """Returns the parsed detail dict, or None if unreachable/not found
    (RSPO returns HTTP 204 for an unassigned id, not an error status).

    RSPO is this app's authoritative floor -- it has the director for most
    schools and an email for nearly all of them, so a transient blip here
    silently loses the one contact source that always works. A batch
    enrichment used to drop that data on a single timeout/429; it now
    retries with a short backoff. A 204 (id genuinely unassigned) is
    definitive and never retried."""
    url = f"{RSPO_API_BASE}/Institution/{rspo_id}"
    for attempt in range(MAX_ATTEMPTS):
        last = attempt == MAX_ATTEMPTS - 1
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT_SECONDS)
        except requests.RequestException:
            if last:
                return None
            time.sleep(0.6 * (attempt + 1))
            continue
        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError:
                return None
        if resp.status_code == 204:
            return None  # unassigned id -- definitive, don't retry
        # 429/5xx/other transient -- back off and retry
        if last:
            return None
        time.sleep(0.6 * (attempt + 1))
    return None


def _full_name(first: str | None, last: str | None) -> str | None:
    parts = [p.strip().title() for p in (first, last) if p and p.strip()]
    return " ".join(parts) if parts else None


def parse_director_and_contacts(detail: dict) -> dict:
    """Extracts the fields we actually use out of the much larger RSPO
    detail payload. Title-cased since RSPO stores names in ALL CAPS
    ("JÓZEF", "GĄBKA") -- title() handles Polish diacritics correctly
    since they're just letters to Python's str.title()."""
    director_name = _full_name(detail.get("directorName"), detail.get("directorSurname"))

    languages = [lang.get("name") for lang in (detail.get("languageList") or []) if lang.get("name")]
    teaches_english = any("angielsk" in (lang or "").lower() for lang in languages)

    authority = detail.get("dataTransmittingAuthority") or {}
    authority_name = authority.get("name")
    authority_type = (authority.get("institutionType") or {}).get("name")

    geotag = detail.get("hqAddressGeotag") or {}

    # RSPO's own "specificity" field is the government's own official
    # classification of a DEDICATED special-education institution --
    # authoritative, not a name-pattern guess. Confirmed directly: several
    # schools whose own name gives no hint at all in the usual places
    # (e.g. "PUBLICZNA SZKOŁA PODSTAWOWA PRZY ZAKŁADACH OPIEKI
    # ZDROWOTNEJ" -- no "specjalna", no disability keyword anywhere) still
    # carry `{"id": 1, "name": "specjalna"}` here, while an ordinary
    # school's is `{"id": 100, "name": "brak specyfiki"}` ("no
    # specificity"). Checked by name (not the id) since that's what
    # RSPO's own API actually documents as the meaningful value.
    specificity = (detail.get("specificity") or {}).get("name")
    is_dedicated_special_needs = (specificity or "").strip().lower() == "specjalna"

    return {
        "director_name": director_name,
        "teaches_english": teaches_english,
        "languages": languages,
        "email": detail.get("email") or None,
        "phone": detail.get("telephone") or None,
        "website": detail.get("website") or None,
        "authority_name": authority_name,
        "authority_type": authority_type,
        "is_dedicated_special_needs": is_dedicated_special_needs,
        "latitude": geotag.get("latitude"),
        "longitude": geotag.get("longitude"),
    }
