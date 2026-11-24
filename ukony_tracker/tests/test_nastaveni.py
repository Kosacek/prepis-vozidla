from html.parser import HTMLParser

import app as appmod
import config
import db
from repositories import typy_repo


class SettingsFormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms = {}
        self.controls = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form" and attrs.get("id", "").startswith("form-typ-"):
            self.forms[attrs["id"]] = attrs
        if tag in ("input", "button") and attrs.get("form", "").startswith("form-typ-"):
            self.controls.append(attrs)


def test_type_edit_form_owns_each_control_and_preserves_fractional_prices(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ADMIN_PASSWORD", "")
    app = appmod.create_app()
    with app.app_context():
        conn = db.get_db()
        typy_repo.upsert(conn, "TEST", 1300.0, 9, 1)
        typy_repo.upsert(conn, "TEST-CENTS", 1300.25, 10, 0)

    response = app.test_client().get("/nastaveni")
    assert response.status_code == 200
    parser = SettingsFormParser()
    parser.feed(response.get_data(as_text=True))
    for code, value, order, active in (("TEST", "1300", "9", True), ("TEST-CENTS", "1300.25", "10", False)):
        form_id = next(c["form"] for c in parser.controls if c.get("name") == "kod" and c["value"] == code)
        assert parser.forms[form_id]["method"] == "post"
        assert parser.forms[form_id]["action"] == "/nastaveni"
        controls = {c.get("name", "save"): c for c in parser.controls if c["form"] == form_id}
        assert controls["vychozi_cena"]["value"] == value
        assert controls["vychozi_cena"]["step"] == "0.01"
        assert controls["poradi"]["value"] == order
        assert ("checked" in controls["aktivni"]) == active
        assert controls["save"]["type"] == "submit"
