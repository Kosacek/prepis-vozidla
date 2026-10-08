"""Fixture-only checks of the read-only query contract and exact SQL metrics."""
import copy
import sqlite3
from datetime import date

import pytest

import db
from repositories import firmy_repo, typy_repo, ukony_repo
from services import ai_tools as ai

TODAY = date(2026, 10, 8)
PERIOD = {"od": "2026-07-01", "do": "2026-08-03"}


def params(**overrides):
    result = {"metrika": "pocet", "skupiny": [], "obdobi": dict(PERIOD),
              "filtry": {}, "prumer_na": None, "jen_kde_vic_nez": None,
              "cele_obdobi": False}
    result.update(overrides)
    return result


def aggregate(conn, **overrides):
    return ai.agregace(conn, params(**overrides), TODAY)


def listing(conn, **overrides):
    query = {"obdobi": dict(PERIOD), "filtry": {}}
    query.update(overrides)
    return ai.seznam_ukonu(conn, query, TODAY)


@pytest.fixture
def data(conn):
    """Amounts total 5545 Kč, paid 1410 Kč, owed 4135 Kč. Tracking starts
    David 1 July, Petr 2 July, Roman 27 July. July 13 has no Monday rows.
    """
    cardion = firmy_repo.create(conn, nazev="Cardion s.r.o.", zkratka="Cardion", ico="1")
    albion = firmy_repo.create(conn, nazev="Albion", zkratka="Albion", ico="2")
    typy_repo.upsert(conn, "PŘEVOD", 101, 1)
    typy_repo.upsert(conn, "DOVOZ", 202, 2)
    rows = [
        ("2026-07-01", cardion, "PŘEVOD", 101, 0, "David", "1AB1234", "EL značky"),
        ("2026-07-02", cardion, "DOVOZ", 202, 100, "Petr", None, "ÉL auto"),
        ("2026-07-06", albion, "PŘEVOD", 303, 303, "David", "", "obyčejný"),
        ("2026-07-20", cardion, "PŘEVOD", 404, 0, "David", "  ", "vyřízení"),
        ("2026-07-27", albion, "DOVOZ", 505, 200, "Roman", "5AB1234", "převoz"),
        ("2026-07-27", cardion, "PŘEVOD", 606, 0, "David", "6AB1234", None),
        ("2026-07-28", cardion, "DOVOZ", 707, 707, None, "\t\n", "žádné"),
        ("2026-07-31", albion, "PŘEVOD", 808, 100, None, "8AB1234", "ELEKTRICKÁ"),
        ("2026-08-02", cardion, "DOVOZ", 909, 0, "Roman", "9AB1234", "pozdě"),
        ("2026-08-03", albion, "PŘEVOD", 1000, 0, "David", "0AB1234", "jiné"),
    ]
    for day, firm, typ, total, paid, person, rz, note in rows:
        state = "zaplaceno" if paid == total else "castecne" if paid else "nezaplaceno"
        ukony_repo.create(conn, firma_id=firm, datum=day, typ_kod=typ, celkem=total,
                          zaplaceno_kc=paid, stav_platby=state, zpracoval=person,
                          rz=rz, poznamka=note, vin=f"VIN{total}")
    return conn, cardion, albion


@pytest.mark.parametrize("metric, expected", [
    ("pocet", 10), ("soucet_kc", 5545), ("prumer_kc", 554.5),
    ("nezaplaceno_kc", 4135), ("zaplaceno_kc", 1410),
])
def test_each_metric_and_return_contract(data, metric, expected):
    conn, _, _ = data
    result = aggregate(conn, metrika=metric)
    assert result == {"radky": [{"skupina": [], "hodnota": expected, "pocet": 10}],
                      "metrika": metric, "obdobi": PERIOD, "upozorneni": None,
                      "bez_zpracovatele": 2, "pouzite_filtry": {}}
    assert type(result["radky"][0]["hodnota"]) is (float if metric == "prumer_kc" else int)


def test_weekday_labels_and_monday_to_sunday_order(data):
    conn, _, _ = data
    assert aggregate(conn, metrika="soucet_kc", skupiny=["den_v_tydnu"])["radky"] == [
        {"skupina": ["Po"], "hodnota": 2818, "pocet": 5},
        {"skupina": ["Út"], "hodnota": 707, "pocet": 1},
        {"skupina": ["St"], "hodnota": 101, "pocet": 1},
        {"skupina": ["Čt"], "hodnota": 202, "pocet": 1},
        {"skupina": ["Pá"], "hodnota": 808, "pocet": 1},
        {"skupina": ["Ne"], "hodnota": 909, "pocet": 1},
    ]


