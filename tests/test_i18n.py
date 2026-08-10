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


def test_the_filter_follows_the_reader_not_the_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The language belongs to whoever is holding the screen, so it is set per
    request; the configured value is only what is answered by default."""
    template = Template('{% load lang %}{{ "Contents"|t }}')

    i18n.activate("fr")
    assert template.render(Context({})) == "Contenu"

    i18n.activate("en")
    assert template.render(Context({})) == "Contents"


def test_without_a_choice_the_configured_language_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template = Template('{% load lang %}{{ "Contents"|t }}')

    monkeypatch.setattr(settings, "LANGUAGE", "fr")
    assert template.render(Context({})) == "Contenu"


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


def test_a_reader_can_switch_language_and_it_sticks(notes: Path) -> None:
    """The choice belongs to whoever is holding the screen, so it rides on
    their device rather than on the installation's configuration."""
    client = Client()

    response = client.get("/langue/", {"to": "fr", "back": "/tags/"})

    assert response.status_code == 302
    assert response["Location"] == "/tags/"
    assert client.cookies[i18n.COOKIE].value == "fr"
    assert "Tous les tags" in client.get("/tags/").content.decode()


def test_an_unknown_language_is_refused(notes: Path) -> None:
    assert Client().get("/langue/", {"to": "klingon"}).status_code == 404


def test_the_switch_only_ever_returns_into_the_site(notes: Path) -> None:
    """`back` comes from a link, so it is never trusted to leave."""
    for hostile in ("https://ailleurs.example/x", "//ailleurs.example/x"):
        response = Client().get("/langue/", {"to": "fr", "back": hostile})
        assert response["Location"] == "/"


def test_the_switch_offers_the_other_language(notes: Path) -> None:
    body = Client().get("/").content.decode()

    assert 'href="/langue/?to=fr' in body  # English is the default here
