"""Deployment: what `setup` writes, and what `install` renders."""

from __future__ import annotations

from pathlib import Path

import pytest

from avallon import deploy


def test_the_env_file_names_the_address_the_unit_will_answer_on() -> None:
    env = deploy.render_env("10.8.0.2", 8000, "jeton", Path("/home/x/notes"))

    assert "AVALLON_HOST=10.8.0.2" in env
    assert "AVALLON_PORT=8000" in env
    assert "AVALLON_TOKEN=jeton" in env
    assert "AVALLON_CONTENT_DIR=/home/x/notes" in env


def test_allowed_hosts_covers_the_bind_address_and_loopback() -> None:
    """A bind nobody is allowed to reach answers 400 to every request."""
    env = deploy.render_env("10.8.0.2", 8000, "jeton")

    (line,) = [x for x in env.splitlines() if x.startswith("AVALLON_ALLOWED_HOSTS=")]
    hosts = line.split("=", 1)[1].split(",")

    assert "10.8.0.2" in hosts
    assert "127.0.0.1" in hosts


def test_a_deployment_never_serves_private_pages_nor_debug() -> None:
    env = deploy.render_env("10.8.0.2", 8000, "jeton")

    assert "AVALLON_DEBUG=0" in env
    assert "AVALLON_SHOW_PRIVATE=0" in env


def test_a_generated_token_is_long_enough_to_be_one() -> None:
    assert len(deploy.generate_token()) >= 32
    assert deploy.generate_token() != deploy.generate_token()


def test_the_env_file_is_owner_only(tmp_path: Path) -> None:
    """It holds the access token."""
    path = deploy.write_env(tmp_path / "server.env", "AVALLON_TOKEN=jeton\n")

    assert path.stat().st_mode & 0o777 == 0o600


def test_the_unit_reads_the_env_file_and_restarts(tmp_path: Path) -> None:
    unit = deploy.render_unit(tmp_path / "server.env", "/usr/bin/avallon")

    assert f"EnvironmentFile={tmp_path / 'server.env'}" in unit
    assert "ExecStart=/usr/bin/avallon serve" in unit
    assert "Restart=on-failure" in unit
    assert "WantedBy=default.target" in unit


def test_the_unit_names_an_absolute_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """systemd starts with a minimal PATH, not the caller's."""
    monkeypatch.setattr(deploy.shutil, "which", lambda _: None)

    assert deploy.executable().startswith("/")


def test_install_writes_the_unit_where_systemd_reads_it(tmp_path: Path) -> None:
    unit = deploy.write_unit(tmp_path / "server.env", unit_dir=tmp_path / "systemd")

    assert unit.name == "avallon.service"
    assert unit.read_text().startswith("[Unit]")
