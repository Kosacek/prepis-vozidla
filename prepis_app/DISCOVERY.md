# DISCOVERY — přepisy app (Phase 0 of HANDOFF.md)

Answers required before containerizing. Target deploy: `https://zadosti.spznaklic.cz`
on the shared QNAP/Container-Station/nginx/Cloudflare-Tunnel stack (reference
app: brno-hunter).

## Code & framework

- **Repo / path:** `D:\Claude Code\prepis_vozidla_app\prepis_app`, git remote
  `https://github.com/Kosacek/prepis-vozidla.git`, default branch `master`.
- **Language / framework:** Python 3.x, **Flask** (single `app.py`, ~1030 lines).
  UI is one Jinja template `templates/index.html` (vanilla HTML/JS).
- **Today it serves HTTP as:** a PyInstaller desktop bundle — `launcher.py`
  starts Flask's dev server on `127.0.0.1:5050` and opens a browser. For the
  web we **add a WSGI server (gunicorn)**; Flask is WSGI (NOT ASGI) so the
  entrypoint runs `gunicorn`, not uvicorn (differs from hunter).
- **Internal port (chosen):** **8089** (hunter uses 8088).

## Datastore & migrations

- **No database.** State is a spreadsheet `firmy.xlsx` plus files on disk:
  `plne_moce/*.pdf`, `scans/*.jpg`, `output/*.pdf`.
- **No migrations.** Nothing to run on container start (unlike hunter's
  `alembic upgrade head`).
- **Persistence:** everything above must live on the `/data` bind mount.
  Current code targets the Windows NAS UNC path
  `\\192.168.1.18\Petr\PrepisVozidla\data` which does not exist in a Linux
  container (it falls back to `BASE_DIR` = `/app`, wiped on every rebuild).
  Fix: a `DATA_DIR` env var override that takes precedence; container sets
  `DATA_DIR=/data`.

## Configuration / secrets (every env var)

| Env var | Purpose | Source |
| --- | --- | --- |
| `ADMIN_PASSWORD` | Login-gate password (NEW — see auth below) | NAS `.env` |
| `SECRET_KEY` | Flask session signing (replaces hardcoded `prepis-vozidla-secret-2024`) | NAS `.env` |
| `ANTHROPIC_API_KEY` | Claude Vision OCR (scan feature) | NAS `.env` |
| `DATAOVOZIDLECH_API_KEY` | dataovozidlech.cz ORV lookup (was hardcoded `app.py:733` — moved to env) | NAS `.env` |
| `DATA_DIR` | Persistent data root | compose → `/data` |
| `TZ` | `Europe/Prague` | compose |

## Auth (decided with owner)

The app has **no authentication today**. It stores personal data (rodné
číslo, addresses, names) and the scan feature spends the owner's Anthropic
budget — both unacceptable on the public internet unauthenticated.

**Decision:** add a single-password login gate mirroring hunter's
`ADMIN_PASSWORD` pattern. Implementation is **conditional**: the gate is
enforced only when `ADMIN_PASSWORD` is set in the environment. Local desktop
builds (no env) keep their current no-login UX; the container sets
`ADMIN_PASSWORD` so the public site is protected.

## Health / readiness

- **None today.** Adding `GET /healthz` → always `200 "ok"`, excluded from
  the login gate, used by the docker `healthcheck`.

## Static assets / uploads

- Scanned images (`scans/`), generated PDFs (`output/`), uploaded plné moci
  (`plne_moce/`), and `firmy.xlsx` are written under `DATA_DIR` → all land on
  the `/data` bind mount and persist.
- `templates/`, `static/`, `pdfs/` are read-only app assets baked into the
  image.

## Reverse-proxy header trust

- Flask has no equivalent of uvicorn `--proxy-headers`. Add
  `werkzeug.middleware.proxy_fix.ProxyFix` so the app honors
  `X-Forwarded-Proto/-For/-Host` from Cloudflare → nginx (correct https URLs,
  Secure cookies).

## Build constraints

- Target arch `x86_64`. Pure-Python deps except Pillow (manylinux wheels
  exist) — base `python:3.12-slim` + the same libxml/libxslt runtime libs as
  hunter is sufficient. No app dependency manifest existed; a
  `requirements.txt` is added (flask, python-dotenv, openpyxl, pypdf,
  requests, pillow, reportlab, gunicorn).

## Adaptation summary vs hunter

| Aspect | hunter | přepisy |
| --- | --- | --- |
| Framework | FastAPI/ASGI | Flask/WSGI |
| Server | uvicorn `--proxy-headers` | gunicorn + `ProxyFix` |
| Migrations | `alembic upgrade head` | none |
| DB | SQLite + Alembic | none (xlsx + files on `/data`) |
| Port | 8088 | 8089 |
| Auth | `ADMIN_PASSWORD` always | `ADMIN_PASSWORD` conditional |
| Health | `/healthz` | `/healthz` (added) |
