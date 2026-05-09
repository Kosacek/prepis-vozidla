from app import build_zmena_fields


def test_vlastnik_only_no_jiny_provozovatel():
    data = {
        "novy_jmeno": "JAN NOVAK",
        "novy_rc_1": "850101",
        "novy_rc_2": "1234",
        "novy_ico": "",
        "novy_adresa": "HLAVNI 5, BRNO",
        "novy_psc": "60200",
        "registracni_znacka": "1AB2345",
        "vin": "WBA3A5C51DF123456",
        "druh_vozidla": "osobni automobil",
        "zadost_zmena": "zápis A50-X",
        "novy_prov_jiny": False,
    }
    f = build_zmena_fields(data)

    # Vehicle
    assert f["comb_1"] == "1AB2345"
    assert f["comb_2"] == "WBA3A5C51DF123456"
    assert f["Druh vozidla"] == "osobni automobil"

    # Vlastník
    assert f["fill_2"] == "JAN NOVAK"
    assert f["comb_3"] == "850101/1234"
    assert f["comb_4"] == ""
    assert f["Adresa místa pobytu fyzické osoby nebo sídlo právnické osoby  místo podnikání fyzické osoby 1"] == "HLAVNI 5, BRNO"
    assert f["fill_6"] == "60200"

    # Provozovatel — must be blank when not jiný
    assert f["fill_7"] == ""
    assert f["fill_8"] == ""
    assert f["comb_5"] == ""
    assert f["comb_6"] == ""
    assert f["fill_11"] == ""

    # Žádá o provedení změny
    assert f["fill_12"] == "zápis A50-X"
    assert f["fill_13"] == ""
    assert f["fill_14"] == ""
    assert f["fill_15"] == ""
    assert f["fill_16"] == ""

    # Místo + datum
    assert f["V"] == "Brně"
    assert f["dne"]


def test_jiny_provozovatel():
    data = {
        "novy_jmeno": "VLASTNIK",
        "novy_rc_1": "850101",
        "novy_rc_2": "1234",
        "novy_adresa": "ADRESA 1",
        "novy_psc": "60200",
        "novy_prov_jiny": True,
        "novy_prov_jmeno": "PROVOZOVATEL",
        "novy_prov_rc_1": "900101",
        "novy_prov_rc_2": "5678",
        "novy_prov_ico": "12345678",
        "novy_prov_adresa": "JINA 5",
        "novy_prov_psc": "11000",
    }
    f = build_zmena_fields(data)
    assert f["fill_7"] == "PROVOZOVATEL"
    assert f["comb_5"] == "900101/5678"
    assert f["comb_6"] == "12345678"
    assert f["fill_11"] == "11000"


def test_pravnicka_osoba_uses_ico_only():
    data = {
        "novy_jmeno": "FIRMA s.r.o.",
        "novy_rc_1": "",
        "novy_rc_2": "",
        "novy_ico": "12345678",
        "novy_adresa": "SIDLO 10",
        "novy_psc": "60200",
        "novy_prov_jiny": False,
    }
    f = build_zmena_fields(data)
    assert f["comb_3"] == ""  # no RČ
    assert f["comb_4"] == "12345678"
