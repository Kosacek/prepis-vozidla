"""
Auto-updater for PrepisVozidla.

Two update strategies:
1. NAS clients: app runs from shared NAS folder — just detect version mismatch
   and tell the user to restart (NAS files are updated via deploy_to_nas.bat).
2. Local installs: download zip from GitHub Releases and replace files.
"""
import os
import sys
import time
import shutil
import zipfile
import tempfile
import logging
import subprocess
import requests

# ── Logging ─────────────────────────────────────────────────────────────────
log = logging.getLogger("updater")
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("[updater] %(levelname)s: %(message)s"))
log.addHandler(_handler)
log.setLevel(logging.DEBUG)

try:
    _fh = logging.FileHandler(
        os.path.join(tempfile.gettempdir(), "PrepisVozidla_updater.log"),
        encoding="utf-8",
    )
    _fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    log.addHandler(_fh)
except Exception:
    pass

# ── Version ─────────────────────────────────────────────────────────────────
BASE_DIR = sys._MEIPASS if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
try:
    with open(os.path.join(BASE_DIR, "VERSION")) as _vf:
        __version__ = _vf.read().strip()
except Exception:
    from version import __version__

# ── Configuration ────────────────────────────────────────────────────────────
GITHUB_OWNER = "Kosacek"
GITHUB_REPO = "prepis-vozidla"
ASSET_NAME = "PrepisVozidla.zip"

# Detect if running from NAS (UNC path)
_app_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else ""
is_nas = _app_dir.startswith("\\\\")
log.info("App dir: %s (NAS: %s, version: %s)", _app_dir, is_nas, __version__)

# ── Module state ─────────────────────────────────────────────────────────────
update_ready = False
update_version = None
update_error = None
update_mode = None  # "restart" (NAS) or "download" (local)
_staged_dir = None


def _compare_versions(current: str, remote: str) -> bool:
    """Return True if remote is newer than current."""
    try:
        cur = tuple(int(x) for x in current.split("."))
        rem = tuple(int(x) for x in remote.split("."))
        return rem > cur
    except (ValueError, AttributeError):
        return False


def _check_nas_version() -> str | None:
    """Check the VERSION file on the NAS (live, not bundled). Returns version or None."""
    try:
        nas_version_path = os.path.join(_app_dir, "_internal", "VERSION")
        if os.path.isfile(nas_version_path):
            with open(nas_version_path) as f:
                return f.read().strip()
    except Exception as e:
        log.warning("Could not read NAS VERSION: %s", e)
    return None


def check_for_update() -> dict | None:
    """Check for a newer version. NAS checks local files; local checks GitHub."""
    # Strategy 1: NAS — compare bundled version vs live NAS version
    if is_nas:
        nas_ver = _check_nas_version()
        if nas_ver and _compare_versions(__version__, nas_ver):
            log.info("NAS has newer version: %s (running: %s)", nas_ver, __version__)
            return {"version": nas_ver, "mode": "restart"}
        log.info("NAS version check: running=%s, nas=%s — no update", __version__, nas_ver)
        # Also check GitHub as fallback

    # Strategy 2: GitHub Releases
    try:
        url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
        log.info("Checking GitHub: %s (current: %s)", url, __version__)
        r = requests.get(url, timeout=10, headers={"Accept": "application/vnd.github.v3+json"})
        if r.status_code != 200:
            log.warning("GitHub API returned status %d", r.status_code)
            return None
        release = r.json()
        tag = release.get("tag_name", "").lstrip("v")
        log.info("Latest GitHub release: %s", tag)
        if not _compare_versions(__version__, tag):
            log.info("Already up to date (%s >= %s)", __version__, tag)
            return None
        for asset in release.get("assets", []):
            if asset["name"] == ASSET_NAME:
                mode = "restart" if is_nas else "download"
                log.info("Update available: %s -> %s (mode: %s)", __version__, tag, mode)
                return {
                    "version": tag,
                    "download_url": asset["browser_download_url"],
                    "size": asset["size"],
                    "mode": mode,
                }
        log.warning("Release %s has no asset named %s", tag, ASSET_NAME)
        return None
    except Exception as e:
        log.error("GitHub check failed: %s", e)
        return None


