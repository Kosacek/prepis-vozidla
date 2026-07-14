"""Local preview server for visual checks of the Úkony Tracker. Uses an ISOLATED
DATA_DIR in the system temp dir — never the real NAS DB — and seeds a few firms
and úkony (paid / partial / unpaid, with převod + poznámka + kdo) so the
dashboard and /ukony/vse render realistic rows. No login gate (ADMIN_PASSWORD
unset locally)."""
import os
import sys
import tempfile

DATA = os.path.join(tempfile.gettempdir(), "ukony_preview_data")
os.makedirs(DATA, exist_ok=True)
os.environ["DATA_DIR"] = DATA

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import config  # noqa: E402
config.DATA_DIR = DATA
config.DB_PATH = os.path.join(DATA, "tracker.db")

import app as appmod  # noqa: E402
import db  # noqa: E402
from repositories import firmy_repo, typy_repo  # noqa: E402
from services import ingest_service as ing  # noqa: E402

application = appmod.create_app()

with application.app_context():
    conn = db.get_db()
    if not firmy_repo.list_all(conn):
        cardion = firmy_repo.create(conn, nazev="Cardion s.r.o.", zkratka="Cardion", ico="11111111")
        albion = firmy_repo.create(conn, nazev="Albion a.s.", zkratka="Albion", ico="22222222")
        typy_repo.upsert(conn, "PŘEVOD", 1300, 1)
        typy_repo.upsert(conn, "NOVÉ", 1500, 2)
        ing.pridat_ukon(conn, firma_id=cardion, datum="2026-07-10", typ_kod="PŘEVOD", celkem=1300,
                        rz="1AB2345", vin="TMBJJ7NS0L8012345", prevod="JAN NOVÁK → CARDION S.R.O.",
                        zpracoval="Petr")
        ing.pridat_ukon(conn, firma_id=albion, datum="2026-07-11", typ_kod="NOVÉ", celkem=1500,
                        rz="2CD6789", vin="WVWZZZ1KZAW123456", poznamka="počká na doklady",
                        zaplaceno_kc=1500, zpracoval="David")
        ing.pridat_ukon(conn, firma_id=cardion, datum="2026-07-12", typ_kod="PŘEVOD", celkem=1300,
                        rz="3EF1122", vin="TMBEG7NE3K0654321", prevod="AUTO OPAT → CARDION S.R.O.",
                        poznamka="zimní kola v kufru", zaplaceno_kc=500, zpracoval="Roman")

if __name__ == "__main__":
    application.run(host="127.0.0.1", port=5056)
