"""Hledání historie — deterministic, no AI, records straight from the files.

Same shape as the sister app's ukony_tracker/tests/test_ask.py: one hand-checkable
fixture so every expected number can be verified by eye.
"""
import json
import os
from datetime import date

import pytest

import hledani

TODAY = date(2026, 7, 25)


@pytest.fixture
def vystupy():
    """Vygenerované žádosti:

        07-15 10:00  Převod        3BR4008  AUTO CARDION -> JAN NOVÁK
        07-15 11:30  Nové vozidlo  (VIN)                 -> TOYOTA FINANCIAL
        07-20 09:00  Převod        1AB2345  AUTO CARDION -> PETR SVOBODA
        06-10 08:00  Změna údajů   9XY8765
    """
    mk = lambda f, typ, kind, d, cas, rz="", vin="", od="", na="": {
        "file": f, "typ": typ, "kind": kind, "datum": d, "cas": cas,
        "velikost": 100, "url": f"/download/{f}", "rz": rz, "vin": vin,
        "znacka": "", "od": od, "na": na,
    }
    return [
        mk("zmeny_20260715_100000.pdf", "Převod", "zmeny", "2026-07-15", "10:00",
           rz="3BR4008", od="AUTO CARDION S. R. O.", na="JAN NOVÁK"),
        mk("zapis_20260715_113000.pdf", "Nové vozidlo", "zapis", "2026-07-15", "11:30",
           vin="TMBJJ7NE5J0123456", na="TOYOTA FINANCIAL SERVICES CZECH S.R.O."),
        mk("zmeny_20260720_090000.pdf", "Převod", "zmeny", "2026-07-20", "09:00",
           rz="1AB2345", od="AUTO CARDION S. R. O.", na="PETR SVOBODA"),
        mk("zmena_20260610_080000.pdf", "Změna údajů", "zmena", "2026-06-10", "08:00",
           rz="9XY8765"),
    ]


@pytest.fixture
def doklady():
    return [
        {"cislo": 152, "datum": "2026-07-15", "prijato_od": "JAN NOVÁK",
         "castka": 1300, "ucel": "přepis", "vozidlo": "3BR4008"},
        {"cislo": 153, "datum": "2026-07-20", "prijato_od": "AUTO CARDION S. R. O.",
         "castka": 1500, "ucel": "přepis", "vozidlo": "1AB2345"},
        {"cislo": 140, "datum": "2026-06-10", "prijato_od": "PETR VYŠKOV",
         "castka": 1300, "ucel": "změna", "vozidlo": "9XY8765"},
    ]


@pytest.fixture
def firmy():
    return [
        {"nazev": "AUTO CARDION s. r. o.", "ico": "04156854", "adresa": "Brno",
         "psc": "60200", "id": "5", "has_plna_moc": True},
        {"nazev": "Albion Cars s.r.o.", "ico": "04168313", "adresa": "Praha",
         "psc": "11000", "id": "7", "has_plna_moc": False},
    ]


@pytest.fixture
def hledej(vystupy, doklady, firmy):
    return lambda q: hledani.hledej(q, vystupy, doklady, firmy, today=TODAY)


# ── období ────────────────────────────────────────────────────────────────────

def test_parse_period_basic():
    p = lambda q: hledani.parse_period(q, TODAY)
    assert p("co jsem dělal dnes")[:2] == ("2026-07-25", "2026-07-25")
    assert p("včera")[:2] == ("2026-07-24", "2026-07-24")
    assert p("tento měsíc")[:2] == ("2026-07-01", "2026-07-31")
    assert p("minulý měsíc")[:2] == ("2026-06-01", "2026-06-30")
    assert p("letos")[:2] == ("2026-01-01", "2026-12-31")
    assert p("posledních 7 dní")[:2] == ("2026-07-19", "2026-07-25")
    assert p("nic o čase")[2] == "celkem"


def test_cervenec_is_not_parsed_as_cerven():
    """'červenec' contains 'červen' — the longest stem must win (this bit us in
    the sister app)."""
    assert hledani.parse_period("za červenec", TODAY)[:2] == ("2026-07-01", "2026-07-31")
    assert hledani.parse_period("v červnu", TODAY)[:2] == ("2026-06-01", "2026-06-30")
    assert hledani.parse_period("červenec 2025", TODAY)[:2] == ("2025-07-01", "2025-07-31")