def test_two_groups_keep_people_and_weekdays_separate(data):
    conn, _, _ = data
    assert aggregate(conn, metrika="soucet_kc", skupiny=["den_v_tydnu", "zpracoval"],
                     cele_obdobi=True)["radky"] == [
        {"skupina": ["Po", "David"], "hodnota": 2313, "pocet": 4},
        {"skupina": ["Po", "Roman"], "hodnota": 505, "pocet": 1},
        {"skupina": ["Út", "nevyplněno"], "hodnota": 707, "pocet": 1},
        {"skupina": ["St", "David"], "hodnota": 101, "pocet": 1},
        {"skupina": ["Čt", "Petr"], "hodnota": 202, "pocet": 1},
        {"skupina": ["Pá", "nevyplněno"], "hodnota": 808, "pocet": 1},
        {"skupina": ["Ne", "Roman"], "hodnota": 909, "pocet": 1},
    ]


@pytest.mark.parametrize("metric, expected", [("pocet", 0.67), ("soucet_kc", 235.67),
                                             ("prumer_kc", 235.67)])
def test_weekday_average_includes_calendar_days_without_rows(data, metric, expected):
    conn, _, _ = data
    # Three Mondays (6, 13, 20 July), two rows. All other weekdays have zero rows.
    result = aggregate(conn, metrika=metric, skupiny=["den_v_tydnu"],
                       obdobi={"od": "2026-07-06", "do": "2026-07-26"}, prumer_na="den_v_tydnu")
    assert result["radky"] == [{"skupina": ["Po"], "hodnota": expected, "pocet": 2}]


def test_weekday_average_with_one_weekday_filter(data):
    conn, _, _ = data
    result = aggregate(conn, prumer_na="den_v_tydnu", filtry={"dny_v_tydnu": [1]})
    assert result["radky"] == [{"skupina": [], "hodnota": 1.0, "pocet": 5}]


def test_weekday_calendar_divisors_differ_with_partial_week(data):
    conn, _, _ = data
    result = aggregate(conn, metrika="soucet_kc", skupiny=["den_v_tydnu"], prumer_na="den_v_tydnu")
    assert [row["hodnota"] for row in result["radky"]] == [563.6, 176.75, 20.2, 40.4, 161.6, 181.8]


@pytest.mark.parametrize("unit, metric, expected", [
    ("den", "pocet", 0.29), ("den", "soucet_kc", 163.09),
    ("tyden", "soucet_kc", 924.17), ("mesic", "soucet_kc", 2772.5),
    ("mesic", "nezaplaceno_kc", 2067.5), ("mesic", "zaplaceno_kc", 705.0),
])
def test_calendar_averages(data, unit, metric, expected):
    conn, _, _ = data
    assert aggregate(conn, metrika=metric, prumer_na=unit)["radky"] == [
        {"skupina": [], "hodnota": expected, "pocet": 10}]


def test_month_average_counts_partial_and_empty_months(data):
    conn, _, _ = data
    # The end cuts August off on the 3rd; an empty September still counts.
    assert aggregate(conn, metrika="soucet_kc", prumer_na="mesic",
                     obdobi={"od": "2026-07-31", "do": "2026-08-03"})["radky"] == [
        {"skupina": [], "hodnota": 1358.5, "pocet": 3}]
    assert aggregate(conn, metrika="soucet_kc", prumer_na="mesic",
                     obdobi={"od": "2026-07-31", "do": "2026-09-01"})["radky"] == [
        {"skupina": [], "hodnota": 905.67, "pocet": 3}]


@pytest.mark.parametrize("group, expected", [
    ("tyden", [("2026-06-29", 303, 2), ("2026-07-06", 303, 1),
               ("2026-07-20", 404, 1), ("2026-07-27", 3535, 5), ("2026-08-03", 1000, 1)]),
    ("mesic", [("červenec 2026", 3636, 8), ("srpen 2026", 1909, 2)]),
    ("firma", [("Albion", 2616, 4), ("Cardion", 2929, 6)]),
    ("typ", [("DOVOZ", 2323, 4), ("PŘEVOD", 3222, 6)]),
    ("stav_platby", [("částečně zaplaceno", 1515, 3), ("nezaplaceno", 3020, 5),
                     ("zaplaceno", 1010, 2)]),
])
def test_remaining_groupings(data, group, expected):
    conn, _, _ = data
    assert aggregate(conn, metrika="soucet_kc", skupiny=[group])["radky"] == [
        {"skupina": [label], "hodnota": value, "pocet": count} for label, value, count in expected]


