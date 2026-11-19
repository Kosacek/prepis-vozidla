from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from datetime import datetime
from functools import partial

from ppd import _HAVE_FCNTL

if _HAVE_FCNTL:
    import fcntl

LOG_NAME = "doklady_storno.jsonl"
_zamek_procesu = threading.Lock()


def stav(data_dir: str) -> dict[tuple[str, int], dict]:
    """Poslední platná událost pro každý doklad."""
    vysledek = {}
    try:
        soubor = open(os.path.join(data_dir, LOG_NAME), "rb")
    except FileNotFoundError:
        return vysledek
    with soubor:
        for radek in soubor:
            try:
                d = json.loads(radek)
                if (d["druh"] not in ("faktura", "ppd") or type(d["cislo"]) is not int
                        or d["akce"] not in ("storno", "obnoveno") or not isinstance(d["kdo"], str)):
                    continue
                datetime.fromisoformat(d["ts"])
            except (ValueError, TypeError, KeyError):
                continue
            vysledek[d["druh"], d["cislo"]] = {
                "storno": d["akce"] == "storno", "storno_cas": d["ts"], "storno_kdo": d["kdo"],
            }
    return vysledek


def priprav_udalost(druh: str, cislo: int, akce: str, kdo: str = "") -> dict:
    kdo = kdo.strip().lstrip("= \t\r\n")[:60].rstrip() if isinstance(kdo, str) else ""
    return {"ts": datetime.now().isoformat(timespec="seconds"), "druh": druh,
            "cislo": cislo, "akce": akce, "kdo": kdo}


def _zapis(data_dir: str, udalost: dict) -> dict:
    radek = (json.dumps(udalost, ensure_ascii=False) + "\n").encode("utf-8")
    with open(os.path.join(data_dir, LOG_NAME), "a+b") as f:
        if f.tell():
            f.seek(-1, os.SEEK_END)
            if f.read(1) != b"\n":
                # Nedokončený řádek po výpadku necháme v logu samostatně.
                radek = b"\n" + radek
        f.write(radek)
        f.flush()
        os.fsync(f.fileno())
    return udalost


@contextmanager
def transakce(data_dir: str):
    """Drží zámek od kontroly stavu až po změnu a zápis události."""
    os.makedirs(data_dir, exist_ok=True)
    with _zamek_procesu, open(os.path.join(data_dir, LOG_NAME + ".lock"), "a+b") as f:
        if _HAVE_FCNTL:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield partial(_zapis, data_dir)


def zapis(data_dir: str, druh: str, cislo: int, akce: str, kdo: str = "") -> dict:
    with transakce(data_dir) as zapis_udalost:
        return zapis_udalost(priprav_udalost(druh, cislo, akce, kdo))