def download_update(download_url: str) -> str | None:
    """Download and extract update zip. Returns staged directory path or None."""
    try:
        update_dir = os.path.join(tempfile.gettempdir(), "PrepisVozidla_update")
        if os.path.exists(update_dir):
            shutil.rmtree(update_dir, ignore_errors=True)
        os.makedirs(update_dir, exist_ok=True)

        zip_path = os.path.join(update_dir, "update.zip")
        staged = os.path.join(update_dir, "staged")

        log.info("Downloading update from %s", download_url)
        with requests.get(download_url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(zip_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    f.write(chunk)
        log.info("Downloaded %d bytes", os.path.getsize(zip_path))

        if not zipfile.is_zipfile(zip_path):
            log.error("Downloaded file is not a valid zip")
            return None

        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(staged)

        contents = os.listdir(staged)
        if len(contents) == 1 and os.path.isdir(os.path.join(staged, contents[0])):
            result = os.path.join(staged, contents[0])
        else:
            result = staged
        log.info("Update staged at %s", result)
        return result

    except Exception as e:
        log.error("Download failed: %s", e)
        return None


def apply_update_and_restart():
    """Apply update — behavior depends on mode."""
    global _staged_dir

    # NAS mode: just exit, user will reopen and get new version
    if update_mode == "restart":
        log.info("NAS mode: exiting app so user can restart with new version")
        os._exit(0)

    # Local mode: write batch script to replace files and restart
    if not _staged_dir or not os.path.isdir(_staged_dir):
        raise RuntimeError("No staged update available")

    app_dir = os.path.dirname(sys.executable)
    pid = os.getpid()
    exe_path = os.path.join(app_dir, "PrepisVozidla.exe")

    update_dir = os.path.join(tempfile.gettempdir(), "PrepisVozidla_update")
    bat_path = os.path.join(update_dir, "do_update.bat")
    bat_log = os.path.join(update_dir, "do_update.log")

    bat_content = f"""@echo off
echo [%date% %time%] Update script started > "{bat_log}"

:wait
tasklist /FI "PID eq {pid}" 2>NUL | find /I "{pid}" >NUL
if not errorlevel 1 (
    timeout /t 1 /nobreak >NUL
    goto wait
)
echo [%date% %time%] Copying files... >> "{bat_log}"
robocopy "{_staged_dir}" "{app_dir}" /E /IS /IT >> "{bat_log}" 2>&1
echo [%date% %time%] Starting app... >> "{bat_log}"
start "" "{exe_path}"
del "%~f0"
"""

    log.info("Writing update batch to %s", bat_path)
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat_content)

    subprocess.Popen(
        ["cmd", "/c", bat_path],
        creationflags=0x00000008 | 0x00000200,
        close_fds=True,
    )
    os._exit(0)


def background_check():
    """Background thread: check for update, download if available."""
    global update_ready, update_version, update_error, update_mode, _staged_dir

    time.sleep(5)

    try:
        info = check_for_update()
        if not info:
            return

        mode = info.get("mode", "download")

        if mode == "restart":
            # NAS: no download needed, just flag the update
            update_mode = "restart"
            update_version = info["version"]
            update_ready = True
            log.info("NAS update ready: restart to get v%s", update_version)
            return

        # Local: download and stage
        staged = download_update(info["download_url"])
        if not staged:
            update_error = "Download failed"
            return

        _staged_dir = staged
        update_mode = "download"
        update_version = info["version"]
        update_ready = True
        log.info("Local update ready: v%s staged at %s", update_version, _staged_dir)
    except Exception as e:
        update_error = str(e)
        log.error("Background check failed: %s", e)