def test_day_grouping_and_inclusive_single_day(data):
    conn, _, _ = data
    assert aggregate(conn, metrika="soucet_kc", skupiny=["den"],
                     obdobi={"od": "2026-07-27", "do": "2026-07-27"})["radky"] == [
        {"skupina": ["2026-07-27"], "hodnota": 1111, "pocet": 2}]


def test_iso_week_across_year_boundary(data):
    conn, firm, _ = data
    for day in ("2026-12-31", "2027-01-03", "2027-01-04"):
        ukony_repo.create(conn, firma_id=firm, datum=day, typ_kod="DOVOZ", celkem=100)
    period = {"od": "2026-12-31", "do": "2027-01-04"}
    assert aggregate(conn, skupiny=["tyden"], obdobi=period)["radky"] == [
        {"skupina": ["2026-12-28"], "hodnota": 2, "pocet": 2},
        {"skupina": ["2027-01-04"], "hodnota": 1, "pocet": 1}]
    assert aggregate(conn, obdobi=period, prumer_na="tyden")["radky"][0]["hodnota"] == 1.5


def test_threshold_excludes_equal_value(data):
    conn, _, _ = data
    assert aggregate(conn, metrika="soucet_kc", skupiny=["firma"], jen_kde_vic_nez=2616)["radky"] == [
        {"skupina": ["Cardion"], "hodnota": 2929, "pocet": 6}]
    assert aggregate(conn, metrika="soucet_kc", skupiny=["firma"], jen_kde_vic_nez=2929)["radky"] == []
    assert aggregate(conn, metrika="prumer_kc", jen_kde_vic_nez=554.5)["radky"] == []


def test_notes_are_case_and_diacritic_insensitive_literal_substrings(data):
    conn, _, _ = data
    assert aggregate(conn, metrika="soucet_kc", filtry={"poznamka_obsahuje": "el"})["radky"] == [
        {"skupina": [], "hodnota": 1111, "pocet": 3}]
    assert aggregate(conn, filtry={"poznamka_obsahuje": "ÉL"})["radky"][0]["hodnota"] == 3
    assert aggregate(conn, filtry={"poznamka_obsahuje": "%_' OR 1=1 --"})["radky"][0]["hodnota"] == 0


def test_without_rz_includes_null_empty_and_whitespace(data):
    conn, _, _ = data
    assert aggregate(conn, metrika="soucet_kc", filtry={"bez_rz": True})["radky"] == [
        {"skupina": [], "hodnota": 1616, "pocet": 4}]
    assert aggregate(conn, filtry={"bez_rz": False})["radky"][0]["hodnota"] == 10


def test_all_filters_apply_to_both_tools_without_mutating_params(data):
    conn, cardion, _ = data
    filters = {"firma_ids": [cardion], "typy": ["DOVOZ"], "zpracoval": ["Petr"],
               "stav_platby": ["castecne"], "dny_v_tydnu": [4],
               "poznamka_obsahuje": "el", "bez_rz": True}
    query = params(metrika="soucet_kc", filtry=filters)
    original = copy.deepcopy(query)
    result = ai.agregace(conn, query, TODAY)
    assert query == original
    assert result["radky"] == [{"skupina": [], "hodnota": 202, "pocet": 1}]
    assert result["pouzite_filtry"] == filters
    assert result["obdobi"] == PERIOD and result["upozorneni"] is None
    assert listing(conn, filtry=filters, vcetne_detailu=True)["radky"] == [
        {"datum": "2026-07-02", "firma": "Cardion", "typ": "DOVOZ", "rz": None,
         "celkem": 202, "stav_platby": "castecne", "zpracoval": "Petr",
         "vin": "VIN202", "poznamka": "ÉL auto"}]


