"""Každý vlastní modul, který app.py importuje, musí Dockerfile zkopírovat.

Dockerfile kopíruje soubory jednotlivě — nový modul bez řádku COPY projde
všemi testy lokálně a v produkci shodí gunicorn na ImportError (stalo se
s releases.py v evidenci)."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_every_local_import_is_copied():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    # Jen importy na nejvyšší úrovni — líný `import updater` v try (stará
    # desktopová verze) do image patřit nemá.
    imported = set(re.findall(r"^(?:import|from)\s+(\w+)", app, re.M))
    local = {m for m in imported if (ROOT / f"{m}.py").exists()}
    missing = [m for m in sorted(local) if f"COPY {m}.py" not in docker]
    assert not missing, f"Dockerfile nekopíruje: {missing}"
