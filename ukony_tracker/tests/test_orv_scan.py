"""Offline scan contract, atomic fill matrix, upload and session boundaries."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace as NS

import pytest

import app as appmod
import config
import db
from repositories import firma_ceny_repo, firmy_repo, typy_repo, ukony_repo
from services import orv_images, orv_scan_service as scan
from services.ingest_service import pridat_ukon

VIN = "TMBEK6NW7M3158470"
RECENT = date.today().isoformat()   # inside the match window
DATA = {"typ": "orv", "rz": "5AB1234", "vin": VIN, "orv_cislo": "UBE037263",
        "provozovatel": "BSAuto s.r.o."}


class FakeClient:
    def __init__(self, data=None, error=None):
        self.data = DATA.copy() if data is None else data
        self.error = error
        self.messages = self
        self.calls = []

    def with_options(self, **options):
        assert options == {"timeout": 45, "max_retries": 0}
        return self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return NS(content=[NS(type="thinking", thinking="private"),
                           NS(type="tool_use", name="zapsat_dokument", input=self.data)],
                  usage=NS(input_tokens=100, output_tokens=25), stop_reason="tool_use")


def test_extract_normalizes_and_uses_strict_tool():
    fake = FakeClient({"typ": "orv", "rz": " 5ab-12 34 ", "vin": "tmb-ek6nw7m3158470",
                       "orv_cislo": " ube\t037-263 ", "provozovatel": " BSAuto   s.r.o. "})
    assert scan.extract(b"photo", "image/jpeg", client=fake) == DATA
    call = fake.calls[0]
    assert call["model"] == "claude-haiku-5-5"
    assert call["max_tokens"] == 1024
    assert call["output_config"] == {"effort": "low"}
    assert call["thinking"] == {"type": "disabled"}
    assert not {"temperature", "top_p", "top_k", "tool_choice"} & call.keys()
    assert len(call["tools"]) == 1 and call["tools"][0]["strict"] is True
    schema = call["tools"][0]["input_schema"]
    assert set(schema["required"]) == set(DATA)
    assert schema["additionalProperties"] is False
    assert schema["properties"]["orv_cislo"]["type"] == ["string", "null"]
    assert schema["properties"]["provozovatel"]["type"] == ["string", "null"]
    assert call["messages"][0]["content"][0]["source"] == {
        "type": "base64", "media_type": "image/jpeg", "data": "cGhvdG8="}
    assert scan.tokens.get() == 125


@pytest.fixture(autouse=True)
def no_registry_network(monkeypatch):
    monkeypatch.setattr(scan.orv_service, "lookup_vin", lambda _orv: {"success": False, "error": "offline"})


@pytest.mark.parametrize("field,value", [
    ("rz", "1234"), ("rz", "123456789"), ("rz", "ABC!123"), ("rz", 12345),
    ("vin", "AB12"), ("vin", "A" * 18), ("orv_cislo", "UB0037263"),
    ("orv_cislo", "UB037263"), ("orv_cislo", "UBE03726O"), ("orv_cislo", "UBE０３７２６３"),
])
def test_invalid_fields_are_null_never_repaired(field, value):
    result = scan.extract(b"photo", "image/png", client=FakeClient({**DATA, field: value}))
    assert result[field] is None


def test_no_legible_fields_and_missing_tool():
    result = scan.extract(b"p", "image/jpeg", client=FakeClient(dict.fromkeys(DATA, None) | {"typ": "orv"}))
    assert result == {"typ": "necitelne", "rz": None, "vin": None, "orv_cislo": None,
                      "provozovatel": None}
    fake = FakeClient()
    fake.create = lambda **kw: NS(content=[NS(type="thinking")])
    with pytest.raises(scan.ScanUnavailable):
        scan.extract(b"p", "image/jpeg", client=fake)


@pytest.fixture
def make(conn):
    fid = firmy_repo.create(conn, nazev="BSAuto", zkratka="BS")
    def create(**fields):
        return pridat_ukon(conn, **({"firma_id": fid, "datum": RECENT, "typ_kod": "ZÁPIS",
                                   "celkem": 1300, "vin": VIN} | fields))
    return create


@pytest.mark.parametrize("fields,expected,changes", [
    ({}, "doplneno", ["rz", "orv"]),
    ({"orv": "UBE037263"}, "doplneno", ["rz"]),
    ({"rz": "5AB1234"}, "doplneno", ["orv"]),
    ({"rz": " 5ab-1234 ", "orv": " ube 037263 "}, "uz_doplneno", []),
    ({"rz": "9ZZ9999"}, "doplneno", ["rz", "orv"]),
    ({"orv": "ABC123456"}, "doplneno", ["rz", "orv"]),
    ({"rz": "9ZZ9999", "orv": "ABC123456"}, "doplneno", ["rz", "orv"]),
])
def test_fill_matrix(conn, make, fields, expected, changes):
    uid = make(**fields)
    before = dict(ukony_repo.get(conn, uid))
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient())
    after = dict(ukony_repo.get(conn, uid))
    assert result["stav"] == expected and result["doplneno"] == changes
    assert result["ukon"] == {"id": uid, "datum": RECENT, "firma": "BSAuto",
                              "firma_id": before["firma_id"], "firma_zkratka": "BS",
                              "typ": "ZÁPIS", "celkem": 1300.0,
                              "stav_platby": "nezaplaceno", "poznamka": None}
    assert all(before[k] == after[k] for k in before if k not in changes + ["updated_at"])
    overwritten = [k for k, v in fields.items() if v.strip().upper().replace(" ", "").replace("-", "")
                   != (DATA["orv_cislo"] if k == "orv" else DATA[k])]
    assert result.get("prepsano", []) == overwritten
    for key in overwritten:
        assert result["zmeny"][key]["pred"] == fields[key]
    for key in changes:
        assert after[key] == DATA["orv_cislo" if key == "orv" else key]
    assert not conn.in_transaction


def test_a_misread_plate_never_overwrites_the_stored_one(conn, make):
    # 2026-11-09, úkon #1646: žádosti stored 1AKI998, the scan read 1AKT998
    # (I misread as T) and overwrote it. The new techničák's ORV number is
    # legitimately new after a change of owner and the registry confirmed it.
    uid = make(rz="1AKI998", orv="UBM028561")
    photo = {**DATA, "rz": "1AKT998", "vin": None, "orv_cislo": "UBP586755"}
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(photo),
                          lookup=lambda _orv: {"success": True, "vin": VIN})
    row = ukony_repo.get(conn, uid)
    assert row["rz"] == "1AKI998" and row["orv"] == "UBP586755"
    assert result["stav"] == "doplneno" and result["ukon"]["id"] == uid
    assert result["rz"] == "1AKI998"
    assert result["rz_ponechano"] == {"evidence": "1AKI998", "foto": "1AKT998"}
    assert result["doplneno"] == ["orv"] and result["prepsano"] == ["orv"]
    assert result["zmeny"] == {"orv": {"pred": "UBM028561", "po": "UBP586755"}}
    assert not conn.in_transaction


def test_a_real_plate_exchange_replaces_the_stored_plate(conn, make):
    # David 2026-11-09: plates get exchanged, 1AKI988 → 3BN4796 is a new number.
    uid = make(rz="1AKI988", orv="UBM028561")
    photo = {**DATA, "rz": "3BN4796", "vin": None, "orv_cislo": "UBP586755"}
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(photo),
                          lookup=lambda _orv: {"success": True, "vin": VIN})
    assert ukony_repo.get(conn, uid)["rz"] == "3BN4796"
    assert result["stav"] == "doplneno" and result["prepsano"] == ["rz", "orv"]
    assert result["zmeny"]["rz"] == {"pred": "1AKI988", "po": "3BN4796"}
    assert "rz_ponechano" not in result


@pytest.mark.parametrize("photo_rz,kept", [
    ("1AKT998", True),    # one look-alike character (I → T)
    ("1AK1998", True),    # I → 1
    ("1AKT99B", True),    # two characters
    ("1AK998", True),     # one character missing
    ("1AKT9B8X", False),  # three edits: treated as a real change
    ("3BN4796", False),   # a new plate
])
def test_misread_threshold(conn, make, photo_rz, kept):
    uid = make(rz="1AKI998", orv=DATA["orv_cislo"])
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient({**DATA, "rz": photo_rz}))
    stored = ukony_repo.get(conn, uid)["rz"]
    assert stored == ("1AKI998" if kept else photo_rz)
    assert result["stav"] == ("uz_doplneno" if kept else "doplneno")
    assert ("rz_ponechano" in result) is kept


def test_vin_preference_creates_even_if_rz_belongs_to_another_vin(conn, make):
    make(vin="OTHER", rz=DATA["rz"])
    before = conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0]
    assert scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient())["stav"] == "bez_firmy"
    assert conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0] == before
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient({**DATA, "vin": None}))
    assert result["stav"] == "doplneno" and result["doplneno"] == ["orv"]


def test_front_photo_looks_up_vin_before_transaction_and_fills(conn, make, monkeypatch):
    uid = make()
    photo_data = {**DATA, "vin": None}
    events = []
    original_transaction = scan.transaction

    @contextmanager
    def transaction_spy(connection):
        events.append("transaction")
        with original_transaction(connection):
            yield

    def lookup(orv):
        events.append("lookup")
        assert orv == DATA["orv_cislo"]
        return {"success": True, "vin": " tmb-ek6nw7m3158470 "}

    monkeypatch.setattr(scan, "transaction", transaction_spy)
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(photo_data), lookup=lookup)
    assert events == ["lookup", "transaction"]
    assert result["stav"] == "doplneno" and result["ukon"]["id"] == uid
    assert result["vin"] == VIN and result["vin_zdroj"] == "registr"
    assert result["doplneno"] == ["rz", "orv"]
    assert ukony_repo.get(conn, uid)["rz"] == DATA["rz"]
    assert ukony_repo.get(conn, uid)["orv"] == DATA["orv_cislo"]


def test_lookup_failure_falls_back_to_rz(conn, make):
    uid = make(vin="OTHER", rz=DATA["rz"])
    photo_data = {**DATA, "vin": None}
    calls = []
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(photo_data),
                          lookup=lambda orv: calls.append(orv) or {"success": False, "error": "offline"})
    assert calls == [DATA["orv_cislo"]]
    assert result["stav"] == "doplneno" and result["ukon"]["id"] == uid
    assert result["vin"] is None and result["vin_zdroj"] is None
    assert result["doplneno"] == ["orv"]


def test_invalid_registry_vin_is_ignored_and_explained(conn):
    photo_data = {**DATA, "vin": None}
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(photo_data),
                          lookup=lambda _orv: {"success": True, "vin": "not a vin!"})
    assert result["stav"] == "chyba" and result["vin"] is None
    assert "Registr" in result["zprava"]
    assert result["vin_zdroj"] is None
    assert result["rz"] == DATA["rz"] and result["orv_cislo"] == DATA["orv_cislo"]


def test_registry_no_match_names_vin_source(conn):
    photo_data = {**DATA, "vin": None}
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(photo_data),
                          lookup=lambda _orv: {"success": True, "vin": VIN})
    assert result["stav"] == "bez_firmy" and result["vin"] == VIN
    assert result["vin_zdroj"] == "registr"
    assert result["vin"] == VIN and result["vin_zdroj"] == "registr"
    assert result["rz"] == DATA["rz"] and result["orv_cislo"] == DATA["orv_cislo"]


def test_lookup_skipped_when_photo_has_vin_or_no_orv(conn, make):
    make()
    calls = []
    lookup = lambda orv: calls.append(orv) or {"success": False}
    photo_with_vin = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(), lookup=lookup)
    assert photo_with_vin["vin_zdroj"] == "foto" and calls == []
    no_orv = {**DATA, "vin": None, "orv_cislo": None}
    scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(no_orv), lookup=lookup)
    assert calls == []


@pytest.mark.parametrize("other_fields,expected", [({}, "vice_shod"),
    ({"rz": DATA["rz"], "orv": DATA["orv_cislo"]}, "doplneno")])
def test_multiple_matches(conn, make, other_fields, expected):
    target = make()
    other = make(**other_fields)
    before = dict(ukony_repo.get(conn, other))
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient())
    assert result["stav"] == expected
    assert dict(ukony_repo.get(conn, other)) == before
    if expected == "doplneno":
        assert result["ukon"]["id"] == target
    else:
        assert ukony_repo.get(conn, target)["rz"] is None


def test_overwrite_picks_newest_when_no_row_awaits(conn, make):
    old = make(datum=(date.today() - timedelta(days=1)).isoformat(), rz="1AA1111", orv="AAA111111")
    new = make(datum=RECENT, rz="1AA1111", orv="AAA111111")
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient())
    assert result["stav"] == "doplneno" and result["ukon"]["id"] == new
    assert result["prepsano"] == ["rz", "orv"]
    assert ukony_repo.get(conn, new)["orv"] == DATA["orv_cislo"]
    assert ukony_repo.get(conn, old)["orv"] == "AAA111111"


@pytest.mark.parametrize("filled", [True, False])
def test_car_back_after_window_needs_review_and_does_not_overwrite(conn, make, filled):
    # 2026-10-21: EL375AT from August (JE & NE) got its ORV overwritten by a
    # new techničák — the car had been sold and bought back. Old úkony stay as they are.
    window = scan.MATCH_WINDOW_DAYS if filled else scan.AWAITING_WINDOW_DAYS
    old_date = (date.today() - timedelta(days=window + 1)).isoformat()
    fields = {"rz": "1AA1111", "orv": "UBC425944"} if filled else {}
    old = make(datum=old_date, **fields)
    before = dict(ukony_repo.get(conn, old))
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient())
    assert dict(ukony_repo.get(conn, old)) == before
    assert result["stav"] == "zmena_ke_kontrole"
    assert result["predchozi"]["id"] == old and result["predchozi"]["datum"] == old_date
    assert result["ukon"] == result["predchozi"]
    assert result["lze_zapsat"] is filled
    assert result["predchozi"]["stav_platby"] == "nezaplaceno"
    assert result["predchozi"]["poznamka"] is None


def test_window_edge_still_matches(conn, make):
    edge = (date.today() - timedelta(days=scan.MATCH_WINDOW_DAYS)).isoformat()
    uid = make(datum=edge)
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient())
    assert result["stav"] == "doplneno" and result["ukon"]["id"] == uid


@pytest.mark.parametrize("prevod,operator,same", [
    ("AUTO CARDION s. r. o. → XYZ s.r.o.", "XYZ, s.r.o.", True),          # scanning that sale
    ("AUTO CARDION s. r. o. → XYZ s.r.o.", "Auto Cardion s.r.o.", False),  # bought back = new sale
    ("Ing. Jakub Šebesta → JE & NE, spol. s r.o.", "JE & NE spol. s r. o.", True),
    ("JE & NE, spol. s r.o. → Ing. Jakub Šebesta", "ŠEBESTA JAKUB", True),
    ("JE & NE, spol. s r.o. → Ing. Jakub Šebesta", "ŠEBESTA PETR", False),
    ("AUTO CARDION s. r. o. → XYZ s.r.o.", None, True),                   # unreadable → date only
    (None, "XYZ s.r.o.", True),                                            # no transfer line → date only
])
def test_owner_on_orv_must_be_the_new_owner_of_that_sale(conn, make, prevod, operator, same):
    uid = make(prevod=prevod)
    before = dict(ukony_repo.get(conn, uid))
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient({**DATA, "provozovatel": operator}))
    if same:
        assert result["stav"] == "doplneno" and result["ukon"]["id"] == uid
    else:
        assert dict(ukony_repo.get(conn, uid)) == before
        assert result["stav"] in ("zalozeno", "bez_firmy") and result["predchozi"]["id"] == uid


def test_new_car_waiting_for_its_plate_is_filled_days_later(conn, make):
    # 2026-10-23: NOVÉ úkony from 21.10. with empty RZ/ORV (Cardion) were
    # skipped as "too old" and the scan made duplicate ORV rows instead.
    two_days = (date.today() - timedelta(days=2)).isoformat()
    uid = make(datum=two_days, typ_kod="NOVÉ", prevod="CARDION s.r.o.")
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient())
    assert result["stav"] == "doplneno" and result["ukon"]["id"] == uid
    assert ukony_repo.get(conn, uid)["rz"] == DATA["rz"]
    assert conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0] == 1


def test_plate_only_read_never_offers_the_car_as_new(conn, make):
    # 2026-10-26: the first photo of a JE & NE techničák gave the RZ but no ORV
    # number, so no VIN. The NOVÉ úkon waiting with only its VIN stayed
    # invisible, "Nové auto" let David create a duplicate (#1523). The rescan
    # read the ORV number, got the VIN and paired with the waiting úkon.
    uid = make(typ_kod="NOVÉ", prevod="Haustech s.r.o.")
    before = dict(ukony_repo.get(conn, uid))
    first = scan.zpracuj(conn, b"p", "image/jpeg",
                         client=FakeClient({**DATA, "vin": None, "orv_cislo": None}))
    assert first["stav"] == "necitelne" and "znovu" in first["zprava"]
    assert dict(ukony_repo.get(conn, uid)) == before
    rescan = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient({**DATA, "vin": None}),
                          lookup=lambda _orv: {"success": True, "vin": VIN})
    assert rescan["stav"] == "doplneno" and rescan["ukon"]["id"] == uid
    assert conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0] == 1


class SeqClient(FakeClient):
    """Returns one payload per read, so the second look can differ from the first."""
    def __init__(self, *reads):
        super().__init__(reads[0])
        self.reads = list(reads)

    def create(self, **kwargs):
        self.data = self.reads[min(len(self.calls), len(self.reads) - 1)]
        return super().create(**kwargs)


OTHER_VIN = "TMBAAAAAA00000001"


def registry(table):
    return lambda orv: ({"success": True, "vin": table[orv]} if orv in table
                        else {"success": False, "error": "Vozidlo nenalezeno"})


def test_second_look_finds_the_unread_orv_number_and_fills(conn, make):
    # Scan 1 on 26.10. would have paired by itself: the app reads the photo a
    # second time before giving up on a missing ORV number.
    uid = make(typ_kod="NOVÉ")
    client = SeqClient({**DATA, "vin": None, "orv_cislo": None}, {**DATA, "vin": None})
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=client,
                          lookup=registry({DATA["orv_cislo"]: VIN}))
    assert len(client.calls) == 2
    assert result["stav"] == "doplneno" and result["ukon"]["id"] == uid
    assert "Druhé čtení" in client.calls[1]["system"]
    assert "Druhé čtení" not in client.calls[0]["system"]


def test_second_look_corrects_a_misread_that_hit_another_car(conn, make):
    uid = make(typ_kod="NOVÉ")
    misread = "UBE037268"
    client = SeqClient({**DATA, "vin": None, "orv_cislo": misread}, {**DATA, "vin": None})
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=client,
                          lookup=registry({misread: OTHER_VIN, DATA["orv_cislo"]: VIN}))
    assert result["stav"] == "doplneno" and result["ukon"]["id"] == uid
    assert ukony_repo.get(conn, uid)["orv"] == DATA["orv_cislo"]


def test_two_different_readings_never_offer_a_new_car(conn):
    client = SeqClient({**DATA, "vin": None, "orv_cislo": "UBE037268"}, {**DATA, "vin": None})
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=client,
                          lookup=registry({"UBE037268": OTHER_VIN, DATA["orv_cislo"]: VIN}))
    assert result["stav"] == "necitelne"
    assert "UBE037268" in result["zprava"] and DATA["orv_cislo"] in result["zprava"]
    assert conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0] == 0


def test_one_reading_of_a_new_car_is_not_enough(conn):
    client = SeqClient({**DATA, "vin": None}, {**DATA, "vin": None, "orv_cislo": None})
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=client,
                          lookup=registry({DATA["orv_cislo"]: VIN}))
    assert result["stav"] == "necitelne" and "znovu" in result["zprava"]


def test_two_matching_readings_offer_a_new_car(conn):
    client = SeqClient({**DATA, "vin": None}, {**DATA, "vin": None})
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=client,
                          lookup=registry({DATA["orv_cislo"]: VIN}))
    assert len(client.calls) == 2
    assert result["stav"] == "bez_firmy" and result["vin"] == VIN


def test_a_paired_scan_reads_the_photo_once(conn, make):
    make()
    client = FakeClient({**DATA, "vin": None})
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=client,
                          lookup=registry({DATA["orv_cislo"]: VIN}))
    assert result["stav"] == "doplneno" and len(client.calls) == 1


def test_second_look_failure_keeps_the_safe_first_answer(conn, make):
    make(typ_kod="NOVÉ")
    client = SeqClient({**DATA, "vin": None, "orv_cislo": None})
    calls = []
    def flaky(**kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            raise TimeoutError("provider down")
        return FakeClient.create(client, **kwargs)
    client.create = flaky
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=client)
    assert result["stav"] == "necitelne" and "znovu" in result["zprava"]


def test_registry_without_vin_never_offers_the_car_as_new(conn, make):
    uid = make(typ_kod="NOVÉ")
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient({**DATA, "vin": None}))
    assert result["stav"] == "chyba" and "Registr" in result["zprava"]
    assert result["rz"] == DATA["rz"] and result["orv_cislo"] == DATA["orv_cislo"]
    assert ukony_repo.get(conn, uid)["rz"] is None


def test_assigning_a_car_without_vin_creates_nothing(conn, make):
    uid = make(typ_kod="NOVÉ")
    fid = ukony_repo.get(conn, uid)["firma_id"]
    data = {"rz": DATA["rz"], "vin": None, "orv_cislo": None, "provozovatel": None,
            "vin_zdroj": None}
    result = scan.zalozit_pro_firmu(conn, data, firma_id=fid, typ_kod="NOVÉ")
    assert result["stav"] == "necitelne"
    assert conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0] == 1


def test_complete_ukon_from_two_days_ago_is_not_overwritten(conn, make):
    uid = make(datum=(date.today() - timedelta(days=2)).isoformat(), rz="1AA1111", orv="UBC425944")
    before = dict(ukony_repo.get(conn, uid))
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient())
    assert result["stav"] == "zmena_ke_kontrole" and result["ukon"]["id"] == uid
    assert dict(ukony_repo.get(conn, uid)) == before


def test_waiting_ukon_older_than_window_is_left_alone(conn, make):
    old = (date.today() - timedelta(days=scan.AWAITING_WINDOW_DAYS + 1)).isoformat()
    uid = make(datum=old)
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient())
    assert result["stav"] == "zmena_ke_kontrole" and ukony_repo.get(conn, uid)["rz"] is None
    assert result["lze_zapsat"] is False


def test_api_fill_still_refuses_to_overwrite(conn, make):
    from services.vehicle_fill_service import FillError, doplnit
    uid = make(orv="ABC123456")
    with pytest.raises(FillError) as exc:
        doplnit(conn, uid, {"orv": "UBE037263"})
    assert exc.value.status == 409
    assert ukony_repo.get(conn, uid)["orv"] == "ABC123456"


def test_ambiguity_beyond_api_display_limit(conn, make):
    make()
    for _ in range(20):
        make(rz=DATA["rz"], orv=DATA["orv_cislo"])
    make()
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient())
    assert result["stav"] == "vice_shod"
    # The client needs the rows it is choosing between — newest first, max 5.
    assert len(result["kandidati"]) == 5
    assert all({"id", "datum", "firma", "typ", "celkem", "stav_platby", "poznamka"}
               <= set(k) for k in result["kandidati"])
    assert [k["id"] for k in result["kandidati"]] == sorted(
        [k["id"] for k in result["kandidati"]], reverse=True)


@pytest.mark.parametrize("data,state", [
    ({**DATA, "typ": "jine"}, "necitelne"),
    ({**DATA, "rz": None, "orv_cislo": None}, "necitelne"),
    ({**DATA, "rz": None, "vin": None}, "nenalezeno"),
])
def test_unusable_photo_changes_nothing(conn, make, data, state):
    uid = make()
    before = dict(ukony_repo.get(conn, uid))
    assert scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(data))["stav"] == state
    assert dict(ukony_repo.get(conn, uid)) == before


def test_provider_failure_and_rollback(conn, make, monkeypatch):
    uid = make()
    before = dict(ukony_repo.get(conn, uid))
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(error=TimeoutError("secret")))
    assert result["stav"] == "chyba" and "secret" not in result["zprava"]
    update = ukony_repo.update
    def fail(*args, **kwargs):
        update(*args, **kwargs)
        raise RuntimeError("after write")
    monkeypatch.setattr(ukony_repo, "update", fail)
    assert scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient())["stav"] == "chyba"
    assert dict(ukony_repo.get(conn, uid)) == before


def test_concurrent_photos_fill_once(conn, make):
    make()
    path = conn.execute("PRAGMA database_list").fetchone()[2]
    def process(_):
        c = db.connect(path)
        try:
            return scan.zpracuj(c, b"p", "image/jpeg", client=FakeClient())["stav"]
        finally:
            c.close()
    with ThreadPoolExecutor(max_workers=3) as pool:
        assert sorted(pool.map(process, range(3))) == ["doplneno", "uz_doplneno", "uz_doplneno"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "routes.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "")
    a = appmod.create_app()
    a.testing = True
    with a.test_client() as c:
        yield c


@pytest.fixture
def vision(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-never-sent")
    original = scan.extract
    fake = FakeClient()
    monkeypatch.setattr(scan, "extract", lambda data, mime, **kw: original(data, mime, client=fake))
    return fake


def photo(fmt="PNG"):
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (24, 16), "green").save(buf, format=fmt)
    return buf.getvalue()


def post(client, data=None, mime="image/jpeg"):
    return client.post("/ukony/orv-sken", data={"foto": (BytesIO(photo() if data is None else data), "foto", mime)})


def test_route_login_and_key(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "test-password")
    assert client.get("/ukony/orv-sken").status_code == 302
    assert post(client).status_code == 302
    assert client.post("/ukony/orv-sken/zapsat", json={"ukon_id": 1, "rz": "5AB1234"}).status_code == 302
    with client.session_transaction() as s:
        s["authed"] = True
    r = post(client)
    assert r.status_code == 503 and r.json == {"error": "Čtení fotek není nastavené."}


def test_fragment_button_and_shared_thinking(client):
    r = client.get("/ukony/orv-sken")
    assert r.status_code == 200 and 'id="orv-video"' in r.text
    assert 'capture="environment"' in r.text and 'id="orv-results"' in r.text
    page = client.get("/ukony/vse").text
    assert 'data-orv-sken' in page and 'Techničák' in page
    assert 'Doplnit RZ a ORV z techničáku' in page and 'js/thinking.js' in page
    assert 'js/thinking.js' in client.get('/zeptej').text


def test_fragment_passes_prices_for_active_firms(client, monkeypatch):
    from routes import orv_scan
    with client.application.app_context():
        c = db.get_db()
        fid = firmy_repo.create(c, nazev="BSAuto", zkratka="BS")
        typy_repo.upsert(c, "ORV", 900, 1)
        firma_ceny_repo.set_price(c, fid, "ORV", 1300)
    assert client.get("/ukony/orv-sken").status_code == 200  # renders with the new context
    seen = {}
    def spy(template, **context):
        seen.update(context)
        return ""
    monkeypatch.setattr(orv_scan, "render_template", spy)
    assert client.get("/ukony/orv-sken").status_code == 200
    assert seen["ceny"] == {str(fid): {t["kod"]: (1300.0 if t["kod"] == "ORV" else
                                                 (float(t["vychozi_cena"])
                                                  if t["vychozi_cena"] is not None else None))
                                       for t in seen["typy"]}}
    assert [f["id"] for f in seen["firmy"]] == [fid] and seen["typy"]
    # Karty v Úkonech mají barevnou tečku firmy — sken musí dostat stejnou paletu.
    assert seen["firma_colors"] == {"BS": seen["firma_colors"]["BS"]}
    assert seen["firmy_data"] == [{"id": fid, "nazev": "BSAuto", "zkratka": "BS",
                                   "color": seen["firmy_data"][0]["color"]}]


def test_view_carries_firm_identity(conn, make):
    uid = make()
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient())
    assert result["ukon"]["id"] == uid
    assert result["ukon"]["firma_id"] and result["ukon"]["firma_zkratka"] == "BS"


# Big payloads are built lazily: a multi-MB bytes literal as a parametrize value
# ends up in the test id and overflows Windows' 32 KB environment-variable limit.
@pytest.mark.parametrize("make,expected", [
    pytest.param(lambda: b"not an image", 400, id="not-an-image"),
    pytest.param(lambda: b"GIF89a", 400, id="gif"),
    pytest.param(lambda: b"\xff\xd8\xffbroken", 400, id="broken-jpeg"),
    pytest.param(lambda: b"x" * (8 * 1024 * 1024 + 1), 413, id="just-over-8mb"),
    pytest.param(lambda: b"x" * (9 * 1024 * 1024), 413, id="9mb")])
def test_route_invalid_upload(client, vision, make, expected):
    r = post(client, make())
    assert r.status_code == expected and r.is_json and "error" in r.json
    assert not vision.calls


def test_missing_multiple_photos_and_memory_stream(client, vision):
    assert client.post('/ukony/orv-sken').status_code == 400
    r = client.post('/ukony/orv-sken', data={'foto': [(BytesIO(photo()), 'a'), (BytesIO(photo()), 'b')]})
    assert r.status_code == 400
    with client.application.test_request_context('/ukony/orv-sken', method='POST',
            data={'foto': (BytesIO(photo() + b' ' * 600000), 'large.png')}):
        from flask import request
        assert isinstance(request.files['foto'].stream, BytesIO)


def test_happy_json_sniffs_bytes_and_logs(client, vision, monkeypatch):
    from routes import orv_scan
    logs = []
    monkeypatch.setattr(orv_scan.logger, "info", lambda *args: logs.append(args))
    with client.application.app_context():
        c = db.get_db()
        fid = firmy_repo.create(c, nazev="BSAuto", zkratka="BS")
        uid = pridat_ukon(c, firma_id=fid, datum=RECENT, typ_kod="ZÁPIS", celkem=1300, vin=VIN)
    result = post(client, mime="application/octet-stream")
    assert result.status_code == 200 and result.json["stav"] == "doplneno"
    assert result.json["ukon"]["id"] == uid and result.json["doplneno"] == ["rz", "orv"]
    assert len(logs) == 1 and logs[0][1:3] == ("doplneno", uid) and logs[0][5] == 125
    # The raw reading is logged too, so "nečitelné" can be explained later.
    assert logs[0][6:] == ("5AB1234", "UBE037263", "UBE037263")


def test_rate_limit_session_and_window(client, vision, monkeypatch):
    from routes import orv_scan
    monkeypatch.setattr(orv_scan.time, "time", lambda: 2000)
    client.get('/ukony/orv-sken')
    with client.session_transaction() as s:
        sid = s['orvsken_sid']
    with client.application.app_context():
        c = db.get_db()
        c.executemany('INSERT INTO orv_scan_rate VALUES (?, ?)', [(sid, 2000)] * 59)
        c.commit()
    assert post(client).status_code == 200
    # Another worker / application instance must see the same DB quota.
    other = appmod.create_app().test_client()
    with other.session_transaction() as s:
        s['orvsken_sid'] = sid
    assert post(other).status_code == 429
    with client.application.test_client() as fresh:
        assert post(fresh).status_code == 200
    monkeypatch.setattr(orv_scan.time, "time", lambda: 2601)
    assert post(client).status_code == 200


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP", "HEIF"])
def test_supported_images_converted_in_memory(fmt):
    if fmt == "HEIF":
        from pillow_heif import register_heif_opener
        register_heif_opener()
    data, mime = orv_images.prepare(photo(fmt))
    assert mime == "image/jpeg" and data.startswith(b'\xff\xd8\xff')


# -- 2026-11-11: 4444PARK and 2BP1720 ----------------------------------------

@pytest.mark.parametrize("raw,fixed", [
    ("UB0056935", "UBO056935"),   # 4444PARK: series O read as zero
    ("UBE03726O", "UBE037260"),   # number zero read as O
    ("U8E037263", "UBE037263"),
    ("UB037263", None),           # a missing character is never invented
    ("UBE０３７２６３", None),
])
def test_orv_lookalikes_become_a_candidate_never_the_reading(raw, fixed):
    result = scan.extract(b"p", "image/jpeg", client=FakeClient({**DATA, "orv_cislo": raw}))
    assert result["orv_cislo"] is None
    assert result.get("orv_oprava") == fixed


def test_orv_with_zero_for_o_fills_once_the_registry_confirms_it(conn, make):
    # 4444PARK: ORV UBO056935, read three times as UB0056935 and rejected as
    # unreadable. Letters only in the series, digits only in the number, and
    # the registry has to know the fixed number before it is used.
    uid = make(typ_kod="NOVÉ", datum=(date.today() - timedelta(days=6)).isoformat(),
               prevod="Jazyková škola P.A.R.K. s.r.o.")
    read = {**DATA, "rz": "4444PARK", "vin": None, "orv_cislo": "UB0056935"}
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(read),
                          lookup=registry({"UBO056935": VIN}))
    assert result["stav"] == "doplneno" and result["ukon"]["id"] == uid
    row = ukony_repo.get(conn, uid)
    assert (row["rz"], row["orv"]) == ("4444PARK", "UBO056935")


def test_unconfirmed_orv_fix_changes_nothing(conn, make):
    uid = make(typ_kod="NOVÉ")
    before = dict(ukony_repo.get(conn, uid))
    read = {**DATA, "vin": None, "orv_cislo": "UB0056935"}
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(read), lookup=registry({}))
    assert result["stav"] == "necitelne"
    assert dict(ukony_repo.get(conn, uid)) == before


def test_new_car_with_a_confirmed_orv_fix_read_twice_is_offered(conn):
    read = {**DATA, "vin": None, "orv_cislo": "UB0056935"}
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(read),
                          lookup=registry({"UBO056935": VIN}))
    assert result["stav"] == "bez_firmy"
    assert (result["orv_cislo"], result["vin"]) == ("UBO056935", VIN)


def _car(result):
    return {k: result[k] for k in ("rz", "vin", "orv_cislo", "provozovatel", "vin_zdroj")}


def test_new_owner_on_the_orv_is_another_sale_not_a_duplicate(conn, make):
    # 2BP1720: JE & NE bought it on 7. 10. and sells it on now. The ORV names a
    # new owner, so it is a new úkon — no "Přesto založit", and the new owner
    # is written on it.
    old = make(datum=(date.today() - timedelta(days=35)).isoformat(), rz="2BP1720",
               orv="UBC162708", prevod="PLACHÝ JIŘÍ → JE & NE, spol. s r.o.")
    before = dict(ukony_repo.get(conn, old))
    read = {**DATA, "rz": "2BP1720", "orv_cislo": "UBP586066", "provozovatel": "ACC Automotive s.r.o."}
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(read))
    assert result["stav"] == "bez_firmy" and result["predchozi"]["id"] == old
    assert "existujici" not in result and not result.get("vyzaduje_potvrzeni")
    made = scan.zalozit_pro_firmu(conn, _car(result), firma_id=before["firma_id"], typ_kod="KOLA")
    assert made["stav"] == "zalozeno"
    assert ukony_repo.get(conn, made["ukon"]["id"])["prevod"] == \
        "JE & NE, spol. s r.o. → ACC Automotive s.r.o."
    assert dict(ukony_repo.get(conn, old)) == before


@pytest.mark.parametrize("operator", ["KOLACEK JAROSLAV", None])
def test_same_or_unread_owner_still_asks_before_a_second_ukon(conn, make, operator):
    # 1AKI647 (5. 11.): the same sale scanned again must not double the úkon.
    old = make(datum=(date.today() - timedelta(days=35)).isoformat(),
               prevod="ŠKOFIN S.R.O. → JAROSLAV KOLACEK")
    result = scan.zpracuj(conn, b"p", "image/jpeg",
                          client=FakeClient({**DATA, "provozovatel": operator}))
    assert result["stav"] == "zmena_ke_kontrole" and result["ukon"]["id"] == old
    assert result["lze_zapsat"] is False
    blocked = scan.zalozit_pro_firmu(conn, _car(result), firma_id=ukony_repo.get(conn, old)["firma_id"],
                                     typ_kod="KOLA")
    assert blocked["stav"] == "jiz_v_evidence"
    assert conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0] == 1


def test_a_car_new_to_evidence_gets_its_owner_written(conn, make):
    fid = ukony_repo.get(conn, make(vin="TMBAAAAAA00000009"))["firma_id"]
    made = scan.zalozit_pro_firmu(conn, {"rz": "5AB1234", "vin": VIN, "orv_cislo": "UBE037263",
                                         "provozovatel": "BSAuto s.r.o.", "vin_zdroj": "foto"},
                                  firma_id=fid, typ_kod="KOLA")
    assert made["stav"] == "zalozeno"
    assert ukony_repo.get(conn, made["ukon"]["id"])["prevod"] == "→ BSAuto s.r.o."


NEW_ORV = "UBP590636"
OLD_ORV = "UBF670979"
OLD_PLATE = "5AB1234"
ALBION = "Albion Cars s.r.o."
TRANSFER = "MM INSTALACE s.r.o. → Albion Cars s.r.o."
WRITE_URL = "/ukony/orv-sken/zapsat"


def _ago(days):
    return (date.today() - timedelta(days=days)).isoformat()


def _read_albion(**fields):
    return {**DATA, "vin": None, "rz": OLD_PLATE,
            "orv_cislo": NEW_ORV, "provozovatel": ALBION, **fields}


@pytest.mark.parametrize("rz,orv", [(OLD_PLATE, OLD_ORV), ("5AB1235", OLD_ORV), (OLD_PLATE, None)])
def test_unchanged_duplicate_is_done_on_first_read(conn, make, rz, orv):
    uid = make(datum=_ago(6), prevod=TRANSFER, rz=OLD_PLATE, orv=OLD_ORV)
    before = dict(ukony_repo.get(conn, uid))
    fake = FakeClient(_read_albion(vin=VIN, rz=rz, orv_cislo=orv))
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=fake)
    assert result["stav"] == "uz_zapsano" and result["ukon"]["id"] == uid
    assert result["rz"] == OLD_PLATE
    assert not result["zmeny"] and not result.get("vyzaduje_potvrzeni")
    assert len(fake.calls) == 1 and not result.get("druhe_cteni")
    assert dict(ukony_repo.get(conn, uid)) == before


@pytest.mark.parametrize("days,prevod,operator,can_write", [
    (6, TRANSFER, ALBION, True),
    (40, TRANSFER, ALBION, False),
    (100, TRANSFER, "Albion s.r.o.", False),
    (40, "Albion", ALBION, False),
    (40, TRANSFER, None, False),
    (scan.AWAITING_WINDOW_DAYS, "Albion", ALBION, True),
])
def test_verified_older_duplicate_compares_newest_and_applies_owner_guard(
    conn, make, days, prevod, operator, can_write,
):
    older = make(datum=_ago(days + 1), prevod=TRANSFER, rz=OLD_PLATE, orv="UBA123456")
    uid = make(datum=_ago(days), prevod=prevod, rz=OLD_PLATE, orv=OLD_ORV)
    fake = FakeClient(_read_albion(rz="3BN4796", provozovatel=operator))
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=fake, lookup=registry({NEW_ORV: VIN}))
    assert result["stav"] == "zmena_ke_kontrole" and result["ukon"]["id"] == uid
    assert result["zmeny"] == {"orv": {"pred": OLD_ORV, "po": NEW_ORV},
                              "rz": {"pred": OLD_PLATE, "po": "3BN4796"}}
    assert result["lze_zapsat"] is can_write
    assert result["vin_zdroj"] == "registr" and len(fake.calls) == 1
    assert ukony_repo.get(conn, older)["orv"] == "UBA123456"
    assert ukony_repo.get(conn, uid)["orv"] == OLD_ORV


@pytest.mark.parametrize("second_orv,expected", [(NEW_ORV, "zmena_ke_kontrole"),
                                                 (None, "necitelne"), ("UBP590637", "necitelne")])
def test_unverified_orv_change_requires_two_identical_readings(conn, make, second_orv, expected):
    uid = make(datum=_ago(6), prevod=TRANSFER, rz=OLD_PLATE, orv=OLD_ORV)
    fake = SeqClient(_read_albion(), _read_albion(orv_cislo=second_orv))
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=fake)
    assert result["stav"] == expected and result["druhe_cteni"] and len(fake.calls) == 2
    assert bool(result["zmeny"]) is (second_orv == NEW_ORV)
    assert ukony_repo.get(conn, uid)["orv"] == OLD_ORV


@pytest.mark.parametrize("read_orv,second_orv,verified,expected,reads", [
    (None, None, False, "necitelne", 2),
    (OLD_ORV, None, False, "necitelne", 2),
    (OLD_ORV, NEW_ORV, False, "necitelne", 2),
    (OLD_ORV, OLD_ORV, False, "zmena_ke_kontrole", 2),
    (OLD_ORV, None, True, "zmena_ke_kontrole", 1),
])
def test_plate_only_change_also_requires_verification(
    conn, make, read_orv, second_orv, verified, expected, reads,
):
    uid = make(datum=_ago(6), prevod=TRANSFER, rz=OLD_PLATE, orv=OLD_ORV)
    first = _read_albion(vin=None if verified else VIN, rz="3BN4796", orv_cislo=read_orv)
    fake = SeqClient(first, {**first, "orv_cislo": second_orv})
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=fake,
                          lookup=registry({OLD_ORV: VIN} if verified else {}))
    assert result["stav"] == expected
    if expected == "zmena_ke_kontrole":
        assert result["ukon"]["id"] == uid
        assert result["zmeny"] == {"rz": {"pred": OLD_PLATE, "po": "3BN4796"}}
    else:
        assert not result["zmeny"] and "vyfoť techničák znovu" in result["zprava"]
    assert len(fake.calls) == reads and ukony_repo.get(conn, uid)["rz"] == OLD_PLATE


def _route_job(**fields):
    with db.connect(config.DB_PATH) as conn:
        db.init_schema(conn)
        firm = firmy_repo.create(conn, nazev="Albion", zkratka="AL")
        return pridat_ukon(conn, **({"firma_id": firm, "datum": _ago(6), "typ_kod": "3RZ",
                                    "celkem": 1300, "vin": VIN, "rz": OLD_PLATE,
                                    "orv": OLD_ORV, "prevod": TRANSFER} | fields))


def _write_request(result, uid):
    return {"ukon_id": uid, "token": result["navrh_token"]}


STALE_MESSAGE = "Úkon se mezitím změnil. Otevři ho a zkontroluj údaje."


def test_zapsat_writes_the_reviewed_orv_and_keeps_a_misread_plate(client, vision, monkeypatch):
    uid = _route_job()
    vision.data = _read_albion(rz="5AB1235")
    monkeypatch.setattr(scan.orv_service, "lookup_vin", registry({NEW_ORV: VIN}))
    result = post(client).json
    assert result["stav"] == "zmena_ke_kontrole" and result["lze_zapsat"]
    with db.connect(config.DB_PATH) as conn:
        assert ukony_repo.get(conn, uid)["orv"] == OLD_ORV
    response = client.post(WRITE_URL, json=_write_request(result, uid))
    assert response.status_code == 200
    assert response.json["stav"] == "doplneno" and response.json["doplneno"] == ["orv"]
    assert response.json["rz_ponechano"] == {"evidence": OLD_PLATE, "foto": "5AB1235"}
    with db.connect(config.DB_PATH) as conn:
        row = ukony_repo.get(conn, uid)
        assert (row["orv"], row["rz"]) == (NEW_ORV, OLD_PLATE)
        assert conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0] == 1
    replay = client.post(WRITE_URL, json={"token": result["navrh_token"]})
    assert replay.status_code == 409 and replay.json["error"] == STALE_MESSAGE


def test_same_vehicle_readings_have_independent_proposals(client, vision, monkeypatch):
    uid = _route_job()
    vision.data = _read_albion()
    monkeypatch.setattr(scan.orv_service, "lookup_vin", registry({NEW_ORV: VIN}))
    first = post(client).json
    vision.data = _read_albion(provozovatel=None)
    second = post(client).json
    assert first["zmeny"] == second["zmeny"]
    assert first["navrh_token"] != second["navrh_token"]
    assert "_snapshot" not in first and "_snapshot" not in second
    write = _write_request(first, uid)
    assert client.post(WRITE_URL, json={**write, "ukon_id": uid + 999}).status_code == 409
    assert client.post(WRITE_URL, json={**write, "orv": "UBP590637"}).status_code == 400
    with db.connect(config.DB_PATH) as conn:
        assert conn.execute("SELECT COUNT(*) FROM orv_scan_review").fetchone()[0] == 2
        # Change only the owner line to exercise the server's sale check independently.
        conn.execute("UPDATE ukony SET prevod = ? WHERE id = ?", ("→ Jiný majitel s.r.o.", uid))
    refused = client.post(WRITE_URL, json=write)
    assert refused.status_code == 409 and "provozovatel nesouhlasí" in refused.json["error"]
    with db.connect(config.DB_PATH) as conn:
        assert ukony_repo.get(conn, uid)["orv"] == OLD_ORV
    allowed = client.post(WRITE_URL, json={"token": second["navrh_token"]})
    assert allowed.status_code == 200 and allowed.json["stav"] == "doplneno"


@pytest.mark.parametrize("field,value", [
    ("updated_at", "2026-01-01T00:00:00+00:00"),
    ("rz", "3BN4796"),
    ("orv", "UBP590638"),
    ("vin", OTHER_VIN),
])
def test_zapsat_refuses_each_changed_snapshot_field_on_a_plate_match(client, vision, field, value):
    uid = _route_job()
    vision.data = _read_albion()
    result = post(client).json
    assert result["vin"] is None and result["druhe_cteni"] and result["lze_zapsat"]
    with db.connect(config.DB_PATH) as conn:
        conn.execute(f"UPDATE ukony SET {field} = ? WHERE id = ?", (value, uid))
        before = dict(ukony_repo.get(conn, uid))
    refused = client.post(WRITE_URL, json=_write_request(result, uid))
    assert refused.status_code == 409 and refused.json["error"] == STALE_MESSAGE
    with db.connect(config.DB_PATH) as conn:
        assert dict(ukony_repo.get(conn, uid)) == before


def test_snapshot_is_taken_at_comparison_even_if_row_changes_before_proposal_storage(
    client, vision, monkeypatch,
):
    uid = _route_job()
    vision.data = _read_albion()
    monkeypatch.setattr(scan.orv_service, "lookup_vin", registry({NEW_ORV: VIN}))
    zpracuj = scan.zpracuj

    def scan_then_correct_plate(conn, *args, **kwargs):
        result = zpracuj(conn, *args, **kwargs)
        ukony_repo.update(conn, uid, rz="3BN4796")
        return result

    monkeypatch.setattr(scan, "zpracuj", scan_then_correct_plate)
    result = post(client).json
    refused = client.post(WRITE_URL, json=_write_request(result, uid))
    assert refused.status_code == 409 and refused.json["error"] == STALE_MESSAGE


def test_note_edit_in_the_same_second_invalidates_proposal(client, vision, monkeypatch):
    uid = _route_job()
    vision.data = _read_albion()
    now = datetime(2026, 11, 19, 10, 30, 0, 100_000, tzinfo=timezone.utc)

    class TestClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    monkeypatch.setattr(db, "datetime", TestClock)
    with db.connect(config.DB_PATH) as conn:
        ukony_repo.update(conn, uid, poznamka="Původní poznámka")
    result = post(client).json
    now = now.replace(microsecond=200_000)
    with db.connect(config.DB_PATH) as conn:
        ukony_repo.update(conn, uid, poznamka="Změněná poznámka")
    refused = client.post(WRITE_URL, json=_write_request(result, uid))
    assert refused.status_code == 409 and refused.json["error"] == STALE_MESSAGE


def test_zapsat_rechecks_awaiting_window_even_for_a_matching_owner(client, vision, monkeypatch):
    today = date.today()
    uid = _route_job(datum=(today - timedelta(days=scan.AWAITING_WINDOW_DAYS)).isoformat())
    vision.data = _read_albion(provozovatel="Albion s.r.o.")
    monkeypatch.setattr(scan.orv_service, "lookup_vin", registry({NEW_ORV: VIN}))
    result = post(client).json
    assert result["lze_zapsat"]

    class Tomorrow(date):
        @classmethod
        def today(cls):
            return today + timedelta(days=1)

    monkeypatch.setattr(scan, "date", Tomorrow)
    refused = client.post(WRITE_URL, json=_write_request(result, uid))
    assert refused.status_code == 409 and "příliš starý" in refused.json["error"]
    with db.connect(config.DB_PATH) as conn:
        assert ukony_repo.get(conn, uid)["orv"] == OLD_ORV


def test_old_job_does_not_issue_a_proposal_token(client, vision, monkeypatch):
    _route_job(datum=_ago(100))
    vision.data = _read_albion(provozovatel="Albion s.r.o.")
    monkeypatch.setattr(scan.orv_service, "lookup_vin", registry({NEW_ORV: VIN}))
    result = post(client).json
    assert result["stav"] == "zmena_ke_kontrole" and result["lze_zapsat"] is False
    assert "navrh_token" not in result
    with db.connect(config.DB_PATH) as conn:
        assert conn.execute("SELECT COUNT(*) FROM orv_scan_review").fetchone()[0] == 0


def test_logout_removes_scan_session_and_relogin_cannot_write_old_proposal(client, vision, monkeypatch):
    uid = _route_job()
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "test-password")
    assert client.post("/login", data={"heslo": "test-password"}).status_code == 302
    vision.data = _read_albion()
    result = post(client).json
    with client.session_transaction() as session:
        old_sid = session["orvsken_sid"]
    assert client.post("/logout").status_code == 302
    with client.session_transaction() as session:
        assert "orvsken_sid" not in session and "authed" not in session
    assert client.post("/login", data={"heslo": "test-password"}).status_code == 302
    refused = client.post(WRITE_URL, json=_write_request(result, uid))
    assert refused.status_code == 409
    with client.session_transaction() as session:
        assert session["orvsken_sid"] != old_sid


def test_explicit_new_job_from_review_keeps_old_job_untouched(client, vision, monkeypatch):
    uid = _route_job()
    vision.data = _read_albion()
    monkeypatch.setattr(scan.orv_service, "lookup_vin", registry({NEW_ORV: VIN}))
    result = post(client).json
    assert result["stav"] == "zmena_ke_kontrole"
    car = {**_car(result), "firma_id": result["ukon"]["firma_id"], "typ_kod": "KOLA"}
    url = "/ukony/orv-sken/zalozit"
    assert client.post(url, json={"auta": [car]}).json["results"][0]["stav"] == "jiz_v_evidence"
    made = client.post(url, json={"auta": [{**car, "potvrdit_novy": True}]}).json["results"][0]
    assert made["stav"] == "zalozeno" and made["ukon"]["id"] != uid
    with db.connect(config.DB_PATH) as conn:
        assert ukony_repo.get(conn, uid)["orv"] == OLD_ORV
        assert ukony_repo.get(conn, made["ukon"]["id"])["orv"] == NEW_ORV


def test_explicit_new_job_from_plate_only_match_is_refused_without_vin(client, vision):
    uid = _route_job()
    vision.data = _read_albion()
    result = post(client).json
    assert result["stav"] == "zmena_ke_kontrole" and result["vin"] is None
    car = {**_car(result), "firma_id": result["ukon"]["firma_id"],
           "typ_kod": "KOLA", "potvrdit_novy": True}
    refused = client.post("/ukony/orv-sken/zalozit", json={"auta": [car]}).json["results"][0]
    assert refused["stav"] == "chyba" and "nevrátil VIN" in refused["zprava"]
    with db.connect(config.DB_PATH) as conn:
        assert conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0] == 1
        assert ukony_repo.get(conn, uid)["orv"] == OLD_ORV


def test_mixed_batch_keeps_both_dupes_and_only_creates_the_selected_car(client, vision, monkeypatch):
    changed_id = _route_job()
    filled_vin, same_vin, new_vin = "TMBAAAAAA00000001", "TMBAAAAAA00000002", "TMBAAAAAA00000003"
    with db.connect(config.DB_PATH) as conn:
        fid = ukony_repo.get(conn, changed_id)["firma_id"]
        shared = dict(firma_id=fid, typ_kod="KOLA", celkem=1300, prevod=TRANSFER)
        filled_id = pridat_ukon(conn, datum=RECENT, vin=filled_vin, **shared)
        same_id = pridat_ukon(conn, datum=_ago(6), vin=same_vin, rz="2AA2222", orv="UBL123456", **shared)
    numbers = {"UBL123455": filled_vin, "UBL123456": same_vin, NEW_ORV: VIN, "UBL123457": new_vin}
    monkeypatch.setattr(scan.orv_service, "lookup_vin", registry(numbers))
    results = []
    for rz, orv in zip(("1AA1111", "2AA2222", OLD_PLATE, "3AA3333"), numbers):
        vision.data = _read_albion(rz=rz, orv_cislo=orv)
        results.append(post(client).json)
    filled, same, changed, new = results
    assert [r["stav"] for r in results] == ["doplneno", "uz_zapsano", "zmena_ke_kontrole", "bez_firmy"]
    assert [r["ukon"]["id"] for r in (filled, same, changed)] == [filled_id, same_id, changed_id]
    with db.connect(config.DB_PATH) as conn:
        assert conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0] == 3
    assert client.post(WRITE_URL, json=_write_request(changed, changed_id)).json["stav"] == "doplneno"
    response = client.post("/ukony/orv-sken/zalozit", json={"auta": [
        {**_car(new), "firma_id": fid, "typ_kod": "KOLA", "potvrdit_novy": False},
    ]})
    assert response.json["results"][0]["stav"] == "zalozeno"
    with db.connect(config.DB_PATH) as conn:
        assert conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0] == 4
        assert [ukony_repo.get(conn, uid)["orv"] for uid in (filled_id, same_id, changed_id)] == [
            "UBL123455", "UBL123456", NEW_ORV]


# --- 2.9.7: a rescan of the same sale updates on its own (David 2026-11-19) ---------



def _rescan(conn, photo):
    return scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(photo),
                        lookup=lambda _orv: {"success": True, "vin": VIN})


@pytest.mark.parametrize("typ,prevod", [("PŘEVOD", TRANSFER), ("KOLA", "FOJTŮ RENATA")])
def test_same_sale_new_techničák_updates_the_orv_without_a_card(conn, make, typ, prevod):
    # Owner matches (PŘEVOD) or is unknown (KOLA, no arrow): every visit to the
    # authorities issues a new techničák, so the new ORV number is written.
    uid = make(datum=_ago(6), typ_kod=typ, prevod=prevod, rz=OLD_PLATE, orv=OLD_ORV)
    result = _rescan(conn, _read_albion())
    assert result["stav"] == "doplneno" and result["aktualizovano"] == ["orv"]
    assert result["zprava"] == "Aktualizováno: ORV" and "navrh_token" not in result
    assert result["zmeny"]["orv"] == {"pred": OLD_ORV, "po": NEW_ORV}
    assert ukony_repo.get(conn, uid)["orv"] == NEW_ORV
    assert conn.execute("SELECT COUNT(*) FROM ukony").fetchone()[0] == 1


@pytest.mark.parametrize("typ,prevod", [("3RZ", TRANSFER), ("3RZ", "FOJTŮ RENATA")])
def test_disagreeing_or_missing_signals_keep_the_decision_card(conn, make, typ, prevod):
    # Owner says same sale but the type comes without a new techničák, or the
    # owner is unknown and the type says no: ask, write nothing.
    uid = make(datum=_ago(6), typ_kod=typ, prevod=prevod, rz=OLD_PLATE, orv=OLD_ORV)
    result = _rescan(conn, _read_albion())
    assert result["stav"] == "zmena_ke_kontrole" and "aktualizovano" not in result
    assert ukony_repo.get(conn, uid)["orv"] == OLD_ORV


def test_an_unverified_reading_is_never_written_automatically(conn, make):
    # The registry knows another VIN for that ORV number: nothing proves the
    # photo belongs to this úkon.
    uid = make(datum=_ago(6), typ_kod="PŘEVOD", prevod=TRANSFER, rz=OLD_PLATE, orv=OLD_ORV)
    result = scan.zpracuj(conn, b"p", "image/jpeg", client=FakeClient(_read_albion(vin=VIN)),
                          lookup=lambda _orv: {"success": True, "vin": "WVWZZZ1KZ6W000001"})
    assert result.get("aktualizovano") is None
    assert ukony_repo.get(conn, uid)["orv"] == OLD_ORV


def test_older_than_30_days_is_not_updated_automatically(conn, make):
    uid = make(datum=_ago(40), typ_kod="PŘEVOD", prevod=TRANSFER, rz=OLD_PLATE, orv=OLD_ORV)
    result = _rescan(conn, _read_albion())
    assert result.get("aktualizovano") is None
    assert ukony_repo.get(conn, uid)["orv"] == OLD_ORV


def test_auto_update_keeps_a_misread_plate(conn, make):
    # #1646 still holds: a plate 1–2 characters off is never written, even when
    # the new ORV number is (the registry has no plate to confirm it).
    uid = make(datum=_ago(6), typ_kod="PŘEVOD", prevod=TRANSFER, rz=OLD_PLATE, orv=OLD_ORV)
    result = _rescan(conn, _read_albion(rz="5AB1235"))
    row = ukony_repo.get(conn, uid)
    assert (row["rz"], row["orv"]) == (OLD_PLATE, NEW_ORV)
    assert result["aktualizovano"] == ["orv"]
    assert result["rz_ponechano"] == {"evidence": OLD_PLATE, "foto": "5AB1235"}


def test_another_sale_still_offers_a_new_ukon(conn, make):
    uid = make(datum=_ago(6), typ_kod="PŘEVOD", prevod="MM INSTALACE s.r.o. → Jiná firma a.s.",
               rz=OLD_PLATE, orv=OLD_ORV)
    result = _rescan(conn, _read_albion())
    assert result.get("aktualizovano") is None and result["stav"] != "doplneno"
    assert ukony_repo.get(conn, uid)["orv"] == OLD_ORV


def test_a_plate_exchange_on_an_older_ukon_is_asked_not_written(conn, make):
    # astra 19. 11.: the stored ORV resolves to the right VIN, but a 3-character
    # plate difference may still be an OCR error — only a new ORV is automatic.
    uid = make(datum=_ago(6), typ_kod="PŘEVOD", prevod=TRANSFER, rz=OLD_PLATE, orv=OLD_ORV)
    result = _rescan(conn, _read_albion(rz="9XY9999", orv_cislo=OLD_ORV))
    assert result["stav"] == "zmena_ke_kontrole" and "aktualizovano" not in result
    assert ukony_repo.get(conn, uid)["rz"] == OLD_PLATE
