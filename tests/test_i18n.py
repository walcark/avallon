"""The interface language: resolution, catalogue and template filter."""

from __future__ import annotations

from pathlib import Path

import pytest
from django.conf import settings
from django.template import Context, Template
from django.test import Client

from avallon.notes import config
from avallon.web import i18n

from .conftest import write_page


@pytest.fixture
def local_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the machine-local config, and forget any env override."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv(config.LANGUAGE_ENV, raising=False)
    return tmp_path


def test_english_is_the_default(local_config: Path) -> None:
    assert config.resolve_language() == "en"


def test_the_choice_is_remembered(local_config: Path) -> None:
    config.write_language("fr")

    assert config.resolve_language() == "fr"


def test_the_environment_wins_over_the_file(
    local_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config.write_language("fr")
    monkeypatch.setenv(config.LANGUAGE_ENV, "en")

    assert config.resolve_language() == "en"


def test_choosing_a_language_keeps_the_notes_directory(local_config: Path) -> None:
    """The config file holds both; writing one must not erase the other."""
    config.write_content_dir(Path("/home/x/notes"))

    config.write_language("fr")

    assert config.read_content_dir() == Path("/home/x/notes")
    assert config.read_language() == "fr"


def test_an_untranslated_string_stays_in_english() -> None:
    assert i18n.translate("Not in the catalogue", "fr") == "Not in the catalogue"


def test_an_unknown_language_falls_back_to_english() -> None:
    assert i18n.translate("Contents", "de") == "Contents"


def test_the_catalogue_translates() -> None:
    assert i18n.translate("Contents", "fr") == "Contenu"


def test_the_filter_follows_the_active_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template = Template('{% load lang %}{{ "Contents"|t }}')

    monkeypatch.setattr(settings, "LANGUAGE", "fr")
    assert template.render(Context({})) == "Contenu"

    monkeypatch.setattr(settings, "LANGUAGE", "en")
    assert template.render(Context({})) == "Contents"


def test_the_page_is_served_in_english_by_default(
    notes: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_page(notes, "informatique/fiche/note", title="A note")
    monkeypatch.setattr(settings, "LANGUAGE", "en")

    body = Client().get("/informatique/fiche/note/").content.decode()

    assert 'lang="en"' in body
    assert "Table of contents" in body
    assert "Sommaire" not in body


def test_the_page_is_served_in_french_when_asked(
    notes: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_page(notes, "informatique/fiche/note", title="A note")
    monkeypatch.setattr(settings, "LANGUAGE", "fr")

    body = Client().get("/informatique/fiche/note/").content.decode()

    assert 'lang="fr"' in body
    assert "Sommaire" in body
