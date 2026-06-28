"""Stable firma -> color map, shared by the dashboard chart and the recent list
so a firm has the SAME color everywhere.

Colors come from a distinct, well-separated palette assigned in the firms' stable
display order (firmy_repo.list_all -> poradi, nazev), so every firm is easy to
tell apart on the line chart and the colors don't shuffle between renders.
"""
from sqlite3 import Connection

from repositories import firmy_repo

# Distinct Apple system colors — picked so adjacent firms never look alike.
PALETTE = [
    "#0a84ff", "#34c759", "#ff9f0a", "#bf5af2", "#ff375f",
    "#5ac8fa", "#ffd60a", "#ff6482", "#64d2ff", "#30d158",
    "#a2845e", "#8e8e93",
]


def firma_color_map(conn: Connection) -> dict[str, str]:
    """Return ``{zkratka: hex}`` for every firm, in stable display order."""
    firmy = firmy_repo.list_all(conn)
    return {f["zkratka"]: PALETTE[i % len(PALETTE)] for i, f in enumerate(firmy)}
