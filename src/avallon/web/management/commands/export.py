"""Management command: export a note to Word or PDF.

    python manage.py export <relpath> [-o out] [--pdf] [--reference ref.docx]

Kept as a command (not a stdlib script) so it runs inside Django, reusing the
site's own renderer and taxonomy rather than a second implementation.
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.http import Http404
from pages import content, exporter


class Command(BaseCommand):
    help = "Exporter une note en Word (.docx) ou en PDF."

    def add_arguments(self, parser):
        parser.add_argument("relpath", help="note, <domaine>/<type>/<slug>")
        parser.add_argument("-o", "--output", help="fichier de sortie")
        parser.add_argument(
            "-f",
            "--format",
            choices=("docx", "pdf"),
            default="docx",
            help="output format (default: docx)",
        )
        parser.add_argument(
            "--pdf", action="store_true", help="raccourci pour --format pdf"
        )
        parser.add_argument("--reference", help="reference.docx (styles) to use")

    def handle(self, *args, **opts):
        relpath = opts["relpath"].strip("/")
        try:
            index_md = content.safe_resolve(relpath) / "index.md"
        except Http404 as exc:
            raise CommandError(str(exc)) from exc
        if not index_md.is_file():
            raise CommandError(f"Page not found: {relpath}")

        page = content.load_page(index_md)
        fmt = "pdf" if opts["pdf"] else opts["format"]
        out = Path(opts["output"]) if opts["output"] else Path(f"{page.slug}.{fmt}")

        try:
            if fmt == "pdf":
                exporter.export_pdf(index_md, out, opts.get("reference"))
            else:
                exporter.export_docx(index_md, out, opts.get("reference"))
        except exporter.ExportError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(f"Écrit : {out}"))
