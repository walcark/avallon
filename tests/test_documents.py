"""Documents: files beside a page, and files promoted to pages of their own."""

from __future__ import annotations

from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

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


def test_a_query_can_render_as_a_gallery(notes: Path) -> None:
    """A collection of scans is recognized by its thumbnails, not by titles."""
    from avallon.web.mdx import fences

    write_page(
        notes, "administratif/fiche/a", title="Carte", file="a.png", tags="[identité]"
    )
    write_page(
        notes,
        "administratif/fiche/b",
        title="Passeport",
        file="b.pdf",
        tags="[identité]",
    )

    html = fences.query_fence("tag: identité\nas: gallery", None, "", {}, None)

    assert 'class="tiles"' in html
    assert "/administratif/fiche/a/a.png" in html  # the image itself
    assert "/thumb/administratif/fiche/b/" in html  # the PDF's first page


def test_a_query_can_render_as_a_list(notes: Path) -> None:
    from avallon.web.mdx import fences

    write_page(
        notes,
        "administratif/fiche/a",
        title="Carte",
        tags="[identité]",
        summary="Recto verso.",
    )

    html = fences.query_fence("tag: identité\nas: list", None, "", {}, None)

    assert 'class="query-list"' in html
    assert "Recto verso." in html


def test_a_query_still_defaults_to_a_table(notes: Path) -> None:
    from avallon.web.mdx import fences

    write_page(notes, "administratif/fiche/a", title="Carte", tags="[identité]")

    html = fences.query_fence("tag: identité", None, "", {}, None)

    assert "query-table" in html or "<table" in html


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture
def tree(notes: Path) -> Path:
    page = write_page(
        notes,
        "science/cr/reunion",
        title="Réunion",
        tags="[hygeos]",
        project="mon-dossier",
    )
    directory = page.parent
    (directory / "flux.png").write_bytes(PNG)
    (directory / "alis-2019.pdf").write_bytes(b"%PDF-1.4\n")
    # What a note works with rather than what it shows: never a document.
    (directory / "data").mkdir()
    (directory / "data" / "grid.nc").write_bytes(b"\x89HDF")
    (directory / "notes.pyc").write_bytes(b"\x00")
    return notes


def test_files_beside_a_page_are_documents(tree: Path) -> None:
    assert sorted(a.file for a in content.all_assets()) == [
        "alis-2019.pdf",
        "flux.png",
    ]


def test_a_subdirectory_is_where_a_note_keeps_what_it_uses(tree: Path) -> None:
    """`data/` and `__pycache__/` hold working files, not documents."""
    assert not any("grid.nc" in a.file for a in content.all_assets())


def test_an_unknown_extension_is_not_a_document(tree: Path) -> None:
    assert not any(a.file.endswith(".pyc") for a in content.all_assets())


def test_a_document_inherits_the_folder_it_sits_in(tree: Path) -> None:
    """This is what "identify a document by its dossier" means."""
    doc = next(a for a in content.all_assets() if a.file == "flux.png")

    assert (doc.domain, doc.type) == ("science", "cr")
    assert doc.tags == ["hygeos"]
    assert doc.project == "mon-dossier"


def test_a_document_leads_to_itself(tree: Path) -> None:
    """The click this removes: a result opens the file, not a page about it."""
    doc = next(a for a in content.all_assets() if a.file == "flux.png")

    assert doc.url == "/science/cr/reunion/flux.png"
    assert doc.kind == "image"


def test_the_kind_facet_offers_documents_from_the_start(tree: Path) -> None:
    """It is the switch that reveals them, so it cannot be derived from a
    selection that excludes them, or it would hide the door behind itself."""
    facet = dict(content.select().facets["kind"])

    assert facet["image"] == 1 and facet["pdf"] == 1 and facet["note"] == 1


def test_documents_stay_out_of_the_default_listing(tree: Path) -> None:
    """44 pages under every figure they contain is not a home page."""
    assert [p.relpath for p in content.select().pages] == ["science/cr/reunion"]


def test_asking_for_a_kind_brings_them_in(tree: Path) -> None:
    selected = content.select(kinds=["image"])

    assert [p.url for p in selected.pages] == ["/science/cr/reunion/flux.png"]


def test_a_document_is_found_by_its_name(tree: Path) -> None:
    """The story that started this: the file existed and was unfindable."""
    found = content.search_assets("alis")

    assert [a.file for a in found] == ["alis-2019.pdf"]


def test_a_document_is_not_found_by_its_page_body(tree: Path) -> None:
    """Or a compte rendu with four figures answers any word it contains, four
    times over."""
    assert content.search_assets("texte") == []


def test_uploading_beside_a_page_creates_no_page(tree: Path) -> None:
    response = Client().post(
        "/upload/",
        {
            "beside": "science/cr/reunion",
            "file": SimpleUploadedFile("Capture Écran.png", PNG),
        },
    )

    assert response.json()["snippet"] == "![](capture-ecran.png)"
    assert (tree / "science/cr/reunion/capture-ecran.png").is_file()
    assert not (tree / "science/doc").exists()


def test_a_pdf_is_linked_rather_than_shown(tree: Path) -> None:
    """Rendered inline it would take the note over."""
    response = Client().post(
        "/upload/",
        {"beside": "science/cr/reunion", "file": SimpleUploadedFile("p.pdf", b"%PDF")},
    )

    assert response.json()["snippet"] == "[[p.pdf]]"


def test_a_second_file_of_the_same_name_never_overwrites(tree: Path) -> None:
    """Two screenshots pasted a minute apart must not replace one another."""
    for _ in range(2):
        Client().post(
            "/upload/",
            {"beside": "science/cr/reunion", "file": SimpleUploadedFile("s.png", PNG)},
        )

    assert (tree / "science/cr/reunion/s.png").is_file()
    assert (tree / "science/cr/reunion/s-2.png").is_file()
