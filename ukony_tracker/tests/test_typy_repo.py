from repositories import typy_repo


def test_upsert_and_get(conn):
    typy_repo.upsert(conn, "PŘEVOD", 1300, 1)
    typy_repo.upsert(conn, "PŘEVOD", 1350, 1)  # update, not duplicate
    t = typy_repo.get_by_kod(conn, "PŘEVOD")
    assert t["vychozi_cena"] == 1350
    assert len(typy_repo.list_active(conn)) == 1
