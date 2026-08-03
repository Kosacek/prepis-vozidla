"""Zeptej se — deterministic question answering (no AI, numbers from SQL)."""
from datetime import date

import pytest

from repositories import firmy_repo, typy_repo, ukony_repo
from services import ask_service

TODAY = date(2026, 7, 25)


@pytest.fixture
def data(conn):
    """Known fixture so every expected number can be checked by hand:

        07-01  Cardion PŘEVOD 1300  David   (nezaplaceno)
        07-01  Cardion PŘEVOD 1300  David   (nezaplaceno)
        07-15  Albion  NOVÉ   1950  Roman   pozn. 'RADIM VYŠKOV'
        07-20  Cardion PŘEVOD 5000  David   ← nejlepší den podle Kč
        06-10  Cardion PŘEVOD 1300  Petr    (zaplaceno)
    """
    cardion = firmy_repo.create(conn, nazev="Cardion s.r.o.", zkratka="Cardion", ico="1")
    albion = firmy_repo.create(conn, nazev="Albion", zkratka="Albion", ico="2")
    typy_repo.upsert(conn, "PŘEVOD", 1300, 1)
    typy_repo.upsert(conn, "NOVÉ", 1950, 2)
    mk = lambda **kw: ukony_repo.create(conn, **kw)
    mk(firma_id=cardion, datum="2026-07-01", typ_kod="PŘEVOD", celkem=1300, zpracoval="David")
    mk(firma_id=cardion, datum="2026-07-01", typ_kod="PŘEVOD", celkem=1300, zpracoval="David")
    mk(firma_id=albion, datum="2026-07-15", typ_kod="NOVÉ", celkem=1950, zpracoval="Roman",
       poznamka="RADIM VYŠKOV")
    mk(firma_id=cardion, datum="2026-07-20", typ_kod="PŘEVOD", celkem=5000, zpracoval="David")
    mk(firma_id=cardion, datum="2026-06-10", typ_kod="PŘEVOD", celkem=1300, zpracoval="Petr",
       stav_platby="zaplaceno", zaplaceno_kc=1300)
    return conn, cardion, albion


def ask(conn, q):
    return ask_service.answer(conn, q, today=TODAY)


# ── období ───────────────────────────────────────────────────────────────────

def test_parse_period_basic():
    p = lambda q: ask_service.parse_period(q, TODAY)
    assert p("kolik dnes")[:2] == ("2026-07-25", "2026-07-25")
    assert p("kolik včera")[:2] == ("2026-07-24", "2026-07-24")
    assert p("tento měsíc")[:2] == ("2026-07-01", "2026-07-31")
    assert p("minulý měsíc")[:2] == ("2026-06-01", "2026-06-30")
    assert p("letos")[:2] == ("2026-01-01", "2026-12-31")
    assert p("posledních 7 dní")[:2] == ("2026-07-19", "2026-07-25")
    assert p("nic o čase")[2] == "celkem"


def test_cervenec_is_not_parsed_as_cerven():
    """'červenec' contains 'červen' — the longest stem must win."""
    assert ask_service.parse_period("za červenec", TODAY)[:2] == ("2026-07-01", "2026-07-31")
    assert ask_service.parse_period("v červnu", TODAY)[:2] == ("2026-06-01", "2026-06-30")
    assert ask_service.parse_period("červenec 2025", TODAY)[:2] == ("2025-07-01", "2025-07-31")


# ── součty ────────────────────────────────────────────────────────────────────

def test_total_for_month(data):
    conn, _, _ = data
    r = ask(conn, "Kolik úkonů jsme udělali v červenci?")
    assert r["understood"]
    assert "4 úkony" in r["headline"]          # 1300+1300+1950+5000
    assert "9 550 Kč" in r["headline"]


def test_money_phrasing_puts_money_first(data):
    conn, _, _ = data
    r = ask(conn, "Kolik peněz za červenec?")
    assert r["headline"].startswith("9 550 Kč")


def test_filter_by_firma(data):
    conn, _, _ = data
    r = ask(conn, "Kolik pro Cardion?")
    assert "4 úkony" in r["headline"] and "8 900 Kč" in r["headline"]
    assert "Cardion" in r["filters"]


def test_filter_by_person(data):
    conn, _, _ = data
    r = ask(conn, "Kolik udělal David?")
    assert "3 úkony" in r["headline"] and "7 600 Kč" in r["headline"]


def test_filter_by_typ(data):
    conn, _, _ = data
    r = ask(conn, "Kolik převodů letos?")
    assert "4 úkony" in r["headline"]          # všechny PŘEVOD = 1300*3 + 5000
    assert "8 900 Kč" in r["headline"]


def test_unpaid(data):
    conn, _, _ = data
    r = ask(conn, "Kolik je nezaplaceno?")
    assert "4 úkony" in r["headline"] and "9 550 Kč" in r["headline"]


# ── superlativy ───────────────────────────────────────────────────────────────

def test_best_day(data):
    conn, _, _ = data
    r = ask(conn, "Jaký byl nejlepší den?")
    assert "20.07.2026" in r["headline"] and "5 000 Kč" in r["headline"]


