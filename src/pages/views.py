import asyncio
import json
import re

import sync
from django.conf import settings
from django.http import (
    FileResponse,
    Http404,
    HttpResponsePermanentRedirect,
    HttpResponseRedirect,
    JsonResponse,
    StreamingHttpResponse,
)
from django.shortcuts import render
from django.views.decorators.http import require_POST

from . import content

# How often the stream re-checks the watched file's modification time (seconds).
POLL_INTERVAL = 0.3


def home(request):
    """Central page: lists every page in the content tree and exposes the
    facet values (domains, types, tags) used by the client-side filters. The
    full-text search box calls the `search` endpoint below."""
    pages = content.all_pages()
    return render(
        request,
        "home.html",
        {
            "pages": pages,
            "domains": sorted({p.domain for p in pages}),
            "types": sorted({p.type for p in pages}),
            "tags": sorted({t for p in pages for t in p.tags}),
        },
    )


def search(request):
    """JSON full-text search over the content tree (`?q=<query>`). Facet
    filtering is applied client-side on the returned results."""
    hits = content.search(request.GET.get("q", ""))
    return JsonResponse(
        {
            "results": [
                {
                    "url": h.page.url,
                    "title": h.page.title,
                    # Both forms travel: the bare names drive the facet filters
                    # client-side, the labels are what gets displayed.
                    "domain": h.page.domain,
                    "type": h.page.type,
                    "domain_label": h.page.domain_label,
                    "type_label": h.page.type_label,
                    "tags": h.page.tags,
                    "date": h.page.display_date,
                    "snippet": h.snippet,
                }
                for h in hits
            ]
        }
    )


def serve_content(request, relpath):
    """Resolve a hierarchical URL to either a Markdown page or a co-located
    asset (image, etc.) sitting next to it in the content tree."""
    target = content.safe_resolve(relpath)
    index_md = target / "index.md"

    if target.is_dir() and index_md.is_file():
        # Enforce a trailing slash so relative image paths in the Markdown
        # (e.g. `![](fig.png)`) resolve under this page's own URL.
        if not request.path.endswith("/"):
            return HttpResponsePermanentRedirect(request.path + "/")
        page = content.load_page(index_md)
        return render(
            request,
            "index.html",
            {
                "page": page,
                "content_html": content.render_markdown(index_md),
                "relpath": page.relpath,
                "reading_minutes": content.reading_minutes(index_md),
                "backlinks": content.backlinks(page),
            },
        )

    if target.is_file():
        # An asset sits next to the index.md that uses it, so it inherits that
        # page's visibility: serving figures from a hidden page would leak it.
        sibling = target.parent / "index.md"
        if sibling.is_file():
            content.load_page(sibling)  # raises Http404 when private
        return FileResponse(open(target, "rb"))

    raise Http404("Page introuvable")


def may_edit(request) -> bool:
    """Whether *request* is allowed to write to the content tree.

    Editing is currently open: the site has no authentication (see the README).
    Every write funnels through this one predicate, so putting the editor
    behind a login later is a change here rather than an audit of the views.
    """
    return True


def _editable_page(relpath: str):
    """Resolve *relpath* to an editable page, or raise Http404.

    Reuses the reader's checks on purpose: ``safe_resolve`` refuses paths that
    escape the content tree, and ``load_page`` refuses a page hidden by
    ``SHOW_PRIVATE``, so the editor cannot reach what the site will not serve.
    """
    index_md = content.safe_resolve(relpath) / "index.md"
    if not index_md.is_file():
        raise Http404("Page introuvable")
    content.load_page(index_md)
    return index_md


def _commit_page(relpath: str, action: str = "edit") -> bool:
    """Commit the saved page, then push in the background. Returns whether a
    commit was made.

    The commit is synchronous because it is local and instant, and because
    answering 200 before the write is recorded would be a lie. The push is
    detached: it is the slow, failure-prone half, and a save must not wait on
    the network.
    """
    content_dir = settings.CONTENT_DIR
    if not sync.is_repo_root(content_dir):
        return False  # not its own repo (dev fallback): saving stays unversioned
    committed, _ = sync.commit_scoped(
        content_dir, f"{action} {relpath}", window=sync.sync_window()
    )
    if committed:
        sync.spawn_flush(content_dir)
    return committed


