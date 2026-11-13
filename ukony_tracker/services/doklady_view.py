"""One doklad row on /doklady, ready for the template (2.8).

David (12. 11. 2026): the list must say at a glance which firm a doklad
belongs to, show the car's VIN next to its SPZ, and tell whether its úkony
are paid. The row is computed here, so _doklad_item.html only draws it.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

from services import ppd_links

VIN_LEN = 17


@dataclass(frozen=True)
class Auto:
    spz: str            # bold; empty when only the VIN is known
    vin: str            # muted next to / under the SPZ
    chybi: bool = False  # the doklad names this car, evidence has no úkon for it


@dataclass(frozen=True)
class Platba:
    stav: str   # "paid" | "partial" | "unpaid" | "none"
    label: str
    title: str


@dataclass(frozen=True)
class Radek:
    cislo: int
    vs: str               # variabilní symbol = číslo dokladu (Moneta QR payments, next project)
    datum: str            # "11.11.2026"
    castka: int
    firma: dict | None    # {"zkratka", "color"}
    prijato_od: str
    prijato_ico: str
    smazano: bool
    auta: tuple[Auto, ...]
    platba: Platba
    ukony_kc: int
    uids: tuple[int, ...]
    chybi: tuple[str, ...]
    hledat: str
    druh: str = "ppd"       # "ppd" (hotově) | "faktura" (převodem)
    splatnost: str = ""     # "26.11.2026", only a faktura has one
    po_splatnosti: bool = False


def _key(value: str | None) -> str:
    return "".join((value or "").split()).upper()


def pocet(n: int) -> str:
    """'1 úkon', '3 úkony', '5 úkonů'."""
    return f"{n} " + ("úkon" if n == 1 else "úkony" if 2 <= n <= 4 else "úkonů")


def platba(ukony: list, druh: str = "ppd") -> Platba:
    """Paid state of a doklad's úkony: the chip is green only when all are paid.
    An unpaid faktura says what it waits for instead of counting úkony."""
    n = len(ukony)
    if not n:
        return Platba("none", "bez úkonu", "Doklad nemá úkon v evidenci")
    paid = sum(1 for u in ukony if u["stav_platby"] == "zaplaceno")
    if paid == n:
        return Platba("paid", "✓ " + pocet(n), "Zaplaceno")
    if not paid and not any((u["zaplaceno_kc"] or 0) > 0 for u in ukony):
        if druh == "faktura":
            return Platba("unpaid", "čeká na platbu", f"Faktura čeká na platbu · {pocet(n)}")
        return Platba("unpaid", pocet(n), "Čeká na zaplacení")
    if n > 1 and paid:
        return Platba("partial", f"◐ {paid}/{n} zapl.", f"Zaplaceno {paid} z {n}")
    return Platba("partial", "◐ částečně", "Částečně zaplaceno")


def auta(vozidlo: str | None, ukony: list, chybi: Iterable[str]) -> tuple[Auto, ...]:
    """Cars of a doklad: each linked úkon's SPZ + VIN, then the cars the
    doklad names that no úkon covers (as written, flagged when missing)."""
    out: list[Auto] = []
    covered: set[str] = set()
    for u in ukony:
        spz, vin = _key(u["rz"]), _key(u["vin"])
        keys = {spz, vin} - {""}
        if not keys or keys & covered:
            continue
        covered |= keys
        out.append(Auto(spz=spz, vin=vin))
    missing = set(chybi)
    for shown, key in ppd_links.auta(vozidlo):
        if key in covered:
            continue
        covered.add(key)
        is_vin = len(key) == VIN_LEN
        out.append(Auto(spz="" if is_vin else shown, vin=shown if is_vin else "", chybi=key in missing))
    return tuple(out)


def _col(doklad, name: str, default=None):
    return doklad[name] if name in doklad.keys() and doklad[name] is not None else default


def _dmy(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}.{iso[0:4]}" if iso else ""


def radek(doklad, links, ukony: Mapping[int, object], firmy_by_id: Mapping[int, object],
          firma_colors: Mapping[str, str], dnes: date | None = None) -> Radek:
    cislo = doklad["cislo"]
    druh = _col(doklad, "druh", "ppd")
    splatnost_iso = _col(doklad, "splatnost", "") if druh == "faktura" else ""
    uids = tuple(links.by_doklad.get(cislo, []))
    chybi = tuple(links.missing.get(cislo, []))
    linked = sorted((ukony[i] for i in uids if i in ukony), key=lambda u: (u["datum"], u["id"]))
    f = firmy_by_id.get(links.firma.get(cislo))
    firma = {"zkratka": f["zkratka"], "color": firma_colors.get(f["zkratka"], "var(--muted)")} if f else None
    cars = auta(doklad["vozidlo"], linked, chybi)
    pay = platba(linked, druh)
    # Past its due date and not paid (a doklad marked paid by hand has no worry left).
    po = bool(splatnost_iso and splatnost_iso < (dnes or date.today()).isoformat()
              and pay.stav in ("unpaid", "partial", "none") and not _col(doklad, "zaplaceno_dne"))
    hledat = " ".join(["faktura" if druh == "faktura" else "", str(cislo), f"{cislo % 10000:04d}" if druh == "faktura" else "", doklad["prijato_od"] or "", doklad["prijato_ico"] or "",
                       doklad["vozidlo"] or "", firma["zkratka"] if firma else "",
                       *(f"{a.spz} {a.vin}" for a in cars)])
    d = doklad["datum"]
    return Radek(
        cislo=cislo, vs=str(cislo), datum=f"{d[8:10]}.{d[5:7]}.{d[0:4]}", castka=doklad["castka"],
        firma=firma, prijato_od=doklad["prijato_od"] or "", prijato_ico=doklad["prijato_ico"] or "",
        smazano=bool(doklad["smazano"]), auta=cars, platba=pay,
        ukony_kc=round(sum(u["celkem"] or 0 for u in linked)), uids=uids, chybi=chybi,
        hledat=" ".join(hledat.split()).lower(),
        druh=druh, splatnost=_dmy(splatnost_iso), po_splatnosti=po,
    )


def radky(doklady, links, ukony, firmy_by_id, firma_colors, dnes: date | None = None) -> list[Radek]:
    return [radek(d, links, ukony, firmy_by_id, firma_colors, dnes) for d in doklady]
