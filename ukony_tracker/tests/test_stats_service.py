from services import stats_service as st
from services import ingest_service as ing
from repositories import firmy_repo


def _setup(conn):
    c = firmy_repo.create(conn, nazev="Cardion", zkratka="Cardion", ico="1")
    a = firmy_repo.create(conn, nazev="Albion", zkratka="Albion", ico="2")
    ing.pridat_ukon(conn, firma_id=c, datum="2026-05-04", typ_kod="PŘEVOD", celkem=1300, zaplaceno_kc=1300)
    ing.pridat_ukon(conn, firma_id=c, datum="2026-05-05", typ_kod="DOVOZ", celkem=2000)
    ing.pridat_ukon(conn, firma_id=a, datum="2026-05-06", typ_kod="PŘEVOD", celkem=1300, zaplaceno_kc=500)
    return c, a


def test_month_summary(conn):
    _setup(conn)
    s = st.mesicni_souhrn(conn, 2026, 5)
    assert s["pocet"] == 3 and s["trzby"] == 4600


def test_outstanding(conn):
    _setup(conn)
    assert st.nezaplaceno_celkem(conn) == 2800


def test_per_firma_and_type(conn):
    _setup(conn)
    byf = {r["zkratka"]: r["trzby"] for r in st.podle_firmy(conn, 2026, 5)}
    assert byf == {"Cardion": 3300, "Albion": 1300}
    byt = {r["typ_kod"]: r["pocet"] for r in st.podle_typu(conn, 2026, 5)}
    assert byt == {"PŘEVOD": 2, "DOVOZ": 1}


def test_year_trend_has_12_months(conn):
    _setup(conn)
    trend = st.rocni_trend(conn, 2026)
    assert len(trend) == 12
    assert trend[4]["trzby"] == 4600


def test_rocni_trend_podle_firmy(conn):
    _setup(conn)  # Cardion: 2 úkony in May; Albion: 1 in May
    rows = st.rocni_trend_podle_firmy(conn, 2026)
    by = {r["zkratka"]: r["pocty"] for r in rows}
    assert len(by["Cardion"]) == 12
    assert by["Cardion"][4] == 2   # index 4 = May
    assert by["Albion"][4] == 1
    assert rows[0]["zkratka"] == "Cardion"  # ordered by total count desc


def test_denni_souhrn(conn):
    _setup(conn)
    s = st.denni_souhrn(conn, "2026-05-04")
    assert s["pocet"] == 1 and s["trzby"] == 1300
    empty = st.denni_souhrn(conn, "2026-01-01")
    assert empty["pocet"] == 0 and empty["trzby"] == 0


def test_nezaplaceno_podle_firmy(conn):
    _setup(conn)
    # Cardion: DOVOZ 2000 unpaid; Albion: PŘEVOD 1300 with 500 paid → 800 owed
    rows = st.nezaplaceno_podle_firmy(conn)
    by = {r["zkratka"]: (r["pocet"], r["dluh"]) for r in rows}
    assert by["Cardion"] == (1, 2000)
    assert by["Albion"] == (1, 800)
    assert rows[0]["zkratka"] == "Cardion"  # ordered by dluh DESC
