import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR") or os.path.join(BASE_DIR, "data")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
DB_PATH = os.path.join(DATA_DIR, "tracker.db")

SEED_DIR = os.path.join(BASE_DIR, "scripts", "seed_data")
SEED_UKONY_XLSX = os.path.join(SEED_DIR, "5.2026.xlsx")
FIRMY_XLSX = os.path.abspath(os.path.join(BASE_DIR, "..", "prepis_app", "firmy.xlsx"))

PORT = int(os.environ.get("HTTP_PORT", "5051"))
SECRET_KEY = os.environ.get("SECRET_KEY", "ukony-tracker-local-dev")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
# Shared secret for server-to-server calls to /api/* (the zadosti push). When
# set, /api/* requires header X-Api-Key == this value; when empty, /api/* is open
# (local/dev — preserves the keyless API tests).
INTEGRATION_API_KEY = os.environ.get("INTEGRATION_API_KEY", "")
# dataovozidlech.cz registry key — lets the úkon form auto-fill the VIN from the
# ORV (same source the zadosti app uses). Empty → the lookup returns a clear
# "missing key" message instead of failing to boot.
DATAOVOZIDLECH_API_KEY = os.environ.get("DATAOVOZIDLECH_API_KEY", "")
# Žádosti issue every doklad (one numbering series); evidence asks them over the
# docker network. Empty = "Nový doklad" says it isn't switched on yet.
ZADOSTI_API_URL = os.environ.get("ZADOSTI_API_URL", "")
ZADOSTI_PUBLIC_URL = os.environ.get("ZADOSTI_PUBLIC_URL", "https://zadosti.spznaklic.cz")

ARES_URL = "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/{ico}"
BACKUP_RETENTION = 30
BACKUP_MIN_INTERVAL_SEC = 300  # throttle: at most one backup per 5 min

STAV_NEZAPLACENO = "nezaplaceno"
STAV_ZAPLACENO = "zaplaceno"
STAV_CASTECNE = "castecne"

# Who filled out / added a car (attribution). Chosen per-device in zadosti and
# pushed through; also selectable on the tracker's own entry/edit forms.
PROFILY = ["David", "Roman", "Petr"]

# MONETA Money Bank (AISP) — automatic settling of fakturas from incoming
# payments (services/moneta_*.py). No token = feature fully off. The token is
# bound to one account and lasts 3 months (auto-extended); never commit it.
MONETA_API_TOKEN = os.environ.get("MONETA_API_TOKEN", "").strip()
MONETA_ACCOUNT_ID = os.environ.get("MONETA_ACCOUNT_ID", "").strip()
MONETA_API_BASE = (os.environ.get("MONETA_API_BASE") or "https://api.moneta.cz").rstrip("/")
try:
    MONETA_POLL_MIN = max(1, int(os.environ.get("MONETA_POLL_MIN") or 15))
except ValueError:
    MONETA_POLL_MIN = 15
