"""The content model: pages, tags, links and visibility."""

from __future__ import annotations

from pathlib import Path

import pytest
from django.http import Http404

from avallon.web import content

from .conftest import write_page


def test_a_page_reads_its_taxonomy_from_its_path(notes: Path) -> None:
    index = write_page(notes, "informatique/fiche/pixi", title="Pixi")

    page = content.load_page(index)

    assert (page.domain, page.type, page.slug) == ("informatique", "fiche", "pixi")
    assert page.url == "/informatique/fiche/pixi/"


def test_labels_rename_a_directory_for_the_reader(notes: Path) -> None:
    index = write_page(notes, "informatique/cr/reunion", title="Réunion")

    page = content.load_page(index)

    assert page.type == "cr"
    assert page.type_label == "compte rendu"


def test_tags_are_folded_to_one_canonical_form(notes: Path) -> None:
    assert content.normalize_tags(["Monte-Carlo", " monte-carlo "]) == ["monte-carlo"]
    assert content.normalize_tags(["Déformation"]) == ["déformation"]


def test_a_malformed_tag_list_yields_no_tags(notes: Path) -> None:
    """A forgotten bracket must not take the page down."""
    index = write_page(notes, "informatique/fiche/casse", title="Cassée", tags="python")

    assert content.load_page(index).tags == []


def test_a_tag_enters_the_facets_once_it_groups_pages(notes: Path) -> None:
    for i in range(content.TAG_FACET_MIN):
        write_page(
            notes, f"informatique/fiche/p{i}", title=f"P{i}", tags="[pixi, seul]"
        )
    write_page(notes, "informatique/fiche/autre", title="Autre", tags="[seul]")
    pages = content.all_pages()

    facets = content.facet_tags(pages)

    assert "pixi" in facets  # carried by exactly TAG_FACET_MIN pages
    assert "seul" in facets  # carried by more


def test_a_tag_on_a_single_page_stays_out_of_the_facets(notes: Path) -> None:
    write_page(notes, "informatique/fiche/une", title="Une", tags="[isole]")

    assert content.facet_tags(content.all_pages()) == []


def test_a_wikilink_resolves_by_slug_path_or_title(notes: Path) -> None:
    write_page(notes, "informatique/fiche/cible", title="La cible")
    source = write_page(notes, "informatique/cr/source", title="Source")
    source.write_text(
        source.read_text(encoding="utf-8") + "\n[[La Cible]] et [[cible]].\n",
        encoding="utf-8",
    )
    target = content.load_page(notes / "informatique/fiche/cible/index.md")

    assert [p.slug for p in content.backlinks(target)] == ["source"]


def test_a_page_does_not_backlink_itself(notes: Path) -> None:
    index = write_page(notes, "informatique/fiche/seule", title="Seule")
    index.write_text(
        index.read_text(encoding="utf-8") + "\nVoir [[seule]].\n", encoding="utf-8"
    )

    assert content.backlinks(content.load_page(index)) == []


def test_a_private_page_is_invisible_when_private_pages_are_off(
    notes: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from django.conf import settings

    index = write_page(
        notes, "informatique/fiche/secret", title="S", visibility="private"
    )
    monkeypatch.setattr(settings, "SHOW_PRIVATE", False)

    assert content.all_pages() == []
    with pytest.raises(Http404):
        content.load_page(index)


def test_the_search_finds_a_word_typed_without_its_accent(notes: Path) -> None:
    index = write_page(notes, "informatique/fiche/systeme", title="Le système")
    index.write_text(
        index.read_text(encoding="utf-8") + "\nUn système complet.\n", encoding="utf-8"
    )

    hits = content.search("systeme")

    assert [h.page.slug for h in hits] == ["systeme"]


def test_the_search_requires_every_term(notes: Path) -> None:
    write_page(notes, "informatique/fiche/a", title="Batterie et mesure")
    write_page(notes, "informatique/fiche/b", title="Batterie seule")

    assert [h.page.slug for h in content.search("batterie mesure")] == ["a"]


def test_a_path_escaping_the_tree_is_refused(notes: Path) -> None:
    with pytest.raises(Http404):
        content.safe_resolve("../../etc/passwd")


def test_folding_preserves_length(notes: Path) -> None:
    """The highlighter indexes the original with the folded string's offsets."""
    from avallon.web.content import _fold_text

    for text in ("système", "DÉCHARGE", "ça et là", "plain ascii", "Œuvre"):
        assert len(_fold_text(text)) == len(text), text


def test_folding_strips_accents_and_case(notes: Path) -> None:
    from avallon.web.content import _fold_text

    assert _fold_text("Système Déformé") == "systeme deforme"


def test_the_snippet_marks_the_term_in_its_original_spelling(notes: Path) -> None:
    index = write_page(notes, "informatique/fiche/systeme", title="Le système")
    index.write_text(
        index.read_text(encoding="utf-8") + "\nUn système complet.\n", encoding="utf-8"
    )

    (hit,) = content.search("systeme")

    assert "<mark>système</mark>" in hit.snippet