def test_multi_value_and_null_filters(data):
    conn, cardion, albion = data
    result = aggregate(conn, filtry={"firma_ids": [cardion, albion], "typy": ["DOVOZ", "PŘEVOD"],
                                    "dny_v_tydnu": [1, 7], "zpracoval": None,
                                    "poznamka_obsahuje": None, "stav_platby": [], "bez_rz": None})
    assert result["radky"] == [{"skupina": [], "hodnota": 6, "pocet": 6}]
    assert set(result["pouzite_filtry"]) == {"firma_ids", "typy", "dny_v_tydnu"}


def test_common_period_for_grouped_people_and_attribution_coverage(data):
    conn, _, _ = data
    result = aggregate(conn, metrika="soucet_kc", skupiny=["zpracoval"])
    assert result["obdobi"] == {"od": "2026-07-27", "do": "2026-08-03"}
    assert result["upozorneni"] == "Roman se v evidenci zapisuje až od 27. 7., srovnávám od tohoto data."
    assert result["bez_zpracovatele"] == 2
    assert result["radky"] == [
        {"skupina": ["David"], "hodnota": 1606, "pocet": 2},
        {"skupina": ["Roman"], "hodnota": 1414, "pocet": 2},
        {"skupina": ["nevyplněno"], "hodnota": 1515, "pocet": 2}]


def test_common_period_is_from_all_data_and_counts_nulls_despite_people_filter(data):
    conn, _, albion = data
    result = aggregate(conn, skupiny=["zpracoval"], filtry={"zpracoval": ["David", "Roman"],
                                                          "firma_ids": [albion]})
    # Albion's first David row is July 6, but tracking is derived globally.
    assert result["obdobi"]["od"] == "2026-07-27"
    assert result["bez_zpracovatele"] == 2
    assert result["radky"] == [{"skupina": ["David"], "hodnota": 1, "pocet": 1},
                               {"skupina": ["Roman"], "hodnota": 1, "pocet": 1}]


def test_common_period_without_people_group_uses_only_compared_people(data):
    conn, _, _ = data
    result = aggregate(conn, filtry={"zpracoval": ["David", "Petr"]})
    assert result["obdobi"]["od"] == "2026-07-02"
    assert result["upozorneni"] == "Petr se v evidenci zapisuje až od 2. 7., srovnávám od tohoto data."
    assert result["radky"] == [{"skupina": [], "hodnota": 5, "pocet": 5}]


def test_whole_period_disables_clamp_and_warning(data):
    conn, _, _ = data
    result = aggregate(conn, skupiny=["zpracoval"], cele_obdobi=True)
    assert result["obdobi"] == PERIOD and result["upozorneni"] is None
    assert result["radky"] == [
        {"skupina": ["David"], "hodnota": 5, "pocet": 5},
        {"skupina": ["Petr"], "hodnota": 1, "pocet": 1},
        {"skupina": ["Roman"], "hodnota": 2, "pocet": 2},
        {"skupina": ["nevyplněno"], "hodnota": 2, "pocet": 2}]
    result = aggregate(conn, filtry={"zpracoval": ["David", "Roman"]}, cele_obdobi=True)
    assert result["obdobi"] == PERIOD and result["upozorneni"] is None
    assert result["radky"][0]["hodnota"] == 7


def test_already_common_period_and_single_person_do_not_warn(data):
    conn, _, _ = data
    assert aggregate(conn, skupiny=["zpracoval"],
                     obdobi={"od": "2026-07-28", "do": "2026-08-03"})["upozorneni"] is None
    assert aggregate(conn, filtry={"zpracoval": ["David", "David"]})["obdobi"] == PERIOD


def test_common_period_has_no_overlap(data):
    conn, _, _ = data
    result = aggregate(conn, prumer_na="den", filtry={"zpracoval": ["David", "Roman"]},
                       obdobi={"od": "2026-07-01", "do": "2026-07-20"})
    assert result["radky"] == [{"skupina": [], "hodnota": 0.0, "pocet": 0}]
    assert result["bez_zpracovatele"] == 0
    assert "není společné období" in result["upozorneni"]


def test_clamp_changes_calendar_divisor(data):
    conn, _, _ = data
    assert aggregate(conn, skupiny=["zpracoval"], prumer_na="den")["radky"] == [
        {"skupina": ["David"], "hodnota": 0.25, "pocet": 2},
        {"skupina": ["Roman"], "hodnota": 0.25, "pocet": 2},
        {"skupina": ["nevyplněno"], "hodnota": 0.25, "pocet": 2}]


