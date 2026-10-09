# Changelog

## 1.21.0 — 2026-10-09

- Every issued PPD is sent to evidence in the background, including receipts
  issued with the evidence checkbox off. PPD and tracker pushes share a žádost ID.
- Deleted and restored receipts update their evidence status. Failed PPD pushes
  are saved separately and retried by the existing periodic sweep.
- Added `scripts/ppd_do_evidence.py` for historical import in batches of 200,
  with a dry run that sends no HTTP requests.
