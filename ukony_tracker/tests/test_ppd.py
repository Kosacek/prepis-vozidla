"""PPD: idempotentní příjem ze zadosti, párování úkonů a přehled dokladů."""
import sqlite3
from datetime import date, timedelta

import pytest

import app as appmod
import config
import db
from repositories import firmy_repo, ppd_repo, prichozi_repo, ukony_repo


def _record(**fields):
    return {
        "cislo": 101, "datum": "14.06.2026", "prijato_od": "  Jan Žižka  ",
        "prijato_ico": " 01234567 ", "castka": 1300, "ucel": "  Převod vozidla ",
        "vozidlo": " 1ab 2345 ", "smazano": False, **fields,
    }


@pytest.fixture
def firma_id(conn):
    return firmy_repo.create(conn, nazev="Cardion", zkratka="Cardion", ico="04156854")


def _ukon(conn, firma_id, **fields):
    return ukony_repo.create(conn, **{
        "firma_id": firma_id, "datum": "2026-06-14", "typ_kod": "PŘEVOD",
        "celkem": 1300, "rz": "1AB2345", **fields,
    })


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Veškerá data i zálohy zůstávají v testovacím adresáři.
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "")
    monkeypatch.setattr(config, "INTEGRATION_API_KEY", "")
    a = appmod.create_app()
    a.testing = True
    with a.test_client() as c:
        yield c


def test_schema_is_idempotent_and_indexes_datum(conn):
    row, _ = ppd_repo.upsert(conn, _record())
    db.init_schema(conn)
    assert dict(ppd_repo.get_by_cislo(conn, 101)) == dict(row)
    assert "idx_ppd_datum" in {
        index["name"] for index in conn.execute("PRAGMA index_list(ppd)")
    }
    assert [r["name"] for r in conn.execute("PRAGMA index_info(idx_ppd_datum)")] == ["datum"]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO ppd(cislo,datum,castka,created_at,updated_at) VALUES(101,?,?,?,?)",
            ("2026-06-14", 1300, "x", "x"),
        )
    conn.rollback()


def test_upsert_create_update_and_identical_retry(conn, monkeypatch):
    monkeypatch.setattr(db, "now_iso", lambda: "2026-06-14T10:00:00+00:00")
    original, created = ppd_repo.upsert(conn, _record())
    assert created is True
    assert original["prijato_od"] == "JAN ŽIŽKA"
    assert original["prijato_ico"] == "01234567"
    assert original["ucel"] == "PŘEVOD VOZIDLA"
    assert original["vozidlo"] == "1AB 2345"
    assert original["ukon_id"] is None

    monkeypatch.setattr(db, "now_iso", lambda: "2026-06-14T11:00:00+00:00")
    same, created = ppd_repo.upsert(conn, _record(datum="2026-06-14", prijato_od="JAN ŽIŽKA"))
    assert created is False
    assert dict(same) == dict(original)

    updated, created = ppd_repo.upsert(conn, _record(castka=1800, prijato_od="  Petra Nová  "))
    assert created is False
    assert updated["id"] == original["id"]
    assert updated["castka"] == 1800 and updated["prijato_od"] == "PETRA NOVÁ"
    assert updated["created_at"] == original["created_at"]
    assert updated["updated_at"] == "2026-06-14T11:00:00+00:00"
    assert len(ppd_repo.list(conn)) == 1


@pytest.mark.parametrize("datum", ["14.06.2026", "2026-06-14", " 14.06.2026 "])
def test_datum_is_stored_as_iso(conn, datum):
    row, _ = ppd_repo.upsert(conn, _record(datum=datum))
    assert row["datum"] == "2026-06-14"


def test_link_via_zadost_id_takes_priority_over_vehicle(conn, firma_id):
    # ID žádosti má přednost i mimo časové okno; vozidlo ukazuje na jiný úkon.
    uid = _ukon(conn, firma_id, datum="2026-01-01", rz="9ZZ9999")
    _ukon(conn, firma_id)
    pid = prichozi_repo.create(
        conn, zadost_id="request-a", datum="2026-01-01", mode="prevod", status="auto",
    )
    prichozi_repo.update(conn, pid, created_ukon_id=uid)
    row, _ = ppd_repo.upsert(conn, _record(zadost_id="  request-a  "))
    assert row["zadost_id"] == "REQUEST-A"
    assert row["ukon_id"] == uid


