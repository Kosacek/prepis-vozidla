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


def test_every_icon_reference_has_a_symbol():
    """<use href="#i-…"> bez odpovídajícího <symbol> se vykreslí jako prázdno —
    v prohlížeči tiše, bez chyby v konzoli."""
    html = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    defined = set(re.findall(r'<symbol id="(i-[a-z0-9-]+)"', html))
    used = set(re.findall(r'<use href="#(i-[a-z0-9-]+)"', html))
    assert used - defined == set(), f"chybí definice ikon: {sorted(used - defined)}"
    assert defined - used == set(), f"nepoužité ikony: {sorted(defined - used)}"
