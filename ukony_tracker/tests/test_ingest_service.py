import pytest
from services import ingest_service as ing
from services.ingest_service import UnknownFirmaError, ValidationError
from repositories import firmy_repo, ukony_repo


def _cardion(conn):
    return firmy_repo.create(conn, nazev="AUTO CARDION s. r. o.", zkratka="Cardion", ico="04156854")


def test_add_by_firma_id_derives_payment(conn):
    fid = _cardion(conn)
    uid = ing.pridat_ukon(conn, firma_id=fid, datum="2026-05-04",
                          typ_kod="PŘEVOD", celkem=1300, zaplaceno_kc=1300)
    assert ukony_repo.get(conn, uid)["stav_platby"] == "zaplaceno"


def test_resolve_by_exact_ico(conn):
    _cardion(conn)
    uid = ing.pridat_ukon(conn, ico="04156854", datum="2026-05-04",
                          typ_kod="DOVOZ", celkem=2000)
    assert ukony_repo.get(conn, uid)["stav_platby"] == "nezaplaceno"


def test_rz_and_vin_stored_uppercase(conn):
    fid = _cardion(conn)
    uid = ing.pridat_ukon(conn, firma_id=fid, datum="2026-05-04",
                          typ_kod="PŘEVOD", celkem=1300, rz="3bk9696", vin="tmbjj7ns ")
    row = ukony_repo.get(conn, uid)
    assert row["rz"] == "3BK9696"
    assert row["vin"] == "TMBJJ7NS"


def test_unknown_firma_rejected(conn):
    with pytest.raises(UnknownFirmaError):
        ing.pridat_ukon(conn, ico="99999999", datum="2026-05-04",
                        typ_kod="PŘEVOD", celkem=1300)


def test_validation_rejects_bad_input(conn):
    fid = _cardion(conn)
    with pytest.raises(ValidationError):
        ing.pridat_ukon(conn, firma_id=fid, datum="2026-05-04", typ_kod="PŘEVOD", celkem=-5)
    with pytest.raises(ValidationError):
        ing.pridat_ukon(conn, firma_id=fid, datum="2026-05-04", typ_kod="PŘEVOD",
                        celkem=1000, zaplaceno_kc=2000)
    with pytest.raises(ValidationError):
        ing.pridat_ukon(conn, firma_id=fid, datum="not-a-date", typ_kod="PŘEVOD", celkem=1300)
