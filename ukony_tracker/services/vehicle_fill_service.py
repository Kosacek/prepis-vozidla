"""Shared fill-only operation for the integration API and ORV scans."""
import re
from contextlib import contextmanager
from uuid import uuid4

from repositories import ukony_repo


class FillError(ValueError):
    def __init__(self, status, error, **details):
        super().__init__(error)
        self.status = status
        self.data = {"error": error, **details}


def normalize(value):
    # Preserve the public integration API's normalization.
    return value.strip().upper().replace(" ", "").replace("-", "")


@contextmanager
def transaction(conn):
    """Lock before reading; a nested operation must not commit its caller."""
    nested = conn.in_transaction
    name = "fill_" + uuid4().hex
    conn.execute(f"SAVEPOINT {name}" if nested else "BEGIN IMMEDIATE")
    try:
        yield
        if nested:
            conn.execute(f"RELEASE {name}")
        else:
            conn.commit()
    except Exception:
        if nested:
            conn.execute(f"ROLLBACK TO {name}")
            conn.execute(f"RELEASE {name}")
        else:
            conn.rollback()
        raise


def doplnit(conn, uid, payload):
    if not isinstance(payload, dict) or not any(k in payload for k in ("rz", "orv")):
        raise FillError(400, "Zadejte RZ nebo ORV.")
    values = {}
    for field, pattern in (("rz", r"[A-Z0-9]{5,8}"), ("orv", r"[A-Z]{3}[0-9]{6}")):
        if field not in payload:
            continue
        value = payload[field]
        if not isinstance(value, str) or not re.fullmatch(pattern, normalize(value)):
            raise FillError(400, f"Neplatná hodnota {field.upper()}.")
        values[field] = normalize(value)
    with transaction(conn):
        ukon = ukony_repo.get(conn, uid)
        if ukon is None:
            raise FillError(404, "Úkon nenalezen.")
        changes = {}
        for field, value in values.items():
            existing = ukon[field]
            if not existing or not existing.strip():
                changes[field] = value
            elif normalize(existing) != value:
                error = "RZ už je vyplněná jinak." if field == "rz" else "ORV už je vyplněné jinak."
                raise FillError(409, error, pole=field, stavajici=existing)
        if changes:
            ukony_repo.update(conn, uid, commit=False, **changes)
        return {"id": uid, "rz": changes.get("rz", ukon["rz"]),
                "orv": changes.get("orv", ukon["orv"]), "zmeneno": list(changes)}
