"""Sken dokladů přes Claude — hlavně aby přechod na Haiku 5.5 nic nerozbil.

Haiku 5.5 se chová jinak než 4.5:
- přemýšlí sám od sebe, takže odpověď může ZAČÍNAT blokem `thinking` bez
  textu. Starý kód četl content[0]["text"] → KeyError → sken by nefungoval;
- vrací 400 na temperature / top_p / top_k a na předvyplněnou odpověď.
"""
import json

import pytest

import app as A


class _Odpoved:
    def __init__(self, body, status=200):
        self._body, self.status_code, self.text = body, status, json.dumps(body)

    def json(self):
        return self._body


def _zachyt(monkeypatch, body, status=200):
    """Podvrhne requests.post a vrátí seznam odeslaných požadavků."""
    odeslane = []

    def fake_post(url, headers=None, json=None, timeout=None):
        odeslane.append(json)
        return _Odpoved(body, status)

    monkeypatch.setattr(A.requests, "post", fake_post)
    return odeslane


OBRAZEK = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "AA=="}},
           {"type": "text", "text": "prompt"}]


def test_odpoved_zacinajici_premyslenim_se_precte(monkeypatch):
    """Přesně tvar odpovědi Haiku 5.5 — thinking blok bez textu, pak JSON."""
    _zachyt(monkeypatch, {"stop_reason": "end_turn", "content": [
        {"type": "thinking", "thinking": "", "signature": "x"},
        {"type": "text", "text": '{"vin": "TMBEK6NW7M3158470"}'},
    ], "usage": {"input_tokens": 1500, "output_tokens": 120}})
    data, meta = A.claude_vision_json(OBRAZEK, "haiku")
    assert data == {"vin": "TMBEK6NW7M3158470"}
    assert meta["model"] == "claude-haiku-5-5"
    assert meta["input_tokens"] == 1500


def test_json_v_markdown_plotu_se_rozbali(monkeypatch):
    _zachyt(monkeypatch, {"stop_reason": "end_turn", "content": [
        {"type": "text", "text": '```json\n{"registracni_znacka": "1AB2345"}\n```'}]})
    data, _ = A.claude_vision_json(OBRAZEK, "sonnet")
    assert data["registracni_znacka"] == "1AB2345"


@pytest.mark.parametrize("text", [
    # přesně tvar, kterým Sonnet 4.6 shodil 11 z 203 reálných skenů
    'The document is upside down. Let me read it by flipping.\n\n```json\n{"osvedceni_cislo": "619676"}\n```',
    'The image shows a Czech ORV.\n{"osvedceni_cislo": "619676"}',
    '{"osvedceni_cislo": "619676"}',
])
def test_json_se_najde_i_za_uvodni_vetou(monkeypatch, text):
    _zachyt(monkeypatch, {"stop_reason": "end_turn", "content": [{"type": "text", "text": text}]})
    data, _ = A.claude_vision_json(OBRAZEK, "sonnet")
    assert data == {"osvedceni_cislo": "619676"}


def test_odpoved_uplne_bez_json_je_porad_chyba(monkeypatch):
    _zachyt(monkeypatch, {"stop_reason": "end_turn", "content": [{"type": "text", "text": "Nevidím doklad."}]})
    with pytest.raises(ValueError):
        A.claude_vision_json(OBRAZEK, "sonnet")


@pytest.mark.parametrize("stop, hlaska", [("refusal", "odmítl"), ("max_tokens", "limitu")])
def test_odmitnuti_a_useknuta_odpoved_daji_srozumitelnou_chybu(monkeypatch, stop, hlaska):
    _zachyt(monkeypatch, {"stop_reason": stop, "content": [{"type": "thinking", "thinking": ""}]})
    with pytest.raises(A.ClaudeError, match=hlaska):
        A.claude_vision_json(OBRAZEK, "haiku")


def test_chyba_api_se_propise(monkeypatch):
    _zachyt(monkeypatch, {"type": "error", "error": {"message": "invalid model"}}, status=400)
    with pytest.raises(A.ClaudeError, match="invalid model"):
        A.claude_vision_json(OBRAZEK, "haiku")


def test_pozadavek_na_haiku_neobsahuje_nic_co_haiku_5_5_odmita(monkeypatch):
    odeslane = _zachyt(monkeypatch, {"stop_reason": "end_turn",
                                     "content": [{"type": "text", "text": "{}"}]})
    A.claude_vision_json(OBRAZEK, "haiku")
    body = odeslane[0]
    assert body["model"] == "claude-haiku-5-5"
    for zakazane in ("temperature", "top_p", "top_k"):
        assert zakazane not in body, f"{zakazane} → Haiku 5.5 vrátí 400"
    assert body["messages"][-1]["role"] == "user", "předvyplněná odpověď → 400"
    assert body["output_config"] == {"effort": "low"}
    assert body["max_tokens"] >= 4096, "přemýšlení se počítá do max_tokens"


def test_sonnet_se_posila_beze_zmeny_chovani(monkeypatch):
    """Sonnet 4.6 bez `thinking` nepřemýšlí — nic se mu nemá měnit."""
    odeslane = _zachyt(monkeypatch, {"stop_reason": "end_turn",
                                     "content": [{"type": "text", "text": "{}"}]})
    A.claude_vision_json(OBRAZEK, "sonnet")
    assert odeslane[0]["model"] == "claude-sonnet-4-6"
    assert "output_config" not in odeslane[0] and "thinking" not in odeslane[0]


def test_neznamy_model_spadne_na_sonnet(monkeypatch):
    odeslane = _zachyt(monkeypatch, {"stop_reason": "end_turn",
                                     "content": [{"type": "text", "text": "{}"}]})
    A.claude_vision_json(OBRAZEK, "gpt-cokoliv")
    assert odeslane[0]["model"] == "claude-sonnet-4-6"


def test_scan_orv_s_haiku_5_5_vyplni_data(client, monkeypatch):
    """Celá cesta /api/scan-orv s odpovědí ve tvaru Haiku 5.5."""
    _zachyt(monkeypatch, {"stop_reason": "end_turn", "content": [
        {"type": "thinking", "thinking": "", "signature": "x"},
        {"type": "text", "text": '{"registracni_znacka": "1AB2345", "vin": "TMBEK6NW7M3158470"}'}]})
    import io
    from PIL import Image
    jpeg = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(jpeg, "JPEG")   # trasa fotku otáčí přes Pillow
    jpeg.seek(0)
    r = client.post("/api/scan-orv", data={"model": "haiku", "image": (jpeg, "orv.jpg", "image/jpeg")},
                    content_type="multipart/form-data")
    body = r.get_json()
    assert body["success"] is True
    assert body["data"]["vin"] == "TMBEK6NW7M3158470"
