import db
from scripts import seed
from services import stats_service as st
from repositories import firmy_repo


def test_seed_reconciles_may(conn):
    seed.seed_all(conn)
    assert len(firmy_repo.list_all(conn)) == 9
    assert all(f["zkratka"] for f in firmy_repo.list_all(conn))  # non-empty
    s = st.mesicni_souhrn(conn, 2026, 5)
    assert s["pocet"] == 90 and s["trzby"] == 145700
    byf = {r["zkratka"]: (r["pocet"], r["trzby"]) for r in st.podle_firmy(conn, 2026, 5)}
    assert byf["Cardion"] == (59, 84400)
    assert byf["Albion"] == (18, 44500)
    assert byf["Orbion"] == (13, 16800)


def test_seed_idempotent(conn):
    seed.seed_all(conn)
    seed.seed_all(conn)
    assert st.mesicni_souhrn(conn, 2026, 5)["pocet"] == 90  # not doubled
