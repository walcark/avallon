"""Files promoted to pages: the derived kind, the viewer, the grid."""

from __future__ import annotations

from pathlib import Path

import pytest

from avallon.notes import add_file
from avallon.web import content

from .conftest import write_page


@pytest.mark.parametrize(
    ("filename", "kind"),
    [
        ("scan.png", "image"),
        ("photo.JPG", "image"),
        ("contrat.pdf", "pdf"),
        ("notes.txt", "text"),
        ("budget.xlsx", "office"),
        ("archive.zip", "archive"),
        ("firmware.bin", "other"),
    ],
)
def test_the_kind_is_derived_from_the_extension(
    notes: Path, filename: str, kind: str
) -> None:
    index = write_page(notes, "administratif/fiche/doc", title="D", file=filename)

    assert content.load_page(index).kind == kind


def test_a_page_without_a_file_is_a_note(notes: Path) -> None:
    index = write_page(notes, "administratif/fiche/note", title="N")

    page = content.load_page(index)
    assert page.kind == "note"
    assert not page.is_visual


def test_the_file_url_sits_next_to_the_page(notes: Path) -> None:
    index = write_page(notes, "administratif/fiche/doc", title="D", file="scan.png")

    assert content.load_page(index).file_url == "/administratif/fiche/doc/scan.png"


def test_kind_is_a_facet_only_when_it_divides(notes: Path) -> None:
    write_page(notes, "administratif/fiche/a", title="A", file="a.png")
    write_page(notes, "administratif/fiche/b", title="B", file="b.png")

    assert content.select().facets["kind"] == []

    write_page(notes, "administratif/fiche/c", title="C")
    kinds = dict(content.select().facets["kind"])
    assert kinds == {"image": 2, "note": 1}


def test_adding_a_file_moves_it_into_its_own_page(notes: Path, tmp_path: Path) -> None:
    source = tmp_path / "carte.png"
    source.write_bytes(b"png")

    target = add_file.add_file(
        source, "administratif", "fiche", "Carte d'identité", ["identité"]
    )

    assert not source.exists()  # moved, so there is one copy and one truth
    assert (target / "carte.png").is_file()
    page = content.load_page(target / "index.md")
    assert page.title == "Carte d'identité"
    assert page.kind == "image"
    assert page.tags == ["identité"]


def test_adding_a_file_can_copy_instead(notes: Path, tmp_path: Path) -> None:
    source = tmp_path / "carte.png"
    source.write_bytes(b"png")

    add_file.add_file(source, "administratif", "fiche", "Carte", [], copy=True)

    assert source.exists()


def test_the_document_date_is_kept_apart_from_the_filing_date(
    notes: Path, tmp_path: Path
) -> None:
    """What one looks for is the date of the document, not the day it was filed."""
    source = tmp_path / "passeport.pdf"
    source.write_bytes(b"%PDF-1.4")

    target = add_file.add_file(
        source, "administratif", "fiche", "Passeport", [], doc_date="2019-03-14"
    )

    text = (target / "index.md").read_text(encoding="utf-8")
    assert "doc_date: 2019-03-14" in text
    assert "date: 2019-03-14" not in text.replace("doc_date: 2019-03-14", "")
