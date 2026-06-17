"""žádost → úkon intake: matching, prichozi repo, and the intake decision."""
import sqlite3

import pytest

from repositories import firmy_repo, typy_repo, ukony_repo, prichozi_repo
from services import matching_service, prichozi_service


def _firms(conn):
    cardion = firmy_repo.create(conn, nazev="Cardion s.r.o.", zkratka="Cardion", ico="11111111")
    albion = firmy_repo.create(conn, nazev="Albion", zkratka="Albion", ico="22222222")
    firmy_repo.create(conn, nazev="Stará", zkratka="Stará", ico="99999999", aktivni=0)
    typy_repo.upsert(conn, "PŘEVOD", 1300, 1)
    typy_repo.upsert(conn, "NOVÉ", 1500, 2)
    return cardion, albion


# ── matching_service ─────────────────────────────────────────────────────────

def test_match_single(conn):
    c, _ = _firms(conn)
    m = matching_service.match(conn, [None, "11111111"])
    assert m["firma_id"] == c and not m["ambiguous"]


def test_match_normalizes_ico(conn):
    c, _ = _firms(conn)
    m = matching_service.match(conn, ["111 111 11", "CZ11111111"])  # spaces/prefix stripped
    assert m["firma_id"] == c


def test_match_none(conn):
    _firms(conn)
    m = matching_service.match(conn, [None, "00000000", ""])
    assert m["firma_id"] is None and not m["ambiguous"]


def test_match_ambiguous_two_firms(conn):
    _firms(conn)
    m = matching_service.match(conn, ["11111111", "22222222"])
    assert m["firma_id"] is None and m["ambiguous"] and len(m["matched"]) == 2


def test_match_same_firm_both_sides_is_single(conn):
    c, _ = _firms(conn)
    m = matching_service.match(conn, ["11111111", "11111111"])
    assert m["firma_id"] == c and not m["ambiguous"]


def test_match_ignores_inactive_firm(conn):
    _firms(conn)
    m = matching_service.match(conn, ["99999999"])  # the inactive firm's IČO
    assert m["firma_id"] is None


# ── prichozi_repo ─────────────────────────────────────────────────────────────

def test_prichozi_unique_zadost_id(conn):
    pid = prichozi_repo.create(conn, zadost_id="z1", datum="2026-06-14", mode="prevod", raw={"a": 1})
    assert prichozi_repo.get(conn, pid)["zadost_id"] == "z1"
    with pytest.raises(sqlite3.IntegrityError):
        prichozi_repo.create(conn, zadost_id="z1", datum="2026-06-14", mode="prevod")


def test_prichozi_count_and_status(conn):
    prichozi_repo.create(conn, zadost_id="z1", datum="2026-06-14", mode="prevod")
    p2 = prichozi_repo.create(conn, zadost_id="z2", datum="2026-06-14", mode="zmena")
    assert prichozi_repo.count_pending(conn) == 2
    prichozi_repo.update(conn, p2, status="discarded")
    assert prichozi_repo.count_pending(conn) == 1
    assert len(prichozi_repo.list_by_status(conn, "discarded")) == 1


# ── prichozi_service.intake ───────────────────────────────────────────────────

def test_intake_auto_creates_on_single_match(conn):
    c, _ = _firms(conn)
    res = prichozi_service.intake(conn, {
        "zadost_id": "zz1", "mode": "prevod", "datum": "2026-06-14",
        "rz": "1ab2345", "vin": "tmbvin1234567890", "orv": "abc123456",
        "novy_ico": "11111111", "novy_jmeno": "Cardion s.r.o.",
        "puvodni_jmeno": "Jan Novák",
    })
    assert res["status"] == "auto"
    u = ukony_repo.get(conn, res["ukon_id"])
    assert u["firma_id"] == c
    assert u["typ_kod"] == "PŘEVOD"
    assert u["celkem"] == 1300
    assert u["rz"] == "1AB2345"            # uppercased
    assert u["orv"] == "ABC123456"
    assert u["vin"] == "TMBVIN1234567890"  # full VIN, uppercased
    assert u["zdroj"] == "zadosti"
    assert u["datum"] == "2026-06-14"      # payload date, never recomputed
    assert u["poznamka"] == "Cardion s.r.o. ← Jan Novák"
    pr = prichozi_repo.get(conn, res["prichozi_id"])
    assert pr["status"] == "auto" and pr["created_ukon_id"] == res["ukon_id"]


