from repositories import typy_repo


def test_upsert_and_get(conn):
    typy_repo.upsert(conn, "PŘEVOD", 1300, 1)
    typy_repo.upsert(conn, "PŘEVOD", 1350, 1)  # update, not duplicate
    t = typy_repo.get_by_kod(conn, "PŘEVOD")
    assert t["vychozi_cena"] == 1350
    # upsert updates in place (no duplicate row). Other baseline types seeded by
    # init_schema (KOLA, A50-X) may also be present, so count PŘEVOD specifically.
    kods = [r["kod"] for r in typy_repo.list_active(conn)]
    assert kods.count("PŘEVOD") == 1
