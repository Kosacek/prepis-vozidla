"""GET /verze — which build of the app is running.

Every page is stamped with the build that drew it (the APP_BUILD template
global) and polls this route; when the two differ, the server was updated
underneath an open page and it shows the "Nová verze aplikace · Obnovit"
bar (templates/_whats_new.html). Behind the normal login gate — it is not
under /api/, which is the key-authenticated server-to-server surface.
"""
import hashlib
from functools import lru_cache
from pathlib import Path

from flask import Blueprint, jsonify

bp = Blueprint("verze", __name__)

_APP_DIR = Path(__file__).resolve().parent.parent
_CODE_SUFFIXES = (".py", ".html", ".js", ".css")
_SKIP_DIRS = {"__pycache__", ".venv", "data", "tests", "docs", "scripts", ".pytest_cache"}


@lru_cache(maxsize=1)
def build_id() -> str:
    """Hash of the app's own code, taken once per process. Any deploy that
    changes code changes it; processes running the same code agree."""
    digest = hashlib.blake2b(digest_size=6)
    for path in sorted(_APP_DIR.rglob("*")):
        rel = path.relative_to(_APP_DIR)
        if path.suffix not in _CODE_SUFFIXES or _SKIP_DIRS.intersection(rel.parts):
            continue
        digest.update(rel.as_posix().encode())
        # Line endings depend on how the tree was copied, not on the code.
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


@bp.route("/verze")
def verze():
    resp = jsonify(build=build_id())
    # Every poll must reach the server, or a page would never see an update.
    resp.headers["Cache-Control"] = "no-store"
    return resp
