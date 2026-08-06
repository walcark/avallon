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


def test_the_home_page_shows_the_selection_with_its_dossier(dossier: Path) -> None:
    body = Client().get("/").content.decode()

    assert "Recours batterie" in body
    assert 'class="card-project"' in body


def test_facets_and_text_narrow_the_same_selection(dossier: Path) -> None:
    """The point of the explorer: filter, then type, without losing the filter.

    Read on the fragment, not on the page: the sidebar lists the whole tree, so
    a title showing up there says nothing about the selection.
    """
    filtered = Client().get("/search/", {"domain": "administratif"}).content.decode()
    assert "Mail du 01/08" in filtered
    assert "Garantie légale" not in filtered

    narrowed = (
        Client()
        .get("/search/", {"domain": "administratif", "q": "Mail"})
        .content.decode()
    )
    assert "Mail du 01/08" in narrowed
    # Same filter, fewer results. Counted on the cards: a dossier's title also
    # appears under the pages that belong to it.
    assert narrowed.count('class="card-title"') < filtered.count('class="card-title"')


def test_the_explorer_fragment_is_what_the_page_embeds(dossier: Path) -> None:
    """One markup, two paths: the browser swaps in what the server rendered."""
    fragment = Client().get("/search/", {"q": "Mail"}).content.decode()

    assert "<html" not in fragment
    assert 'class="facets"' in fragment
    assert "Mail du 01/08" in fragment


def test_a_facet_that_cannot_divide_anything_is_not_shown(dossier: Path) -> None:
    """`kind` is chrome on a corpus of notes: every page holds the same value."""
    body = Client().get("/search/").content.decode()

    assert 'data-facet="kind"' not in body


def test_a_chosen_facet_keeps_its_alternatives(dossier: Path) -> None:
    """Otherwise picking a domain removes the chip needed to unpick it."""
    body = Client().get("/search/", {"domain": "administratif"}).content.decode()

    assert 'data-facet="domain"' in body
    assert 'data-value="administratif"' in body
    assert 'data-value="informatique"' in body  # switching stays possible
    assert 'aria-pressed="true"' in body


def test_a_selection_of_images_renders_as_a_grid(notes: Path) -> None:
    from .conftest import write_page as wp

    for i in range(2):
        wp(notes, f"administratif/fiche/scan-{i}", title=f"Scan {i}", file="scan.png")
    body = Client().get("/", {"kind": "image"}).content.decode()

    assert 'class="tiles"' in body
    assert 'class="cards"' not in body


def test_the_view_can_be_forced(notes: Path) -> None:
    from .conftest import write_page as wp

    wp(notes, "administratif/fiche/scan", title="Scan", file="scan.png")
    body = Client().get("/", {"kind": "image", "view": "cards"}).content.decode()

    assert 'class="cards"' in body


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


def test_the_manifest_is_valid_json_and_follows_the_language(
    dossier: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from django.conf import settings

    monkeypatch.setattr(settings, "LANGUAGE", "fr")
    response = Client().get("/manifest.webmanifest")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/manifest+json"
    payload = json.loads(response.content)
    assert payload["name"] == "Mes notes"
    assert payload["display"] == "standalone"
    assert {icon["sizes"] for icon in payload["icons"]} == {"192x192", "512x512"}


def test_the_service_worker_is_served_from_the_root(dossier: Path) -> None:
    """A worker only controls what sits under its own URL."""
    response = Client().get("/sw.js")

    assert response.status_code == 200
    assert response["Service-Worker-Allowed"] == "/"
    body = b"".join(response.streaming_content)
    assert b"addEventListener('fetch'" in body


def test_writes_are_never_replayed_from_the_cache(dossier: Path) -> None:
    """A POST silently succeeding later would corrupt a note."""
    from pathlib import Path as P

    worker = P("src/avallon/web/static/avallon/pwa/sw.js").read_text(encoding="utf-8")

    assert "request.method !== 'GET'" in worker


def test_a_facet_counts_against_the_other_facets_only(dossier: Path) -> None:
    """Counting on the final selection would hide every alternative at once."""
    from avallon.web import content

    selection = content.select(domains=["administratif"])
    domains = dict(selection.facets["domain"])

    # The domain facet still offers the whole corpus, so switching is possible.
    assert set(domains) == {"administratif", "informatique"}
    # While the other facets describe the narrowed set.
    assert "cr" in dict(selection.facets["type"])


def test_tags_narrow_together(notes: Path) -> None:
    """Two tags ask for pages carrying both, which is what adding words means."""
    from .conftest import write_page as wp

    wp(notes, "informatique/fiche/a", title="A", tags="[python, pixi]")
    wp(notes, "informatique/fiche/b", title="B", tags="[python]")

    from avallon.web import content

    assert content.select(tags=["python"]).total == 2
    assert content.select(tags=["python", "pixi"]).total == 1
