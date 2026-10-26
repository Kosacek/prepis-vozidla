"""POST /api/ppd/vystavit — evidence vystaví pokladní doklad (PPD) přes žádosti.

„Nový doklad" v evidenci (2.5, 2026-10-26): čísla dokladů dál přiděluje jen
žádosti, takže evidence nevystavuje sama, ale požádá sem. Vystavení je totéž
co u dokladu k žádosti (app.api_generate): ledger + číslo, záloha, PDF
ppd_<n>.pdf a push do evidence. Kontrakt: ukony_tracker/docs/superpowers/
specs/2026-10-26-doklady-prestavba-design.md, „Kontrakt pro žádosti".

Každé číslo je skutečný účetní doklad, proto:
- nevalidní tělo se odmítne dřív, než se sáhne na číslování (over());
- stejný request_id (opakování, dvojklik) vrátí už vystavený doklad a nové
  číslo nerezervuje — pod zámkem přes oba gunicorn workery (vystav()).
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime

import ppd
import ppd_push

try:
    import fcntl  # type: ignore
    _HAVE_FCNTL = True
except ImportError:  # pragma: no cover - Windows dev only
    _HAVE_FCNTL = False

_log = logging.getLogger("prepis.ppd_api")

MAX_CASTKA = 10_000_000          # Kč — pojistka proti překlepu o pár nul
MAX_VOZIDEL = 30
MAX_PRIJATO_OD = 200
MAX_UCEL = 120
MAX_VOZIDLO = 20                 # RZ má 7–8 znaků, VIN 17
MAX_ZPRACOVAL = 60
MAX_REQUEST_ID = 100
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]+$")
_VIN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")

VYSTAVENE = "ppd_api_vystavene.jsonl"   # request_id → doklad (idempotence + audit)
_ZAMEK = "ppd_api.lock"
_zamek_procesu = threading.Lock()       # vlákna v jednom workeru; flock mezi workery


class Chyba(ValueError):
    """Nevalidní požadavek → 400 s touhle zprávou."""


def _text(telo: dict, klic: str, *, povinne: bool = False, max_delka: int) -> str:
    hodnota = telo.get(klic)
    if hodnota is None:
        hodnota = ""
    if not isinstance(hodnota, str):
        raise Chyba(f"{klic} musí být text.")
    hodnota = hodnota.strip()
    if povinne and not hodnota:
        raise Chyba(f"{klic} chybí.")
    if len(hodnota) > max_delka:
        raise Chyba(f"{klic} je delší než {max_delka} znaků.")
    _bez_vzorce(klic, hodnota)
    return hodnota


def _bez_vzorce(klic: str, hodnota: str) -> None:
    # openpyxl zapíše text začínající „=" do knihy dokladů jako vzorec.
    if hodnota.startswith("="):
        raise Chyba(f"{klic} nesmí začínat znakem =.")


def _castka(hodnota) -> int:
    # bool je v Pythonu int — True by jinak prošlo jako 1 Kč.
    if isinstance(hodnota, bool) or not isinstance(hodnota, (int, float)):
        raise Chyba("castka musí být celé číslo v korunách.")
    if isinstance(hodnota, float):
        if not hodnota.is_integer():
            raise Chyba("castka musí být celé číslo v korunách.")
        hodnota = int(hodnota)
    if not 1 <= hodnota <= MAX_CASTKA:
        raise Chyba(f"castka musí být mezi 1 a {MAX_CASTKA} Kč.")
    return hodnota


def _vozidla(hodnota) -> list[str]:
    if not isinstance(hodnota, list) or not hodnota:
        raise Chyba("vozidla musí být neprázdný seznam RZ nebo VIN.")
    if len(hodnota) > MAX_VOZIDEL:
        raise Chyba(f"vozidla smí mít nejvýš {MAX_VOZIDEL} položek.")
    vysledek = []
    for v in hodnota:
        if not isinstance(v, str) or not v.strip():
            raise Chyba("Každé vozidlo musí být neprázdný text (RZ nebo VIN).")
        v = " ".join(v.split()).upper()
        if len(v) > MAX_VOZIDLO:
            raise Chyba(f"Vozidlo „{v[:MAX_VOZIDLO]}…“ je delší než {MAX_VOZIDLO} znaků.")
        _bez_vzorce("vozidla", v)
        vysledek.append(v)
    return vysledek


def over(telo) -> dict:
    """Zkontroluje a znormalizuje tělo požadavku; při chybě vyhodí Chyba."""
    if not isinstance(telo, dict):
        raise Chyba("Tělo musí být JSON objekt.")
    prijato_ico = re.sub(r"\s", "", _text(telo, "prijato_ico", max_delka=20))
    if prijato_ico and (not prijato_ico.isdigit() or len(prijato_ico) > 12):
        raise Chyba("prijato_ico smí obsahovat jen číslice (nejvýš 12).")
    request_id = _text(telo, "request_id", max_delka=MAX_REQUEST_ID)
    if request_id and not _REQUEST_ID.match(request_id):
        raise Chyba("request_id smí obsahovat jen písmena, číslice a . _ : -")
    return {
        "prijato_od": _text(telo, "prijato_od", povinne=True, max_delka=MAX_PRIJATO_OD),
        "prijato_ico": prijato_ico,
        "castka": _castka(telo.get("castka")),
        "ucel": _text(telo, "ucel", povinne=True, max_delka=MAX_UCEL),
        "vozidla": _vozidla(telo.get("vozidla")),
        "zpracoval": _text(telo, "zpracoval", max_delka=MAX_ZPRACOVAL),
        "request_id": request_id,
    }


def _najdi_vystaveny(data_dir: str, request_id: str) -> dict | None:
    path = os.path.join(data_dir, VYSTAVENE)
    if not request_id or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        for radek in f:
            try:
                zaznam = json.loads(radek)
            except ValueError:
                continue
            if zaznam.get("request_id") == request_id:
                return zaznam.get("doklad")
    return None


def _zapis_vystaveny(data_dir: str, udaje: dict, doklad: dict) -> None:
    zaznam = {"ts": datetime.now().isoformat(timespec="seconds"),
              "request_id": udaje["request_id"], "zpracoval": udaje["zpracoval"],
              "doklad": doklad}
    with open(os.path.join(data_dir, VYSTAVENE), "a", encoding="utf-8") as f:
        f.write(json.dumps(zaznam, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def _pod_zamkem(data_dir: str, fn):
    os.makedirs(data_dir, exist_ok=True)
    with _zamek_procesu:
        lock_fd = open(os.path.join(data_dir, _ZAMEK), "a+")
        try:
            if _HAVE_FCNTL:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
            return fn()
        finally:
            try:
                if _HAVE_FCNTL:
                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
            finally:
                lock_fd.close()


def vystav(data_dir: str, udaje: dict, adresa_podle_ico) -> tuple[dict, bool]:
    """Vystaví doklad (nebo vrátí už vystavený pro stejný request_id).

    adresa_podle_ico(ico) → adresa uložené firmy nebo "" (u dokladu k žádosti
    ji doplní výběr firmy v UI). Vrací (doklad pro evidenci, nově_vystaven).
    Push do evidence je na volajícím — až po uvolnění zámku.
    """
    def _run():
        hotovy = _najdi_vystaveny(data_dir, udaje["request_id"])
        if hotovy:
            return hotovy, False
        dnes = datetime.now().strftime("%d.%m.%Y")
        # Plátce velkými písmeny jako u dokladu k žádosti; účel tak, jak přišel.
        payer = udaje["prijato_od"].upper()
        payer_ico = udaje["prijato_ico"]
        payer_address = (adresa_podle_ico(payer_ico) if payer_ico else "").strip().upper()
        purpose = udaje["ucel"]
        vozidla = udaje["vozidla"]
        # Jako u žádosti: SPZ přednostně, VIN jen když je to jediné auto bez značky.
        if len(vozidla) == 1 and _VIN.match(vozidla[0]):
            spz, vin = "", vozidla[0]
        else:
            spz, vin = ", ".join(vozidla), ""
        number = ppd.reserve_ppd_number_and_log(data_dir, {
            "date": dnes, "payer": payer, "payer_ico": payer_ico,
            "amount": udaje["castka"], "purpose": purpose, "vehicle": spz or vin,
        })
        ppd.append_backup(data_dir, {
            "cislo": number, "ts": datetime.now().isoformat(timespec="seconds"),
            "date": dnes, "payer": payer, "payer_ico": payer_ico,
            "payer_address": payer_address, "amount": udaje["castka"], "purpose": purpose,
            "spz": spz, "vin": vin,
        })
        doklad = ppd_push.build_record({
            "cislo": number, "date": dnes, "payer": payer, "payer_ico": payer_ico,
            "amount": udaje["castka"], "purpose": purpose, "vehicle": spz or vin,
        })
        _zapis_vystaveny(data_dir, udaje, doklad)
        # PDF až po účetní části: kdyby selhalo, doklad i tak existuje a tisková
        # stránka /ppd-print/<n> se staví ze zálohy.
        try:
            out_dir = os.path.join(data_dir, "output")
            os.makedirs(out_dir, exist_ok=True)
            with open(os.path.join(out_dir, f"ppd_{number}.pdf"), "wb") as f:
                f.write(ppd.build_ppd_pdf({
                    "number": number, "date": dnes, "payer": payer, "payer_ico": payer_ico,
                    "payer_address": payer_address, "spz": spz, "vin": vin,
                    "amount": udaje["castka"], "purpose": purpose,
                }))
        except Exception as e:
            _log.warning("PPD %s: PDF se nepovedlo (%s), doklad platí, tisk jde ze zálohy", number, e)
        return doklad, True

    return _pod_zamkem(data_dir, _run)
