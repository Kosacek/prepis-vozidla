"""Šablona se musí dát naparsovat jako JavaScript.

Vzniklo z reálné chyby: automatická náhrada v index.html ukousla tři řádky
uprostřed funkce a zbyl osiřelý `return; }`. Celý <script> tím přestal jít
naparsovat, takže se nedefinovala ANI JEDNA funkce a stránka byla mrtvá —
žádné tlačítko nefungovalo. Python testy to nemohly odhalit, protože do
JavaScriptu nevidí, a v prohlížeči to vypadalo jen jako „nefunguje 3RZ".

Levná pojistka: každý <script> blok prožene `node --check`.
"""
import os
import pathlib
import re
import shutil
import subprocess
import tempfile

import pytest

TEMPLATES = pathlib.Path(__file__).resolve().parent.parent / "templates"


def _scripts(path: pathlib.Path):
    html = path.read_text(encoding="utf-8")
    return re.findall(r"<script>(.*?)</script>", html, re.S)


@pytest.mark.parametrize("template", sorted(p.name for p in TEMPLATES.glob("*.html")))
def test_inline_scripts_parse(template):
    node = shutil.which("node")
    if not node:  # pragma: no cover - závisí na stroji
        pytest.skip("node není nainstalovaný")
    blocks = _scripts(TEMPLATES / template)
    for i, block in enumerate(blocks):
        # Jinja výrazy uvnitř skriptů by parser rozbily; v těchhle šablonách
        # se nepoužívají, takže se kontroluje surový obsah.
        if "{{" in block or "{%" in block:
            continue
        tmp = pathlib.Path(tempfile.gettempdir()) / f"_tpl_{template}_{i}.js"
        tmp.write_text(block, encoding="utf-8")
        try:
            r = subprocess.run([node, "--check", str(tmp)],
                               capture_output=True, text=True, timeout=30)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        assert r.returncode == 0, (
            f"{template} blok {i} se nedá naparsovat:\n{r.stderr[:800]}")


def test_owner_wording_is_decided_in_one_place():
    """„Nový vlastník" má smysl jen u převodu — jinde se vlastník nemění, jen
    o něco žádá. Dřív to bylo natvrdo v šabloně a na třech místech zvlášť, takže
    u vývozu zůstalo „Nový provozovatel", i když je pořád tentýž.

    Test hlídá, že se to rozhoduje jednou funkcí a texty nejsou zadrátované.
    """
    html = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    assert "function jeNovyVlastnik()" in html
    for id_ in ("vlastnik-nadpis", "prov-toggle-nadpis", "prov-sekce-nadpis"):
        assert f'id="{id_}"' in html, f"{id_} chybí — text by nešel přepnout"
    # O znění nesmí rozhodovat podmínka na mód roztroušená po šabloně —
    # jinak se při přidání dalšího tiskopisu zase někde zapomene.
    spatne = [l.strip() for l in html.splitlines()
              if "appMode ===" in l and ("Nový vlastník" in l or "Nový provozovatel" in l)]
    assert not spatne, f"znění se rozhoduje mimo jeNovyVlastnik(): {spatne}"


def test_every_icon_reference_has_a_symbol():
    """<use href="#i-…"> bez odpovídajícího <symbol> se vykreslí jako prázdno —
    v prohlížeči tiše, bez chyby v konzoli."""
    html = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    defined = set(re.findall(r'<symbol id="(i-[a-z0-9-]+)"', html))
    used = set(re.findall(r'<use href="#(i-[a-z0-9-]+)"', html))
    assert used - defined == set(), f"chybí definice ikon: {sorted(used - defined)}"
    assert defined - used == set(), f"nepoužité ikony: {sorted(defined - used)}"


def test_prefill_picker_also_serves_vyvoz():
    """Vývoz sdílí s 3RZ panel Vozidlo i Vlastník, takže „navázat na dřívější
    žádost" mu sedí beze změny — jen se mu dřív nezobrazovalo a všechno se
    přepisovalo ručně. Test hlídá, že se to zase neutrhne na `=== '3rz'`.
    """
    html = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    i = html.index("const dps = document.getElementById('d3rz-prefill-section')")
    blok = html[i:i + 400]
    assert "vyvoz" in blok, "prefill picker se vývozu neukáže"
    assert "loadPrefillList()" in blok


