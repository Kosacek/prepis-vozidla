"""Dashboard period picker: ?obdobi=YYYY | YYYY-MM drives trend + breakdown cards."""
import json
import re
from datetime import date

import pytest

import app as appmod
import config
import db
from repositories import firmy_repo, typy_repo, ukony_repo
from routes import dashboard as dash

TODAY = date(2026, 10, 11)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    a = appmod.create_app()
    a.testing = True
    with a.test_client() as c:
        with a.app_context():
            conn = db.get_db()
            alb = firmy_repo.create(conn, nazev="Albion", zkratka="Albion", ico="11")
            car = firmy_repo.create(conn, nazev="Cardion", zkratka="Cardion", ico="22")
            typy_repo.upsert(conn, "PŘEVOD", 1300, 1)
            typy_repo.upsert(conn, "NOVÉ", 1500, 2)
            for firma, datum, typ, kc in [
                (alb, "2026-05-10", "PŘEVOD", 1000),
                (alb, "2026-05-11", "PŘEVOD", 1000),
                (car, "2026-05-12", "NOVÉ", 5000),
                (car, "2026-09-03", "NOVÉ", 700),
                (alb, "2025-12-01", "PŘEVOD", 300),
            ]:
                ukony_repo.create(conn, firma_id=firma, datum=datum, typ_kod=typ, celkem=kc,
                                  rz="", stav_platby="nezaplaceno", zaplaceno_kc=0)
        yield c


def window_json(body, name):
    m = re.search(rf"window\.{name} = (.*?);\n", body, re.S)
    assert m, name
    return json.loads(m.group(1))


@pytest.mark.parametrize("raw,expected", [
    ("2026-05", (2026, 5)),
    ("2026", (2026, None)),
    (None, (2026, 10)),
    ("", (2026, 10)),
    ("garbage", (2026, 10)),
    ("2026-13", (2026, 10)),
    ("2026-00", (2026, 10)),
    ("1999", (2026, 10)),
    ("2026-5", (2026, 10)),
    ("<script>", (2026, 10)),
])
def test_parse_obdobi(raw, expected):
    assert dash.parse_obdobi(raw, TODAY) == expected


def test_labels_and_values():
    assert dash.obdobi_value(2026, 5) == "2026-05"
    assert dash.obdobi_value(2026, None) == "2026"
    assert dash.obdobi_label(2026, 10) == "Říjen 2026"
    assert dash.obdobi_label(2026, None) == "Celý rok 2026"


def test_month_view_scopes_breakdowns_and_trend(client):
    body = client.get("/?obdobi=2026-05").get_data(as_text=True)
    assert "Květen 2026" in body
    per_firma = {r["zkratka"]: r for r in window_json(body, "PER_FIRMA")}
    assert per_firma["Albion"]["pocet"] == 2 and per_firma["Albion"]["trzby"] == 2000
    assert per_firma["Cardion"]["pocet"] == 1 and per_firma["Cardion"]["trzby"] == 5000
    typy = {t["kod"]: t for t in window_json(body, "PER_TYP")}
    assert typy["NOVÉ"]["trzby"] == 5000 and typy["PŘEVOD"]["pocet"] == 2
    trend = window_json(body, "TREND")
    assert trend["kind"] == "den" and len(trend["labels"]) == 31   # a past month shows all days
    assert sum(r["pocet"] for r in trend["rows"]) == 3
    assert trend["rows"][11]["trzby"] == 5000                      # 12 May


def test_year_view_has_monthly_points(client):
    body = client.get("/?obdobi=2026").get_data(as_text=True)
    assert "Celý rok 2026" in body
    trend = window_json(body, "TREND")
    assert trend["kind"] == "mesic"
    assert 1 <= len(trend["labels"]) <= 12 and trend["labels"][0] == "Led"
    assert len(trend["rows"]) == len(trend["labels"])
    may = trend["rows"][4] if len(trend["rows"]) > 4 else None
    if may is not None:                       # only present once the year has reached May
        assert may["pocet"] == 3 and may["trzby"] == 7000
    per_firma = {r["zkratka"]: r for r in window_json(body, "PER_FIRMA")}
    assert per_firma["Albion"]["pocet"] == 2          # the 2025 úkon is excluded
    assert per_firma["Cardion"]["trzby"] == 5700


def test_past_year_shows_all_twelve_months(client):
    body = client.get("/?obdobi=2025").get_data(as_text=True)
    trend = window_json(body, "TREND")
    assert len(trend["labels"]) == 12 and trend["rows"][11]["pocet"] == 1


def test_rok_alias_and_invalid_fall_back(client):
    assert "Celý rok 2026" in client.get("/?rok=2026").get_data(as_text=True)
    for raw in ("nonsense", "2026-99", "'; drop table ukony;--"):
        r = client.get("/", query_string={"obdobi": raw})
        assert r.status_code == 200
        assert "Říjen" in r.get_data(as_text=True) or "Celý rok" in r.get_data(as_text=True)


def test_empty_period_shows_message(client):
    body = client.get("/?obdobi=2026-02").get_data(as_text=True)
    assert "Žádné úkony v tomto období" in body
    assert window_json(body, "PER_FIRMA") == [] and window_json(body, "PER_TYP") == []


def test_picker_lists_months_and_years_with_selection(client):
    body = client.get("/?obdobi=2026-05").get_data(as_text=True)
    assert 'name="obdobi"' in body and "Celý rok 2025" in body and "Celý rok 2026" in body
    assert re.search(r'<option value="2026-05"\s+selected>Květen 2026', body)
    assert 'value="2025-12"' in body and 'value="2026-09"' in body
    current = f"{date.today():%Y-%m}"
    assert f'value="{current}"' in body                 # current month always selectable
    assert body.index("2026-09") < body.index("2026-05")  # newest first


def test_kpis_ignore_the_selected_period(client):
    a = client.get("/?obdobi=2026-05").get_data(as_text=True)
    b = client.get("/?obdobi=2025").get_data(as_text=True)
    kpi = lambda body: re.findall(r'class="kpi-v" data-count="(\d+)"', body)
    assert kpi(a) == kpi(b) and len(kpi(a)) == 4