def test_list_default_limit_cap_order_and_detail_toggle(data):
    conn, firm, _ = data
    for number in range(55):
        ukony_repo.create(conn, firma_id=firm, datum="2026-08-03", typ_kod="PŘEVOD", celkem=number,
                          vin=f"PRIVATE{number}", poznamka=f"detail {number}")
    result = listing(conn)
    assert len(result["radky"]) == 20
    assert len(listing(conn, limit=None)["radky"]) == 20
    assert len(listing(conn, limit=999)["radky"]) == 50
    assert len(listing(conn, limit=1)["radky"]) == 1
    assert [row["celkem"] for row in result["radky"]] == list(range(54, 34, -1))
    assert all(set(row) == {"datum", "firma", "typ", "rz", "celkem", "stav_platby", "zpracoval"}
               for row in result["radky"])
    assert listing(conn, limit=1, vcetne_detailu=True)["radky"][0] == {
        "datum": "2026-08-03", "firma": "Cardion", "typ": "PŘEVOD", "rz": None,
        "celkem": 54, "stav_platby": "nezaplaceno", "zpracoval": None,
        "vin": "PRIVATE54", "poznamka": "detail 54"}


def test_list_date_order_and_common_period(data):
    conn, _, _ = data
    dates = [row["datum"] for row in listing(conn)["radky"]]
    assert dates == sorted(dates, reverse=True)
    result = listing(conn, filtry={"zpracoval": ["David", "Roman"]})
    assert result["obdobi"]["od"] == "2026-07-27" and len(result["radky"]) == 4
    assert result["bez_zpracovatele"] == 2 and result["upozorneni"] is not None
    assert len(listing(conn, filtry={"zpracoval": ["David", "Roman"]}, cele_obdobi=True)["radky"]) == 7


def test_integer_halere_sums_before_rounding_to_koruna(data):
    conn, firm, _ = data
    for _ in range(50):
        ukony_repo.create(conn, firma_id=firm, datum="2026-10-08", typ_kod="DOVOZ", celkem=0.01)
    period = {"od": "2026-10-08", "do": "2026-10-08"}
    # Sum 50 haléře exactly, then round once. Per-row Kč rounding would lose all of it.
    assert aggregate(conn, metrika="soucet_kc", obdobi=period)["radky"][0]["hodnota"] == 1
    assert aggregate(conn, metrika="nezaplaceno_kc", obdobi=period)["radky"][0]["hodnota"] == 1
    assert aggregate(conn, metrika="prumer_kc", obdobi=period)["radky"][0]["hodnota"] == 0.01
    assert aggregate(conn, metrika="soucet_kc", obdobi=period, prumer_na="den")["radky"][0]["hodnota"] == 0.5


def test_ciselniky_and_empty_database(data):
    conn, cardion, albion = data
    assert ai.ciselniky(conn, TODAY) == {
        "firmy": [{"id": albion, "zkratka": "Albion", "ico": "2"},
                  {"id": cardion, "zkratka": "Cardion", "ico": "1"}],
        "typy": ["A50-X", "DOVOZ", "KOLA", "PŘEVOD"],
        "lide": ["David", "Petr", "Roman"], "obdobi": PERIOD, "dnes": "2026-10-08"}


def test_empty_results(conn):
    assert ai.ciselniky(conn, TODAY)["obdobi"] == {"od": None, "do": None}
    for metric in ai.METRIKY:
        assert aggregate(conn, metrika=metric)["radky"] == [{"skupina": [], "hodnota": 0, "pocet": 0}]
        assert aggregate(conn, metrika=metric, skupiny=["firma"])["radky"] == []
    assert listing(conn)["radky"] == []


def test_connect_ro_rejects_writes_even_with_query_only_disabled(tmp_path):
    path = tmp_path / "příliš # evidence.db"  # "?" is illegal in Windows filenames
    writer = db.connect(str(path))
    db.init_schema(writer)
    firmy_repo.create(writer, nazev="Test", zkratka="Test", ico="1")
    writer.close()
    reader = ai.connect_ro(path)
    try:
        assert reader.row_factory is sqlite3.Row
        assert reader.execute("PRAGMA query_only").fetchone()[0] == 1
        assert reader.execute("SELECT zkratka FROM firmy").fetchone()["zkratka"] == "Test"
        for sql in ("UPDATE firmy SET zkratka='Změna'", "DELETE FROM firmy", "CREATE TABLE bad (id)"):
            with pytest.raises(sqlite3.OperationalError):
                reader.execute(sql)
        reader.execute("PRAGMA query_only=OFF")
        with pytest.raises(sqlite3.OperationalError):
            reader.execute("DELETE FROM firmy")
        assert ai.ciselniky(reader, TODAY)["firmy"][0]["zkratka"] == "Test"
        assert aggregate(reader)["radky"][0]["hodnota"] == 0
    finally:
        reader.close()


