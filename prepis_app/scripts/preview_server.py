"""Local preview server for visual checks. Uses an ISOLATED DATA_DIR in the
system temp dir — never the real NAS evidence ledger — and seeds one receipt
so /ppd-print/1 renders something."""
import os
import sys
import tempfile

os.environ.setdefault("DATA_DIR", os.path.join(tempfile.gettempdir(), "ppd_preview_data"))
os.makedirs(os.environ["DATA_DIR"], exist_ok=True)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import app  # noqa: E402  (must come after DATA_DIR is set)
import ppd  # noqa: E402

DATA = os.environ["DATA_DIR"]
if not ppd.read_backup(DATA):
    n = ppd.reserve_ppd_number_and_log(DATA, {
        "date": "05.06.2026", "payer": "AUTODOPRAVA NOVÁK s.r.o.",
        "amount": 1300, "purpose": "Zastupování na MMB", "vehicle": "1AB 2345",
    })
    ppd.append_backup(DATA, {
        "cislo": n, "ts": "2026-06-05T10:00:00", "date": "05.06.2026",
        "payer": "AUTODOPRAVA NOVÁK s.r.o.", "payer_ico": "04156854",
        "payer_address": "Veverkova 1234/5, 60200 Brno", "amount": 1300,
        "purpose": "Zastupování na MMB", "spz": "1AB 2345", "vin": "",
    })

app.app.run(host="127.0.0.1", port=5055)
