"""Filing a document from the browser, which is the only way on a server."""

from __future__ import annotations

from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from avallon.web import content

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _post(client: Client, name: str, data: bytes, **extra: str):
    payload = {"domain": "administratif", "file": SimpleUploadedFile(name, data)}
    payload.update(extra)
    return client.post("/upload/", payload)


def test_a_file_becomes_a_page_that_holds_it(notes: Path) -> None:
    response = _post(Client(), "Carte Identité.png", PNG, title="Carte d'identité")

    assert response.status_code == 200
    page = content.load_page(notes / "administratif/doc/carte-d-identite/index.md")
    assert page.file == "carte-identite.png"
    assert page.kind == "image"
    assert (notes / "administratif/doc/carte-d-identite/carte-identite.png").is_file()


def test_the_answer_says_what_to_write_in_the_citing_note(notes: Path) -> None:
    body = _post(Client(), "facture.pdf", b"%PDF-1.4\n", title="Facture").json()

    assert body["snippet"] == "![[facture]]"
    assert body["url"] == "/administratif/doc/facture/"


def test_a_document_joins_a_dossier_like_any_page(notes: Path) -> None:
    _post(Client(), "piece.pdf", b"%PDF-1.4\n", title="Pièce", project="mon-dossier")

    page = content.load_page(notes / "administratif/doc/piece/index.md")
    assert page.project == "mon-dossier"


def test_a_type_this_site_cannot_hold_is_refused(notes: Path) -> None:
    """The allowlist is the set of kinds the site can classify; anything else
    it would neither display, nor filter, nor say a thing about."""
    response = _post(Client(), "installer.exe", b"MZ\x90\x00")

    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["error"]
    assert not (notes / "administratif/doc").exists()


def test_a_name_cannot_escape_its_directory(notes: Path) -> None:
    """The path components are dropped, not escaped: one segment comes out."""
    assert content.safe_filename("../../etc/passwd.png") == "passwd.png"
    assert content.safe_filename("a/b/Mon Scan (1).PDF") == "mon-scan-1.pdf"


def test_a_file_over_the_limit_is_refused(notes: Path) -> None:
    """Git keeps every version of a binary, so a big one is paid for forever."""
    with pytest.raises(content.RejectedUpload, match="too large"):
        content.create_document(
            "administratif",
            "doc",
            "Gros",
            "gros.pdf",
            b"0" * (content.UPLOAD_LIMIT + 1),
        )


def test_an_empty_file_is_refused(notes: Path) -> None:
    with pytest.raises(content.RejectedUpload, match="Empty"):
        content.create_document("administratif", "doc", "Vide", "vide.pdf", b"")


def test_a_name_already_borne_is_refused(notes: Path) -> None:
    _post(Client(), "facture.pdf", b"%PDF-1.4\n", title="Facture")

    response = _post(Client(), "facture.pdf", b"%PDF-1.4\n", title="Facture")

    assert response.status_code == 400
    assert "already goes by" in response.json()["error"]


def test_an_undeclared_domain_is_refused(notes: Path) -> None:
    response = Client().post(
        "/upload/",
        {"domain": "nexistepas", "file": SimpleUploadedFile("a.pdf", b"%PDF")},
    )

    assert response.status_code == 400


def test_the_creation_form_accepts_a_document(notes: Path) -> None:
    """Same form, same vocabulary: a file only changes what the page shows."""
    response = Client().post(
        "/nouvelle/",
        {
            "domain": "administratif",
            "type": "doc",
            "title": "Relevé de juin",
            "tags": "banque",
            "summary": "",
            "project": "",
            "file": SimpleUploadedFile("releve.pdf", b"%PDF-1.4\n"),
        },
    )

    assert response.status_code == 302
    # A document opens on itself: it already shows what was just filed.
    assert response["Location"] == "/administratif/doc/releve-de-juin/"
    page = content.load_page(notes / "administratif/doc/releve-de-juin/index.md")
    assert page.file == "releve.pdf"
    assert page.tags == ["banque"]


def test_the_form_without_a_file_still_makes_a_note(notes: Path) -> None:
    response = Client().post(
        "/nouvelle/",
        {
            "domain": "administratif",
            "type": "fiche",
            "title": "Une note",
            "tags": "",
            "summary": "",
            "project": "",
        },
    )

    assert response["Location"] == "/administratif/fiche/une-note/#edit"


def test_a_rejected_document_reports_on_the_form(notes: Path) -> None:
    """The form comes back with the reason, rather than a 500."""
    response = Client().post(
        "/nouvelle/",
        {
            "domain": "administratif",
            "type": "doc",
            "title": "Piégé",
            "tags": "",
            "summary": "",
            "project": "",
            "file": SimpleUploadedFile("x.exe", b"MZ"),
        },
    )

    assert response.status_code == 200
    assert "Unsupported file type" in response.content.decode()


def test_saved_markup_is_rendered_but_sandboxed(notes: Path) -> None:
    """A merchant's page kept as evidence is worth seeing, and is exactly the
    kind of file that carries scripts. The sandbox puts it in an opaque origin
    with scripts off: it draws as itself and can do nothing as this site."""
    from .conftest import write_page

    write_page(notes, "administratif/recueil/pieces", title="Pièces")
    (notes / "administratif/recueil/pieces/pj5b.html").write_text(
        "<script>alert(1)</script>", encoding="utf-8"
    )

    response = Client().get("/administratif/recueil/pieces/pj5b.html")

    assert response["Content-Security-Policy"] == "sandbox"
    assert response["Content-Disposition"].startswith("inline")
    assert response["X-Content-Type-Options"] == "nosniff"


def test_a_diagram_is_still_shown_rather_than_downloaded(notes: Path) -> None:
    """SVG is a kind these notes draw by hand; forcing a download would break
    every diagram to guard against a file one wrote oneself."""
    from .conftest import write_page

    write_page(notes, "informatique/fiche/schema", title="Schéma")
    (notes / "informatique/fiche/schema/onde.svg").write_text("<svg/>", "utf-8")

    response = Client().get("/informatique/fiche/schema/onde.svg")

    # FileResponse always sets the header; what matters is that it says inline.
    assert not response["Content-Disposition"].startswith("attachment")


def test_text_a_browser_would_not_render_is_declared_plain(notes: Path) -> None:
    """A .sh and a .py are text, but the type guessed from their extension is
    one no browser shows, so they downloaded while a .txt beside them opened."""
    from .conftest import write_page

    write_page(notes, "informatique/fiche/outils", title="Outils")
    for name in ("build.sh", "calc.py", "mail.eml"):
        (notes / "informatique/fiche/outils" / name).write_text("x", encoding="utf-8")

    for name in ("build.sh", "calc.py", "mail.eml"):
        response = Client().get(f"/informatique/fiche/outils/{name}")
        assert response["Content-Type"] == "text/plain; charset=utf-8", name
        assert response["Content-Disposition"].startswith("inline"), name


def test_a_pdf_is_left_to_the_browser_viewer(notes: Path) -> None:
    """It renders one natively, and text/plain would break that."""
    from .conftest import write_page

    write_page(notes, "informatique/fiche/doc", title="D")
    (notes / "informatique/fiche/doc/a.pdf").write_bytes(b"%PDF-1.4\n")

    response = Client().get("/informatique/fiche/doc/a.pdf")

    assert "text/plain" not in response["Content-Type"]