def test_pickers_show_who_filled_it_in():
    """Hledání „roman" v pickeru je k ničemu, když u řádků není vidět,
    že jsou opravdu jeho."""
    html = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    for fn in ("function renderPrefillList()", "function renderPmZadosti()"):
        blok = html[html.index(fn):][:1500]
        assert "v.profil" in blok, fn + " neukáže, kdo žádost dělal"


def test_pm_jedina_strana_se_vybere_sama():
    """Klikat na jedinou možnost, aby se „potvrdila", je jen práce navíc —
    a uživatel to čekal automaticky. Při dvou stranách (převod) se vybírat MUSÍ."""
    html = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    blok = html[html.index("async function pmVyberZadost("):][:2700]
    assert "strany.length === 1" in blok, "jediná strana se nerozeznává"
    assert "pmVyberStranu(s0.role)" in blok, "jediná strana se nevybere sama"
    assert "onclick=\"pmVyberStranu(" in blok, "u více stran musí jít vybrat"
    assert "pm-vystavit').disabled = true" in blok,         "po přepnutí žádosti musí být tlačítko zase zamknuté"


def test_historie_se_predvyplni_drive_nez_zacnes_psat():
    """377 kB historie se z NASu taže chvíli; než dorazila, byl seznam prázdný
    a vypadalo to, že se hledá až od prvního písmene."""
    html = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    blok = html[html.index("async function loadPrefillList()"):][:1400]
    assert "pm-zadosti" in blok, "do seznamu plné moci se nic nepíše"
    assert "Načítám historii" in blok, "chybí hláška, že se načítá"
    assert "renderPmZadosti()" in blok, "seznam se po načtení nevykreslí"


def test_po_vystaveni_plne_moci_jde_zpatky_na_zacatek():
    html = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    blok = html[html.index("async function vystavitPlnouMoc()"):][:2000]
    assert "resetForm()" in blok, "chybí tlačítko zpět na začátek"


def test_evidence_paid_checkbox_is_wired_end_to_end():
    """The 2026-09-14 'ÚKON UŽ ZAPLACEN' checkbox: must exist, must feed the
    /api/generate payload, and must respect the master 'ZAPSAT ÚKON DO
    EVIDENCE' toggle like the other evidence fields do."""
    html = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    assert 'id="evidence_zaplaceno"' in html
    assert "evidence_zaplaceno:  cb('evidence_zaplaceno')" in html, \
        "checkbox exists but its value never reaches the generate payload"
    blok = html[html.index("function toggleEvidence()"):][:500]
    assert "evidence_zaplaceno" in blok, \
        "unchecking 'ZAPSAT ÚKON DO EVIDENCE' must also disable the paid checkbox"


def test_ppd_nahled_a_extra_vozidla_jsou_zapojena():
    """Náhled dokladu + „Přidat vozidlo" (2026-09-15): musí existovat, musí
    dorazit do generate payloadu jako ppd_extra_spz, a nový castka field musí
    mít placeholder „0", ne skutečnou hodnotu 0 (kterou by musel mazat)."""
    html = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    assert 'id="ppd-extra-vozidla"' in html
    assert 'onclick="ppdPridatVozidlo()"' in html
    assert "function ppdNahledUpdate()" in html
    assert "ppd_extra_spz:       ppdExtraSpzList().join(', ')" in html
    assert 'id="ppd_castka"' in html
    castka_tag = html[html.index('id="ppd_castka"') - 40: html.index('id="ppd_castka"') + 150]
    assert 'placeholder="0"' in castka_tag
    assert 'value="0"' not in castka_tag


