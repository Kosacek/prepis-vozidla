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

# Pár vygenerovaných žádostí + index, ať má 🔍 hledání co zobrazit.
import hledani  # noqa: E402

OUT = os.path.join(DATA, "output")
os.makedirs(OUT, exist_ok=True)
_SEED = [
    ("zmeny_20260715_100000.pdf", {"registracni_znacka": "3BR4008", "vin": "",
     "znacka": "Škoda Octavia", "puvodni_jmeno": "AUTO CARDION s. r. o.",
     "novy_jmeno": "JAN NOVÁK"}),
    ("zapis_20260715_113000.pdf", {"registracni_znacka": "", "vin": "TMBJJ7NE5J0123456",
     "znacka": "Toyota Corolla", "puvodni_jmeno": "",
     "novy_jmeno": "TOYOTA FINANCIAL SERVICES CZECH S.R.O."}),
    ("zmeny_20260720_090000.pdf", {"registracni_znacka": "1AB2345", "vin": "",
     "znacka": "Volvo XC60", "puvodni_jmeno": "AUTO CARDION s. r. o.",
     "novy_jmeno": "PETR SVOBODA"}),
]
if not app.read_firmy():
    app.save_firmy([
        {"nazev": "AUTO CARDION s. r. o.", "ico": "04156854",
         "adresa": "Veverkova 1234/5, Brno", "psc": "60200", "id": "5"},
        {"nazev": "Albion Cars s.r.o.", "ico": "04168313",
         "adresa": "Náměstí 1, Praha", "psc": "11000", "id": "7"},
    ])

if not hledani.nacti_index(DATA):
    for name, meta in _SEED:
        path = os.path.join(OUT, name)
        if not os.path.exists(path):
            with open(path, "wb") as fh:
                fh.write(b"%PDF-1.4\n% preview placeholder\n")
        hledani.zapis_vystup(DATA, [name], meta)

app.app.run(host="127.0.0.1", port=5055)