@pytest.mark.parametrize("zadost_id", ["unknown", "pending"])
def test_unlinked_zadost_falls_back_to_vehicle(conn, firma_id, zadost_id):
    uid = _ukon(conn, firma_id)
    prichozi_repo.create(conn, zadost_id="pending", datum="2026-06-14", mode="prevod")
    row, _ = ppd_repo.upsert(conn, _record(zadost_id=zadost_id))
    assert row["ukon_id"] == uid


def test_zadost_id_is_matched_exactly_before_text_normalization(conn, firma_id):
    uid = _ukon(conn, firma_id)
    pid = prichozi_repo.create(conn, zadost_id="request-a", datum="2026-06-14", mode="prevod")
    prichozi_repo.update(conn, pid, created_ukon_id=uid)
    row, _ = ppd_repo.upsert(conn, _record(zadost_id="REQUEST-A", vozidlo=""))
    assert row["ukon_id"] is None


@pytest.mark.parametrize("column,vehicle", [
    ("rz", "1ab2345"), ("vin", "tmb12345678901234"),
])
@pytest.mark.parametrize("offset,linked", [(-8, False), (-7, True), (0, True), (7, True), (8, False)])
def test_link_by_vehicle_within_seven_days(conn, firma_id, column, vehicle, offset, linked):
    datum = (date(2026, 6, 14) + timedelta(days=offset)).isoformat()
    # Porovnání ignoruje velikost písmen i vnitřní bílé znaky na obou stranách.
    uid = _ukon(conn, firma_id, **{
        "datum": datum, column: "  " + vehicle[:3] + "\t" + vehicle[3:] + "  ",
    })
    row, _ = ppd_repo.upsert(conn, _record(vozidlo=vehicle[:2] + "\u00a0" + vehicle[2:]))
    assert row["ukon_id"] == (uid if linked else None)


def test_ambiguous_vehicle_is_not_linked(conn, firma_id):
    _ukon(conn, firma_id, datum="2026-06-07")
    _ukon(conn, firma_id, datum="2026-06-21", rz=None, vin="1ab 2345")
    row, _ = ppd_repo.upsert(conn, _record())
    assert row["ukon_id"] is None


def test_same_ukon_matching_rz_and_vin_is_only_one_match(conn, firma_id):
    uid = _ukon(conn, firma_id, vin="1AB 2345")
    row, _ = ppd_repo.upsert(conn, _record())
    assert row["ukon_id"] == uid


def test_blank_vehicle_does_not_link_blank_ukon(conn, firma_id):
    _ukon(conn, firma_id, rz="", vin=None)
    row, _ = ppd_repo.upsert(conn, _record(vozidlo="  "))
    assert row["ukon_id"] is None


def test_existing_link_is_not_wiped_by_unmatched_update(conn, firma_id):
    uid = _ukon(conn, firma_id)
    ppd_repo.upsert(conn, _record())
    row, created = ppd_repo.upsert(conn, _record(datum="2026-10-08", vozidlo="9ZZ9999"))
    assert created is False
    assert row["datum"] == "2026-10-08" and row["vozidlo"] == "9ZZ9999"
    assert row["ukon_id"] == uid


def test_retry_can_link_receipt_after_zadost_arrives(conn, firma_id):
    row, _ = ppd_repo.upsert(conn, _record(vozidlo="", zadost_id="later"))
    assert row["ukon_id"] is None
    uid = _ukon(conn, firma_id)
    pid = prichozi_repo.create(conn, zadost_id="later", datum="2026-06-14", mode="prevod")
    prichozi_repo.update(conn, pid, created_ukon_id=uid)
    row, created = ppd_repo.upsert(conn, _record(vozidlo="", zadost_id="later"))
    assert created is False and row["ukon_id"] == uid


