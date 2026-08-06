"""`![[…]]`: showing a document instead of copying it."""

from __future__ import annotations

from pathlib import Path

from avallon.web import content

from .conftest import write_page


def render(notes: Path, body: str) -> str:
    """Render *body* as the body of a page, and return the HTML."""
    index = write_page(notes, "informatique/fiche/hote", title="Hôte")
    index.write_text(
        index.read_text(encoding="utf-8") + "\n" + body + "\n", encoding="utf-8"
    )
    return content.render_markdown(index)


def test_an_embedded_image_is_shown_from_its_own_page(notes: Path) -> None:
    """One copy: the file stays in the document, the note shows a view of it."""
    write_page(notes, "administratif/fiche/carte", title="Carte", file="carte.png")

    html = render(notes, "![[carte]]")

    assert 'src="/administratif/fiche/carte/carte.png"' in html
    assert 'href="/administratif/fiche/carte/"' in html  # click goes to the doc
    assert "<figcaption>Carte</figcaption>" in html


def test_an_embed_can_be_captioned(notes: Path) -> None:
    write_page(notes, "administratif/fiche/carte", title="Carte", file="carte.png")

    html = render(notes, "![[carte|Recto de la carte]]")

    assert "<figcaption>Recto de la carte</figcaption>" in html


def test_an_embed_can_pick_one_file_of_a_document(notes: Path) -> None:
    write_page(notes, "administratif/fiche/carte", title="Carte", file="recto.png")

    html = render(notes, "![[carte/verso.png]]")

    assert 'src="/administratif/fiche/carte/verso.png"' in html


def test_a_non_image_is_announced_rather_than_shown(notes: Path) -> None:
    """A viewer inside a paragraph would take over the note it illustrates."""
    write_page(notes, "administratif/fiche/facture", title="Facture", file="f.pdf")

    html = render(notes, "![[facture]]")

    assert "<img" not in html
    assert 'class="embed-file"' in html
    assert "Facture" in html


def test_a_missing_embed_is_flagged_not_dropped(notes: Path) -> None:
    html = render(notes, "![[inexistant]]")

    assert "wikilink-missing" in html
    assert "inexistant" in html


def test_a_plain_wikilink_still_links(notes: Path) -> None:
    """The embed must not swallow the link syntax it sits next to."""
    write_page(notes, "administratif/fiche/carte", title="Carte", file="carte.png")

    html = render(notes, "Voir [[carte]] pour le détail.")

    assert "<figure" not in html
    assert 'href="/administratif/fiche/carte/"' in html
