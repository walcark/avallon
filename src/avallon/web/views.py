import asyncio
import json
import re
import tempfile
from pathlib import Path

from django.conf import settings
from django.http import (
    FileResponse,
    Http404,
    HttpResponse,
    HttpResponsePermanentRedirect,
    HttpResponseRedirect,
    JsonResponse,
    StreamingHttpResponse,
)
from django.shortcuts import render
from django.views.decorators.http import require_POST

from avallon.notes import sync

from . import content, exporter, security

# How often the stream re-checks the watched file's modification time (seconds).
POLL_INTERVAL = 0.3


def home(request):
    """Central page: lists every page in the content tree and exposes the
    facet values (domains, types, projects, statuses, tags) used by the
    client-side filters. The full-text search box calls the `search` endpoint
    below.

    Each card carries the project it belongs to, so a title written inside a
    project ("Mail retour") still says which dossier it comes from once it is
    read out of context.
    """
    pages = content.all_pages()
    projects = content.all_projects()
    membership = content.membership()
    return render(
        request,
        "home.html",
        {
            "cards": [{"page": p, "project": membership.get(p.relpath)} for p in pages],
            "domains": sorted({p.domain for p in pages}),
            "types": sorted({p.type for p in pages}),
            "projects": projects,
            "statuses": [
                s for s in content.STATUSES if any(p.status == s for p in pages)
            ],
            # Only tags that group several pages: see content.facet_tags.
            "tags": content.facet_tags(pages),
        },
    )


def search(request):
    """JSON full-text search over the content tree (`?q=<query>`). Facet
    filtering is applied client-side on the returned results."""
    hits = content.search(request.GET.get("q", ""))
    projects = content.membership()
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
                    "status": h.page.status,
                    # Slug for the facet, title to show the dossier a page
                    # named "Mail retour" comes from.
                    "project": projects[h.page.relpath].slug
                    if h.page.relpath in projects
                    else "",
                    "project_title": projects[h.page.relpath].title
                    if h.page.relpath in projects
                    else "",
                }
                for h in hits
            ]
        }
    )


def manifest(request):
    """The web app manifest, rendered so its name follows the language."""
    return render(
        request,
        "manifest.webmanifest",
        {
            # Matches the stylesheet's --bg / --accent in the light theme, so
            # the splash screen does not flash a different colour.
            "background": "#faf9f6",
            "theme": "#2a5d8f",
        },
        content_type="application/manifest+json",
    )


