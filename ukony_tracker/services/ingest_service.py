"""Single write path for adding úkony.

All payment-state derivation happens here so that ``stav_platby`` can never
disagree with ``zaplaceno_kc``.
"""
from datetime import date
from sqlite3 import Connection

from repositories import firmy_repo, ukony_repo
import config


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class IngestError(Exception):
    """Base class for ingest errors."""


class UnknownFirmaError(IngestError):
    """Raised when the firma cannot be resolved from the supplied identifiers."""


class ValidationError(IngestError):
    """Raised when the supplied data fails basic validation."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_firma(conn: Connection, firma_id: int | None, ico: str | None) -> int:
    if firma_id is not None:
        f = firmy_repo.get(conn, firma_id)
        if f:
            return f["id"]
        raise UnknownFirmaError(f"firma_id {firma_id} neexistuje")
    if ico:
        f = firmy_repo.get_by_ico(conn, ico)
        if f:
            return f["id"]
    raise UnknownFirmaError("firmu nelze určit (chybí firma_id i platné IČO)")


def derive_stav(celkem: float, zaplaceno_kc: float) -> str:
    """Derive payment state from the amount received. The single source of truth
    for ``stav_platby`` — used by the create path AND by edit/mark-paid routes."""
    if zaplaceno_kc <= 0:
        return config.STAV_NEZAPLACENO
    if zaplaceno_kc >= celkem:
        return config.STAV_ZAPLACENO
    return config.STAV_CASTECNE


# Backward-compatible alias (existing imports/tests may reference the old name).
_derive_stav = derive_stav


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def pridat_ukon(
    conn: Connection,
    *,
    firma_id: int | None = None,
    ico: str | None = None,
    datum: str,
    typ_kod: str,
    celkem: float,
    rz: str | None = None,
    vin: str | None = None,
    orv: str | None = None,
    poznamka: str | None = None,
    zaplaceno_kc: float = 0,
    zdroj: str = "rucni",
) -> int:
    """Validate, resolve firma, derive payment state and persist a new úkon.

    Returns the new úkon id.
    """
    # --- date validation ---
    try:
        date.fromisoformat(str(datum))
    except ValueError:
        raise ValidationError(f"neplatné datum: {datum!r}")

    # --- typ validation ---
    if not typ_kod:
        raise ValidationError("typ úkonu je povinný")

    # --- numeric validation ---
    try:
        celkem = float(celkem)
        zaplaceno_kc = float(zaplaceno_kc or 0)
    except (TypeError, ValueError):
        raise ValidationError("cena musí být číslo")

    if celkem < 0:
        raise ValidationError("cena nesmí být záporná")
    if not (0 <= zaplaceno_kc <= celkem):
        raise ValidationError("zaplaceno musí být mezi 0 a celkovou cenou")

    # --- normalize RZ / VIN / ORV: always stored uppercase ---
    if isinstance(rz, str):
        rz = rz.strip().upper() or None
    if isinstance(vin, str):
        vin = vin.strip().upper() or None
    if isinstance(orv, str):
        orv = orv.strip().upper() or None

    # --- firma resolution ---
    fid = _resolve_firma(conn, firma_id, ico)

    # --- derive payment state (single source of truth) ---
    stav = derive_stav(celkem, zaplaceno_kc)

    return ukony_repo.create(
        conn,
        firma_id=fid,
        datum=str(datum),
        typ_kod=typ_kod,
        celkem=celkem,
        rz=rz,
        vin=vin,
        orv=orv,
        poznamka=poznamka,
        stav_platby=stav,
        zaplaceno_kc=zaplaceno_kc,
        zdroj=zdroj,
    )