def test_smazano_toggle_keeps_receipt_and_can_restore_it(conn):
    original, _ = ppd_repo.upsert(conn, _record())
    deleted, created = ppd_repo.upsert(conn, _record(smazano=True))
    assert created is False and deleted["id"] == original["id"]
    assert ppd_repo.get_by_cislo(conn, 101)["smazano"] == 1
    assert ppd_repo.list(conn) == []
    assert len(ppd_repo.list(conn, include_deleted=True)) == 1
    assert ppd_repo.totals(conn, None, None) == {"pocet": 0, "castka": 0}
    restored, created = ppd_repo.upsert(conn, _record(smazano=False))
    assert created is False and restored["id"] == original["id"]
    assert restored["smazano"] == 0 and len(ppd_repo.list(conn)) == 1


def test_list_and_totals_share_filters_and_inclusive_bounds(conn):
    for record in [
        _record(cislo=1, datum="2026-05-31", castka=100),
        _record(cislo=2, datum="2026-06-01", castka=200),
        _record(cislo=3, datum="2026-06-30", castka=300, prijato_od="Petra Nová"),
        _record(cislo=4, datum="2026-07-01", castka=400),
        _record(cislo=5, datum="2026-06-30", castka=500, smazano=True),
    ]:
        ppd_repo.upsert(conn, record)
    assert [r["cislo"] for r in ppd_repo.list(conn, "2026-06-01", "2026-06-30")] == [3, 2]
    assert ppd_repo.totals(conn, "2026-06-01", "2026-06-30") == {"pocet": 2, "castka": 500}
    assert ppd_repo.totals(conn, "2026-06-01", "2026-06-30", q="nová") == {"pocet": 1, "castka": 300}
    assert [r["cislo"] for r in ppd_repo.list(conn, od="2026-06-30")] == [4, 3]
    assert [r["cislo"] for r in ppd_repo.list(conn, do="2026-06-01")] == [2, 1]
    assert len(ppd_repo.list(conn, limit=1)) == 1
    assert ppd_repo.totals(conn, None, None)["pocet"] == 4
    assert ppd_repo.totals(conn, "2026-06-01", "2026-06-30", include_deleted=True) == {
        "pocet": 3, "castka": 1000,
    }


@pytest.mark.parametrize("query", ["žižka", "1ab", "101"])
def test_search_payer_vehicle_and_number(conn, query):
    ppd_repo.upsert(conn, _record())
    ppd_repo.upsert(conn, _record(cislo=202, prijato_od="Petra Nová", vozidlo="9ZZ9999"))
    assert [r["cislo"] for r in ppd_repo.list(conn, q=query)] == [101]


def test_search_treats_sql_wildcards_as_literal_text(conn):
    ppd_repo.upsert(conn, _record())
    assert ppd_repo.list(conn, q="%") == []
    assert ppd_repo.list(conn, q="_") == []


def test_default_list_limit_does_not_truncate_search_or_totals(conn):
    conn.executemany(
        "INSERT INTO ppd(cislo,datum,prijato_od,castka,created_at,updated_at)"
        " VALUES(?, '2026-06-14', ?, 10, 'x', 'x')",
        [(n, "HLEDANÝ" if n == 1 else "OSTATNÍ") for n in range(1, 502)],
    )
    conn.commit()
    rows = ppd_repo.list(conn)
    assert len(rows) == 500 and rows[0]["cislo"] == 501 and rows[-1]["cislo"] == 2
    assert ppd_repo.totals(conn, None, None) == {"pocet": 501, "castka": 5010}
    assert [r["cislo"] for r in ppd_repo.list(conn, q="hledaný")] == [1]
    assert ppd_repo.totals(conn, None, None, q="hledaný") == {"pocet": 1, "castka": 10}


def test_put_create_update_and_idempotent_retry(client):
    created = client.put("/api/ppd/101", json=_record())
    assert created.status_code == 201
    assert created.get_json()["datum"] == "2026-06-14"
    same = client.put("/api/ppd/101", json=_record())
    assert same.status_code == 200 and same.get_json() == created.get_json()
    updated = client.put("/api/ppd/101", json=_record(castka=0, smazano=True))
    assert updated.status_code == 200
    assert updated.get_json()["castka"] == 0 and updated.get_json()["smazano"] == 1