def test_connect_ro_does_not_create_missing_database(tmp_path):
    path = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        ai.connect_ro(path)
    assert not path.exists()


def test_tools_schemas_are_strict_recursively():
    def walk(value):
        if isinstance(value, dict):
            types = value.get("type", [])
            if types == "object" or "object" in types:
                assert value["additionalProperties"] is False
                assert set(value["required"]) == set(value["properties"])
                assert len(value["required"]) == len(value["properties"])
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    assert [tool["name"] for tool in ai.TOOLS] == ["agregace", "seznam_ukonu", "odpoved", "doptat_se"]
    for tool in ai.TOOLS:
        assert tool["strict"] is True
        assert set(tool) == {"name", "description", "input_schema", "strict"}
        walk(tool["input_schema"])
    schema = ai.TOOLS[0]["input_schema"]["properties"]
    assert schema["prumer_na"]["type"] == ["string", "null"]
    assert set(schema["filtry"]["properties"]) == {
        "firma_ids", "typy", "zpracoval", "stav_platby", "dny_v_tydnu", "poznamka_obsahuje", "bez_rz"}


@pytest.mark.parametrize("bad", [
    {"metrika": "sql"}, {"metrika": []}, {"skupiny": ["unknown"]},
    {"skupiny": ["firma", "typ", "den"]}, {"skupiny": ["firma", "firma"]},
    {"skupiny": "firma"}, {"skupiny": [None]}, {"prumer_na": "rok"},
    {"prumer_na": "den_v_tydnu"}, {"jen_kde_vic_nez": "100"},
    {"jen_kde_vic_nez": float("nan")}, {"jen_kde_vic_nez": float("inf")},
    {"jen_kde_vic_nez": True}, {"cele_obdobi": "true"}, {"sql": "DROP TABLE ukony"},
    {"obdobi": {"od": "2026-02-30", "do": "2026-08-03"}},
    {"obdobi": {"od": "20260701", "do": "2026-08-03"}},
    {"obdobi": {"od": "2026-7-1", "do": "2026-08-03"}},
    {"obdobi": {"od": "2026-08-04", "do": "2026-08-03"}},
    {"obdobi": {"od": None, "do": "2026-08-03"}}, {"obdobi": None},
    {"filtry": {"firma_ids": "1"}}, {"filtry": {"firma_ids": [True]}},
    {"filtry": {"firma_ids": [0]}}, {"filtry": {"dny_v_tydnu": [0]}},
    {"filtry": {"dny_v_tydnu": [8]}}, {"filtry": {"dny_v_tydnu": [1.5]}},
    {"filtry": {"zpracoval": ["Eva"]}}, {"filtry": {"stav_platby": ["paid"]}},
    {"filtry": {"typy": [""]}}, {"filtry": {"typy": [1]}},
    {"filtry": {"poznamka_obsahuje": 1}}, {"filtry": {"bez_rz": "true"}},
    {"filtry": {"unknown": 1}}, {"filtry": None},
])
def test_bad_aggregation_input_raises_czech_value_error(conn, bad):
    with pytest.raises(ValueError, match=r"musí|Neplatná|neplatn|nesmí|neznámý|vyžaduje"):
        aggregate(conn, **bad)


@pytest.mark.parametrize("bad", [
    {"limit": 0}, {"limit": -1}, {"limit": True}, {"limit": "20"}, {"limit": 1.5},
    {"vcetne_detailu": "true"}, {"cele_obdobi": None}, {"filtry": {"bez_rz": 1}},
    {"obdobi": {"od": "bad", "do": "2026-08-03"}}, {"sql": "SELECT *"},
])
def test_bad_list_input_raises_value_error(conn, bad):
    with pytest.raises(ValueError):
        listing(conn, **bad)


@pytest.mark.parametrize("bad", [None, [], "SELECT *"])
def test_non_object_params_raise_value_error(conn, bad):
    for tool in (ai.agregace, ai.seznam_ukonu):
        with pytest.raises(ValueError, match="musí být objekt"):
            tool(conn, bad, TODAY)
