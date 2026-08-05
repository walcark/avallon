"""The dispatcher: every subcommand reaches the module that implements it."""

from __future__ import annotations

import pytest

from avallon import cli


def test_no_argument_prints_the_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == 0
    assert "avallon <commande>" in capsys.readouterr().out


def test_an_unknown_command_fails_and_says_so(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["frobnique"]) == 2
    assert "commande inconnue" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("argv", "module", "expected"),
    [
        (["repo"], "avallon.notes.repo", ["where"]),
        (["repo", "/tmp/notes"], "avallon.notes.repo", ["set", "/tmp/notes"]),
        (["init", "/tmp/notes"], "avallon.notes.repo", ["init", "/tmp/notes"]),
        (["sync", "--local"], "avallon.notes.sync", ["--local"]),
        (["check"], "avallon.notes.taxonomy", ["check"]),
        (
            ["add-domain", "cuisine"],
            "avallon.notes.taxonomy",
            ["add-domain", "cuisine"],
        ),
    ],
)
def test_a_subcommand_forwards_its_arguments(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], module: str, expected: list[str]
) -> None:
    import importlib

    seen: list[list[str]] = []
    target = importlib.import_module(module)
    monkeypatch.setattr(target, "main", lambda a: seen.append(list(a)) or 0)

    assert cli.main(argv) == 0
    assert seen == [expected]


def test_init_without_a_target_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit):
        cli.main(["init"])


def test_an_unconfigured_install_says_what_to_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """No notes repository is an error, never a directory inside the install."""
    from avallon.notes import config

    monkeypatch.delenv(config.ENV_VAR, raising=False)
    monkeypatch.delenv(config.LEGACY_ENV_VAR, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(config.Path, "home", staticmethod(lambda: tmp_path))

    with pytest.raises(config.NotConfigured, match="avallon init"):
        config.resolve_content_dir()
