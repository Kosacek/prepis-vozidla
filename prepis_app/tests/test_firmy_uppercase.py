"""Saved firms are stored UPPERCASE regardless of how the field was filled
(typed → live-uppercased; ARES/scan autofill → only uppercased on save), so
firmy.xlsx stays consistent with the rest of the always-capital workflow."""
import app as appmod


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "FIRMY_XLSX", str(tmp_path / "firmy.xlsx"))
    monkeypatch.setattr(appmod, "FIRMY_BACKUP", str(tmp_path / "firmy.xlsx.bak"))


def test_add_firm_stores_uppercase(client, tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    r = client.post("/api/firmy", json={
        "nazev": "Škoda Auto a.s.", "ico": "00177041",
        "adresa": "tř. Václava Klementa 869, Mladá Boleslav",
    })
    assert r.get_json()["success"] is True
    firms = client.get("/api/firmy").get_json()
    f = next(x for x in firms if x["ico"] == "00177041")
    assert f["nazev"] == "ŠKODA AUTO A.S."
    assert f["adresa"] == "TŘ. VÁCLAVA KLEMENTA 869, MLADÁ BOLESLAV"


def test_update_firm_uppercases(client, tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    client.post("/api/firmy", json={"nazev": "X", "ico": "00177041"})
    r = client.patch("/api/firmy/00177041", json={"nazev": "nová firma s.r.o.",
                                                  "adresa": "ulice 1, brno"})
    assert r.get_json()["success"] is True
    f = next(x for x in client.get("/api/firmy").get_json() if x["ico"] == "00177041")
    assert f["nazev"] == "NOVÁ FIRMA S.R.O."
    assert f["adresa"] == "ULICE 1, BRNO"