def test_intake_queues_when_no_match(conn):
    _firms(conn)
    res = prichozi_service.intake(conn, {
        "zadost_id": "zz2", "mode": "prevod", "datum": "2026-06-14", "novy_ico": "00000000",
    })
    assert res["status"] == "pending"
    assert prichozi_repo.get(conn, res["prichozi_id"])["status"] == "pending"


def test_intake_zmena_always_queues_even_if_matched(conn):
    c, _ = _firms(conn)
    res = prichozi_service.intake(conn, {
        "zadost_id": "zz3", "mode": "zmena", "datum": "2026-06-14", "novy_ico": "11111111",
    })
    assert res["status"] == "pending"
    pr = prichozi_repo.get(conn, res["prichozi_id"])
    assert pr["status"] == "pending"
    assert pr["suggested_firma_id"] == c   # still suggests the firm for the inbox


def test_intake_ambiguous_queues(conn):
    _firms(conn)
    res = prichozi_service.intake(conn, {
        "zadost_id": "zz4", "mode": "prevod", "datum": "2026-06-14",
        "puvodni_ico": "11111111", "novy_ico": "22222222",
    })
    assert res["status"] == "pending"


def test_intake_duplicate_zadost_id_is_noop(conn):
    _firms(conn)
    p = {"zadost_id": "dup", "mode": "prevod", "datum": "2026-06-14", "novy_ico": "11111111"}
    r1 = prichozi_service.intake(conn, p)
    r2 = prichozi_service.intake(conn, p)
    assert r1["status"] == "auto"
    assert r2["status"] == "duplicate"
    assert len(ukony_repo.list(conn)) == 1   # exactly one úkon, no double


def test_intake_auto_price_zero_when_type_missing(conn):
    firmy_repo.create(conn, nazev="C", zkratka="C", ico="11111111")  # no typy seeded
    res = prichozi_service.intake(conn, {
        "zadost_id": "zz5", "mode": "prevod", "datum": "2026-06-14", "novy_ico": "11111111",
    })
    assert res["status"] == "auto"
    assert ukony_repo.get(conn, res["ukon_id"])["celkem"] == 0


def test_intake_orv_only_when_both_parts(conn):
    assert prichozi_service.build_orv("ABC", "123456") == "ABC123456"
    assert prichozi_service.build_orv("ABC", "") is None
    assert prichozi_service.build_orv("", "123456") is None
    assert prichozi_service.build_orv(None, None) is None


def test_export_csv_includes_orv(conn):
    from services import ingest_service, export_service
    fid = firmy_repo.create(conn, nazev="C", zkratka="C", ico="1")
    ingest_service.pridat_ukon(conn, firma_id=fid, datum="2026-06-14",
                               typ_kod="PŘEVOD", celkem=1300, orv="ABC123456")
    csv = export_service.export_csv(conn, "2026-06-01", "2026-06-30")
    assert "orv" in csv.splitlines()[0]    # header column present
    assert "ABC123456" in csv              # value exported


def test_export_excel_has_orv_header(conn):
    import io
    import openpyxl
    from services import ingest_service, export_service
    fid = firmy_repo.create(conn, nazev="C", zkratka="C", ico="1")
    ingest_service.pridat_ukon(conn, firma_id=fid, datum="2026-06-14",
                               typ_kod="PŘEVOD", celkem=1300, orv="ABC123456")
    data = export_service.export_excel(conn, "2026-06-01", "2026-06-30")
    wb = openpyxl.load_workbook(io.BytesIO(data))
    ws = wb[wb.sheetnames[0]]
    header = [c.value for c in ws[1]]
    assert "ORV" in header
    orv_col = header.index("ORV")
    assert ws[2][orv_col].value == "ABC123456"