def test_top_firma(data):
    conn, _, _ = data
    r = ask(conn, "Která firma nejvíc?")
    assert "Cardion" in r["headline"]
    labels = [row["label"] for row in r["rows"]]
    assert "Cardion" in labels and "Albion" in labels


def test_who_did_most(data):
    conn, _, _ = data
    r = ask(conn, "Kdo udělal nejvíc?")
    assert "David" in r["headline"] and "7 600 Kč" in r["headline"]


def test_most_common_typ(data):
    conn, _, _ = data
    r = ask(conn, "Jaký typ úkonu nejčastěji?")
    assert "PŘEVOD" in r["headline"]


# ── volný text (jméno protistrany) ───────────────────────────────────────────

def test_free_text_name_with_czech_declension(data):
    """'od Radima Vyškova' must find the note stored as 'RADIM VYŠKOV' —
    diacritics folded AND the declined ending stripped."""
    conn, _, _ = data
    r = ask(conn, "Kolik práce od Radima Vyškova?")
    assert r["understood"]
    assert "1 úkon" in r["headline"] and "1 950 Kč" in r["headline"]


def test_free_text_does_not_hijack_plain_totals(data):
    """A question with no name must still give the overall total, not a search."""
    conn, _, _ = data
    r = ask(conn, "Kolik úkonů celkem?")
    assert "5 úkonů" in r["headline"] and "10 850 Kč" in r["headline"]


def test_unknown_question_says_so(data):
    conn, _, _ = data
    r = ask(conn, "jaké bude zítra počasí")
    assert not r["understood"]
    assert "nerozumím" in r["headline"].lower()


def test_empty_question(data):
    conn, _, _ = data
    assert ask(conn, "")["understood"] is False


# ── formátování ───────────────────────────────────────────────────────────────

def test_czech_plurals_and_money():
    assert ask_service._ukony(1) == "1 úkon"
    assert ask_service._ukony(3) == "3 úkony"
    assert ask_service._ukony(12) == "12 úkonů"
    assert ask_service.kc(48000) == "48 000 Kč"
    assert ask_service.kc(0) == "0 Kč"


# ── regrese z reálných dat ────────────────────────────────────────────────────

def test_best_month_is_not_hijacked_by_current_month(data):
    """'nejlepší měsíc' groups BY month — bare 'měsíc' must not be read as the
    current month (that made the question return 'žádná data')."""
    conn, _, _ = data
    r = ask(conn, "Nejlepší měsíc?")
    assert r["understood"]
    assert "červenec 2026" in r["headline"] and "9 550 Kč" in r["headline"]


def test_qualified_month_is_still_a_period(data):
    conn, _, _ = data
    assert ask_service.parse_period("tento měsíc", TODAY)[:2] == ("2026-07-01", "2026-07-31")
    assert ask_service.parse_period("minulý měsíc", TODAY)[:2] == ("2026-06-01", "2026-06-30")


def test_who_did_most_names_a_person_not_the_unassigned_bucket(data):
    """Úkony without `zpracoval` must not win the 'kdo' ranking."""
    conn, cardion, _ = data
    for _ in range(9):   # a pile of unattributed úkony
        ukony_repo.create(conn, firma_id=cardion, datum="2026-07-05",
                          typ_kod="PŘEVOD", celkem=9000)
    r = ask(conn, "Kdo udělal nejvíc?")
    # names a real person even though the unattributed pile is far bigger
    assert r["headline"].startswith("Nejvíc udělal David")
    assert all(row["label"] in ("David", "Roman", "Petr") for row in r["rows"])


# ── stránka /zeptej ───────────────────────────────────────────────────────────

def test_ask_page_renders_and_answers(tmp_path, monkeypatch):
    import app as appmod, db, config
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    a = appmod.create_app(); a.testing = True
    with a.test_client() as c:
        with a.app_context():
            conn = db.get_db()
            fid = firmy_repo.create(conn, nazev="Cardion", zkratka="Cardion", ico="1")
            typy_repo.upsert(conn, "PŘEVOD", 1300, 1)
            ukony_repo.create(conn, firma_id=fid, datum="2026-07-20",
                              typ_kod="PŘEVOD", celkem=1300, zpracoval="David")
        empty = c.get("/zeptej")
        assert empty.status_code == 200
        assert "Zeptej se" in empty.get_data(as_text=True)

        r = c.get("/zeptej?q=" + "Kolik pro Cardion?")
        body = r.get_data(as_text=True)
        assert r.status_code == 200
        assert "1 úkon" in body and "1 300 Kč" in body

        unknown = c.get("/zeptej?q=jaké bude počasí").get_data(as_text=True)
        assert "Tomu nerozumím." in unknown


# ── den v týdnu ───────────────────────────────────────────────────────────────

