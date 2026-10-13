"""AI hledání — model jen vybírá filtry, čísla a záznamy počítá Python.

Model se tu nahrazuje skriptovaným `post`: každé volání vrátí další připravenou
odpověď, takže se testuje celá smyčka (nástroj → výsledek → věta → kontrola
čísel) bez sítě. Data jsou stejná jako v test_hledani.py.
"""
from datetime import date

import pytest

import hledani_ai
from tests.test_hledani import doklady, firmy, vystupy  # noqa: F401  (fixtures)

TODAY = date(2026, 7, 25)


class _Resp:
    def __init__(self, data, status=200):
        self._data, self.status_code = data, status

    def json(self):
        return self._data


def _tool(name, inp, id_="t1"):
    return {"type": "tool_use", "id": id_, "name": name, "input": inp}


def _turn(*blocks, stop="tool_use"):
    return {"content": list(blocks), "stop_reason": stop,
            "usage": {"input_tokens": 100, "output_tokens": 20}}


def scripted(*turns):
    calls = []
    queue = list(turns)

    def post(url, headers=None, json=None, timeout=None):
        calls.append(json)
        item = queue.pop(0)
        return item if isinstance(item, _Resp) else _Resp(item)
    post.calls = calls
    return post


def ask(post, data, q="kolik převodů v červenci"):
    vys, dok, fir = data
    return hledani_ai.zeptej(q, vys, dok, fir, api_key="k", post=post, today=TODAY)


@pytest.fixture
def data(vystupy, doklady, firmy):  # noqa: F811
    return vystupy, doklady, firmy


def test_model_picks_filters_python_counts(data):
    post = scripted(
        _turn(_tool("zadosti", {"od": "2026-07-01", "do": "2026-07-31", "typy": ["zmeny"]})),
        _turn(_tool("odpoved", {"veta": "V červenci byly **2 převody**, naposledy 20. 7."}, "t2")),
    )
    res = ask(post, data)
    assert res["ai"] is True
    assert [v["rz"] for v in res["vystupy"]] == ["3BR4008", "1AB2345"]
    assert res["veta"] == "V červenci byly **2 převody**, naposledy 20. 7."
    assert res["headline"] == "2 žádosti"
    # Model dostal součty z Pythonu, ne aby si je počítal.
    tool_result = post.calls[1]["messages"][-1]["content"][0]["content"]
    assert '"pocet": 2' in tool_result


def test_invented_number_drops_the_sentence(data):
    post = scripted(
        _turn(_tool("zadosti", {"od": "2026-07-01", "do": "2026-07-31", "typy": ["zmeny"]})),
        _turn(_tool("odpoved", {"veta": "V červenci bylo **6 převodů**."}, "t2")),
    )
    res = ask(post, data)
    assert res["veta"] == ""                 # 6 ve výsledku není
    assert res["headline"] == "2 žádosti"    # deterministický nadpis zůstává
    assert len(res["vystupy"]) == 2


def test_receipts_sum_comes_from_python(data):
    post = scripted(
        _turn(_tool("doklady", {"od": "2026-07-01", "do": "2026-07-31"})),
        _turn(_tool("odpoved", {"veta": "V červenci **2 doklady** za **2 800 Kč**."}, "t2")),
    )
    res = ask(post, data, "doklady za červenec")
    assert [d["cislo"] for d in res["doklady"]] == [153, 152]
    assert res["headline"] == "2 doklady za 2 800 Kč"
    assert res["veta"]


def test_receipt_plate_matches_without_spaces(data):
    vys, dok, fir = data
    dok = [dict(dok[0], vozidlo="3BR 4008")]
    post = scripted(_turn(_tool("doklady", {"hledat": "3BR4008"})),
                    _turn(_tool("odpoved", {"veta": "Našel jsem **1 doklad**."}, "t2")))
    res = hledani_ai.zeptej("doklad 3BR4008", vys, dok, fir, api_key="k", post=post, today=TODAY)
    assert len(res["doklady"]) == 1


def test_who_filter_uses_profile(data):
    vys, dok, fir = data
    vys = [dict(v, profil="Roman" if i == 0 else "David") for i, v in enumerate(vys)]
    post = scripted(_turn(_tool("zadosti", {"kdo": ["roman"]})),
                    _turn(_tool("odpoved", {"veta": "Roman udělal **1 žádost**."}, "t2")))
    res = hledani_ai.zeptej("co dělal Roman", vys, dok, fir, api_key="k", post=post, today=TODAY)
    assert [v["profil"] for v in res["vystupy"]] == ["Roman"]


def test_clarifying_question(data):
    post = scripted(_turn(_tool("doptat_se", {"otazka": "Myslíš žádosti, nebo doklady?",
                                              "moznosti": ["Žádosti dnes", "Doklady dnes", "Firmy", "navíc"]})))
    res = ask(post, data, "dnes")
    assert res["otazka"] == "Myslíš žádosti, nebo doklady?"
    assert res["moznosti"] == ["Žádosti dnes", "Doklady dnes", "Firmy"]


def test_answer_without_data_is_rejected(data):
    post = scripted(_turn(_tool("odpoved", {"veta": "Bylo jich hodně."})))
    with pytest.raises(hledani_ai.AINedostupna):
        ask(post, data)


def test_api_error_raises_for_fallback(data):
    post = scripted(_Resp({"error": {"message": "overloaded"}}, status=529))
    with pytest.raises(hledani_ai.AINedostupna):
        ask(post, data)


