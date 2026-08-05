"""The views, through Django's test client: what a reader actually receives."""

from __future__ import annotations

from pathlib import Path

import pytest
from django.test import Client

from .conftest import write_page

INDEX = "administratif/recueil/recours-batterie"


@pytest.fixture
def dossier(notes: Path) -> Path:
    """A dossier index with one member, plus a page outside any dossier."""
    write_page(notes, INDEX, title="Recours batterie", summary="Le dossier.")
    write_page(
        notes,
        "administratif/cr/mail-du-01-08",
        title="Mail du 01/08",
        project="recours-batterie",
        status="en cours",
    )
    write_page(notes, "informatique/fiche/garantie", title="Garantie légale")
    return notes


def test_a_page_renders_with_its_title_and_body(dossier: Path) -> None:
    response = Client().get("/informatique/fiche/garantie/")

    assert response.status_code == 200
    assert "Garantie légale" in response.content.decode()


def test_a_missing_page_is_a_404(dossier: Path) -> None:
    assert Client().get("/informatique/fiche/inexistante/").status_code == 404


def test_a_page_without_its_trailing_slash_redirects(dossier: Path) -> None:
    """Relative image paths only resolve under a URL that ends in a slash."""
    response = Client().get("/informatique/fiche/garantie")

    assert response.status_code == 301
    assert response["Location"].endswith("/garantie/")


def test_a_member_page_names_its_dossier_and_browses_it(dossier: Path) -> None:
    body = Client().get("/administratif/cr/mail-du-01-08/").content.decode()

    assert 'class="page-project"' in body  # named above the title
    assert 'class="tree dossier"' in body  # browsed in the sidebar
    assert "Recours batterie" in body


def test_a_dossier_index_lists_its_own_pages(dossier: Path) -> None:
    body = Client().get(f"/{INDEX}/").content.decode()

    assert 'class="tree dossier"' in body
    assert "Mail du 01/08" in body


def test_a_page_outside_a_dossier_keeps_the_whole_tree(dossier: Path) -> None:
    body = Client().get("/informatique/fiche/garantie/").content.decode()

    assert 'class="tree dossier"' not in body
    assert "tree-all" not in body  # the tree is not folded away


def test_the_home_page_lists_every_page_with_its_dossier(dossier: Path) -> None:
    body = Client().get("/").content.decode()

    assert 'data-project="recours-batterie"' in body
    assert 'class="card-project"' in body


def test_the_search_endpoint_returns_the_dossier_of_a_hit(dossier: Path) -> None:
    payload = Client().get("/search/", {"q": "Mail"}).json()

    (hit,) = [r for r in payload["results"] if r["title"] == "Mail du 01/08"]
    assert hit["project"] == "recours-batterie"
    assert hit["project_title"] == "Recours batterie"
    assert hit["status"] == "en cours"


def test_a_private_page_404s_when_private_pages_are_off(
    dossier: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from django.conf import settings

    write_page(dossier, "informatique/fiche/secret", title="S", visibility="private")
    monkeypatch.setattr(settings, "SHOW_PRIVATE", False)

    assert Client().get("/informatique/fiche/secret/").status_code == 404


def test_an_asset_inherits_the_visibility_of_its_page(
    dossier: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Serving a figure from a hidden page would leak the page itself."""
    from django.conf import settings

    write_page(dossier, "informatique/fiche/secret", title="S", visibility="private")
    (dossier / "informatique/fiche/secret/figure.png").write_bytes(b"png")
    monkeypatch.setattr(settings, "SHOW_PRIVATE", False)

    assert Client().get("/informatique/fiche/secret/figure.png").status_code == 404


def test_the_creation_form_offers_the_declared_taxonomy(dossier: Path) -> None:
    body = Client().get("/nouvelle/").content.decode()

    assert 'value="informatique"' in body
    assert 'value="recueil"' in body
    assert 'value="chantier"' not in body  # not declared in this tree
