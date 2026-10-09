"""Import historical receipts into evidence, without changing local files.

On the NAS: python scripts/ppd_do_evidence.py [--dry-run]
Configuration: DATA_DIR, UKONY_API_URL and UKONY_API_KEY from the environment.
"""
import argparse
import json
import os
import sys

# Also works when launched as a script from outside the application directory.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import requests

import ppd
import ppd_push

BATCH_SIZE = 200


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Show counts and first 3 records; no HTTP")
    args = parser.parse_args(argv)
    data_dir = os.environ.get("DATA_DIR", BASE_DIR)
    api_url = os.environ.get("UKONY_API_URL", ppd_push.UKONY_API_URL).rstrip("/")
    api_key = os.environ.get("UKONY_API_KEY", "")

    def say(message):
        # Even an unexpected server error echoing credentials must not print them.
        message = str(message)
        print(message.replace(api_key, "[redacted]") if api_key else message)

    ledger = ppd.read_ppd_log(data_dir)
    live = {int(row["cislo"]) for row in ledger}
    backup = ppd.read_backup(data_dir)
    in_backup = {int(row["cislo"]) for row in backup if isinstance(row.get("cislo"), int)}
    # The oldest receipts (before the append-only backup existed) live only in
    # the ledger; send them too or evidence would be missing them forever.
    rows = [*backup, *(row for row in ledger if int(row["cislo"]) not in in_backup)]
    records = []
    errors = []
    for row in rows:
        try:
            records.append(ppd_push.build_record(row, smazano=int(row["cislo"]) not in live))
        except (TypeError, ValueError, OverflowError) as e:
            errors.append({"cislo": row.get("cislo"), "error": str(e)})

    deleted = sum(record["smazano"] for record in records)
    say(f"Doklady: {len(records)} / zive: {len(records) - deleted} / smazane: {deleted} / chyby: {len(errors)}")
    if args.dry_run:
        for record in records[:3]:
            say(json.dumps(record, ensure_ascii=False))
        return 1 if errors else 0
    if records and not api_key:
        parser.error("UKONY_API_KEY must be set for import")

    created = updated = 0
    for error in errors:
        say(json.dumps(error, ensure_ascii=False))
    batch_count = (len(records) + BATCH_SIZE - 1) // BATCH_SIZE
    for offset in range(0, len(records), BATCH_SIZE):
        batch = records[offset:offset + BATCH_SIZE]
        try:
            response = requests.post(f"{api_url}/api/ppd/import", json={"doklady": batch},
                                     headers={"X-Api-Key": api_key}, timeout=ppd_push.TIMEOUT)
            if not 200 <= response.status_code < 300:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
            result = response.json()
            batch_created = int(result["vytvoreno"])
            batch_updated = int(result["aktualizovano"])
            batch_errors = result["chyby"]
        except Exception as e:
            batch_created = batch_updated = 0
            batch_errors = [{"cislo": record["cislo"], "error": str(e)} for record in batch]
        created += batch_created
        updated += batch_updated
        errors.extend(batch_errors)
        say(f"Davka {offset // BATCH_SIZE + 1}/{batch_count}: "
            f"vytvoreno={batch_created} / aktualizovano={batch_updated} / chyby={len(batch_errors)}")
        for error in batch_errors:
            say(json.dumps(error, ensure_ascii=False))
    say(f"Celkem: vytvoreno={created} / aktualizovano={updated} / chyby={len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