def test_explicit_date():
    """David's own phrasing: 'co jsem dělal 15.7.'"""
    assert hledani.parse_period("co jsem dělal 15.7.", TODAY)[:2] == ("2026-07-15", "2026-07-15")
    assert hledani.parse_period("15. 7. 2025", TODAY)[:2] == ("2025-07-15", "2025-07-15")
    # nesmyslné datum se nesmí propsat jako období
    assert hledani.parse_period("32.13.", TODAY)[2] == "celkem"


def test_fold_strips_diacritics():
    assert hledani.fold("VYŠKOV") == "vyskov"
    assert hledani.fold("Červenec") == "cervenec"


def test_czech_plurals_and_money():
    assert hledani._pl(1, "žádost", "žádosti", "žádostí") == "žádost"
    assert hledani._pl(3, "žádost", "žádosti", "žádostí") == "žádosti"
    assert hledani._pl(9, "žádost", "žádosti", "žádostí") == "žádostí"
    assert hledani.kc(12345) == "12 345 Kč"


# ── výstupy ───────────────────────────────────────────────────────────────────

def test_what_did_i_do_on_a_day(hledej):
    r = hledej("co jsem dělal 15.7.")
    assert r["understood"]
    assert "2 žádosti" in r["headline"]
    assert {v["file"] for v in r["vystupy"]} == {
        "zmeny_20260715_100000.pdf", "zapis_20260715_113000.pdf"}
    assert "1× Převod" in r["detail"] and "1× Nové vozidlo" in r["detail"]


def test_records_are_listed_not_just_counted(hledej):
    """Spec bod 2: chci ty záznamy vidět, ne se jen dozvědět číslo."""
    r = hledej("co jsem dělal 15.7.")
    assert r["vystupy"], "musí vypsat konkrétní PDF"
    for v in r["vystupy"]:
        assert v["url"].startswith("/download/"), "musí být klikací"


def test_filter_by_type(hledej):
    r = hledej("poslední zápisy")
    assert [v["kind"] for v in r["vystupy"]] == ["zapis"]
    assert "Nové vozidlo" in r["filters"]


def test_prevody_this_month(hledej):
    r = hledej("převody tento měsíc")
    assert "2 žádosti" in r["headline"]
    assert all(v["kind"] == "zmeny" for v in r["vystupy"])


# ── vozidlo ───────────────────────────────────────────────────────────────────

def test_find_by_rz_across_pdfs_and_receipts(hledej):
    """'kdy jsem tiskl 3BR4008' — spec bod 1."""
    r = hledej("kdy jsem tiskl 3BR4008")
    assert r["understood"]
    assert [v["file"] for v in r["vystupy"]] == ["zmeny_20260715_100000.pdf"]
    assert [d["cislo"] for d in r["doklady"]] == [152]
    assert "15.07.2026" in r["detail"]


def test_plate_matches_across_spacing(vystupy, doklady, firmy):
    """Doklad má v evidenci '1AB 2345', žádost '1AB2345' — musí se najít oba."""
    doklady = [dict(doklady[1], vozidlo="1AB 2345")]
    r = hledani.hledej("1AB2345", vystupy, doklady, firmy, today=TODAY)
    assert [v["file"] for v in r["vystupy"]] == ["zmeny_20260720_090000.pdf"]
    assert [d["cislo"] for d in r["doklady"]] == [153]


def test_find_by_vin(hledej):
    r = hledej("TMBJJ7NE5J0123456")
    assert [v["file"] for v in r["vystupy"]] == ["zapis_20260715_113000.pdf"]


def test_unknown_vehicle_says_so(hledej):
    r = hledej("kdy jsem tiskl 9ZZ9999")
    assert not r["understood"]
    assert "9ZZ9999" in r["headline"]


def test_verb_is_not_mistaken_for_a_plate(hledej):
    """'tiskl' is 5 chars — must not be read as a registration mark."""
    assert hledani._vehicle_terms("kdy jsem tiskl neco") == []
    assert hledani._vehicle_terms("kdy jsem tiskl 3BR4008") == ["3BR4008"]


# ── doklady ───────────────────────────────────────────────────────────────────

def test_receipt_by_number(hledej):
    r = hledej("doklad 152")
    assert r["understood"]
    assert [d["cislo"] for d in r["doklady"]] == [152]
    assert r["doklady"][0]["url"] == "/download/ppd_152.pdf"


