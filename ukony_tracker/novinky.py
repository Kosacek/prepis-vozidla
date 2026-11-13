"""Data for the "Co umí Evidence" sheet (templates/_novinky.html).

The old version browser listed every release. The sheet lists only what the
app can do NOW, grouped in a few sections. Left off the sheet:

  - superseded releases (named in another release's `nahrazuje`),
  - obsolete ones (`zastarale=True`),
  - releases without a section (`oblast` is None).

Inside a section the newest comes first. When several releases describe one
feature, the newest names the older ones in `nahrazuje` and its wording wins.
The classification lives on each Release in releases.py.
"""
from __future__ import annotations

from releases import RELEASES, Release

# Fixed order: a section must not jump around from one update to the next.
SEKCE: tuple[tuple[str, str], ...] = (
    ("ukony", "Úkony"),
    ("doklady", "Doklady a platby"),
    ("technicak", "Techničák a sken"),
    ("firmy", "Firmy a příchozí"),
    ("prehled", "Přehled a Zeptej se"),
)


def _klic(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in version.split("."))


def aktualni(releases: tuple[Release, ...] = RELEASES) -> list[Release]:
    """Releases that are still true and belong on the sheet, newest first."""
    nahrazene = {v for r in releases for v in r.nahrazuje}
    zive = [r for r in releases
            if r.oblast and not r.zastarale and r.version not in nahrazene]
    return sorted(zive, key=lambda r: _klic(r.version), reverse=True)


def sekce(current: str, releases: tuple[Release, ...] = RELEASES) -> list[dict]:
    """[{key, nazev, karty: [{version, od, nazev, radek, demo, nova}]}];
    empty sections are dropped."""
    zive = aktualni(releases)
    out = []
    for key, nazev in SEKCE:
        karty = [
            dict(version=r.version, od=r.version, nazev=r.nazev or r.title,
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
        elif r.zastarale:
            out.append((r.version, "zastaralé"))
        else:
            out.append((r.version, "bez oblasti"))
    return out
