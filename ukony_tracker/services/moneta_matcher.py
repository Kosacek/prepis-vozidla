"""Pure matching of bank payments to open fakturas. Never auto-settles when in doubt."""
from __future__ import annotations

from decimal import Decimal


def _key(s) -> str:
    return "".join(str(s or "").split()).upper()


def _kc(n) -> str:
    n = Decimal(n)
    return f"{int(n):,}".replace(",", " ") if n == n.to_integral() else f"{n:,.2f}".replace(",", " ")


def _mentions(zprava: str, vozidlo: str) -> bool:
    """The message contains the faktura's VIN or plate (case/space-insensitive)."""
    v = _key(vozidlo)
    return len(v) >= 5 and v in _key(zprava)


def _mismatch(p, f) -> str:
    return f"částka nesedí (přišlo {_kc(p.castka)}, faktura {_kc(f['castka'])})"


def sparuj(platby, otevrene_faktury, zaplacene_cisla=()):
    """-> (shody, nesparene): shody = [(Platba, cislo)], nesparene = [(Platba, duvod)].

    `otevrene_faktury`: rows/dicts with cislo, castka, vozidlo (unpaid, not
    deleted). `zaplacene_cisla`: numbers already paid, only to explain why a
    late payment is left alone."""
    faktury = {int(f["cislo"]): f for f in otevrene_faktury}
    zaplacene = {int(c) for c in zaplacene_cisla}
    shody, nesparene, pouzite = [], [], set()
    for p in platby:
        cislo, duvod = _najdi(p, faktury, zaplacene, pouzite)
        if cislo is None:
            nesparene.append((p, duvod))
        else:
            pouzite.add(cislo)
            shody.append((p, cislo))
    return shody, nesparene


def _najdi(p, faktury, zaplacene, pouzite):
    vs = int(p.vs) if p.vs.isdigit() else None
    if vs in zaplacene:
        return None, f"faktura č. {vs} je už zaplacená"
    if vs in pouzite:
        return None, f"faktura č. {vs} už je zaplacená jinou platbou"
    if vs in faktury:  # primary: variabilní symbol
        f = faktury[vs]
        return (vs, "") if Decimal(f["castka"]) == p.castka else (None, _mismatch(p, f))
    # secondary: VIN / plate in the message, amount must be equal, one candidate only
    kandidati = [f for c, f in faktury.items() if c not in pouzite and _mentions(p.zprava, f["vozidlo"])]
    shodne = [f for f in kandidati if Decimal(f["castka"]) == p.castka]
    if len(shodne) == 1:
        return int(shodne[0]["cislo"]), ""
    if len(shodne) > 1:
        return None, "více možných faktur: " + ", ".join(str(f["cislo"]) for f in shodne)
    if len(kandidati) == 1:
        return None, _mismatch(p, kandidati[0])
    if kandidati:
        return None, "více možných faktur: " + ", ".join(str(f["cislo"]) for f in kandidati)
    return None, "žádná odpovídající faktura"