def test_weekday_breakdown_counts_pieces(data):
    """'který den v týdnu má nejvíc kusů' seskupuje podle dne v týdnu (ne podle
    data) a řadí podle POČTU. 07-01 ×2, 07-15 a 06-10 jsou všechno středy."""
    conn, _, _ = data
    r = ask(conn, "Který den v týdnu máme nejvíc kusů?")
    assert r["understood"]
    assert r["headline"].startswith("Nejvíc: středa")
    assert "4 úkony" in r["headline"]                  # 1300+1300+1950+1300
    labels = [row["label"] for row in r["rows"]]
    assert "středa" in labels and "pondělí" in labels  # 07-20 je pondělí


def test_weekday_breakdown_switches_to_money_when_asked(data):
    """Na peníze se řadí podle Kč — jeden drahý úterní úkon přebije 4 středeční."""
    conn, cardion, _ = data
    ukony_repo.create(conn, firma_id=cardion, datum="2026-07-21",  # úterý
                      typ_kod="PŘEVOD", celkem=20000, zpracoval="David")
    by_count = ask(conn, "Který den v týdnu máme nejvíc kusů?")
    by_money = ask(conn, "Který den v týdnu vyděláme nejvíc peněz?")
    assert by_count["headline"].startswith("Nejvíc: středa")   # 4 kusy
    assert by_money["headline"].startswith("Nejvíc: úterý")    # 20 000 Kč
    assert "20 000 Kč" in by_money["headline"]


def test_weekday_as_filter(data):
    """'v pondělí' filtruje na pondělky (07-20 = pondělí, 5 000 Kč)."""
    conn, _, _ = data
    r = ask(conn, "Kolik děláme v pondělí?")
    assert "1 úkon" in r["headline"] and "5 000 Kč" in r["headline"]
    assert "pondělí" in r["filters"]


def test_weekday_question_does_not_become_best_date(data):
    """Nesmí spadnout do větve 'nejlepší den' (konkrétní datum)."""
    conn, _, _ = data
    r = ask(conn, "Který den v týdnu je nejlepší?")
    assert "2026" not in r["headline"]          # není to konkrétní datum
    assert r["detail"] == "Podle dne v týdnu:"


def test_this_week_still_parses_as_period(data):
    """'tento týden' zůstává obdobím, nezmění se na rozpad podle dnů."""
    conn, _, _ = data
    assert ask_service.parse_period("tento týden", TODAY)[2] == "tento týden"


# ── výpis konkrétních úkonů pod odpovědí ──────────────────────────────────────

def test_totals_list_the_matching_ukony(data):
    """Odpověď nese i konkrétní úkony, o kterých mluví."""
    conn, _, _ = data
    r = ask(conn, "Kolik pro Cardion?")
    assert len(r["ukony"]) == 4
    assert all(u["firma_zkratka"] == "Cardion" for u in r["ukony"])
    assert r["ukony"][0]["datum"] >= r["ukony"][-1]["datum"]   # nejnovější první


def test_free_text_lists_the_found_ukony(data):
    """Případ ze screenshotu: hledání jména vypíše nalezené úkony."""
    conn, _, _ = data
    r = ask(conn, "Kolik práce od Radima Vyškova?")
    assert len(r["ukony"]) == 1
    assert r["ukony"][0]["poznamka"] == "RADIM VYŠKOV"


def test_best_day_lists_only_that_day(data):
    conn, _, _ = data
    r = ask(conn, "Nejlepší den?")
    assert [u["datum"] for u in r["ukony"]] == ["2026-07-20"]


def test_weekday_lists_only_that_weekday(data):
    conn, _, _ = data
    r = ask(conn, "Který den v týdnu máme nejvíc kusů?")
    assert len(r["ukony"]) == 4                       # všechny středy
    assert all(u["datum"] in ("2026-07-01", "2026-07-15", "2026-06-10")
               for u in r["ukony"])


def test_top_firma_lists_that_firms_ukony(data):
    conn, _, _ = data
    r = ask(conn, "Která firma nejvíc?")
    assert all(u["firma_zkratka"] == "Cardion" for u in r["ukony"])


def test_unknown_question_lists_nothing(data):
    conn, _, _ = data
    assert ask(conn, "jaké bude zítra počasí")["ukony"] == []


def test_ask_page_renders_the_ukon_rows(tmp_path, monkeypatch):
    """Stránka vykreslí řádky stejným partialem jako přehled úkonů."""
    import app as appmod, db, config
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    a = appmod.create_app(); a.testing = True
    with a.test_client() as c:
        with a.app_context():
            conn = db.get_db()
            fid = firmy_repo.create(conn, nazev="Cardion", zkratka="Cardion", ico="1")
            typy_repo.upsert(conn, "PŘEVOD", 1300, 1)
            uid = ukony_repo.create(conn, firma_id=fid, datum="2026-07-20", typ_kod="PŘEVOD",
                                    celkem=1300, rz="1AB2345", vin="TMBVIN1234567890",
                                    poznamka="TOYOTA", zpracoval="David")
        body = c.get("/zeptej?q=toyota").get_data(as_text=True)
        assert "1AB2345" in body                       # SPZ v seznamu
        assert "TMBVIN1234567890" in body              # VIN
        assert f"/ukony/{uid}/upravit" in body         # klikací na úpravu
        assert "firma-dot" in body                     # barva firmy jako v přehledu
