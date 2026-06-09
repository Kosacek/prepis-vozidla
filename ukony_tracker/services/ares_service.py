"""ARES (Czech business register) lookup service."""
import requests

import config


def lookup_ico(ico: str | None) -> dict | None:
    """Fetch company data from ARES for the given IČO.

    Returns a dict with keys ``nazev``, ``adresa``, ``psc`` on success,
    or ``None`` if the IČO is not found or any network error occurs.

    The IČO is always zero-padded to 8 digits before the request is made.
    """
    digits = "".join(c for c in (ico or "") if c.isdigit())[:8]
    if not digits:
        return None
    ico_padded = digits.zfill(8)  # ARES requires the full 8-digit, zero-padded IČO

    try:
        r = requests.get(
            config.ARES_URL.format(ico=ico_padded),
            timeout=8,
            headers={"Accept": "application/json"},
        )
    except requests.RequestException:
        return None

    if r.status_code != 200:
        return None

    d = r.json()
    s = d.get("sidlo") or {}

    # Build a human-readable address from sidlo components
    ulice = s.get("nazevUlice") or s.get("nazevObce", "")
    cd = s.get("cisloDomovni")
    co = s.get("cisloOrientacni")
    cislo = f"{cd}/{co}" if cd and co else (str(cd) if cd else "")
    adresa = " ".join(p for p in [ulice, cislo] if p).strip()

    # Append city name if not already present
    nazev_obce = s.get("nazevObce")
    if nazev_obce and nazev_obce not in adresa:
        adresa = f"{adresa}, {nazev_obce}".strip(", ")

    return {
        "nazev": d.get("obchodniJmeno", ""),
        "adresa": adresa,
        "psc": str(s.get("psc", "") or ""),
    }