def test_put_accepts_number_from_url_when_body_omits_it(client):
    record = _record()
    del record["cislo"]
    response = client.put("/api/ppd/101", json=record)
    assert response.status_code == 201 and response.get_json()["cislo"] == 101


@pytest.mark.parametrize("fields", [
    {"cislo": 102}, {"cislo": "101"}, {"cislo": True}, {"cislo": None},
    {"castka": -1}, {"castka": 1.5}, {"castka": "1300"}, {"castka": True},
    {"castka": None}, {"castka": 2**63}, {"datum": "31.02.2026"},
    {"datum": "bad"}, {"datum": None}, {"prijato_od": []}, {"smazano": "false"},
])
def test_put_validation_returns_json_error_and_keeps_existing_row(client, fields):
    original = client.put("/api/ppd/101", json=_record()).get_json()
    response = client.put("/api/ppd/101", json=_record(**fields))
    assert response.status_code == 400
    assert isinstance(response.get_json()["error"], str)
    with client.application.app_context():
        assert dict(ppd_repo.get_by_cislo(db.get_db(), 101)) == original


@pytest.mark.parametrize("payload", [None, [], "text", {}])
def test_put_rejects_invalid_or_empty_body(client, payload):
    assert client.put("/api/ppd/101", json=payload).status_code == 400


@pytest.mark.parametrize("method,path,payload", [
    ("PUT", "/api/ppd/101", _record()),
    ("POST", "/api/ppd/import", {"doklady": [_record()]}),
])
def test_ppd_api_requires_correct_key_even_with_logged_in_session(client, monkeypatch, method, path, payload):
    monkeypatch.setattr(config, "INTEGRATION_API_KEY", "ppd-secret")
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "login-secret")
    with client.session_transaction() as session:
        session["authed"] = True
    for headers in ({}, {"X-Api-Key": "wrong"}):
        response = client.open(path, method=method, json=payload, headers=headers)
        assert response.status_code == 401
        assert response.get_json() == {"error": "unauthorized"}
    with client.session_transaction() as session:
        session.clear()
    response = client.open(path, method=method, json=payload, headers={"X-Api-Key": "ppd-secret"})
    assert response.status_code == (201 if method == "PUT" else 200)
    with client.application.app_context():
        assert len(ppd_repo.list(db.get_db())) == 1


def test_import_continues_after_bad_row_and_counts_retries(client):
    client.put("/api/ppd/101", json=_record())
    response = client.post("/api/ppd/import", json={"doklady": [
        _record(castka=1500), _record(cislo=102),
        _record(cislo=103, datum="31.02.2026"), _record(cislo=104),
    ]})
    assert response.status_code == 200
    body = response.get_json()
    assert body["vytvoreno"] == 2 and body["aktualizovano"] == 1
    assert len(body["chyby"]) == 1 and body["chyby"][0]["cislo"] == 103
    assert body["chyby"][0]["error"]
    with client.application.app_context():
        conn = db.get_db()
        assert [r["cislo"] for r in ppd_repo.list(conn)] == [104, 102, 101]
        assert ppd_repo.get_by_cislo(conn, 101)["castka"] == 1500
        assert ppd_repo.get_by_cislo(conn, 103) is None
    retry = client.post("/api/ppd/import", json={"doklady": [_record(cislo=102)]}).get_json()
    assert retry == {"vytvoreno": 0, "aktualizovano": 1, "chyby": []}


def test_import_reports_non_object_and_missing_number_without_aborting(client):
    record = _record()
    del record["cislo"]
    body = client.post("/api/ppd/import", json={"doklady": [None, record, _record()]}).get_json()
    assert body["vytvoreno"] == 1 and body["aktualizovano"] == 0
    assert len(body["chyby"]) == 2
    assert all(error["cislo"] is None and error["error"] for error in body["chyby"])


