"""Creating and re-filing pages: the rules that guard the tree."""

from __future__ import annotations

from pathlib import Path

import pytest

from avallon.web import content

from .conftest import write_page


def test_a_new_page_lands_under_its_taxonomy(notes: Path) -> None:
    page = content.create_page("informatique", "fiche", "Diagnostiquer un écran", [])

    assert page.relpath == "informatique/fiche/diagnostiquer-un-ecran"
    assert (notes / page.relpath / "index.md").is_file()


def test_a_new_page_carries_its_frontmatter(notes: Path) -> None:
    page = content.create_page(
        "informatique", "fiche", "Pixi", ["Python", "pixi"], "Une phrase.", "un-dossier"
    )
    text = (notes / page.relpath / "index.md").read_text(encoding="utf-8")

    assert "title: Pixi" in text
    assert "tags: [python, pixi]" in text  # normalized on the way in
    assert "summary: Une phrase." in text
    assert "project: un-dossier" in text


def test_a_page_without_a_dossier_has_no_project_field(notes: Path) -> None:
    page = content.create_page("informatique", "fiche", "Seule", [])
    text = (notes / page.relpath / "index.md").read_text(encoding="utf-8")

    assert "project:" not in text


def test_an_undeclared_domain_or_type_is_refused(notes: Path) -> None:
    with pytest.raises(content.InvalidPage):
        content.create_page("inexistant", "fiche", "Titre", [])
    with pytest.raises(content.InvalidPage):
        content.create_page("informatique", "chantier", "Titre", [])


def test_an_empty_title_is_refused(notes: Path) -> None:
    with pytest.raises(content.InvalidPage):
        content.create_page("informatique", "fiche", "   ", [])


def test_a_taken_slug_gets_a_suffix_rather_than_an_overwrite(notes: Path) -> None:
    first = content.create_page("informatique", "fiche", "Pixi", [])
    second = content.create_page("informatique", "fiche", "Pixi", [])

    assert first.slug == "pixi"
    assert second.slug == "pixi-2"


def test_moving_a_page_keeps_its_slug_and_its_assets(notes: Path) -> None:
    write_page(notes, "informatique/fiche/note", title="Note")
    (notes / "informatique/fiche/note/figure.png").write_bytes(b"png")

    moved = content.move_page("informatique/fiche/note", "administratif", "cr")

    assert moved.relpath == "administratif/cr/note"
    assert (notes / "administratif/cr/note/figure.png").is_file()
    assert not (notes / "informatique/fiche/note").exists()


def test_moving_onto_a_taken_slug_is_refused(notes: Path) -> None:
    write_page(notes, "informatique/fiche/note", title="Note")
    write_page(notes, "administratif/cr/note", title="Autre note")

    with pytest.raises(content.InvalidPage):
        content.move_page("informatique/fiche/note", "administratif", "cr")


def test_moving_a_page_nowhere_is_refused(notes: Path) -> None:
    write_page(notes, "informatique/fiche/note", title="Note")

    with pytest.raises(content.InvalidPage):
        content.move_page("informatique/fiche/note", "informatique", "fiche")
