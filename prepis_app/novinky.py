"""Data for the "Co umí Žádosti" sheet (templates/_novinky.html).

The old version history listed every release. The sheet lists only what the
app can do NOW, grouped in a few sections. Left off the sheet:

  - superseded releases (named in another release's `nahrazuje`),
  - obsolete ones (`zastarale=True`),
  - releases not placed in a section (`oblast` is None).

Inside a section the newest comes first. When several releases describe one
feature, the newest names the older ones in `nahrazuje` and its wording wins.
Every Release carries its own classification (oblast, nahrazuje, zastarale,
nazev, radek - see releases.py, the single source of truth); this module only
holds the logic.
"""
from __future__ import annotations

from releases import RELEASES, Release

# Fixed order: a section must not jump around from one update to the next.
SEKCE: tuple[tuple[str, str], ...] = (
    ("formular", "Formulář a klávesnice"),
    ("typy", "Typy žádostí"),
    ("faktury", "Faktury a platby"),
    ("sdileni", "Sdílení a tisk"),
    ("evidence", "Evidence"),
    ("hledani", "Hledání a AI"),
)

def _klic(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in version.split("."))


def aktualni(releases: tuple[Release, ...] = RELEASES) -> list[Release]:
    """Releases that are still true and belong on the sheet, newest first."""
    vse = releases
    nahrazene = {v for r in vse for v in r.nahrazuje}
    zive = [r for r in vse if r.oblast and not r.zastarale and r.version not in nahrazene]
    return sorted(zive, key=lambda r: _klic(r.version), reverse=True)


def zkratka(version: str) -> str:
    """1.35.0 -> 1.35; 1.3.13 stays."""
    return version[:-2] if version.endswith(".0") else version


def sekce(current: str, releases: tuple[Release, ...] = RELEASES) -> list[dict]:
    """[{key, nazev, karty: [{version, od, nazev, radek, demo, nova}]}]; empty sections dropped."""
    zive = aktualni(releases)
    out = []
    for key, nazev in SEKCE:
        karty = [
            dict(version=r.version, od=zkratka(r.version), nazev=r.nazev or r.title,
                 radek=r.radek or (r.points[0] if r.points else ""), demo=r.demo,
                 nova=r.version == current)
            for r in zive if r.oblast == key
        ]
        if karty:
            out.append(dict(key=key, nazev=nazev, karty=karty))
    return out


def skryte(releases: tuple[Release, ...] = RELEASES) -> list[tuple[str, str]]:
    """(version, reason) for everything left off the sheet - for review."""
    zive = {r.version for r in aktualni(releases)}
    nahrazene = {v: r.version for r in releases for v in r.nahrazuje}
    out = []
    for r in releases:
        if r.version in zive:
            continue
        if r.version in nahrazene:
            out.append((r.version, f"nahrazeno {nahrazene[r.version]}"))
        else:
            out.append((r.version, "zastaralé" if r.zastarale else "bez oblasti"))
    return out
