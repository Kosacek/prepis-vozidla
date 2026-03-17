"""
Auto-updater for PrepisVozidla.
Checks GitHub Releases for new versions, downloads silently, prompts restart.
"""
import os
import sys
import time
import shutil
import zipfile
import tempfile
import threading
import subprocess
import requests

from version import __version__

# ── Configuration ────────────────────────────────────────────────────────────
# TODO: Fill in your GitHub username and repo name after creating the repo
GITHUB_OWNER = "Kosacek"
GITHUB_REPO = "prepis-vozidla"
ASSET_NAME = "PrepisVozidla.zip"

# ── Module state ─────────────────────────────────────────────────────────────
update_ready = False
update_version = None
update_error = None
_staged_dir = None


def _compare_versions(current: str, remote: str) -> bool:
    """Return True if remote is newer than current."""
    try:
        cur = tuple(int(x) for x in current.split("."))
        rem = tuple(int(x) for x in remote.split("."))
        return rem > cur
    except (ValueError, AttributeError):
        return False


def check_for_update() -> dict | None:
    """Check GitHub Releases for a newer version. Returns release info or None."""
    try:
        url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
        r = requests.get(url, timeout=10, headers={"Accept": "application/vnd.github.v3+json"})
        if r.status_code != 200:
            return None
        release = r.json()
        tag = release.get("tag_name", "").lstrip("v")
        if not _compare_versions(__version__, tag):
            return None
        # Find the zip asset
        for asset in release.get("assets", []):
            if asset["name"] == ASSET_NAME:
                return {
                    "version": tag,
                    "download_url": asset["browser_download_url"],
                    "size": asset["size"],
                }
        return None
    except Exception:
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

        # Stream download
        with requests.get(download_url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(zip_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    f.write(chunk)

        # Verify zip
        if not zipfile.is_zipfile(zip_path):
            return None

        # Extract
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(staged)

        # The zip contains a PrepisVozidla/ folder — find it
        contents = os.listdir(staged)
        if len(contents) == 1 and os.path.isdir(os.path.join(staged, contents[0])):
            return os.path.join(staged, contents[0])
        return staged

    except Exception:
        return None


def apply_update_and_restart():
    """Write a batch script that replaces the app after exit, then restart."""
    global _staged_dir
    if not _staged_dir or not os.path.isdir(_staged_dir):
        raise RuntimeError("No staged update available")

    app_dir = os.path.dirname(sys.executable)
    pid = os.getpid()
    exe_path = os.path.join(app_dir, "PrepisVozidla.exe")

    update_dir = os.path.join(tempfile.gettempdir(), "PrepisVozidla_update")
    bat_path = os.path.join(update_dir, "do_update.bat")

    bat_content = f"""@echo off
:wait
tasklist /FI "PID eq {pid}" 2>NUL | find /I "{pid}" >NUL
if not errorlevel 1 (
    timeout /t 1 /nobreak >NUL
    goto wait
)
xcopy /Y /Q /E /I "{_staged_dir}\\*" "{app_dir}\\"
start "" "{exe_path}"
del "%~f0"
"""

    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat_content)

    # Launch the batch file detached
    subprocess.Popen(
        ["cmd", "/c", bat_path],
        creationflags=0x00000008 | 0x00000200,  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        close_fds=True,
    )

    # Exit the app
    os._exit(0)


def background_check():
    """Background thread: check for update, download if available."""
    global update_ready, update_version, update_error, _staged_dir

    # Wait a bit before checking
    time.sleep(5)

    try:
        info = check_for_update()
        if not info:
            return

        staged = download_update(info["download_url"])
        if not staged:
            update_error = "Download failed"
            return

        _staged_dir = staged
        update_version = info["version"]
        update_ready = True
    except Exception as e:
        update_error = str(e)
