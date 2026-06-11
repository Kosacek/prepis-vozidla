# Pulls the live Úkony Tracker DB from the NAS to this PC (off-NAS backup layer).
# Run manually or via the scheduled task "UkonyTracker NAS backup" (daily 20:00).
# Keeps the last 60 daily copies in data\nas_backups\ (gitignored).

$ErrorActionPreference = "Stop"
$nasDb     = "\\192.168.1.18\Container\ukony\data\tracker.db"
$backupDir = "D:\Claude Code\prepis_vozidla_app\ukony_tracker\data\nas_backups"
$keep      = 60
$log       = Join-Path $backupDir "backup.log"

New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$dest  = Join-Path $backupDir "tracker_$stamp.db"

try {
    Copy-Item $nasDb $dest -Force

    # Integrity check: open the copy read-only and run PRAGMA integrity_check.
    $py = "D:\Claude Code\prepis_vozidla_app\ukony_tracker\.venv\Scripts\python.exe"
    if (Test-Path $py) {
        $check = & $py -c "import sqlite3; c = sqlite3.connect(r'$dest'); print(c.execute('PRAGMA integrity_check').fetchone()[0]); r = c.execute('SELECT COUNT(*), COALESCE(SUM(celkem),0) FROM ukony').fetchone(); print(f'{r[0]} ukonu / {int(r[1])} Kc')"
        $checkText = ($check -join " | ")
    } else {
        $checkText = "no venv python - integrity not checked"
    }

    # Prune to the newest $keep copies.
    Get-ChildItem $backupDir -Filter "tracker_*.db" | Sort-Object Name -Descending |
        Select-Object -Skip $keep | Remove-Item -Force

    Add-Content $log "$stamp OK $((Get-Item $dest).Length) bytes | $checkText"
} catch {
    Add-Content $log "$stamp FAIL $($_.Exception.Message)"
    throw
}
