# Přepis Vozidla — Project Instructions

**This is a Python / Flask / PyInstaller desktop app. NOT a frontend website.**

Ignore any frontend rules inherited from `D:\Claude Code\CLAUDE.md` (Tailwind, puppeteer, `serve.mjs`, `localhost:3000`, screenshot workflow, `brand_assets/`). Those belong to a different project and do not apply here.

## What this project actually is

- **Language:** Python 3.x
- **Framework:** Flask (single `app.py`, ~42 KB)
- **UI:** single-file Jinja template `templates/index.html` (vanilla HTML/CSS/JS, no framework)
- **Packaging:** PyInstaller (`prepis_vozidla.spec`) → `.exe` deployed to NAS
- **Launcher / auto-updater:** `launcher.py`, `updater.py`
- **Version:** tracked in `VERSION` file and `version.py`
- **Run locally:** `python app.py` → http://localhost:5050

## Read before changing anything

- [CONTEXT.md](CONTEXT.md) — deep reference: user flow, PDF field mappings for `zmeny.pdf` and `zapis.pdf`, diacritics fix, checkbox on-value quirks, ARES + Claude Vision API notes, hardcoded business rules.
- [README.md](README.md) — short Czech-language quick-start.

## Hard constraints

- Default city is `Brně`, date is tomorrow, účel is `vozidlo obecného užití`, `undefined_4` (TP číslo) stays blank. These are intentional business rules — do not change without confirmation.
- Czech diacritics only render correctly when `NeedAppearances=True` is set on the AcroForm.
- `firmy.xlsx` saves must be atomic (write-temp-then-rename) with auto-backup. Don't break that.
- API key loads from `.env` via `_MEIPASS` path so it also works inside the PyInstaller bundle. Don't hardcode.

## Not part of this project (moved out)

Kabeláž / structured-cabling files were moved to `D:\Claude Code\kabelaz_projekt\`. If you see references to `nacrtek.html`, `projekt_kabelaz.js`, or a Node `package.json` here, something is wrong.
