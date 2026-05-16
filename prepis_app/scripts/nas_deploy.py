"""Zadosti NAS deployer (paramiko).

Robust against shell-quoting hell: every remote step is written to a temp
script via SFTP and executed with `bash`, instead of passing complex
command strings through an interactive PTY.

Credentials & target from env (nothing committed):
    NAS_USER      (default: admin)
    NAS_PASSWORD  (required)
    NAS_HOST      (default: 192.168.1.18)

Subcommands:
    run "<bash script text>"        run an ad-hoc script, stream output
    runfile <local.sh>             upload + run a local script file
    put <local_path> <remote_path> SFTP a single file (mkdir -p parent)
    puttree <local_dir> <remote_dir>  recursively SFTP a directory

Exit code mirrors the remote script's exit code.
"""
from __future__ import annotations

import os
import posixpath
import stat
import sys
import time

import paramiko

# Remote docker/compose output contains UTF-8 spinners/box chars the Windows
# cp1250 console can't encode; force a lossless stdout so streaming never
# crashes the deploy.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

HOST = os.environ.get("NAS_HOST", "192.168.1.18")
USER = os.environ.get("NAS_USER", "admin")
PASSWORD = os.environ.get("NAS_PASSWORD", "")
DOCKER_DIR = "/share/CACHEDEV1_DATA/.qpkg/container-station/usr/bin"

# .dockerignore-style skip list for puttree (keep the image build context lean
# and never upload secrets / local state / build junk).
SKIP_DIRS = {
    ".git", "__pycache__", ".pytest_cache", ".venv", "dist", "build",
    "tests", "docs", "data", "scans", "output", "plne_moce", ".claude",
    "tahaky",
}
SKIP_FILES = {
    ".env", "firmy.xlsx", "firmy.bak.xlsx", "deploy_output.txt",
}
SKIP_SUFFIX = (".pyc", ".spec", ".bat", ".ps1", ".bak")


def _connect() -> paramiko.SSHClient:
    if not PASSWORD:
        print("NAS_PASSWORD env required", file=sys.stderr)
        sys.exit(2)
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASSWORD, timeout=25)
    return c


def _exec(client: paramiko.SSHClient, command: str) -> int:
    chan = client.get_transport().open_session()
    chan.get_pty()
    chan.exec_command(command)
    buf = b""
    while True:
        if chan.recv_ready():
            data = chan.recv(4096)
            if not data:
                break
            buf += data
            sys.stdout.write(data.decode(errors="replace"))
            sys.stdout.flush()
        if chan.exit_status_ready() and not chan.recv_ready():
            break
        time.sleep(0.05)
    while chan.recv_ready():
        sys.stdout.write(chan.recv(4096).decode(errors="replace"))
    return chan.recv_exit_status()


def _run_script(client: paramiko.SSHClient, script: str) -> int:
    sftp = client.open_sftp()
    remote = f"/tmp/zadosti_step_{int(time.time()*1000)}.sh"
    # The non-admin SSH user can't write the Container Station homes dir
    # docker/compose default to; point HOME + DOCKER_CONFIG at a writable
    # temp path so `docker compose` doesn't fail with "permission denied".
    body = (
        "export PATH=" + DOCKER_DIR + ":$PATH\n"
        "export HOME=/tmp/zadosti-home\n"
        "export DOCKER_CONFIG=/tmp/zadosti-home/.docker\n"
        "mkdir -p /tmp/zadosti-home/.docker\n"
        "set -e\n" + script + "\n"
    )
    with sftp.open(remote, "w") as f:
        f.write(body)
    sftp.chmod(remote, 0o755)
    try:
        return _exec(client, f"bash {remote}")
    finally:
        try:
            sftp.remove(remote)
        except OSError:
            pass
        sftp.close()


def _ensure_dir(sftp: paramiko.SFTPClient, remote_dir: str) -> None:
    """Idempotently create remote_dir and every missing parent."""
    parts, cur = remote_dir.split("/"), ""
    for p in parts:
        if not p:
            continue
        cur += "/" + p
        try:
            sftp.stat(cur)
        except FileNotFoundError:
            try:
                sftp.mkdir(cur)
            except OSError:
                # Race / already exists between stat and mkdir — re-stat;
                # if it still fails, re-raise the original.
                sftp.stat(cur)


def _mkparent(sftp: paramiko.SFTPClient, remote_path: str) -> None:
    _ensure_dir(sftp, posixpath.dirname(remote_path))


def _puttree(sftp: paramiko.SFTPClient, local_dir: str, remote_dir: str) -> int:
    n = 0
    for root, dirs, files in os.walk(local_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel = os.path.relpath(root, local_dir)
        rdir = remote_dir if rel == "." else posixpath.join(remote_dir, rel.replace(os.sep, "/"))
        _ensure_dir(sftp, rdir)
        for fn in files:
            if fn in SKIP_FILES or fn.endswith(SKIP_SUFFIX):
                continue
            sftp.put(os.path.join(root, fn), posixpath.join(rdir, fn))
            n += 1
    print(f"[puttree] uploaded {n} files -> {remote_dir}")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    client = _connect()
    try:
        if cmd == "run":
            return _run_script(client, sys.argv[2])
        if cmd == "runfile":
            with open(sys.argv[2], encoding="utf-8") as f:
                return _run_script(client, f.read())
        if cmd == "put":
            sftp = client.open_sftp()
            _mkparent(sftp, sys.argv[3])
            sftp.put(sys.argv[2], sys.argv[3])
            print(f"[put] {sys.argv[2]} -> {sys.argv[3]}")
            sftp.close()
            return 0
        if cmd == "puttree":
            sftp = client.open_sftp()
            rc = _puttree(sftp, sys.argv[2], sys.argv[3])
            sftp.close()
            return rc
        print(f"unknown subcommand: {cmd}", file=sys.stderr)
        return 2
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
