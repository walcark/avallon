"""The access token: what it guards, and what it lets through."""

from __future__ import annotations

from pathlib import Path

import pytest
from django.conf import settings
from django.test import Client

from avallon.web import security

from .conftest import write_page

TOKEN = "un-jeton-de-test"


@pytest.fixture
def locked(notes: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A site with a token configured, and one page to try to reach."""
    write_page(notes, "informatique/fiche/note", title="Une note")
    monkeypatch.setattr(settings, "ACCESS_TOKEN", TOKEN)
    return notes


def test_without_a_token_configured_nothing_is_guarded(notes: Path) -> None:
    write_page(notes, "informatique/fiche/note", title="Une note")

    assert Client().get("/").status_code == 200


def test_a_locked_site_redirects_to_the_unlock_page(locked: Path) -> None:
    response = Client().get("/informatique/fiche/note/")

    assert response.status_code == 302
    assert response["Location"].startswith("/deverrouiller/")


def test_the_redirect_remembers_where_the_reader_was_going(locked: Path) -> None:
    response = Client().get("/informatique/fiche/note/")

    assert "next=/informatique/fiche/note/" in response["Location"]


def test_the_unlock_page_itself_is_reachable(locked: Path) -> None:
    assert Client().get("/deverrouiller/").status_code == 200


def test_a_wrong_token_does_not_open_the_session(locked: Path) -> None:
    client = Client()

    response = client.post("/deverrouiller/", {"token": "faux"})

    assert response.status_code == 401
    assert client.get("/").status_code == 302


def test_the_right_token_opens_the_session(locked: Path) -> None:
    client = Client()

    response = client.post("/deverrouiller/", {"token": TOKEN, "next": "/"})

    assert response.status_code == 302
    assert client.get("/").status_code == 200


def test_the_session_survives_the_next_requests(locked: Path) -> None:
    client = Client()
    client.post("/deverrouiller/", {"token": TOKEN})

    assert client.get("/informatique/fiche/note/").status_code == 200
    assert client.get("/search/", {"q": "note"}).status_code == 200


def test_writing_is_refused_while_locked(locked: Path) -> None:
    """The editor endpoints answer to the same predicate as the reader."""
    response = Client().get("/source/", {"path": "informatique/fiche/note"})

    assert response.status_code == 302


def test_the_token_comparison_is_constant_time() -> None:
    """A secret compared with == leaks its length and its first characters."""
    source = Path(security.__file__).read_text(encoding="utf-8")

    assert "secrets.compare_digest" in source
