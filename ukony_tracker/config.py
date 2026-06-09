import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
DB_PATH = os.path.join(DATA_DIR, "tracker.db")

SEED_DIR = os.path.join(BASE_DIR, "scripts", "seed_data")
SEED_UKONY_XLSX = os.path.join(SEED_DIR, "5.2026.xlsx")
FIRMY_XLSX = os.path.abspath(os.path.join(BASE_DIR, "..", "prepis_app", "firmy.xlsx"))

PORT = 5051
ARES_URL = "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/{ico}"
BACKUP_RETENTION = 30
BACKUP_MIN_INTERVAL_SEC = 300  # throttle: at most one backup per 5 min (avoids churn during batch entry)

STAV_NEZAPLACENO = "nezaplaceno"
STAV_ZAPLACENO = "zaplaceno"
STAV_CASTECNE = "castecne"
