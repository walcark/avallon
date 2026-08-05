r"""Export a note to a styled Word document (and optionally a PDF).

The site already renders each note to clean HTML; exporting reuses that render
in *export mode* (plots become self-contained images, the gallery becomes plain
figures, see :mod:`pages.mdx.fences`) and hands the HTML to Pandoc::

    HTML  --pandoc-->  .docx        (styles from a reference document)
          --libreoffice-->  .pdf

Math survives as native Word equations (Pandoc reads the ``\(...\)`` arithmatex
emits), and a Lua filter maps the site's semantic classes (colors, admonitions)
onto the reference document's named styles, so the company template drives the
look. The reference document is built by ``scripts/make_reference_docx.py``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import content

_HERE = Path(__file__).resolve().parent
LUA_FILTER = _HERE / "word_styles.lua"
DEFAULT_REFERENCE = _HERE / "exporter_data" / "reference-entreprise.docx"


class ExportError(RuntimeError):
    """A document conversion (Pandoc or LibreOffice) failed."""


def export_docx(
    index_md: Path, out_path: Path, reference: Path | str | None = None
) -> Path:
    """Render *index_md* to a Word document at *out_path*.

    Parameters
    ----------
    index_md : pathlib.Path
        The note's ``index.md``.
    out_path : pathlib.Path
        Destination ``.docx``.
    reference : pathlib.Path or str, optional
        Reference document whose named styles are applied. Defaults to the
        bundled company template.

    Returns
    -------
    pathlib.Path
        *out_path*.

    Raises
    ------
    ExportError
        Pandoc is missing or returns an error.
    """
    page = content.load_page(index_md)
    reference = Path(reference) if reference else DEFAULT_REFERENCE
    out_path = Path(out_path)
    note_dir = index_md.parent

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        ctx = content.ExportContext(assets_dir=tmp)
        html = content.render_markdown(index_md, export=ctx)
        src = tmp / "doc.html"
        src.write_text(html, encoding="utf-8")

        cmd = [
            "pandoc",
            "--from",
            "html+tex_math_single_backslash",
            str(src),
            "--lua-filter",
            str(LUA_FILTER),
            "--reference-doc",
            str(reference),
            # Bare filenames in the HTML resolve either next to the note
            # (co-located images) or in the temp dir (generated plot SVGs).
            "--resource-path",
            os.pathsep.join([str(note_dir), str(tmp)]),
            "--metadata",
            f"title={page.title}",
            "--output",
            str(out_path),
        ]
        _run(cmd, "Pandoc")
    return out_path


def export_pdf(
    index_md: Path, out_path: Path, reference: Path | str | None = None
) -> Path:
    """Render *index_md* to a PDF, via a styled ``.docx`` then LibreOffice.

    Going through the Word document keeps the PDF on exactly the same company
    styles, using the LibreOffice already present rather than a second engine.
    """
    out_path = Path(out_path)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        docx = tmp / "doc.docx"
        export_docx(index_md, docx, reference)
        cmd = [
            "libreoffice",
            # A private profile dir avoids clashing with a desktop session.
            "-env:UserInstallation=file://" + str(tmp / "lo-profile"),
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(tmp),
            str(docx),
        ]
        _run(cmd, "LibreOffice", timeout=180)
        produced = tmp / "doc.pdf"
        if not produced.is_file():
            raise ExportError("LibreOffice n'a pas produit de PDF.")
        shutil.move(str(produced), str(out_path))
    return out_path


def _run(cmd: list[str], tool: str, timeout: int | None = None) -> None:
    """Run *cmd*, raising :class:`ExportError` with the tool's stderr on failure."""
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise ExportError(f"{tool} introuvable.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ExportError(f"{tool} a dépassé le délai.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip().splitlines()
        raise ExportError(f"{tool} a échoué : {detail[-1] if detail else '?'}") from exc
