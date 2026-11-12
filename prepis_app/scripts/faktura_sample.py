"""Write sample invoices (with and without IBAN) so the look can be reviewed.

Usage: python scripts/faktura_sample.py <output_dir>
Writes faktura_sample.pdf (dummy IBAN, "VZOR" watermark) and
faktura_sample_bez_iban.pdf. Sample files are never committed.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import faktura_pdf  # noqa: E402

DUMMY_IBAN = "CZ6508000000192000145399"
RECORD = {
    "number": 20260001, "date": "12.11.2026", "due": "19.11.2026",
    "payer": "JE & NE, SPOL. S R.O.", "payer_ico": "44960263",
    "payer_address": "VEVEŘÍ 102, 616 00 BRNO", "amount": 5200,
    "purpose": "Zastupování na MMB",
    "vozidla": ["3BR9309", "3BR7164", "TMBJJ7NE5J0123456"],
}


def main(out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    os.environ.setdefault("ISSUER_ADRESA", "")
    os.environ["FAKTURA_IBAN"] = DUMMY_IBAN
    os.environ["FAKTURA_UCET"] = "192000145399/0800"
    _write(out_dir, "faktura_sample.pdf")
    os.environ.pop("FAKTURA_IBAN")
    os.environ.pop("FAKTURA_UCET")
    _write(out_dir, "faktura_sample_bez_iban.pdf")


def _write(out_dir: str, name: str) -> None:
    path = os.path.join(out_dir, name)
    with open(path, "wb") as f:
        f.write(faktura_pdf.build_faktura_pdf(RECORD, sample=True))
    print(path)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