def test_missing_key_raises(data):
    vys, dok, fir = data
    with pytest.raises(hledani_ai.AINedostupna):
        hledani_ai.zeptej("x", vys, dok, fir, api_key="", post=None, today=TODAY)


def test_round_limit(data):
    loops = [_turn(_tool("firmy", {}, f"t{i}")) for i in range(hledani_ai.MAX_DATA_ROUNDS + 1)]
    with pytest.raises(hledani_ai.AINedostupna):
        ask(scripted(*loops), data)


def test_leaked_markup_is_trimmed(data):
    post = scripted(
        _turn(_tool("firmy", {"hledat": "cardion"})),
        _turn(_tool("odpoved", {"veta": "Mám **1 firmu**.</veta>\n<parameter name=x>"}, "t2")),
    )
    res = ask(post, data, "firma cardion")
    assert res["veta"] == "Mám **1 firmu**."
    assert res["firmy"][0]["ico"] == "04156854"


def test_unbalanced_stars_are_stripped(data):
    post = scripted(_turn(_tool("firmy", {})),
                    _turn(_tool("odpoved", {"veta": "Uložené jsou **2 firmy."}, "t2")))
    assert ask(post, data, "firmy")["veta"] == "Uložené jsou 2 firmy."


def test_bad_dates_from_model_are_ignored(data):
    post = scripted(_turn(_tool("zadosti", {"od": "včera", "do": "2026-13"})),
                    _turn(_tool("odpoved", {"veta": "Celkem **4 žádosti**."}, "t2")))
    assert len(ask(post, data, "všechno")["vystupy"]) == 4


def test_plate_with_space_quoted_from_data_passes():
    assert hledani_ai.overit_vetu("Jediný doklad, vozidlo 1AB 2345.", [{"vozidlo": "1AB 2345", "pocet": 1}],
                                  "", TODAY)


def test_list_after_the_sentence_is_dropped(data):
    post = scripted(_turn(_tool("firmy", {"hledat": "a"})),
                    _turn(_tool("odpoved", {"veta": "Mám **2 firmy**:\n- AUTO CARDION\n- Albion"}, "t2")))
    assert ask(post, data, "firmy")["veta"] == "Mám **2 firmy**"


def test_headline_covers_every_tool(data):
    post = scripted(_turn(_tool("zadosti", {"hledat": "1AB2345"}), _tool("doklady", {"hledat": "1AB2345"}, "t9")),
                    _turn(_tool("odpoved", {"veta": "Bylo jich 99."}, "t2")))
    res = ask(post, data, "1AB2345")
    assert res["veta"] == ""
    assert res["headline"] == "1 žádost · 1 doklad za 1 500 Kč"


def test_plate_digits_are_not_allowed_numbers():
    # "3BR4008" nesmí povolit 4008 ani 3 — jinak by prošlo vymyšlené číslo.
    assert not hledani_ai.overit_vetu("Bylo jich 4008.", [{"rz": "3BR4008"}], "", TODAY)


def test_verify_sentence_allows_question_and_today():
    assert hledani_ai.overit_vetu("Za poslední 3 dny nic, dnes je 25. 7.", [{"pocet": 0}],
                                  "za poslední 3 dny", TODAY)
    assert not hledani_ai.overit_vetu("Bylo jich 12.", [{"pocet": 3}], "kolik", TODAY)


def test_route_falls_back_without_ai(client, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "ANTHROPIC_API_KEY", "")
    res = client.get("/api/hledat?q=firma").get_json()
    assert res["ai"] is False and res["jednoduchy"] is True


def test_route_falls_back_on_ai_error(client, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "ANTHROPIC_API_KEY", "k")

    def boom(*a, **kw):
        raise hledani_ai.AINedostupna("down")
    monkeypatch.setattr(app_module.hledani_ai, "zeptej", boom)
    res = client.get("/api/hledat?q=firma").get_json()
    assert res["ai"] is False and "headline" in res


def test_route_uses_ai_when_available(client, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(app_module.hledani_ai, "zeptej",
                        lambda *a, **kw: {"ai": True, "headline": "x", "veta": "y", "tokeny": {}})
    res = client.get("/api/hledat?q=cokoli").get_json()
    assert res["ai"] is True and "tokeny" not in res


def test_route_rate_limit(client, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(app_module, "_HLEDANI_LIMIT", 1)
    monkeypatch.setattr(app_module, "_hledani_casy", {})
    monkeypatch.setattr(app_module.hledani_ai, "zeptej",
                        lambda *a, **kw: {"ai": True, "headline": "x", "veta": "", "tokeny": {}})
    assert client.get("/api/hledat?q=a").get_json()["ai"] is True
    second = client.get("/api/hledat?q=a").get_json()
    assert second["ai"] is False and second["limit_dotazu"] is True


def test_dates_do_not_split_sentences():
    veta = "Naposledy **15. 7.** jako převod. Předtím 10. 6."
    assert hledani_ai._zkrat(veta) == veta


def test_long_answer_keeps_only_the_main_point():
    dlouha = "Roman udělal **1 žádost**. " + "Pak " + "ještě něco dalšího a dalšího " * 10 + "."
    assert hledani_ai._zkrat(dlouha) == "Roman udělal **1 žádost**."


def test_three_sentences_become_two():
    assert hledani_ai._zkrat("Jedna. Dvě. Tři.") == "Jedna. Dvě."
