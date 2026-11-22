"""Vzorky skenů ORV pro test lokálního OCR (žádosti 1.37.1).

David 2026-11-22 („Yes, keep 30"): příštích 30 fotek ze /api/scan-orv se
uloží přesně tak, jak přišly, do DATA_DIR/ocr_vzorky/001.jpg … 030.jpg, každá
s 001.json (výsledek modelu, orv_qr, zachyt, čas, trvání na serveru). Pak už
nic — počítadlo v stav.json zůstává i po smazání souborů, takže limit 30
platí natrvalo. Soubory starší 7 dní se mažou při každém skenu a při startu.
Jména souborů jsou jen čísla. Složka se přes HTTP nikde neservíruje
(/download čte jen output/). Chyba ukládání sken nikdy neshodí.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time

try:
    import fcntl  # type: ignore
    _HAVE_FCNTL = True
except ImportError:  # pragma: no cover - Windows dev only
    _HAVE_FCNTL = False

SLOZKA = "ocr_vzorky"
LIMIT = 30
PLATNOST_S = 7 * 24 * 3600
_STAV = "stav.json"
_ZAMEK = ".zamek"
_SOUBOR = re.compile(r"^\d{3}\.(?:jpg|png|webp|json)$")
_PRIPONY = {"image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/webp": "webp"}

_log = logging.getLogger("prepis.ocr_vzorky")


def _slozka(data_dir: str) -> str:
    return os.path.join(data_dir, SLOZKA)


def uklid(data_dir: str, now: float | None = None) -> int:
    """Smaže vzorky starší 7 dní. Vrací počet smazaných souborů; nikdy nevyhodí."""
    slozka = _slozka(data_dir)
    hranice = (time.time() if now is None else now) - PLATNOST_S
    smazano = 0
    try:
        jmena = os.listdir(slozka)
    except OSError:
        return 0
    for jmeno in jmena:
        if not _SOUBOR.match(jmeno):
            continue
        cesta = os.path.join(slozka, jmeno)
        try:
            if os.path.getmtime(cesta) < hranice:
                os.remove(cesta)
                smazano += 1
        except OSError as e:
            _log.warning("ocr vzorek %s nejde smazat: %s", jmeno, e)
    return smazano


def _zapis(cesta: str, obsah: bytes) -> None:
    tmp = cesta + ".tmp"
    with open(tmp, "wb") as f:
        f.write(obsah)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, cesta)


def uloz(data_dir: str, obrazek: bytes, mime: str, meta: dict, now: float | None = None) -> str | None:
    """Uloží další vzorek (001…030), jinak None. Nikdy nevyhodí."""
    try:
        slozka = _slozka(data_dir)
        os.makedirs(slozka, exist_ok=True)
        with open(os.path.join(slozka, _ZAMEK), "a+") as zamek:
            if _HAVE_FCNTL:
                fcntl.flock(zamek.fileno(), fcntl.LOCK_EX)   # 2 workery gunicornu
            uklid(data_dir, now)
            stav_cesta = os.path.join(slozka, _STAV)
            try:
                with open(stav_cesta, encoding="utf-8") as f:
                    ulozeno = int(json.load(f).get("ulozeno", 0))
            except (OSError, ValueError, AttributeError):
                ulozeno = 0
            if ulozeno >= LIMIT:
                return None
            cislo = ulozeno + 1
            jmeno = f"{cislo:03d}"
            pripona = _PRIPONY.get((mime or "").lower(), "jpg")
            # Počítadlo napřed: kdyby zápis fotky spadl, číslo se znovu nepoužije
            # a limit 30 platí i tak.
            _zapis(stav_cesta, json.dumps({"ulozeno": cislo, "limit": LIMIT}).encode("utf-8"))
            _zapis(os.path.join(slozka, f"{jmeno}.{pripona}"), obrazek)
            _zapis(os.path.join(slozka, f"{jmeno}.json"),
                   json.dumps({**meta, "soubor": f"{jmeno}.{pripona}", "mime": mime},
                              ensure_ascii=False, indent=1).encode("utf-8"))
            return jmeno
    except Exception as e:   # noqa: BLE001 — vzorek je bonus, sken musí doběhnout
        _log.warning("ocr vzorek se neuložil: %s", e)
        return None