@pytest.mark.parametrize("payload", [None, [], {}, {"doklady": {}}, {"doklady": None}])
def test_import_rejects_invalid_envelope(client, payload):
    response = client.post("/api/ppd/import", json=payload)
    assert response.status_code == 400 and response.get_json()["error"]


def test_doklady_renders_link_and_hides_deleted_by_default(client):
    with client.application.app_context():
        conn = db.get_db()
        fid = firmy_repo.create(conn, nazev="Cardion", zkratka="Cardion")
        uid = _ukon(conn, fid)
        ppd_repo.upsert(conn, _record())
        ppd_repo.upsert(conn, _record(cislo=102, smazano=True))
    response = client.get("/doklady")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert '<a href="/doklady">Doklady</a>' in body
    assert 'data-cislo="101"' in body and 'data-cislo="102"' not in body
    assert "14.06.2026" in body and "JAN ŽIŽKA" in body and "1AB 2345" in body
    assert f'href="/ukony/{uid}/upravit"' in body
    assert '<span id="doklady-count">1</span>' in body
    assert '<span id="doklady-sum">1\u00a0300</span>' in body
    body = client.get("/doklady?smazane=1").get_data(as_text=True)
    assert 'data-cislo="102"' in body and "smazaný" in body
    assert '<span id="doklady-count">2</span>' in body
    assert '<span id="doklady-sum">2\u00a0600</span>' in body


@pytest.mark.parametrize("query", ["nová", "9zz", "102"])
def test_doklady_filters_month_and_search_and_updates_header(client, query):
    with client.application.app_context():
        conn = db.get_db()
        ppd_repo.upsert(conn, _record())
        ppd_repo.upsert(conn, _record(cislo=102, datum="30.06.2026", castka=700,
                                    prijato_od="Petra Nová", vozidlo="9ZZ9999"))
        ppd_repo.upsert(conn, _record(cislo=103, datum="01.07.2026", prijato_od="Petra Nová", vozidlo="9ZZ9999"))
        ppd_repo.upsert(conn, _record(cislo=104, smazano=True, prijato_od="Petra Nová", vozidlo="9ZZ9999"))
    response = client.get("/doklady", query_string={"mesic": "2026-06", "q": query})
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'data-cislo="102"' in body
    assert all(f'data-cislo="{n}"' not in body for n in (101, 103, 104))
    assert '<span id="doklady-count">1</span>' in body
    assert '<span id="doklady-sum">700</span>' in body
    assert 'name="mesic" value="2026-06"' in body
    assert f'name="q" value="{query}"' in body


def test_doklady_month_filter_without_search_includes_boundaries(client):
    for number, datum in [(1, "31.05.2026"), (2, "01.06.2026"), (3, "30.06.2026"), (4, "01.07.2026")]:
        client.put(f"/api/ppd/{number}", json=_record(cislo=number, datum=datum))
    body = client.get("/doklady?mesic=2026-06").get_data(as_text=True)
    assert all(f'data-cislo="{n}"' in body for n in (2, 3))
    assert all(f'data-cislo="{n}"' not in body for n in (1, 4))
    assert body.index('data-cislo="3"') < body.index('data-cislo="2"')


def test_doklady_empty_filter_shows_zero_totals(client):
    client.put("/api/ppd/101", json=_record())
    body = client.get("/doklady?mesic=2026-01").get_data(as_text=True)
    assert "Žádné doklady neodpovídají filtru." in body
    assert '<span id="doklady-count">0</span>' in body
    assert '<span id="doklady-sum">0</span>' in body


@pytest.mark.parametrize("mesic", ["bad", "2026-13", "2026-00", "0000-01", "2026-1"])
def test_doklady_rejects_invalid_month(client, mesic):
    assert client.get("/doklady", query_string={"mesic": mesic}).status_code == 400


def test_doklady_uses_existing_login_gate(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "secret")
    response = client.get("/doklady")
    assert response.status_code == 302 and "/login" in response.headers["Location"]
    with client.session_transaction() as session:
        session["authed"] = True
    assert client.get("/doklady").status_code == 200
