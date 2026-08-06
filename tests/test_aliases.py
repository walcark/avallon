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
        aliases='[ancien-slug, "Ancien titre"]',
    )
    page = content.load_page(index)

    for form in ("nouveau-titre", "Nouveau titre", "ancien-slug", "Ancien titre"):
        assert resolves_to(form, page.slug, page.relpath, page.aliases), form


def test_an_alias_matches_however_it_is_written(notes: Path) -> None:
    """Same rule as titles: the link reads like prose, not like a folder name."""
    index = write_page(
        notes, "informatique/fiche/p", title="P", aliases='["Ancien Titre"]'
    )
    page = content.load_page(index)

    assert resolves_to("ancien titre", page.slug, page.relpath, page.aliases)
    assert resolves_to("ancien-titre", page.slug, page.relpath, page.aliases)


def test_a_link_to_an_old_title_still_renders(notes: Path) -> None:
    write_page(
        notes,
        "informatique/fiche/cible",
        title="Titre actuel",
        aliases='["Titre d\'avant"]',
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
        notes,
        "administratif/recueil/dossier",
        title="Dossier",
        aliases="[ancien-dossier]",
    )
    write_page(notes, "administratif/cr/piece", title="Pièce", project="ancien-dossier")

    index = content.load_page(notes / "administratif/recueil/dossier/index.md")
    assert [p.slug for p in content.project_members(index)] == ["piece"]


def test_a_page_without_aliases_is_unaffected(notes: Path) -> None:
    index = write_page(notes, "informatique/fiche/simple", title="Simple")
    page = content.load_page(index)

    assert page.aliases == []
    assert not resolves_to("autre-chose", page.slug, page.relpath, page.aliases)


def test_changing_a_title_records_the_old_one(notes: Path) -> None:
    """The moment a title stops being the title is when the alias must appear."""
    from django.test import Client

    write_page(notes, "informatique/fiche/p", title="Ancien titre")
    body = "---\ntitle: Nouveau titre\ndate: 2026-01-01\n---\n\nDu texte.\n"

    response = Client().post(
        "/save/",
        data='{"path": "informatique/fiche/p", "text": %s}'
        % __import__("json").dumps(body),
        content_type="application/json",
    )

    assert response.status_code == 200
    page = content.load_page(notes / "informatique/fiche/p/index.md")
    assert page.title == "Nouveau titre"
    assert page.aliases == ["Ancien titre"]


def test_saving_without_a_title_change_adds_nothing(notes: Path) -> None:
    from django.test import Client

    write_page(notes, "informatique/fiche/p", title="Stable")
    body = "---\ntitle: Stable\ndate: 2026-01-01\n---\n\nAutre texte.\n"

    Client().post(
        "/save/",
        data='{"path": "informatique/fiche/p", "text": %s}'
        % __import__("json").dumps(body),
        content_type="application/json",
    )

    assert content.load_page(notes / "informatique/fiche/p/index.md").aliases == []


def test_the_frontmatter_keeps_its_shape(notes: Path) -> None:
    """A YAML round-trip would reorder and requote what was written by hand."""
    text = (
        "---\ntitle: T\ndate: 2026-01-01\ntags: [a, b]\n"
        'summary: "Une phrase."\n---\n\nCorps.\n'
    )

    out = content.add_alias(text, "vieux")

    assert 'summary: "Une phrase."' in out
    assert "tags: [a, b]" in out
    assert out.index("date:") < out.index("tags:")


def test_renaming_keeps_both_former_names(notes: Path) -> None:
    """The slug and the title both stop being current at the same instant."""
    from avallon.notes import rename

    write_page(notes, "informatique/fiche/ancien-titre", title="Ancien titre")

    target = rename.rename("informatique/fiche/ancien-titre", "Nouveau titre")

    assert target.name == "nouveau-titre"
    page = content.load_page(target / "index.md")
    assert page.title == "Nouveau titre"
    assert set(page.aliases) == {"Ancien titre", "ancien-titre"}


def test_links_to_a_renamed_page_still_resolve(notes: Path) -> None:
    from avallon.notes import rename

    write_page(notes, "informatique/fiche/ancien-titre", title="Ancien titre")
    source = write_page(notes, "informatique/cr/source", title="Source")
    source.write_text(
        source.read_text(encoding="utf-8") + "\n[[ancien-titre]] et [[Ancien titre]]\n",
        encoding="utf-8",
    )

    rename.rename("informatique/fiche/ancien-titre", "Nouveau titre")

    html = content.render_markdown(source)
    assert html.count('href="/informatique/fiche/nouveau-titre/"') == 2
    assert "wikilink-missing" not in html


def test_renaming_onto_a_taken_slug_is_refused(notes: Path) -> None:
    import pytest

    from avallon.notes import rename

    write_page(notes, "informatique/fiche/a", title="A")
    write_page(notes, "informatique/fiche/b", title="B")

    with pytest.raises(SystemExit):
        rename.rename("informatique/fiche/a", "B")
