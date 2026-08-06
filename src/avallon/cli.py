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
  setup                 écrire le fichier d'environnement (adresse, jeton)
  install               installer et démarrer l'unité systemd utilisateur
"""


def _is_loopback(host: str) -> bool:
    """Whether *host* can only be reached from this machine."""
    import ipaddress

    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


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

    # The guard is a no-op without a token, which only holds on loopback. Any
    # other bind reaches other machines, so refuse rather than serve the notes
    # to whoever finds the port.
    if not _is_loopback(args.host) and not os.environ.get("AVALLON_TOKEN", "").strip():
        sys.exit(
            f"Refus de servir sur {args.host} sans jeton d'accès.\n"
            "  AVALLON_TOKEN=$(openssl rand -hex 32) avallon serve --host "
            f"{args.host}\n"
            "  (ou `avallon setup`, qui en génère un et l'écrit dans le fichier "
            "d'environnement)"
        )

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


def _setup(argv: Sequence[str]) -> int:
    """Write the environment file a deployment reads: address, port, token."""
    from avallon import deploy
    from avallon.notes import config

    parser = argparse.ArgumentParser(prog="avallon setup")
    parser.add_argument("--host", default="127.0.0.1", help="adresse d'écoute")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--token", default="", help="jeton d'accès (généré par défaut)")
    args = parser.parse_args(argv)

    token = args.token or deploy.generate_token()
    try:
        content_dir = config.resolve_content_dir()
    except config.NotConfigured:
        content_dir = None

    path = deploy.write_env(
        deploy.env_file_path(),
        deploy.render_env(args.host, args.port, token, content_dir),
    )
    print(f"✓ environnement écrit : {path}  (0600)")
    print(f"  - écoute      : {args.host}:{args.port}")
    print(f"  - jeton       : {token}")
    if content_dir is None:
        print("  ! aucun dépôt de notes : lance `avallon init <chemin|url>`")
    print("  → `avallon install` pour l'unité systemd")
    return 0


def _install(argv: Sequence[str]) -> int:
    """Install and start the systemd user unit."""
    from avallon import deploy

    parser = argparse.ArgumentParser(prog="avallon install")
    parser.add_argument(
        "--no-start", action="store_true", help="installer sans démarrer"
    )
    args = parser.parse_args(argv)

    env_path = deploy.env_file_path()
    if not env_path.exists():
        sys.exit(f"Aucun environnement en {env_path} : lance d'abord `avallon setup`")

    unit = deploy.write_unit(env_path)
    print(f"✓ unité écrite : {unit}")
    if args.no_start:
        return 0

    deploy.systemctl("daemon-reload")
    result = deploy.systemctl("enable", "--now", deploy.UNIT_NAME)
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        return 1
    print(f"✓ service démarré : systemctl --user status {deploy.UNIT_NAME}")
    # Without lingering, a user unit stops at logout, which is exactly when a
    # server is expected to keep running.
    print("  ↳ `loginctl enable-linger $USER` pour qu'il survive à la déconnexion")
    return 0


def _django(command: list[str]) -> int:
    """Run a Django management command in-process."""
    from django.core.management import execute_from_command_line

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "avallon.settings.settings")
    execute_from_command_line(["avallon", *command])
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch to the subcommand named by the first argument."""
    from avallon.notes.config import NotConfigured

    try:
        return _dispatch(list(sys.argv[1:] if argv is None else argv))
    except NotConfigured as exc:
        # Reaching the notes without having chosen them is an ordinary mistake,
        # not a crash: say what to run, not where the exception came from.
        sys.exit(str(exc))


def _dispatch(args: list[str]) -> int:
    """Route *args* to the module implementing the subcommand."""
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

    if command == "setup":
        return _setup(rest)

    if command == "install":
        return _install(rest)

    if command == "export":
        return _django(["export", *rest])

    print(f"commande inconnue : {command}\n", file=sys.stderr)
    print(USAGE, end="", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