def test_receipts_for_month_sum_exactly(hledej):
    r = hledej("doklady za červenec")
    assert "2 doklady" in r["headline"]
    assert "2 800 Kč" in r["headline"]        # 1300 + 1500, spočteno z dat


def test_receipts_by_amount(hledej):
    r = hledej("kdo platil 1300")
    assert {d["cislo"] for d in r["doklady"]} == {152, 140}
    assert "2 doklady" in r["headline"]


def test_receipt_by_payer_ignores_diacritics(hledej):
    """'vyskov' musí najít 'VYŠKOV'."""
    r = hledej("doklad vyskov")
    assert [d["cislo"] for d in r["doklady"]] == [140]


def test_year_is_not_a_receipt_number(hledej):
    """'doklady 2026' se nesmí hledat jako doklad č. 2026."""
    r = hledej("doklady 2026")
    assert len(r["doklady"]) == 3


# ── firmy ─────────────────────────────────────────────────────────────────────

def test_firm_by_name(hledej):
    r = hledej("firma Cardion")
    assert [x["ico"] for x in r["firmy"]] == ["04156854"]


def test_firm_by_ico_shows_id(hledej):
    """David používá ID firmy při vyplňování — musí být ve výsledku."""
    r = hledej("IČO 04156854")
    assert r["firmy"][0]["id"] == "5"


def test_unknown_ico_says_so(hledej):
    r = hledej("IČO 99999999")
    assert not r["understood"]


# ── nerozumím ─────────────────────────────────────────────────────────────────

def test_gibberish_is_honest_and_offers_examples(hledej):
    r = hledej("xyzzy qwertz")
    assert not r["understood"]
    assert r["priklady"], "musí nabídnout klikací příklady"


def test_truncated_list_is_declared(vystupy, doklady, firmy, monkeypatch):
    """Headline řekne 'N žádostí', ale výpis je omezený — UI to musí umět
    přiznat, jinak vypadá zkrácený seznam jako úplný."""
    monkeypatch.setattr(hledani, "LIMIT", 2)
    r = hledani.hledej("co jsem dělal v červenci", vystupy, doklady, firmy, today=TODAY)
    assert "3 žádosti" in r["headline"]     # kolik jich opravdu je
    assert len(r["vystupy"]) == 2           # kolik se jich vypsalo
    assert r["limit"] == 2                  # ať to UI pozná


def test_empty_query(hledej):
    r = hledej("")
    assert not r["understood"] and r["vystupy"] == []


def test_never_invents_records(hledej):
    """Nikdy nesmí vrátit záznam, který není ve vstupních datech."""
    r = hledej("co jsem dělal 1.1.")
    assert r["vystupy"] == [] and r["doklady"] == []


def test_understood_but_empty_is_not_the_same_as_not_understood(hledej):
    """'převody v srpnu' — typu i období rozumíme, jen v nich nic není.
    Tvrdit „nerozumím" by uživatele poslalo hledat chybu v dotazu místo v datech."""
    r = hledej("převody v srpnu")
    assert r["understood"]
    assert "Žádné žádosti" in r["headline"] and "srpen 2026" in r["headline"]
    assert r["vystupy"] == []
    assert "nic nemám" not in r["headline"]


def test_empty_period_without_type(hledej):
    r = hledej("co jsem dělal 3.3.")
    assert r["understood"] and r["vystupy"] == []


# ── index výstupů ─────────────────────────────────────────────────────────────

def test_index_roundtrip(tmp_path):
    d = str(tmp_path)
    hledani.zapis_vystup(d, ["/x/y/zmeny_20260715_100000.pdf"], {
        "registracni_znacka": "3br4008", "vin": "", "znacka": "Škoda",
        "puvodni_jmeno": "A", "novy_jmeno": "B"})
    idx = hledani.nacti_index(d)
    assert idx["zmeny_20260715_100000.pdf"]["rz"] == "3BR4008"   # uppercased


def test_index_never_raises_on_bad_input(tmp_path):
    """Indexace nesmí nikdy shodit generování žádosti."""
    hledani.zapis_vystup("/nonexistent/dir", ["a.pdf"], {})
    hledani.zapis_vystup(str(tmp_path), [], {})


