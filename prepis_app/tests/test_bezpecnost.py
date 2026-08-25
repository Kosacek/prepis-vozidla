"""Přihlašovací stránka musí být nedosažitelná po nešifrovaném HTTP.

Vzniklo z reálné stížnosti: na iPhonu Safari u pole s heslem hlásilo
„připojení není zabezpečené a tvoje údaje uvidí kdokoliv". Nešlo o certifikát
(ten je v pořádku) — stránka se dala normálně otevřít přes http:// a nic
prohlížeč nepostrčilo na https.

Past, kvůli které to musí hlídat test: nginx v našem server bloku přepisuje
X-Forwarded-Proto na $scheme, a to je uvnitř dockeru VŽDYCKY http. Kdyby se
podle téhle hlavičky přesměrovávalo, vznikla by nekonečná smyčka i na https.
Poznat se to dá jen z CF-Visitor, kterou posílá Cloudflare — a když nedorazí,
nesmí se přesměrovávat vůbec.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as A

HTTPS = {"CF-Visitor": '{"scheme":"https"}'}
HTTP = {"CF-Visitor": '{"scheme":"http"}'}


@pytest.fixture
def prod(monkeypatch):
    """Aplikace jako na webu — s přihlašovací bránou."""
    monkeypatch.setattr(A, "ADMIN_PASSWORD", "heslo-jen-pro-test")
    A._login_pokusy.clear()
    with A.app.test_client() as c:
        yield c
    A._login_pokusy.clear()


# ── vynucené https ───────────────────────────────────────────────────────────
def test_http_se_presmeruje_na_https(prod):
    r = prod.get("/login", base_url="http://zadosti.spznaklic.cz", headers=HTTP)
    assert r.status_code == 301
    assert r.headers["Location"] == "https://zadosti.spznaklic.cz/login"


def test_https_se_nepresmerovava(prod):
    """Kdyby ano, byla by z toho nekonečná smyčka."""
    r = prod.get("/login", base_url="http://zadosti.spznaklic.cz", headers=HTTPS)
    assert r.status_code == 200


def test_bez_cf_visitor_se_nepresmerovava(prod):
    """Bez důkazu o schématu se raději nedělá nic — X-Forwarded-Proto lže."""
    r = prod.get("/login", base_url="http://zadosti.spznaklic.cz",
                 headers={"X-Forwarded-Proto": "http"})
    assert r.status_code == 200


def test_presmerovani_neztrati_dotaz(prod):
    r = prod.get("/api/hledat?q=roman", base_url="http://zadosti.spznaklic.cz",
                 headers=HTTP)
    assert r.headers["Location"] == "https://zadosti.spznaklic.cz/api/hledat?q=roman"


def test_post_se_presmeruje_beze_zmeny_metody(prod):
    """301 by POST změnila na GET a data by se ztratila — na to je 308."""
    r = prod.post("/login", data={"password": "x"},
                  base_url="http://zadosti.spznaklic.cz", headers=HTTP)
    assert r.status_code == 308


def test_healthz_po_http_projde(prod):
    """Healthcheck kontejneru chodí zevnitř po http — přesměrování by ho
    shodilo a Container Station by aplikaci pořád restartovala."""
    r = prod.get("/healthz", base_url="http://localhost:8089", headers=HTTP)
    assert r.status_code == 200


def test_lokalni_beh_bez_brany_se_nepresmerovava(monkeypatch):
    """Na počítači běží app.py bez ADMIN_PASSWORD a bez https."""
    monkeypatch.setattr(A, "ADMIN_PASSWORD", "")
    with A.app.test_client() as c:
        assert c.get("/", base_url="http://localhost:5050", headers=HTTP).status_code == 200


# ── hlavičky ─────────────────────────────────────────────────────────────────
def test_hsts_rekne_prohlizeci_at_uz_http_nezkousi(prod):
    r = prod.get("/login", base_url="https://zadosti.spznaklic.cz", headers=HTTPS)
    hsts = r.headers.get("Strict-Transport-Security", "")
    assert "max-age=" in hsts
    assert int(hsts.split("max-age=")[1].split(";")[0]) >= 15552000


def test_zakladni_bezpecnostni_hlavicky(prod):
    r = prod.get("/login", base_url="https://zadosti.spznaklic.cz", headers=HTTPS)
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert "Referrer-Policy" in r.headers
    csp = r.headers.get("Content-Security-Policy", "")
    assert "frame-ancestors 'none'" in csp
    assert "form-action 'self'" in csp


def test_csp_nerozbije_kameru_ani_nahledy(prod):
    """Fotky z kamery jdou do <img> jako data:, PDF se otevírají ze /api/…"""
    r = prod.get("/login", base_url="https://zadosti.spznaklic.cz", headers=HTTPS)
    csp = r.headers.get("Content-Security-Policy", "")
    assert "data:" in csp and "'unsafe-inline'" in csp


# ── hádání hesla ─────────────────────────────────────────────────────────────
def test_spatna_hesla_se_po_case_zablokuji(prod):
    kody = [prod.post("/login", data={"password": "spatne%d" % i},
                      base_url="https://zadosti.spznaklic.cz", headers=HTTPS).status_code
            for i in range(A._LOGIN_MAX_POKUSU + 3)]
    assert kody[0] == 401, "první pokus se má normálně odmítnout"
    assert kody[-1] == 429, "po vyčerpání pokusů se má zavřít"
    assert 429 not in kody[:A._LOGIN_MAX_POKUSU], "nesmí se zavřít předčasně"


def test_zablokovany_dostane_retry_after(prod):
    for i in range(A._LOGIN_MAX_POKUSU + 1):
        r = prod.post("/login", data={"password": "spatne"},
                      base_url="https://zadosti.spznaklic.cz", headers=HTTPS)
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0


def test_blokuje_se_podle_ip_ne_plosne(prod):
    """Jinak by jeden útočník zamkl aplikaci i tobě."""
    for i in range(A._LOGIN_MAX_POKUSU + 1):
        prod.post("/login", data={"password": "spatne"},
                  base_url="https://zadosti.spznaklic.cz",
                  headers=dict(HTTPS, **{"CF-Connecting-IP": "203.0.113.9"}))
    r = prod.post("/login", data={"password": "heslo-jen-pro-test"},
                  base_url="https://zadosti.spznaklic.cz",
                  headers=dict(HTTPS, **{"CF-Connecting-IP": "198.51.100.4"}))
    assert r.status_code == 302, "jiná IP se musí dostat dovnitř"


def test_uspesne_prihlaseni_smaze_pocitadlo(prod):
    ip = {"CF-Connecting-IP": "203.0.113.20"}
    for i in range(A._LOGIN_MAX_POKUSU - 1):
        prod.post("/login", data={"password": "spatne"},
                  base_url="https://zadosti.spznaklic.cz", headers=dict(HTTPS, **ip))
    ok = prod.post("/login", data={"password": "heslo-jen-pro-test"},
                   base_url="https://zadosti.spznaklic.cz", headers=dict(HTTPS, **ip))
    assert ok.status_code == 302
    znovu = prod.post("/login", data={"password": "spatne"},
                      base_url="https://zadosti.spznaklic.cz", headers=dict(HTTPS, **ip))
    assert znovu.status_code == 401, "po úspěchu se má počítadlo vynulovat"


def test_heslo_se_porovnava_v_konstantnim_case():
    """Naivní == prozradí heslo po znacích měřením času."""
    import inspect
    src = inspect.getsource(A.login)
    assert "compare_digest" in src


def test_prihlasovaci_pole_umi_ios_spravu_hesel(prod):
    r = prod.get("/login", base_url="https://zadosti.spznaklic.cz", headers=HTTPS)
    html = r.get_data(as_text=True)
    assert 'autocomplete="current-password"' in html


def test_csp_se_nelepi_na_pdf(prod):
    """Žádost se otevírá přímo jako PDF v nové záložce — do vestavěného
    prohlížeče PDF není co omezovat a dá se tím jen něco rozbít."""
    r = prod.get("/healthz", base_url="https://zadosti.spznaklic.cz", headers=HTTPS)
    assert r.mimetype != "text/html"
    assert "Content-Security-Policy" not in r.headers
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