def service_worker(request):
    """Serve the worker from the root.

    A worker only controls what sits under its own URL, so one served from
    /static/ would control /static/ and nothing else.
    """
    path = Path(__file__).resolve().parent / "static" / "avallon" / "pwa" / "sw.js"
    return FileResponse(
        open(path, "rb"),
        content_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
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
        vocab = content.vocabulary()
        return render(
            request,
            "index.html",
            {
                "page": page,
                "content_html": content.render_markdown(index_md),
                "relpath": page.relpath,
                "reading_minutes": content.reading_minutes(index_md),
                "backlinks": content.backlinks(page),
                # The dossier this page belongs to: `project` names it above
                # the title, `dossier` is what the sidebar browses. Both are
                # derived from the pages themselves, so a dossier's contents
                # can never fall behind.
                "project": content.project_of(page),
                "dossier": content.dossier_nav(page),
                # Destinations offered by the "move" control in the editor:
                # exactly the declared taxonomy, like the creation form.
                "domains": vocab["domains"],
                "types": vocab["types"],
            },
        )

    if target.is_file():
        # An asset sits next to the index.md that uses it, so it inherits that
        # page's visibility: serving figures from a hidden page would leak it.
        sibling = target.parent / "index.md"
        if sibling.is_file():
            content.load_page(sibling)  # raises Http404 when private
        return FileResponse(open(target, "rb"))

    raise Http404("Page not found")


def may_edit(request) -> bool:
    """Whether *request* is allowed to write to the content tree.

    Every write funnels through this one predicate. Reading is already gated by
    the middleware, so this is the same answer for now; keeping it separate is
    what will allow a read-only session later without auditing every view.
    """
    return security.is_unlocked(request)


def _editable_page(relpath: str):
    """Resolve *relpath* to an editable page, or raise Http404.

    Reuses the reader's checks on purpose: ``safe_resolve`` refuses paths that
    escape the content tree, and ``load_page`` refuses a page hidden by
    ``SHOW_PRIVATE``, so the editor cannot reach what the site will not serve.
    """
    index_md = content.safe_resolve(relpath) / "index.md"
    if not index_md.is_file():
        raise Http404("Page not found")
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
    create what `avallon check` would then flag as out of vocabulary.
    """
    if not may_edit(request):
        raise Http404("Editing unavailable")

    vocab = content.vocabulary()
    form = {
        "domain": "",
        "type": "",
        "title": "",
        "tags": "",
        "summary": "",
        "project": "",
    }
    error = ""

    if request.method == "POST":
        form = {k: request.POST.get(k, "").strip() for k in form}
        tags = [t for t in re.split(r"[,\n]+", form["tags"]) if t.strip()]
        try:
            page = content.create_page(
                form["domain"],
                form["type"],
                form["title"],
                [t.strip() for t in tags],
                form["summary"],
                form["project"],
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
            # Existing tags, offered as clickable chips so they get reused
            "known_tags": content.all_tags(),
            # Existing projects, so a new page can join a dossier at birth.
            "projects": content.all_projects(),
        },
    )


def page_source(request):
    """Return a page's raw Markdown (`?path=<relpath>`), for the editor.

    The ``mtime`` travels with the text and must come back on save: it is what
    lets the server tell an ordinary write from one that would silently
    overwrite an edit made meanwhile in a local text editor.
    """
    if not may_edit(request):
        raise Http404("Editing unavailable")
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
        raise Http404("Editing unavailable")
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Unreadable request."}, status=400)

    relpath = str(payload.get("path", ""))
    index_md = _editable_page(relpath)
    text = payload.get("text")
    if not isinstance(text, str):
        return JsonResponse({"error": "Missing content."}, status=400)

    try:
        content.save_source(index_md, text, payload.get("mtime"))
    except content.InvalidFrontmatter as exc:
        return JsonResponse({"error": f"Invalid frontmatter: {exc}"}, status=400)
    except content.StaleEdit:
        return JsonResponse(
            {
                "error": "The file changed on disk since the editor opened it. "
                "Reload the page to start from the current version.",
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


@require_POST
def move_page(request):
    """Re-file a page under another domain/type (its directory moves on disk).

    The slug is kept, so the page's assets and the wikilinks pointing at it by
    slug keep resolving; only its URL changes, which the browser follows via
    the ``url`` returned here. Answers 400 on an undeclared destination or a
    slug collision, rather than moving the page somewhere it cannot live.
    """
    if not may_edit(request):
        raise Http404("Editing unavailable")
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Unreadable request."}, status=400)

    relpath = str(payload.get("path", ""))
    # Same guards as the reader: refuse a path escaping the tree or a page the
    # site would not serve, before touching anything on disk.
    _editable_page(relpath)
    try:
        page = content.move_page(
            relpath, str(payload.get("domain", "")), str(payload.get("type", ""))
        )
    except content.InvalidPage as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    _commit_page(page.relpath, action=f"move {relpath} ->")
    return JsonResponse({"url": page.url})


_EXPORT_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}


def export_page(request):
    """Download a note as a styled Word document (``?format=pdf`` for a PDF).

    The document is built in a temp dir and streamed back as an attachment;
    nothing is written into the content tree. Reuses the reader's path guards
    so only a servable page can be exported.
    """
    index_md = _editable_page(request.GET.get("path", ""))
    page = content.load_page(index_md)
    fmt = request.GET.get("format", "docx")
    if fmt not in _EXPORT_TYPES:
        raise Http404("Unknown export format")

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / f"{page.slug}.{fmt}"
        try:
            if fmt == "pdf":
                exporter.export_pdf(index_md, out)
            else:
                exporter.export_docx(index_md, out)
        except exporter.ExportError as exc:
            return JsonResponse({"error": str(exc)}, status=500)
        data = out.read_bytes()

    response = HttpResponse(data, content_type=_EXPORT_TYPES[fmt])
    response["Content-Disposition"] = f'attachment; filename="{page.slug}.{fmt}"'
    return response


async def markdown_stream(request):
    """Server-Sent Events endpoint: watch one page's index.md mtime and push
    the freshly rendered HTML whenever it changes. The page to watch is given
    by `?path=<relpath>`, so live-reload works for any page. The browser swaps
    it into `.prose` in place, keeping scroll position and UI state."""
    target = content.safe_resolve(request.GET.get("path", ""))
    index_md = target / "index.md"
    if not index_md.is_file():
        raise Http404("Page not found")
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

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"  # disable proxy buffering (e.g. nginx)
    return response
