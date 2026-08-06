"""Aliases: a page keeps answering to the names it used to have."""

from __future__ import annotations

from pathlib import Path

from avallon.web import content
from avallon.web.mdx.wikilinks import resolves_to

from .conftest import write_page


def test_a_page_answers_to_its_alias(notes: Path) -> None:
    index = write_page(
        notes,
        "informatique/fiche/nouveau-titre",
        title="Nouveau titre",
        aliases="[ancien-slug, \"Ancien titre\"]",
    )
    page = content.load_page(index)

    for form in ("nouveau-titre", "Nouveau titre", "ancien-slug", "Ancien titre"):
        assert resolves_to(form, page.slug, page.relpath, page.aliases), form


def test_an_alias_matches_however_it_is_written(notes: Path) -> None:
    """Same rule as titles: the link reads like prose, not like a folder name."""
    index = write_page(
        notes, "informatique/fiche/p", title="P", aliases="[\"Ancien Titre\"]"
    )
    page = content.load_page(index)

    assert resolves_to("ancien titre", page.slug, page.relpath, page.aliases)
    assert resolves_to("ancien-titre", page.slug, page.relpath, page.aliases)


def test_a_link_to_an_old_title_still_renders(notes: Path) -> None:
    write_page(
        notes, "informatique/fiche/cible", title="Titre actuel",
        aliases="[\"Titre d'avant\"]",
    )
    source = write_page(notes, "informatique/cr/source", title="Source")
    source.write_text(
        source.read_text(encoding="utf-8") + "\nVoir [[Titre d'avant]].\n",
        encoding="utf-8",
    )

    html = content.render_markdown(source)

    assert 'href="/informatique/fiche/cible/"' in html
    assert "wikilink-missing" not in html


def test_a_backlink_follows_an_alias(notes: Path) -> None:
    """Otherwise a renamed page loses the trace of what cites it."""
    target = write_page(
        notes, "informatique/fiche/cible", title="Cible", aliases="[vieux-nom]"
    )
    source = write_page(notes, "informatique/cr/source", title="Source")
    source.write_text(
        source.read_text(encoding="utf-8") + "\n[[vieux-nom]]\n", encoding="utf-8"
    )

    assert [p.slug for p in content.backlinks(content.load_page(target))] == ["source"]


def test_a_dossier_keeps_its_members_after_a_rename(notes: Path) -> None:
    write_page(
        notes, "administratif/recueil/dossier", title="Dossier",
        aliases="[ancien-dossier]",
    )
    write_page(
        notes, "administratif/cr/piece", title="Pièce", project="ancien-dossier"
    )

    index = content.load_page(notes / "administratif/recueil/dossier/index.md")
    assert [p.slug for p in content.project_members(index)] == ["piece"]


def test_a_page_without_aliases_is_unaffected(notes: Path) -> None:
    index = write_page(notes, "informatique/fiche/simple", title="Simple")
    page = content.load_page(index)

    assert page.aliases == []
    assert not resolves_to("autre-chose", page.slug, page.relpath, page.aliases)