def new_page(request):
    """Create a page from the browser: the form on GET, the page on POST.

    Domain and type are offered from taxonomy.toml only, so the web cannot
    create what `pixi run check-taxo` would then flag as out of vocabulary.
    """
    if not may_edit(request):
        raise Http404("Édition indisponible")

    vocab = content.vocabulary()
    form = {"domain": "", "type": "", "title": "", "tags": "", "summary": ""}
    error = ""

    if request.method == "POST":
        form = {k: request.POST.get(k, "").strip() for k in form}
        tags = [t for t in re.split(r"[,\n]+", form["tags"]) if t.strip()]
        try:
            page = content.create_page(
                form["domain"], form["type"], form["title"],
                [t.strip() for t in tags], form["summary"],
            )
        except content.InvalidPage as exc:
            error = str(exc)
        else:
            _commit_page(page.relpath, action="new")
            # Straight into the editor: a page created from the browser is
            # empty, so the next thing wanted is always to write in it.
            return HttpResponseRedirect(page.url + "#edit")

    return render(
        request,
        "new.html",
        {
            "domains": vocab["domains"],
            "types": vocab["types"],
            "form": form,
            "error": error,
        },
    )


def page_source(request):
    """Return a page's raw Markdown (`?path=<relpath>`), for the editor.

    The ``mtime`` travels with the text and must come back on save: it is what
    lets the server tell an ordinary write from one that would silently
    overwrite an edit made meanwhile in a local text editor.
    """
    if not may_edit(request):
        raise Http404("Édition indisponible")
    index_md = _editable_page(request.GET.get("path", ""))
    return JsonResponse(
        {"text": content.read_source(index_md), "mtime": content.page_mtime(index_md)}
    )


@require_POST
def save_page(request):
    """Write a page's Markdown back to disk, then commit it.

    Answers 409 when the file moved under the editor and 400 when the
    frontmatter would no longer parse, rather than saving something that
    breaks the page.
    """
    if not may_edit(request):
        raise Http404("Édition indisponible")
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Requête illisible."}, status=400)

    relpath = str(payload.get("path", ""))
    index_md = _editable_page(relpath)
    text = payload.get("text")
    if not isinstance(text, str):
        return JsonResponse({"error": "Contenu manquant."}, status=400)

    try:
        content.save_source(index_md, text, payload.get("mtime"))
    except content.InvalidFrontmatter as exc:
        return JsonResponse(
            {"error": f"Frontmatter invalide : {exc}"}, status=400
        )
    except content.StaleEdit:
        return JsonResponse(
            {
                "error": "Le fichier a changé sur le disque depuis l'ouverture "
                         "de l'éditeur. Recharge la page pour repartir de la "
                         "version courante.",
            },
            status=409,
        )

    committed = _commit_page(relpath)
    # Re-read *after* committing: the content repo's pre-commit hook stamps
    # `updated:` into the frontmatter, so the text and the mtime the editor
    # holds are already out of date by the time we answer.
    page = content.load_page(index_md)
    return JsonResponse(
        {
            "text": content.read_source(index_md),
            "mtime": content.page_mtime(index_md),
            "title": page.title,
            "committed": committed,
        }
    )


async def markdown_stream(request):
    """Server-Sent Events endpoint: watch one page's index.md mtime and push
    the freshly rendered HTML whenever it changes. The page to watch is given
    by `?path=<relpath>`, so live-reload works for any page. The browser swaps
    it into `.prose` in place, keeping scroll position and UI state."""
    target = content.safe_resolve(request.GET.get("path", ""))
    index_md = target / "index.md"
    if not index_md.is_file():
        raise Http404("Page introuvable")
    content.load_page(index_md)  # refuse to stream a page that is not visible

    async def event_stream():
        # When the client disconnects, the ASGI server closes this generator
        # (raising GeneratorExit here), so the loop ends on its own.
        last_mtime = None
        while True:
            try:
                mtime = index_md.stat().st_mtime
            except FileNotFoundError:
                mtime = None
            if mtime != last_mtime:
                last_mtime = mtime
                # Markdown rendering is CPU work; keep the event loop free.
                html = await asyncio.to_thread(content.render_markdown, index_md)
                # JSON-encode so the (multi-line) HTML fits a single SSE
                # `data:` line; the client JSON.parses it back.
                yield f"event: update\ndata: {json.dumps(html)}\n\n"
            await asyncio.sleep(POLL_INTERVAL)

    response = StreamingHttpResponse(
        event_stream(), content_type="text/event-stream"
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"  # disable proxy buffering (e.g. nginx)
    return response
