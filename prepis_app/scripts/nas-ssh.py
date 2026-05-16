"""SSH helper for driving the QNAP NAS over paramiko (zadosti deploy).

Adapted from the brno-hunter reference. Credentials are read from the
environment so nothing sensitive is committed:

    NAS_USER     SSH username (default: admin)
    NAS_PASSWORD SSH password (required; or piped on stdin)
    NAS_HOST     SSH host     (default: 192.168.1.18)

The Container Station docker binary is not on the default PATH, so it is
prepended for every command.

Usage:
    NAS_USER=Kosci NAS_PASSWORD=*** python scripts/nas-ssh.py docker ps
"""
from __future__ import annotations

import os
import shlex
import sys

import paramiko

HOST = os.environ.get("NAS_HOST", "192.168.1.18")
USER = os.environ.get("NAS_USER", "admin")
DOCKER_DIR = "/share/CACHEDEV1_DATA/.qpkg/container-station/usr/bin"
ENV_PREFIX = f"export PATH={DOCKER_DIR}:$PATH; "


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: nas-ssh.py <command...>", file=sys.stderr)
        return 2
    cmd = " ".join(shlex.quote(a) for a in sys.argv[1:])
    password = os.environ.get("NAS_PASSWORD") or sys.stdin.read().strip()
    if not password:
        print("NAS_PASSWORD env or stdin required", file=sys.stderr)
        return 2
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=password, timeout=20)
    _, stdout, stderr = client.exec_command(ENV_PREFIX + cmd, get_pty=True)
    rc = stdout.channel.recv_exit_status()
    print(stdout.read().decode(errors="replace"), end="")
    err = stderr.read().decode(errors="replace")
    if err:
        print(err, end="", file=sys.stderr)
    client.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