def test_sdileni_tlacitko_je_zapojene():
    """Sdílecí odkaz (2026-09-17): tlačítko musí existovat, brát URL z
    result.<mode>_sdilet a ukazovat celou adresu i s doménou — samotné
    /1234 se z SMS ani z displeje přečíst nedá."""
    html = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    assert 'id="btn-sdilet"' in html
    assert "function otevriSdileni()" in html
    assert "result.sdilet" in html, "odkaz se bere z jednoho pole na balik"
    blok = html[html.index("function sdileciOdkaz()"):][:400]
    assert "location.host" in blok, "odkaz musí být i s doménou, jinak je k ničemu"


def test_sdileni_ukaze_kod_na_tlacitku_i_v_okne():
    """David odkaz většinou neposílá — přečte ho z displeje nebo nadiktuje.
    Číslo proto musí být vidět na tlačítku a okno musí jít otevřít přes
    celou obrazovku, s tlačítkem odeslat."""
    html = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    assert 'id="btn-sdilet-kod"' in html
    assert 'id="sdilet-modal"' in html and 'id="sdilet-url"' in html
    assert "function odesliSdileni()" in html
    assert "navigator.share" in html, "na mobilu ať to nabídne SMS/WhatsApp"
    assert "function zavriSdileni()" in html


def test_sdileni_a_pojisteni_jsou_na_jednom_radku():
    """Obě tlačítka mají být vedle sebe půl na půl (.out-row je flex 1:1)."""
    html = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    zacatek = html.index('id="btn-sdilet"')
    radek = html.rindex('<div class="out-row">', 0, zacatek)
    konec = html.index("</div>", html.index('id="btn-pojisteni"'))
    assert html.index('id="btn-pojisteni"') > radek
    assert konec > html.index('id="btn-pojisteni"')


def test_primarni_zadost_ma_jen_jednu_definici():
    """Mapování mód→soubor bylo dřív zkopírované ve dvou funkcích; ať se
    zase nerozejde."""
    html = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    assert html.count("prevod: 'zmeny', zapis: 'zapis'") == 1


def test_vychozi_model_skenu_je_haiku_i_se_starou_volbou():
    """2026-10-08: po přepnutí výchozího modelu na Haiku 5.5 David pořád viděl
    Sonnet 4.6 — v prohlížeči měl ze staré verze uložené „sonnet". Stará
    volba se proto jednou zahodí a ukládá se pod novým klíčem."""
    html = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    assert "localStorage.removeItem('scan_model')" in html
    assert "localStorage.getItem(MODEL_KLIC) || 'haiku'" in html
    assert "localStorage.setItem('scan_model'," not in html, "zápis pod starým klíčem by vracel Sonnet"


def test_okno_sdileni_je_nad_ostatnimi_okny():
    """Sdílet jde z okna historie a z Dokladů (z-index 500) — okno s kódem
    se dřív otevřelo POD nimi a nebylo vidět (nalezeno v prohlížeči 2026-10-08)."""
    import re as _re
    html = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    ostatni = max(int(z) for z in _re.findall(r"\.modal-overlay \{[^}]*z-index:\s*(\d+)", html))
    sdileni = int(_re.search(r"#sdilet-modal \{ z-index:\s*(\d+)", html).group(1))
    assert sdileni > ostatni


def test_niche_kroky_nemaji_vlastni_mensi_velikosti():
    """2026-10-08: plná moc a vývoz vypadaly menší než převod a zápis —
    plná moc měla zmenšený padding, nadpis i pole, vyhledávání v 3RZ/vývozu/
    plné moci natvrdo 14px. Všechny kroky mají mít stejné základní velikosti."""
    html = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    for zakazane in ("#panel-6 .card {", "#panel-6 .card-title {", "#panel-6 .field input {",
                     "#panel-6 .field label {", "#panel-6 .hl-row {"):
        assert zakazane not in html, zakazane
    for pole in ('id="d3rz-hledat"', 'id="pm-hledat"', 'id="zadost_zmena"'):
        radek = html[html.index(pole):html.index(">", html.index(pole))]
        assert "font-size" not in radek and "padding" not in radek, pole


