"""Firma -> color map, shared by the dashboard chart and the recent list so a
firm has the SAME color everywhere.

Colors are brand-based: most firms are car dealerships, so each is colored by the
marque it represents (researched), e.g. Tesla -> red, CarTec (BMW) -> blue,
Cardion (Volvo) -> navy. Firms with no known brand fall back to a neutral palette
in stable order. Keys match the firm `zkratka` (whitespace-insensitive).
"""
from sqlite3 import Connection

from repositories import firmy_repo

# Brand color per firm shortcut. Each dealership maps to its marque's identity.
BRAND_COLORS = {
    "Tesla":   "#E31937",  # Tesla — signature red
    "CarTec":  "#0066B1",  # BMW dealer — BMW blue
    "Cardion": "#003057",  # Volvo dealer — Volvo deep navy
    "Albion":  "#005A2B",  # Jaguar / Land Rover dealer — British racing green
    "C & K":   "#EB0A1E",  # Toyota (+ Lexus/Subaru) dealer — Toyota red
    "Lexus":   "#23272B",  # Lexus — graphite / black
    "CanoCar": "#2D5BD0",  # Suzuki dealer — Suzuki royal blue
    "Orbion":  "#A6192E",  # MG dealer — MG deep red
    "JE & NE": "#4BA82E",  # Škoda dealer — Škoda green
    "Sapik":   "#E8730C",  # used-car dealer (no single marque) — distinct orange
    "Ostatní": "#8E8E93",  # catch-all "Other" — neutral grey
}

# Fallback for firms not in BRAND_COLORS (future firms), Apple system colors.
PALETTE = [
    "#0a84ff", "#34c759", "#ff9f0a", "#bf5af2", "#ff375f",
    "#5ac8fa", "#ffd60a", "#ff6482", "#64d2ff", "#30d158",
]


def firma_color_map(conn: Connection) -> dict[str, str]:
    """Return ``{zkratka: hex}`` for every firm: its brand color when known,
    otherwise the next palette color (assigned in stable display order)."""
    out: dict[str, str] = {}
    palette_i = 0
    for f in firmy_repo.list_all(conn):
        zkratka = f["zkratka"]
        key = (zkratka or "").strip()  # tolerate stray trailing spaces in data
        if key in BRAND_COLORS:
            out[zkratka] = BRAND_COLORS[key]
        else:
            out[zkratka] = PALETTE[palette_i % len(PALETTE)]
            palette_i += 1
    return out
