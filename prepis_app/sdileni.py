"""Sdílecí odkazy na vygenerované žádosti — funguj bez přihlášení.

David chtěl posílat hotovou žádost přes SMS/WhatsApp místo Gmailu, ale
`/download/<file>` je za přihlašovací branou (jinak by šlo z internetu
prohlížet cizí žádosti — obsahují jméno, adresu i rodné číslo). Token je
náhodný (`secrets.token_urlsafe`), ne sekvenční číslo: uhodnutelné číslo by
šlo zkoušet jedno po druhém a projít tak úplně všechny žádosti, co appka
kdy vygenerovala. Token navíc sám o sobě VYPRŠÍ (`TTL_DNI`), takže starý
přeposlaný link časem přestane fungovat.

Jen nové žádosti od teď — staré soubory token nemají a `/s/<token>` na ně
nikdy neukáže. Kdo potřebuje sdílet starou žádost, vygeneruje ji znovu.
"""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timedelta

# fcntl je jen POSIX (produkční Linux kontejner, kde gunicorn běží se 2
# workery — stejná pojistka jako ppd.py a tracker_push.py). Na Windows
# (jeden vývojář, žádná souběžnost) se degraduje na no-op zámek.
try:
    import fcntl  # type: ignore
    _HAVE_FCNTL = True
except ImportError:  # pragma: no cover - jen Windows dev
    _HAVE_FCNTL = False

TOKENS_NAME = "share_tokens.jsonl"
TTL_DNI = 30


def _cesta(data_dir: str) -> str:
    return os.path.join(data_dir, TOKENS_NAME)


def vytvor_token(data_dir: str, filename: str) -> str:
    """Nový náhodný token pro `filename` (v DATA_DIR/output). Nikdy nevyhazuje —
    sdílení je bonus, nesmí shodit samotné generování žádosti."""
    token = secrets.token_urlsafe(24)
    try:
        os.makedirs(data_dir, exist_ok=True)
        radek = {"token": token, "file": filename,
                  "vytvoreno": datetime.now().isoformat(timespec="seconds")}
        lock_fd = open(_cesta(data_dir) + ".lock", "a+")
        try:
            if _HAVE_FCNTL:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
            with open(_cesta(data_dir), "a", encoding="utf-8") as f:
                f.write(json.dumps(radek, ensure_ascii=False) + "\n")
        finally:
            if _HAVE_FCNTL:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
            lock_fd.close()
    except Exception:
        pass
    return token


def najdi_soubor(data_dir: str, token: str) -> str | None:
    """Jméno souboru pro platný (nevypršelý) token, jinak None.

    Řádky, které se nedají přečíst (poškozený zápis), se přeskočí — jeden
    špatný řádek nesmí shodit hledání ve všech ostatních."""
    path = _cesta(data_dir)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        for radek in f:
            try:
                d = json.loads(radek)
            except Exception:
                continue
            if d.get("token") != token:
                continue
            try:
                vytvoreno = datetime.fromisoformat(d["vytvoreno"])
            except Exception:
                return None
            if datetime.now() - vytvoreno > timedelta(days=TTL_DNI):
                return None  # vypršelo
            return d.get("file")
    return None
