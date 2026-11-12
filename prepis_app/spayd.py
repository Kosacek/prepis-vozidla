"""SPAYD 1.0 (Czech "QR Platba") string builder — pure, no I/O.

Format: SPD*1.0*ACC:<IBAN>*AM:<amount>*CC:CZK*X-VS:<vs>*MSG:<msg>*RN:<name>
Text fields are reduced to safe ASCII (no diacritics, no '*' or '%') because
'*' is the field separator and '%' starts an escape sequence in SPAYD.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal

MAX_MSG = 60
MAX_RN = 35
MAX_VS = 10
_IBAN = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$")


def normalize_iban(iban: str) -> str:
    """Upper-case IBAN without spaces; ValueError when it is not IBAN-shaped."""
    clean = re.sub(r"\s", "", str(iban or "")).upper()
    if not _IBAN.match(clean):
        raise ValueError("IBAN není ve správném tvaru.")
    return clean


def sanitize_text(text: str, max_len: int) -> str:
    """Strip diacritics, '*' and '%' and non-ASCII leftovers; cap the length."""
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.replace("*", " ").replace("%", " ")
    return " ".join(ascii_text.split())[:max_len].strip()


def variable_symbol(value) -> str:
    """Digits only, at most 10 (the Czech VS limit)."""
    return re.sub(r"\D", "", str(value or ""))[:MAX_VS]


def format_amount(amount) -> str:
    """Amount with exactly two decimals ('2600' -> '2600.00')."""
    value = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if value <= 0:
        raise ValueError("Částka musí být kladná.")
    return f"{value:.2f}"


def build_spayd(iban: str, amount, vs, message: str = "", recipient: str = "") -> str:
    """Assemble the SPAYD payment string."""
    parts = ["SPD", "1.0", f"ACC:{normalize_iban(iban)}", f"AM:{format_amount(amount)}", "CC:CZK"]
    vs_clean = variable_symbol(vs)
    if vs_clean:
        parts.append(f"X-VS:{vs_clean}")
    msg = sanitize_text(message, MAX_MSG)
    if msg:
        parts.append(f"MSG:{msg}")
    rn = sanitize_text(recipient, MAX_RN)
    if rn:
        parts.append(f"RN:{rn}")
    return "*".join(parts)
