"""Doklad ↔ úkony: which úkony a doklad (PPD) pays, computed fresh on every read."""
import pytest

from repositories import firmy_repo, ppd_repo, ukony_repo
from services import ppd_links


@pytest.fixture
def jene(conn):
    return firmy_repo.create(conn, nazev="JE & NE, spol. s r.o.", zkratka="JE & NE", ico="44960263")


@pytest.fixture
def cardion(conn):
    return firmy_repo.create(conn, nazev="AUTO CARDION s. r. o.", zkratka="Cardion", ico="04156854")


def ukon(conn, firma_id, datum="2026-10-07", **fields):
    return ukony_repo.create(conn, **{"firma_id": firma_id, "datum": datum, "typ_kod": "NOVÉ",
                                      "celkem": 1300, **fields})


def doklad(conn, cislo, vozidlo, datum="2026-10-08", castka=1300, **fields):
    row, _ = ppd_repo.upsert(conn, {"cislo": cislo, "datum": datum, "castka": castka,
                                    "prijato_od": "JE & NE, SPOL. S R.O.", "vozidlo": vozidlo,
                                    **fields})
    return row


def test_one_doklad_with_five_cars_links_all_five(conn, jene):
    # Doklad č. 179 (8. 10.): three plates and two VINs, úkony from 6.–7. 10.
    ids = [ukon(conn, jene, datum="2026-10-06", rz="3BR9196"),
           ukon(conn, jene, rz="2BP1720"), ukon(conn, jene, rz="3BR5699"),
           ukon(conn, jene, vin="TMBJR0NX6VY010010"), ukon(conn, jene, vin="TMBGR6NW6V3090605")]
    doklad(conn, 179, "3BR9196, 2BP1720; 3br 5699,\nTMBJR0NX6VY010010, TMBGR6NW6V3090605",
           castka=6500)
    links = ppd_links.compute(conn)
    assert links.by_doklad[179] == sorted(ids)
    assert links.missing[179] == []
    assert all(links.by_ukon[i] == [179] for i in ids)
    assert links.firma[179] == jene


def test_doklad_older_than_its_ukon_still_links(conn, jene):
    # č. 182 arrived before its úkon was created; links are computed on read, not on push.
    doklad(conn, 182, "5XYRLDLCXMG039299", datum="2026-10-22")
    assert ppd_links.compute(conn).by_doklad[182] == []
    uid = ukon(conn, jene, datum="2026-10-22", vin="5XYRLDLCXMG039299")
    assert ppd_links.compute(conn).by_doklad[182] == [uid]


@pytest.mark.parametrize("days,linked", [(-14, True), (14, True), (-15, False), (15, False)])
def test_window_is_fourteen_days_each_way(conn, jene, days, linked):
    from datetime import date, timedelta
    uid = ukon(conn, jene, datum=(date(2026, 10, 8) + timedelta(days=days)).isoformat(), rz="1AB2345")
    doklad(conn, 1, "1AB2345")
    links = ppd_links.compute(conn)
    assert links.by_doklad[1] == ([uid] if linked else [])
    assert links.missing[1] == ([] if linked else ["1AB2345"])


def test_nearest_ukon_of_the_same_car_wins(conn, jene):
    older = ukon(conn, jene, datum="2026-09-13", rz="2BR3906")
    newer = ukon(conn, jene, datum="2026-09-15", rz="2BR3906")
    doklad(conn, 139, "2BR3906", datum="2026-09-15")
    doklad(conn, 135, "2BR3906", datum="2026-09-13")
    links = ppd_links.compute(conn)
    assert links.by_doklad[139] == [newer] and links.by_doklad[135] == [older]


def test_same_day_tie_prefers_the_ukon_with_the_doklad_amount(conn, jene):
    nove = ukon(conn, jene, datum="2026-08-17", vin="LRW3E7FS0TC898843", celkem=1700)
    ukon(conn, jene, datum="2026-08-17", vin="LRW3E7FS0TC898843", typ_kod="3RZ", celkem=700)
    doklad(conn, 103, "LRW3E7FS0TC898843", datum="2026-08-17", castka=1700)
    assert ppd_links.compute(conn).by_doklad[103] == [nove]


def test_same_day_tie_without_amount_match_links_both(conn, jene):
    a = ukon(conn, jene, datum="2026-08-17", rz="1AB2345", celkem=500)
    b = ukon(conn, jene, datum="2026-08-17", rz="1AB2345", celkem=700)
    doklad(conn, 104, "1AB2345", datum="2026-08-17", castka=9999)
    assert ppd_links.compute(conn).by_doklad[104] == sorted([a, b])


def test_explicit_links_win_and_ignore_the_window(conn, jene):
    old = ukon(conn, jene, datum="2026-07-01", rz="9ZZ9999")
    near = ukon(conn, jene, datum="2026-10-08", rz="9ZZ9999")
    doklad(conn, 200, "9ZZ9999")
    ppd_links.set_explicit(conn, 200, [old])
    links = ppd_links.compute(conn)
    assert links.by_doklad[200] == [old] and near not in links.by_ukon
    assert links.missing[200] == []


def test_zadost_id_links_the_ukon_created_from_that_zadost(conn, jene):
    uid = ukon(conn, jene, datum="2026-06-01", rz="4AB4444")
    conn.execute("INSERT INTO prichozi(zadost_id, received_at, mode, status, created_ukon_id,"
                 " created_at, updated_at) VALUES('Z-1', 'x', 'prevod', 'auto', ?, 'x', 'x')", (uid,))
    conn.commit()
    doklad(conn, 300, "", zadost_id="Z-1")
    assert ppd_links.compute(conn).by_doklad[300] == [uid]


def test_deleted_doklad_links_nothing(conn, jene):
    uid = ukon(conn, jene, rz="1AB2345")
    doklad(conn, 1, "1AB2345", smazano=True)
    links = ppd_links.compute(conn)
    assert 1 not in links.by_doklad and uid not in links.by_ukon


def test_unknown_car_is_reported_missing(conn, jene):
    found = ukon(conn, jene, rz="1AB2345")
    doklad(conn, 5, "1AB2345, 7ZZ0000")
    links = ppd_links.compute(conn)
    assert links.by_doklad[5] == [found] and links.missing[5] == ["7ZZ0000"]


def test_firm_is_the_firm_of_its_ukony_else_payer_ico(conn, jene, cardion):
    ukon(conn, jene, rz="1AB2345")
    doklad(conn, 181, "1AB2345", prijato_od="LEGENDARY. S R.O.", prijato_ico="")
    doklad(conn, 400, "", prijato_ico="04156854")
    doklad(conn, 401, "", prijato_ico="")
    links = ppd_links.compute(conn)
    assert links.firma[181] == jene
    assert links.firma[400] == cardion
    assert links.firma[401] is None


def test_reverse_map_lists_doklady_by_number(conn, jene):
    uid = ukon(conn, jene, rz="1AB2345")
    doklad(conn, 12, "1AB2345")
    doklad(conn, 7, "1AB2345")
    assert ppd_links.compute(conn).by_ukon[uid] == [7, 12]