def test_index_survives_corrupt_line(tmp_path):
    d = str(tmp_path)
    with open(os.path.join(d, hledani.INDEX_NAME), "w", encoding="utf-8") as fh:
        fh.write("{neplatny json\n")
        fh.write(json.dumps({"files": ["zapis_20260715_113000.pdf"], "rz": "1AB2345"}) + "\n")
    assert "zapis_20260715_113000.pdf" in hledani.nacti_index(d)


def test_nacti_vystupy_reads_date_from_filename(tmp_path):
    out = tmp_path / "output"
    out.mkdir()
    (out / "zmeny_20260715_100000.pdf").write_bytes(b"x")
    (out / "ppd_152.pdf").write_bytes(b"x")          # doklady sem nepatří
    (out / "neco_jineho.txt").write_bytes(b"x")
    rows = hledani.nacti_vystupy(str(tmp_path))
    assert [r["file"] for r in rows] == ["zmeny_20260715_100000.pdf"]
    assert rows[0]["datum"] == "2026-07-15" and rows[0]["cas"] == "10:00"


# ── názvy souborů ─────────────────────────────────────────────────────────────

def test_filename_carries_who_and_which_car():
    """David hledá ve složce podle toho, PRO KOHO žádost byla — ne podle času."""
    n = hledani.nazev_vystupu("3rz", {
        "novy_jmeno": "Toyota Financial Services Czech s.r.o.",
        "registracni_znacka": "9EE1234"}, "20260808_141632")
    assert n.startswith("3rz_TOYOTA-FINANCIAL")
    assert "9EE1234" in n and n.endswith("_20260808.pdf")
    assert "141632" not in n            # čas jen při kolizi


def test_filename_strips_diacritics_and_punctuation():
    n = hledani.nazev_vystupu("zmeny", {"novy_jmeno": "Škoda Příbram, a. s.",
                                        "registracni_znacka": "1AB 2345"}, "20260808_141632")
    assert n == "zmeny_SKODA-PRIBRAM-A-S_1AB-2345_20260808.pdf"


def test_filename_falls_back_to_vin_and_seller(tmp_path):
    n = hledani.nazev_vystupu("zapis", {"puvodni_jmeno": "PRODEJCE",
                                        "vin": "TMBJJ7NE5J0123456"}, "20260808_141632")
    assert "PRODEJCE" in n and "TMBJJ7NE5J0123456" in n


def test_filename_adds_time_only_on_collision(tmp_path):
    data = {"novy_jmeno": "JAN NOVAK", "registracni_znacka": "1AB2345"}
    first = hledani.nazev_vystupu("3rz", data, "20260808_141632", str(tmp_path))
    (tmp_path / first).write_bytes(b"x")
    second = hledani.nazev_vystupu("3rz", data, "20260808_150000", str(tmp_path))
    assert first != second and second.endswith("_150000.pdf")


def test_filename_survives_a_nameless_zadost():
    n = hledani.nazev_vystupu("zmena", {}, "20260808_141632")
    assert n == "zmena_20260808.pdf"


@pytest.mark.parametrize("name,expected", [
    ("zmeny_20260720_090000.pdf", ("zmeny", "2026-07-20", "09:00")),      # starý tvar
    ("zmeny_PETR-SVOBODA_1AB2345_20260720.pdf", ("zmeny", "2026-07-20", "")),
    ("3rz_TOYOTA_9EE1234_20260808_141632.pdf", ("3rz", "2026-08-08", "14:16")),
    ("zmena_20260808.pdf", ("zmena", "2026-08-08", "")),
    ("ppd_152.pdf", None),
    ("neco.txt", None),
])
def test_both_filename_shapes_are_understood(name, expected):
    """Starých souborů je ve složce ~850 a nepřejmenovávají se — musí jít číst
    dál, jinak by z hledání i z předvyplnění zmizela celá historie."""
    assert hledani.rozbor_nazvu(name) == expected


# ── route ─────────────────────────────────────────────────────────────────────

def test_route_hledat(client):
    r = client.get("/api/hledat?q=poslední zápisy")
    assert r.status_code == 200
    body = r.get_json()
    assert set(body) >= {"understood", "headline", "vystupy", "doklady", "firmy"}


def test_route_hledat_empty_query(client):
    assert client.get("/api/hledat?q=").get_json()["understood"] is False


def test_route_outputs_lists_generated_pdfs(client):
    r = client.get("/api/outputs")
    assert r.status_code == 200
    assert isinstance(r.get_json(), list)
