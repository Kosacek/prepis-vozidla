"""Offline contract tests: no Anthropic request is sent."""
import copy
import time
from datetime import date
from types import SimpleNamespace as NS

import pytest

import config
import db
from repositories import firmy_repo, ppd_repo, typy_repo, ukony_repo
from services import ai_assistant as assistant, ai_tools

TODAY = date(2026, 10, 8)
PERIOD = {"od": "2026-10-01", "do": "2026-10-08"}


def block(name, input, id="call-1"):
    return NS(type="tool_use", name=name, input=input, id=id)


def response(*blocks, stop="tool_use"):
    return NS(content=list(blocks), stop_reason=stop,
              usage=NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=3))


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.messages = self

    def with_options(self, **options):
        self.options = options
        return self

    def create(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


@pytest.fixture
def ai_db(conn):
    fid = firmy_repo.create(conn, nazev="Albion", zkratka="Albion", ico="1")
    typy_repo.upsert(conn, "PŘEVOD", 1300, 1)
    ukony_repo.create(conn, firma_id=fid, datum="2026-10-02", typ_kod="PŘEVOD",
                      celkem=1300, zpracoval="David")
    return conn.execute("PRAGMA database_list").fetchone()["file"]


def query(**changes):
    data = {"metrika": "soucet_kc", "skupiny": [], "obdobi": PERIOD,
            "filtry": {}, "prumer_na": None, "jen_kde_vic_nez": None,
            "cele_obdobi": False}
    data.update(changes)
    return data


def test_thinking_first_two_rounds_and_append_only_history(ai_db):
    thinking = NS(type="thinking", text="reasoning")
    first = block("agregace", query(), "a")
    second = block("seznam_ukonu", {"obdobi": PERIOD, "filtry": {},
                                    "limit": 1, "vcetne_detailu": False,
                                    "cele_obdobi": False}, "b")
    fake = FakeClient([response(thinking, first), response(second),
                       response(block("odpoved", {"veta": "1 300 Kč za 1 úkon.",
                                                        "graf": "sloupcovy", "predpoklady": ""}))])
    result = assistant.ask("Kolik?", db_path=ai_db, today=TODAY, client=fake)
    assert result["typ"] == "odpoved" and result["veta_overena"]
    assert result["nastroj"] == "seznam_ukonu"
    assert [c["name"] for c in result["volani"]] == ["agregace", "seznam_ukonu"]
    assert result["tokeny"] == {"input_tokens": 30, "output_tokens": 15,
                                "cache_read_input_tokens": 9}
    assert fake.calls[1]["messages"][1]["content"][0].type == "thinking"
    assert fake.calls[1]["messages"][1]["content"][1].id == "a"
    assert [b.type for b in fake.calls[2]["messages"][1]["content"]] == ["thinking", "tool_use"]
    assert fake.calls[0]["model"] == "claude-haiku-5-5"
    assert fake.calls[0]["max_tokens"] == 4096
    assert fake.calls[0]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert fake.calls[0]["output_config"] == {"effort": "low"}
    assert not ({"temperature", "top_p", "top_k", "thinking", "tool_choice"} & fake.calls[0].keys())
    assert fake.options["max_retries"] == 1 and 0 < fake.options["timeout"] <= 30


def test_all_results_one_user_turn(ai_db):
    fake = FakeClient([response(block("agregace", query(), "a"),
                                block("agregace", query(metrika="pocet"), "b")),
                       response(block("odpoved", {"veta": "", "graf": "zadny",
                                                        "predpoklady": ""}))])
    assistant.ask("Souhrn", db_path=ai_db, today=TODAY, client=fake)
    messages = fake.calls[1]["messages"]
    assert len(messages) == 3
    assert messages[2]["role"] == "user"
    assert [r["tool_use_id"] for r in messages[2]["content"]] == ["a", "b"]


def test_validation_error_is_tool_result_and_recovers(ai_db):
    fake = FakeClient([response(block("agregace", query(metrika="wrong"))),
                       response(block("agregace", query(), "ok")),
                       response(block("odpoved", {"veta": "1 300 Kč", "graf": "zadny",
                                                        "predpoklady": ""}))])
    result = assistant.ask("Kolik", db_path=ai_db, today=TODAY, client=fake)
    error = fake.calls[1]["messages"][-1]["content"][0]
    assert error["is_error"] is True and "Neplatná" in error["content"]
    assert result["veta_overena"] and result["vysledek"]["radky"][0]["hodnota"] == 1300


def test_clarification_and_end_turn(ai_db):
    fake = FakeClient([response(block("doptat_se", {"otazka": "Co myslíte?",
                                                   "moznosti": ["Dluhy", "Tržby"]}))])
    result = assistant.ask("Peníze", db_path=ai_db, today=TODAY, client=fake)
    assert result["typ"] == "doptat_se" and result["moznosti"] == ["Dluhy", "Tržby"]
    fake = FakeClient([response(block("agregace", query())),
                       response(NS(type="text", text="hotovo"), stop="end_turn")])
    result = assistant.ask("Peníze", db_path=ai_db, today=TODAY, client=fake)
    assert result["veta"] == "" and result["vysledek"]["radky"][0]["hodnota"] == 1300


def test_four_round_cap_and_model_failures(ai_db):
    fake = FakeClient([response(block("agregace", query(), str(i))) for i in range(5)])
    with pytest.raises(assistant.AssistantUnavailable, match="čtyř"):
        assistant.ask("Opakuj", db_path=ai_db, today=TODAY, client=fake)
    assert len(fake.calls) == 5
    for stop in ("max_tokens", "refusal"):
        with pytest.raises(assistant.AssistantUnavailable):
            assistant.ask("Peníze", db_path=ai_db, today=TODAY,
                          client=FakeClient([response(NS(type="text", text=""), stop=stop)]))


@pytest.mark.parametrize("name", ["APITimeoutError", "APIConnectionError",
                                    "RateLimitError", "APIStatusError"])
def test_api_errors_become_unavailable(ai_db, name):
    error_type = type(name, (Exception,), {})
    with pytest.raises(assistant.AssistantUnavailable):
        assistant.ask("Peníze", db_path=ai_db, today=TODAY,
                      client=FakeClient([error_type("offline")]))


def test_missing_key_raises_before_sdk_import(ai_db, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(assistant.AssistantUnavailable, match="ANTHROPIC_API_KEY"):
        assistant.ask("Peníze", db_path=ai_db, today=TODAY)


@pytest.mark.parametrize("sentence,valid", [
    ("Celkem 12 345 Kč.", True), ("Průměr 1,5 Kč.", True),
    ("Průměr 1,50 Kč.", True), ("Od 27. 7. 2026.", True),
    ("Přesně 12 346 Kč.", False), ("Průměr 1,51 Kč.", False),
    ("Bylo to 28. 7.", False), ("13 úkonů.", False),
])
def test_sentence_number_check(sentence, valid):
    result = {"radky": [{"skupina": ["firma"], "hodnota": 12345,
                         "pocet": 12}, {"skupina": ["den"], "hodnota": 1.5, "pocet": 1}],
              "obdobi": {"od": "2026-07-27", "do": "2026-10-08"},
              "upozorneni": "Roman se zapisuje od 27. 7."}
    assert assistant.verify_sentence(sentence, [result]) is valid


def test_ppd_tool_excludes_deleted_and_limits_list(conn):
    for i in range(25):
        ppd_repo.upsert(conn, {"cislo": i + 1, "datum": "2026-09-15", "castka": 100,
                               "prijato_od": "Jan", "ucel": "Převod", "vozidlo": f"RZ{i}",
                               "smazano": i == 24})
    period = {"od": "2026-09-01", "do": "2026-09-30"}
    result = ai_tools.doklady_ppd(conn, {"obdobi": period, "hledat": None, "seznam": True}, TODAY)
    assert result["pocet"] == 24 and result["soucet_kc"] == 2400
    assert len(result["polozky"]) == 20
    assert all(set(row) == {"cislo", "datum", "prijato_od", "castka", "ucel", "vozidlo"}
               for row in result["polozky"])
    assert ai_tools.doklady_ppd(conn, {"obdobi": period, "hledat": "RZ24", "seznam": True}, TODAY)["pocet"] == 0
    assert "polozky" not in ai_tools.doklady_ppd(conn, {"obdobi": period, "hledat": None, "seznam": False}, TODAY)
    with pytest.raises(ValueError):
        ai_tools.doklady_ppd(conn, {"obdobi": period, "hledat": 9, "seznam": True}, TODAY)


def test_route_fallback_for_missing_key_error_simple_mode_and_rate_limit(tmp_path, monkeypatch):
    import app as appmod
    from routes import ask as ask_route
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app = appmod.create_app()
    app.testing = True
    with app.test_client() as client:
        with app.app_context():
            conn = db.get_db()
            fid = firmy_repo.create(conn, nazev="Cardion", zkratka="Cardion", ico="1")
            ukony_repo.create(conn, firma_id=fid, datum="2026-10-01", typ_kod="PŘEVOD", celkem=1300)
        body = client.get("/zeptej?q=Kolik+pro+Cardion%3F").get_data(as_text=True)
        assert "Jednodušší režim" in body and "1 300 Kč" in body
        monkeypatch.setattr(ask_route.ai_assistant, "ask", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("API down")))
        assert "Jednodušší režim" in client.get("/zeptej?q=Cardion").get_data(as_text=True)
        assert "Jednodušší režim" in client.get("/zeptej?q=Cardion&rezim=jednoduchy").get_data(as_text=True)
        monkeypatch.setattr(ask_route.ai_assistant, "ask", lambda *a, **k: {"typ": "doptat_se",
            "otazka": "Co chcete?", "moznosti": ["Dluhy", "Tržby"], "volani": [], "tokeny": {},
            "ms": 1, "veta_overena": False})
        with client.session_transaction() as sess:
            sid = sess["zeptej_sid"]
        monkeypatch.setitem(ask_route._rate, sid, [time.monotonic()] * 30)
        assert "limit dotazů" in client.get("/zeptej?q=Cardion").get_data(as_text=True)


def test_route_ai_chart_table_clarification_and_ppd(tmp_path, monkeypatch):
    import app as appmod
    from routes import ask as ask_route
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    app = appmod.create_app()
    app.testing = True
    with app.test_client() as client:
        with app.app_context():
            conn = db.get_db()
            fid = firmy_repo.create(conn, nazev="Albion", zkratka="Albion", ico="1")
            uid = ukony_repo.create(conn, firma_id=fid, datum="2026-10-02",
                                    typ_kod="PŘEVOD", celkem=1300, rz="1AB2345")
        ai = {"typ": "odpoved", "veta": "Albion 1 300 Kč", "veta_overena": True,
              "graf": "sloupcovy", "predpoklady": "souhrn", "nastroj": "agregace",
              "vysledek": {"radky": [{"skupina": ["Albion"], "hodnota": 1300, "pocet": 1}],
                           "metrika": "soucet_kc", "obdobi": PERIOD,
                           "pouzite_filtry": {}, "upozorneni": "Roman se zapisuje od 27. 7.",
                           "bez_zpracovatele": 2},
              "volani": [{"name": "agregace", "input": query(skupiny=["firma"])}],
              "tokeny": {}, "ms": 1}
        monkeypatch.setattr(ask_route.ai_assistant, "ask", lambda *a, **k: ai)
        body = client.get("/zeptej?q=Albion").get_data(as_text=True)
        assert "Albion 1 300 Kč" in body and 'id="ask-chart"' in body
        assert "Jak jsem to spočítal" in body and "Roman se zapisuje" in body
        assert "<td>Albion</td>" in body and "Přemýšlím" in body
        ai["veta_overena"] = False
        body = client.get("/zeptej?q=Albion").get_data(as_text=True)
        assert "Albion 1 300 Kč" not in body and "<td>Albion</td>" in body
        ai.update(typ="doptat_se", otazka="Co chcete vědět?", moznosti=["Dluhy", "Tržby"])
        body = client.get("/zeptej?q=penize").get_data(as_text=True)
        assert "Co chcete vědět?" in body and "/zeptej?q=Dluhy" in body
        ai.update(typ="odpoved", nastroj="doklady_ppd", graf="zadny", veta="",
                  vysledek={"pocet": 1, "soucet_kc": 1300, "obdobi": PERIOD,
                            "polozky": [{"cislo": 7, "datum": "2026-10-02", "prijato_od": "Jan",
                                         "castka": 1300, "ucel": "Převod", "vozidlo": "ABC"}]},
                  volani=[{"name": "doklady_ppd", "input": {"obdobi": PERIOD,
                                                              "hledat": None, "seznam": True}}])
        body = client.get("/zeptej?q=PPD").get_data(as_text=True)
        assert "přijaté hotovosti" in body and "<td>Jan</td>" in body
        ai.update(nastroj="seznam_ukonu", vysledek={"radky": [{"datum": "2026-10-02"}],
            "obdobi": PERIOD, "pouzite_filtry": {}, "upozorneni": None},
            volani=[{"name": "seznam_ukonu", "input": {"obdobi": PERIOD, "filtry": {}}}])
        body = client.get("/zeptej?q=posledni").get_data(as_text=True)
        assert "1AB2345" in body and f"/ukony/{uid}/upravit" in body


def test_sentence_accepts_decimal_and_rounding():
    result = {"radky": [{"hodnota": 12345.5, "pocet": 1}],
              "obdobi": {"od": "2026-10-01", "do": "2026-10-31"}}
    assert assistant.verify_sentence("12 345,50 Kč", [result])
    assert assistant.verify_sentence("12 346 Kč", [result])
    assert not assistant.verify_sentence("12 347 Kč", [result])


# ── API schema compatibility (found in the live eval, 2026-10-08) ─────────────
_UNSUPPORTED = {"minimum", "maximum", "minItems", "maxItems",
                "minLength", "maxLength", "pattern"}


def _walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def test_api_tools_have_no_keywords_strict_mode_rejects():
    for node in _walk(ai_tools.API_TOOLS):
        assert not (_UNSUPPORTED & set(node)), node
        if isinstance(node.get("type"), list) and "enum" in node:
            assert None not in node["enum"], node


def test_api_tools_stay_under_the_union_type_limit():
    unions = sum(1 for node in _walk(ai_tools.API_TOOLS)
                 if isinstance(node.get("type"), list) or "anyOf" in node)
    assert unions <= 16


def test_api_tools_leave_the_validation_schemas_untouched():
    agregace = ai_tools.TOOLS[0]["input_schema"]["properties"]
    assert agregace["skupiny"]["maxItems"] == 2
    assert None in agregace["prumer_na"]["enum"]


def test_prumer_zadny_maps_back_to_none():
    assert ai_tools.from_api_input({"prumer_na": "zadny", "x": 1}) == {"prumer_na": None, "x": 1}
    assert ai_tools.from_api_input({"prumer_na": "den"})["prumer_na"] == "den"


# ── sentence check additions ──────────────────────────────────────────────────
ROWS = {"radky": [{"skupina": ["červenec"], "hodnota": 389450, "pocet": 277},
                  {"skupina": ["srpen"], "hodnota": 545100, "pocet": 339}],
        "obdobi": {"od": "2026-07-01", "do": "2026-08-31"}}


def test_sentence_may_use_numbers_from_the_question():
    result = {"radky": [{"skupina": [], "hodnota": 14, "pocet": 14}],
              "obdobi": {"od": "2026-08-01", "do": "2026-10-08"}}
    sentence = "Za poslední 3 měsíce (1. 8. – 8. 10. 2026) je 14 úkonů typu 3RZ."
    assert assistant.verify_sentence(sentence, [result], question="kolik 3RZ za poslední 3 měsíce")
    assert not assistant.verify_sentence(sentence, [result])


def test_sentence_may_use_row_dates_and_row_counts():
    result = {"radky": [{"datum": "2026-10-07", "celkem": 1800}] * 3,
              "obdobi": {"od": "2026-05-04", "do": "2026-10-08"}}
    assert assistant.verify_sentence("Poslední 3 úkony jsou ze 7. 10., po 1 800 Kč.", [result])


def test_two_row_difference_and_percentage_are_accepted_but_invented_numbers_not():
    ok = "Srpen má o 62 úkonů a o 155 650 Kč víc (+22 %, +40 %)."
    assert assistant.verify_sentence(ok, [ROWS])
    assert not assistant.verify_sentence("Srpen má o 63 úkonů víc.", [ROWS])


def test_group_total_comes_from_the_tool(conn):
    result = ai_tools.agregace(conn, {
        "metrika": "pocet", "skupiny": ["firma"], "obdobi": PERIOD, "filtry": {},
        "prumer_na": None, "jen_kde_vic_nez": None, "cele_obdobi": False}, TODAY)
    assert result["celkem"]["pocet"] == sum(r["pocet"] for r in result["radky"])
    assert result["pocet_radku"] == len(result["radky"])


def test_leaked_tool_markup_is_cut_from_the_sentence():
    raw = 'Nejvíc bylo 93 úkonů.</veta>\n<parameter name="graf">cara'
    assert assistant._clean_sentence(raw) == "Nejvíc bylo 93 úkonů."
