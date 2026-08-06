"""Deployment helpers: env file and systemd user unit.

These back ``avallon setup`` and ``avallon install``. Rendering is kept pure
(strings in, strings out) so it is testable without touching the real systemd,
and only the two write helpers reach the filesystem.

A *user* unit, not a system one: the site reads a notes repository that lives
in a home directory and speaks to a git remote with that user's keys. Running
it as root would only add a way to get the ownership wrong.
"""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

UNIT_NAME = "avallon.service"


def systemd_user_dir() -> Path:
    """The systemd *user* unit directory (``$XDG_CONFIG_HOME/systemd/user``)."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return root / "systemd" / "user"


def env_file_path() -> Path:
    """Where the environment file is written."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return root / "avallon" / "server.env"


def executable() -> str:
    """The ``avallon`` command to put in the unit.

    Resolved to an absolute path: systemd starts with a minimal PATH, and the
    one the user happens to have when running `install` is not it.
    """
    found = shutil.which("avallon")
    if found:
        return found
    # Installed but not on PATH (a virtualenv that is not activated): call the
    # module through the interpreter that is running right now.
    return f"{sys.executable} -m avallon.cli"


def generate_token() -> str:
    """A fresh access token."""
    return secrets.token_urlsafe(32)


def render_env(
    host: str, port: int, token: str, content_dir: Path | None = None
) -> str:
    """Render the environment file.

    The token is what makes a non-loopback bind acceptable, and ALLOWED_HOSTS
    has to name the address that will answer, so both are derived from the
    address given here rather than left to be remembered later.
    """
    hosts = {"127.0.0.1", "localhost", host}
    lines = [
        "# Written by `avallon setup`. Read by the systemd user unit.",
        f"AVALLON_HOST={host}",
        f"AVALLON_PORT={port}",
        f"AVALLON_TOKEN={token}",
        f"AVALLON_ALLOWED_HOSTS={','.join(sorted(hosts))}",
        "AVALLON_DEBUG=0",
        "AVALLON_SHOW_PRIVATE=0",
        # One commit per save rather than one per quarter of an hour: the
        # history panel offers a page's last five states, and folding a day of
        # edits into a single commit would leave most pages with one.
        "AVALLON_SYNC_WINDOW=0",
    ]
    if content_dir is not None:
        lines.append(f"AVALLON_CONTENT_DIR={content_dir}")
    return "\n".join(lines) + "\n"


def render_unit(env_path: Path, exec_start: str) -> str:
    """Render the systemd user unit."""
    return f"""\
[Unit]
Description=avallon, personal note site
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile={env_path}
ExecStart={exec_start} serve
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
"""


def write_env(path: Path, content: str) -> Path:
    """Write the env file with owner-only permissions; return its path.

    It holds the access token, so it is created 0600 rather than fixed up
    afterwards: a secret must never exist as world-readable, not even briefly.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    path.write_text(content, encoding="utf-8")
    return path


def write_unit(env_path: Path, unit_dir: Path | None = None) -> Path:
    """Render and install the systemd user unit; return its path."""
    target = (unit_dir or systemd_user_dir()) / UNIT_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_unit(env_path, executable()), encoding="utf-8")
    return target


def systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    """Run ``systemctl --user`` with *args*."""
    return subprocess.run(
        ["systemctl", "--user", *args], capture_output=True, text=True
    )
