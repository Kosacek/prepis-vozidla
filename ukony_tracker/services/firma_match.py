"""Conservative matching of ORV operators to active firms."""
import re
import unicodedata

from repositories import firmy_repo


_LEGAL_FORMS = (
    ("S", "R", "O"), ("SRO",), ("A", "S"), ("AS",),
    ("V", "O", "S"), ("VOS",), ("K", "S"), ("KS",), ("SPOL",),
)


def normalize_name(value: str | None) -> str:
    """Fold diacritics, punctuation, whitespace and Czech company suffixes."""
    if not isinstance(value, str):
        return ""
    folded = "".join(
        ch for ch in unicodedata.normalize("NFD", value.upper())
        if not unicodedata.combining(ch)
    )
    words = re.findall(r"[A-Z0-9]+", folded)
    changed = True
    while changed:
        changed = False
        for form in _LEGAL_FORMS:
            size = len(form)
            for start in range(len(words) - size, -1, -1):
                if tuple(words[start:start + size]) == form:
                    del words[start:start + size]
                    changed = True
                    break
            if changed:
                break
    return " ".join(words)


_TITLES = {"ING", "MGR", "BC", "JUDR", "MUDR", "MVDR", "PHDR", "RNDR", "PHARMDR", "DIS",
           "CSC", "PHD", "MBA", "DR", "DOC", "PROF", "ARCH"}


def same_party(a: str | None, b: str | None) -> bool | None:
    """Is it the same person/company? None when either name is missing.

    Order-free word sets (an ORV prints "ŠEBESTA JAKUB", the žádost "Ing. Jakub
    Šebesta"), titles and legal forms ignored; a shorter name inside a longer
    one counts when it is specific enough (2+ words, or one word of 5+ chars).
    """
    words_a = set(normalize_name(a).split()) - _TITLES
    words_b = set(normalize_name(b).split()) - _TITLES
    if not words_a or not words_b:
        return None
    if words_a == words_b:
        return True
    small, big = sorted((words_a, words_b), key=len)
    specific = len(small) >= 2 or len(next(iter(small))) >= 5
    return small <= big and specific


def match_firma(conn, name: str | None) -> dict | None:
    """Return one confident active-firm match; ambiguity is always rejected.

    A match is an equal normalized name/shortcut, or containment where the
    shorter normalized name has at least five characters. Containment across
    multiple firms is not enough to choose one.
    """
    needle = normalize_name(name)
    if not needle:
        return None
    matches = []
    for firm in firmy_repo.list_all(conn, only_active=True):
        candidates = {
            normalize_name(firm["nazev"]),
            normalize_name(firm["zkratka"]),
        } - {""}
        confidence = None
        for candidate in candidates:
            if candidate == needle:
                confidence = "presna"
                break
            shorter, longer = sorted((needle, candidate), key=len)
            if len(shorter) >= 5 and shorter in longer:
                confidence = "obsahuje"
                break
        if confidence:
            matches.append((firm, confidence))
    if len(matches) != 1:
        return None
    firm, confidence = matches[0]
    return {"firma_id": firm["id"], "firma": firm["nazev"], "jistota": confidence}
