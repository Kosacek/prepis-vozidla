from repositories import ukony_repo, firmy_repo


def _firma(conn):
    return firmy_repo.create(conn, nazev="F", zkratka="F", ico="1")


def test_create_and_filter(conn):
    fid = _firma(conn)
    ukony_repo.create(conn, firma_id=fid, datum="2026-05-04", rz="3BP3552",
                      typ_kod="PŘEVOD", celkem=1300)
    ukony_repo.create(conn, firma_id=fid, datum="2026-04-04", rz="X",
                      typ_kod="DOVOZ", celkem=2000)
    may = ukony_repo.list(conn, year=2026, month=5)
    assert len(may) == 1 and may[0]["rz"] == "3BP3552"
    assert len(ukony_repo.list(conn, firma_id=fid)) == 2
    assert len(ukony_repo.list(conn, typ_kod="DOVOZ")) == 1


def test_update_and_delete(conn):
    fid = _firma(conn)
    uid = ukony_repo.create(conn, firma_id=fid, datum="2026-05-04",
                            typ_kod="PŘEVOD", celkem=1300)
    ukony_repo.update(conn, uid, zaplaceno_kc=1300, stav_platby="zaplaceno")
    assert ukony_repo.get(conn, uid)["stav_platby"] == "zaplaceno"
    ukony_repo.delete(conn, uid)
    assert ukony_repo.get(conn, uid) is None
