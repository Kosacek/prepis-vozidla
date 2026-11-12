"""MONETA Money Bank AISP client — the ONLY file that knows the bank's JSON.

Nothing here is confirmed against the official spec yet (ČOBS v7 /
Berlin-Group style assumed). When real JSON shows up, adjust
`_parse_transaction` (field paths) and `_extract_items` / `_next_request`
(response envelope); the rest of the app only sees `Platba`.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

import requests

import config

TIMEOUT = (5, 20)  # connect, read seconds
MAX_PAGES = 20
PAGE_SIZE = 100


class MonetaError(Exception):
    """Any failure talking to the bank (network, 5xx, unexpected body)."""


class MonetaAuthError(MonetaError):
    """401/403 — the token expired or was revoked."""


@dataclass(frozen=True)
class Platba:
    id: str
    datum: str  # ISO booking date
    castka: Decimal
    mena: str
    vs: str  # digits only, leading zeros stripped ("" = none)
    zprava: str
    protiucet: str


def enabled() -> bool:
    return bool(config.MONETA_API_TOKEN)


# ---------------------------------------------------------------- parsing

def _dig(obj, *path):
    for key in path:
        if isinstance(obj, dict):
            obj = obj.get(key)
        else:
            return None
    return obj


def _first(raw, *paths):
    for path in paths:
        v = _dig(raw, *path)
        if v not in (None, "", [], {}):
            return v
    return None


def _text(v) -> str:
    if v is None or isinstance(v, dict):
        return ""
    if isinstance(v, (list, tuple)):
        return " ".join(t for t in (_text(x) for x in v) if t)
    return str(v).strip()


def _amount(raw: dict):
    """(Decimal, currency) from {amount:{value,currency}} / Berlin-Group
    {transactionAmount:{amount,currency}} / flat fields; None if unreadable."""
    box = _first(raw, ("amount",), ("transactionAmount",))
    if isinstance(box, dict):
        value = _first(box, ("value",), ("amount",))
        cur = box.get("currency")
    else:
        value, cur = box, raw.get("currency")
    try:
        return Decimal(str(value).replace(",", ".").replace(" ", "")), _text(cur).upper()
    except (InvalidOperation, ValueError):
        return None


def _iso_day(v) -> str | None:
    if isinstance(v, dict):
        v = _first(v, ("date",), ("dateTime",))
    try:
        return date.fromisoformat(_text(v)[:10]).isoformat()
    except ValueError:
        return None


def _vs(raw: dict) -> str:
    v = _first(
        raw,
        ("variableSymbol",), ("references", "variableSymbol"),
        ("remittanceInformation", "structured", "variableSymbol"),
        ("remittanceInformation", "structured", "reference"),
        ("remittanceInformation", "structured", "creditorReferenceInformation", "reference"),
        ("remittanceInformation", "variableSymbol"),
        ("creditorReference",), ("endToEndId",),
        ("references", "endToEndIdentification"),
    )
    digits = "".join(ch for ch in _text(v) if ch.isdigit())
    return digits.lstrip("0")


def _message(raw: dict) -> str:
    return _text(_first(
        raw,
        ("remittanceInformation", "unstructured"),
        ("remittanceInformationUnstructured",), ("remittanceInformation",),
        ("messageForRecipient",), ("message",), ("additionalTransactionInformation",),
    ))


def _counterparty(raw: dict) -> str:
    acct = _text(_first(
        raw,
        ("debtorAccount", "iban"), ("debtorAccount", "number"), ("debtorAccount", "bban"),
        ("counterParty", "accountNumber"), ("counterparty", "accountNumber"),
        ("counterPartyAccount",),
        ("relatedParties", "debtorAccount", "identification", "other", "identification"),
        ("relatedParties", "debtorAccount", "identification", "iban"),
    ))
    name = _text(_first(raw, ("debtorName",), ("debtor", "name"), ("counterParty", "name"),
                        ("relatedParties", "debtor", "name")))
    return " ".join(p for p in (name, acct) if p)


def _parse_transaction(raw: dict) -> Platba | None:
    """One raw transaction -> Platba, or None unless it is a CZK credit."""
    if not isinstance(raw, dict):
        return None
    amt = _amount(raw)
    if amt is None:
        return None
    value, mena = amt
    indicator = _text(_first(raw, ("creditDebitIndicator",), ("creditDebit",))).upper()
    if indicator:
        if not indicator.startswith(("CRDT", "CREDIT")):
            return None
    elif value <= 0:  # no indicator (Berlin style): the sign decides
        return None
    value = abs(value)
    if value == 0 or (mena or "CZK") != "CZK":
        return None
    datum = _iso_day(_first(raw, ("bookingDate",), ("bookingDateTime",), ("valueDate",),
                            ("transactionDate",)))
    if datum is None:
        return None
    if raw.get("reversalIndicator") is True or _text(raw.get("status") or "BOOK").upper() != "BOOK":
        return None
    # MONETA (ČOBS v7, verified 2026-11-12) nests the details here; VS comes as
    # "VS:0000898843" in remittanceInformation.structured.creditorReferenceInformation.reference.
    details = _dig(raw, "entryDetails", "transactionDetails")
    flat = {**raw, **details} if isinstance(details, dict) else raw
    vs, zprava, protiucet = _vs(flat), _message(flat), _counterparty(flat)
    tx_id = _text(_first(raw, ("entryReference",), ("transactionId",), ("id",), ("entryId",)))
    if not tx_id:  # no id in the payload: stable fingerprint
        tx_id = "h:" + hashlib.sha1(f"{datum}|{value}|{vs}|{protiucet}|{zprava}".encode()).hexdigest()[:20]
    return Platba(tx_id, datum, value, "CZK", vs, zprava, protiucet)


# --------------------------------------------------------------- transport

def _extract_items(body) -> list:
    if isinstance(body, list):
        return body
    if not isinstance(body, dict):
        return []
    for key in ("transactions", "items", "content", "data"):
        v = body.get(key)
        if isinstance(v, list):
            return v
        if isinstance(v, dict) and isinstance(v.get("booked"), list):  # Berlin
            return v["booked"]
    return []


def _next_request(body, url: str, params: dict):
    """(url, params) of the next page, or None."""
    if not isinstance(body, dict):
        return None
    link = _first(body, ("_links", "next", "href"), ("_links", "next"), ("links", "next"),
                  ("transactions", "_links", "next", "href"), ("nextPage",), ("next",))
    if isinstance(link, str) and link.startswith(("http://", "https://", "/")):
        return (link if link.startswith("http") else config.MONETA_API_BASE + link), {}
    try:
        number, count = int(body.get("pageNumber")), int(body.get("pageCount"))
    except (TypeError, ValueError):
        return None
    return (url, {**params, "page": number + 1}) if number + 1 < count else None


class MonetaClient:
    def __init__(self, token=None, base=None, account_id=None, session=None):
        self.token = token or config.MONETA_API_TOKEN
        self.base = (base or config.MONETA_API_BASE).rstrip("/")
        self.account_id = account_id or config.MONETA_ACCOUNT_ID
        self.session = session or requests.Session()

    def _get(self, url: str, params: dict | None = None):
        try:
            resp = self.session.get(
                url, params=params or None, timeout=TIMEOUT,
                headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"})
        except requests.RequestException as e:
            raise MonetaError(f"Banka nedostupná: {type(e).__name__}") from e
        if resp.status_code in (401, 403):
            raise MonetaAuthError(f"HTTP {resp.status_code}")
        if resp.status_code != 200:
            raise MonetaError(f"HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError as e:
            raise MonetaError("Banka vrátila nečitelnou odpověď") from e

    def _account(self) -> str:
        if self.account_id:
            return self.account_id
        body = self._get(f"{self.base}/api/v4/vip/aisp/my/accounts")
        accounts = body.get("accounts") if isinstance(body, dict) else body
        first = accounts[0] if isinstance(accounts, list) and accounts else None
        acc = _text(_first(first, ("id",), ("accountId",), ("resourceId",))) if isinstance(first, dict) else ""
        if not acc:
            raise MonetaError("Účet nenalezen")
        self.account_id = acc
        return acc

    def fetch_incoming(self, since_date) -> list[Platba]:
        url = f"{self.base}/api/v4/vip/aisp/my/accounts/{self._account()}/transactions"
        params = {"fromDate": _iso_day(str(since_date)) or str(since_date),
                  "toDate": date.today().isoformat(), "size": PAGE_SIZE}
        out: list[Platba] = []
        nxt = (url, params)
        for _ in range(MAX_PAGES):
            body = self._get(*nxt)
            out.extend(p for p in map(_parse_transaction, _extract_items(body)) if p)
            nxt = _next_request(body, *nxt)
            if nxt is None:
                break
        return out


def fetch_incoming(since_date) -> list[Platba]:
    return MonetaClient().fetch_incoming(since_date)
