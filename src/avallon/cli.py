"""The `avallon` command: one entry point for the site and its notes.

There is no standalone CLI here, only the handful of operations a note site
needs around itself: run it, point it at a notes repository, scaffold and
re-file pages, sync, export. Each subcommand delegates to the module that
already implements it, so this file stays a dispatcher and never becomes a
second implementation.

Subcommands parse their own arguments (they each own an argparse parser, or a
positional grammar), so everything after the subcommand name is handed over
untouched.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

USAGE = """\
avallon <commande> [options]

  serve                 lancer le site
  init <chemin|url>     créer ou adopter un dépôt de notes, et l'activer
  repo [chemin]         afficher ou changer le dépôt actif
  new                   créer une page
  move                  reclasser une page sous un autre domaine/type
  sync                  pull, commit, push
  export                exporter une page en .docx ou .pdf
  add-domain <nom>      étendre le vocabulaire
  add-type <nom>        étendre le vocabulaire
  check                 vérifier que chaque page est dans le vocabulaire
  stamp                 compléter les dates manquantes du frontmatter
"""


def _serve(argv: Sequence[str]) -> int:
    """Run the ASGI server.

    Uvicorn rather than ``runserver``: the live-reload stream is a real SSE
    response, and the WSGI development server buffers it instead of streaming.
    """
    import uvicorn

    parser = argparse.ArgumentParser(prog="avallon serve")
    parser.add_argument("--host", default=os.environ.get("AVALLON_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("AVALLON_PORT", "8000"))
    )
    parser.add_argument(
        "--reload", action="store_true", help="recharger à chaque modification"
    )
    args = parser.parse_args(argv)

    # Watch the package itself rather than the working directory: it holds the
    # templates and the stylesheet as well as the code, and it is the same
    # place whether avallon runs from a checkout or from site-packages.
    package_dir = str(Path(__file__).resolve().parent)
    uvicorn.run(
        "avallon.settings.asgi:application",
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=[package_dir] if args.reload else None,
        reload_includes=["*.html", "*.css"] if args.reload else None,
    )
    return 0


def _django(command: list[str]) -> int:
    """Run a Django management command in-process."""
    from django.core.management import execute_from_command_line

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "avallon.settings.settings")
    execute_from_command_line(["avallon", *command])
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch to the subcommand named by the first argument."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help", "help"):
        print(USAGE, end="")
        return 0

    command, rest = args[0], args[1:]
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "avallon.settings.settings")

    if command == "serve":
        return _serve(rest)

    if command in ("init", "repo"):
        from avallon.notes import repo

        if command == "init":
            if not rest:
                sys.exit("usage : avallon init <chemin|url>")
            return repo.main(["init", *rest])
        return repo.main(["set", *rest] if rest else ["where"])

    if command == "new":
        from avallon.notes import scaffold

        sys.argv = ["avallon new", *rest]
        return scaffold.main()

    if command == "move":
        from avallon.notes import move

        sys.argv = ["avallon move", *rest]
        return move.main()

    if command == "sync":
        from avallon.notes import sync

        return sync.main(rest)

    if command == "stamp":
        from avallon.notes import stamp

        sys.argv = ["avallon stamp", *rest]
        return stamp.main()

    if command in ("add-domain", "add-type", "check"):
        from avallon.notes import taxonomy

        return taxonomy.main([command, *rest])

    if command == "export":
        return _django(["export", *rest])

    print(f"commande inconnue : {command}\n", file=sys.stderr)
    print(USAGE, end="", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
