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

ARES_URL = "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/{ico}"
BACKUP_RETENTION = 30
BACKUP_MIN_INTERVAL_SEC = 300  # throttle: at most one backup per 5 min

STAV_NEZAPLACENO = "nezaplaceno"
STAV_ZAPLACENO = "zaplaceno"
STAV_CASTECNE = "castecne"
