from repositories import firmy_repo


def test_create_list_get_by_ico(conn):
    fid = firmy_repo.create(conn, nazev="AUTO CARDION s. r. o.", zkratka="Cardion",
                            ico="04156854", poradi=1)
    assert firmy_repo.get(conn, fid)["zkratka"] == "Cardion"
    assert firmy_repo.get_by_ico(conn, "04156854")["id"] == fid
    firmy_repo.create(conn, nazev="Albion Cars s.r.o.", zkratka="Albion", poradi=2)
    rows = firmy_repo.list_all(conn)
    assert [r["zkratka"] for r in rows] == ["Cardion", "Albion"]  # ordered by poradi


def test_update_changes_fields_and_noop_is_safe(conn):
    fid = firmy_repo.create(conn, nazev="X", zkratka="X")
    firmy_repo.update(conn, fid, zkratka="EV trans", aktivni=0)
    row = firmy_repo.get(conn, fid)
    assert row["zkratka"] == "EV trans" and row["aktivni"] == 0
    # no-op edit (no fields) must not raise / corrupt the row
    firmy_repo.update(conn, fid)
    assert firmy_repo.get(conn, fid)["zkratka"] == "EV trans"