# ── Plynulé vyplňování z klávesnice (2026-10-08) ─────────────────────────────

def test_sken_posune_dal_jen_kdyz_uzivatel_porad_stoji_na_kroku_1():
    """Sken trvá pár vteřin; když David mezitím sám pokračoval (Enter),
    navNext() po skenu přeskočil další krok a ten se v liště označil jako
    hotový. Posun smí jen přes skenPosunoutDal (pořád krok 1, stejný typ)."""
    html = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    sken = html[html.index("async function quickScanOrv()"):]
    sken = sken[:sken.index("\n}\n")]
    assert "skenPosunoutDal(startIdx, startMode)" in sken
    assert "closeCamera();\n    navNext();" not in sken, "nepodmíněný posun je zpátky"
    assert "currentPanel() === 1" in html[html.index("function skenPosunoutDal"):][:300]


def test_auto_skok_jen_pri_psani_na_konci_pole():
    html = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    f = html[html.index("function autoDal(ev)"):][:1400]
    assert "/^insert/.test(ev.inputType" in f, "mazání nesmí skákat"
    assert "el.selectionStart !== el.value.length" in f, "oprava uprostřed nesmí skákat"
    assert "ev.isTrusted" in f, "vyplnění skriptem (sken, registr) nesmí skákat"
    for pole in ("'vin'", "'vin_z'", "_rc_1", "_rc_2", "'osvedceni_orv'"):
        assert pole in f, pole


def test_ares_tlacitka_nejsou_v_ceste_tabulatoru():
    import re as _re
    html = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    tlacitka = _re.findall(r'<button class="btn-lookup"[^>]*lookupIco', html)
    assert tlacitka and all('tabindex="-1"' in t for t in tlacitka)


def test_volitelna_pole_auto_skok_preskoci():
    html = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    for pole in ("jiny_doklad", "poznamky", "puvodni_id", "novy_id", "puvodni_prov_id", "novy_prov_id"):
        tag = html[html.index(f'id="{pole}"'):][:120]
        assert "data-volitelne" in tag, pole


def test_klepnuti_otoci_nahled_i_fotku_pro_sken():
    """Doma visí kamera vzhůru nohama (výchozí otočení), na mobilu ne —
    klepnutí do náhledu otočí obraz. Otočit se musí i FOTKA, která jde na
    sken, jinak by model dostal jiný obraz, než je vidět."""
    html = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    video = html[html.index('id="camera-video"'):][:300]
    assert 'onclick="prepniOtoceniKamery()"' in video
    sken = html[html.index("async function _naskenujOrv()"):][:900]
    assert "if (kameraOtocena())" in sken and "ctx.rotate(Math.PI)" in sken
    assert "!== '0'" in html[html.index("function kameraOtocena()"):][:200], "výchozí = otočeno (doma)"


def test_camera_rotate_badge_is_an_accessible_icon_button():
    html = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    start = html.index('id="camera-container"')
    camera = html[start:html.index('<div class="scan-actions">', start)]
    buttons = re.findall(r'<button\b[^>]*>', camera)
    assert "klepni" not in html.lower()
    assert any('onclick="prepniOtoceniKamery()"' in button
               and 'aria-label="Otočit obraz o 180°"' in button
               and 'title="Otočit obraz o 180°"' in button for button in buttons)
    assert '<use href="#i-rotate">' in camera


def test_firmy_modal_has_search_and_compact_svg_controls():
    html = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    modal = html[html.index('id="firmy-modal"'):html.index('id="sdilet-modal"')]
    search = re.search(r'<input\b[^>]*id="firmy-search"[^>]*>', modal)
    assert search, "chybí vyhledávání firem"
    classes = re.search(r'class="([^"]*)"', search.group()).group(1).split()
    assert "no-uc" in classes
    assert 'placeholder="Hledat"' in search.group()
    assert "plných mocí" not in modal.lower()
    render = html[html.index("function _renderFirmyBody()"):
                  html.index("async function renderFirmyModal()")]
    assert "✏️" not in render and "➕" not in render
