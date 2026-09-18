"""Sdílecí odkazy na vygenerované dokumenty — funguj bez přihlášení.

David chtěl posílat hotovou žádost přes SMS/WhatsApp místo Gmailu, ale
`/download/<file>` je za přihlašovací branou (jinak by šlo z internetu
prohlížet cizí žádosti — obsahují jméno, adresu i rodné číslo).

Odkaz je krátký: `https://zadosti.spznaklic.cz/1234`. Čtyři číslice proto,
že David odkaz většinou neposílá — nadiktuje ho nebo napíše rukou na papír,
a dlouhý náhodný kód se opsat nedá. Kód je přesto **náhodný, ne pořadový**:
u pořadového by stačilo napsat 1, 2, 3… a projít všechno po řadě. Čtyři
číslice jsou ale jen 9000 možností, takže sám o sobě je to slabá ochrana —
strojové zkoušení musí brzdit appka (rate limit v app.py) a kód po
`TTL_DNI` vyprší. Vědomé rozhodnutí: žádost není extra tajný dokument a
krátký kód je to, co dělá funkci použitelnou.

Jeden kód pokrývá **celý balík** dokumentů z jednoho generování — žádost,
plné moci i pokladní doklad. Sdílet jen žádost a nechat si plnou moc v
appce nedávalo smysl; protějšek potřebuje vytisknout všechno.

Jen nové žádosti od teď — starší soubory kód nemají a nikdy na ně neukáže.
Kdo potřebuje sdílet starou žádost, vygeneruje ji znovu.
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

KOD_MIN = 1000
KOD_MAX = 9999

# Kde soubor leží (obojí je podadresář DATA_DIR). Žádosti a doklady padají do
# output/, plné moci mají vlastní složku a přežívají jednotlivá generování.
KDE_OUTPUT = "output"
KDE_PLNE_MOCE = "plne_moce"


def _cesta(data_dir: str) -> str:
    return os.path.join(data_dir, TOKENS_NAME)


def _polozka(x) -> dict:
    """Jedna položka balíku. Holý string = soubor v output/ bez popisku —
    tak vypadají i staré záznamy zapsané, než balíky existovaly."""
    if isinstance(x, str):
        return {"file": x, "kde": KDE_OUTPUT, "popis": ""}
    return {"file": x.get("file", ""),
            "kde": x.get("kde", KDE_OUTPUT),
            "popis": x.get("popis", "")}


def _polozky(soubory) -> list[dict]:
    if isinstance(soubory, (str, dict)):
        soubory = [soubory]
    return [_polozka(x) for x in soubory if x]


def _nevyprsel(d: dict) -> bool:
    try:
        vytvoreno = datetime.fromisoformat(d["vytvoreno"])
    except Exception:
        return False
    return datetime.now() - vytvoreno <= timedelta(days=TTL_DNI)


def _nacti(data_dir: str) -> list[dict]:
    """Všechny zapsané záznamy; poškozené řádky se přeskočí — jeden špatný
    řádek nesmí shodit čtení všech ostatních."""
    path = _cesta(data_dir)
    if not os.path.exists(path):
        return []
    zaznamy = []
    with open(path, encoding="utf-8") as f:
        for radek in f:
            try:
                zaznamy.append(json.loads(radek))
            except Exception:
                continue
    return zaznamy


def _zapis(data_dir: str, vyber) -> str:
    """Pod zámkem: nech `vyber` vybrat kód podle už obsazených a připiš ho.

    Výběr i zápis musí být v jednom zámku — jinak by dva workery mohly
    současně sáhnout po stejném volném čísle a druhá žádost by přepsala
    odkaz na tu první."""
    lock_fd = open(_cesta(data_dir) + ".lock", "a+")
    try:
        if _HAVE_FCNTL:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
        obsazene = {str(d.get("token")) for d in _nacti(data_dir) if _nevyprsel(d)}
        return vyber(obsazene)
    finally:
        if _HAVE_FCNTL:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        lock_fd.close()


def _pripis(data_dir: str, token: str, polozky: list[dict]) -> None:
    radek = {"token": token, "soubory": polozky,
             "vytvoreno": datetime.now().isoformat(timespec="seconds")}
    with open(_cesta(data_dir), "a", encoding="utf-8") as f:
        f.write(json.dumps(radek, ensure_ascii=False) + "\n")


def vytvor_kod(data_dir: str, soubory) -> str:
    """Nový čtyřmístný kód pro balík dokumentů.

    `soubory` je jméno souboru, nebo seznam {file, kde, popis}. Nikdy
    nevyhazuje — sdílení je bonus, nesmí shodit generování žádosti."""
    polozky = _polozky(soubory)

    def _vyber(obsazene: set[str]) -> str:
        volne = [k for k in range(KOD_MIN, KOD_MAX + 1) if str(k) not in obsazene]
        if not volne:
            # 9000 živých odkazů naráz se nestane (pár žádostí denně × 30 dnů),
            # ale kdyby ano, ať to radši dá dlouhý kód než by to spadlo.
            return secrets.token_urlsafe(8)
        kod = str(secrets.choice(volne))
        _pripis(data_dir, kod, polozky)
        return kod

    try:
        os.makedirs(data_dir, exist_ok=True)
        return _zapis(data_dir, _vyber)
    except Exception:
        return str(secrets.randbelow(KOD_MAX - KOD_MIN + 1) + KOD_MIN)


def vytvor_token(data_dir: str, soubory) -> str:
    """Dlouhý náhodný token — původní podoba odkazu (`/s/<token>`).

    Nové žádosti dostávají krátký `vytvor_kod`; tohle zůstává kvůli odkazům,
    které už jsou někde rozeslané, a jako záloha, kdyby došly krátké kódy."""
    token = secrets.token_urlsafe(24)
    polozky = _polozky(soubory)

    def _vyber(_obsazene: set[str]) -> str:
        _pripis(data_dir, token, polozky)
        return token

    try:
        os.makedirs(data_dir, exist_ok=True)
        _zapis(data_dir, _vyber)
    except Exception:
        pass
    return token


def najdi(data_dir: str, token: str) -> list[dict] | None:
    """Balík pro platný (nevypršelý) kód, jinak None.

    Od konce: krátkých kódů je jen 9000, takže se po vypršení zase použijí.
    Platí vždycky ten poslední zápis — starší (vypršelý) záznam se stejným
    číslem nesmí přebít žádost, která ho dostala teď."""
    for d in reversed(_nacti(data_dir)):
        if str(d.get("token")) != token:
            continue
        if not _nevyprsel(d):
            return None  # vypršelo
        # "file" je starý tvar záznamu (jeden soubor, před balíky).
        return _polozky(d.get("soubory") or d.get("file") or [])
    return None


def najdi_soubor(data_dir: str, token: str) -> str | None:
    """Jméno prvního souboru v balíku — tj. té hlavní žádosti."""
    polozky = najdi(data_dir, token)
    return polozky[0]["file"] if polozky else None
