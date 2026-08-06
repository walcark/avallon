"""Custom SuperFences blocks: server-rendered galleries, plots, tables, queries.

Each function here is a ``pymdownx.superfences`` *custom fence formatter*: it
receives the raw text of a fenced block whose language is its own name and
returns a finished HTML string, stashed verbatim (never re-processed). The four
blocks all render on the server, so they need no external JavaScript library and
survive a future static/PDF export:

    ```gallery      a grid of co-located images, opened in a lightbox
    ```plot         a line/scatter/bar chart drawn as inline SVG
    ```csv          a sortable data table from inline CSV or a co-located file
    ```query        a live table of notes matching a frontmatter filter

Config inside ``plot`` and ``query`` is YAML; ``gallery`` and ``csv`` take a
plain line-oriented body. A malformed block renders a visible error rather than
raising, so a typo never 500s the page it sits on.
"""

from __future__ import annotations

import csv as csvmod
import html
import io
import math
from typing import Any

import yaml

_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif")


def _error(message: str) -> str:
    """Render *message* as a visible in-page error box (safe HTML)."""
    return f'<div class="block-error">{html.escape(message)}</div>'


def _attr(value: str) -> str:
    """Escape *value* for use inside a double-quoted HTML attribute."""
    return html.escape(str(value), quote=True)


# --------------------------------------------------------------------------- #
# Gallery                                                                     #
# --------------------------------------------------------------------------- #


def gallery_fence(source: str, language, css_class, options, md, **kwargs) -> str:
    """Render a ``gallery`` block into a thumbnail grid.

    Each non-empty, non-comment line of *source* is one of:

    - a directory (``figures/``), expanded to every image it holds, sorted;
    - ``file.ext``, a single image, its caption defaulting to the file stem;
    - ``file.ext | caption``, a single image with an explicit caption.

    Paths resolve next to the page being rendered, the same base its relative
    image links use, so a bare filename is all that is needed.
    """
    from avallon.web import content

    base = content.current_render_dir()
    items: list[tuple[str, str]] = []  # (relative path, caption)
    for raw in source.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        path, _, caption = line.partition("|")
        path, caption = path.strip(), caption.strip()

        target = (base / path) if base is not None else None
        if target is not None and target.is_dir():
            for child in sorted(target.iterdir()):
                if child.suffix.lower() in _IMAGE_EXT:
                    rel = f"{path.rstrip('/')}/{child.name}"
                    items.append((rel, child.stem))
        else:
            items.append((path, caption or path.rsplit("/", 1)[-1].rsplit(".", 1)[0]))

    if not items:
        return _error("Empty gallery: no image found.")

    # In an export, drop the lightbox anchor: a document wants plain figures,
    # each image resolved against the note dir by Pandoc's resource path.
    if content.current_export() is not None:
        figs = "".join(
            f'<figure><img src="{_attr(path)}" alt="{_attr(caption)}">'
            f"<figcaption>{html.escape(caption)}</figcaption></figure>"
            for path, caption in items
        )
        return figs

    cells = []
    for path, caption in items:
        cells.append(
            '<figure class="gallery-item">'
            f'<a class="gallery-link" href="{_attr(path)}" '
            f'data-caption="{_attr(caption)}">'
            f'<img src="{_attr(path)}" alt="{_attr(caption)}" loading="lazy"></a>'
            f"<figcaption>{html.escape(caption)}</figcaption>"
            "</figure>"
        )
    return '<div class="gallery">' + "".join(cells) + "</div>"


# --------------------------------------------------------------------------- #
# CSV table                                                                   #
# --------------------------------------------------------------------------- #


def _is_number(text: str) -> bool:
    """Whether *text* parses as a finite float (so its column sorts numerically)."""
    try:
        float(text)
        return True
    except ValueError:
        return False


def _render_table(header: list[str], rows: list[list[str]], table_class: str) -> str:
    """Render a header + rows into a sortable HTML table.

    A column whose every cell is a number is marked ``num`` (right-aligned and
    sorted numerically by the client script); the rest sort as text.
    """
    numeric = [
        all(_is_number(r[c]) for r in rows if c < len(r) and r[c] != "")
        and any(c < len(r) and r[c] != "" for r in rows)
        for c in range(len(header))
    ]
    head = "".join(
        f'<th class="{"num" if numeric[c] else ""}" '
        f'data-type="{"num" if numeric[c] else "text"}">{html.escape(col)}</th>'
        for c, col in enumerate(header)
    )
    body = []
    for row in rows:
        cells = "".join(
            f'<td class="{"num" if c < len(numeric) and numeric[c] else ""}">'
            f"{html.escape(row[c]) if c < len(row) else ''}</td>"
            for c in range(len(header))
        )
        body.append(f"<tr>{cells}</tr>")
    return (
        f'<div class="data-table-wrap"><table class="{table_class} sortable">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


def csv_fence(source: str, language, css_class, options, md, **kwargs) -> str:
    """Render a ``csv`` block into a sortable table.

    The body is either inline CSV (first row is the header) or a single
    ``file: results.csv`` line pointing at a CSV sitting next to the page. A
    numeric column is right-aligned and sorts numerically.
    """
    from avallon.web import content

    text = source.strip("\n")
    first = text.lstrip().split("\n", 1)[0].strip()
    if first.startswith("file:"):
        name = first[len("file:") :].strip()
        base = content.current_render_dir()
        target = (base / name) if base is not None else None
        if target is None or not target.is_file():
            return _error(f"CSV introuvable : {name}")
        try:
            text = target.read_text(encoding="utf-8")
        except OSError as exc:
            return _error(f"CSV illisible : {exc}")

    reader = csvmod.reader(io.StringIO(text))
    rows = [row for row in reader if any(c.strip() for c in row)]
    if not rows:
        return _error("Tableau vide.")
    header, data = rows[0], rows[1:]
    return _render_table(header, data, "data-table")


# --------------------------------------------------------------------------- #
# Query (frontmatter -> live table)                                          #
# --------------------------------------------------------------------------- #

_QUERY_FIELDS = ("title", "domain", "type", "date", "updated", "tags", "summary")


def _as_list(value: Any) -> list[str]:
    """Normalize a scalar-or-list config value to a list of strings."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return [str(value)]


def _query_cell(page: Any, field: str) -> str:
    """Render one query-table cell for *field* of *page* (safe HTML)."""
    if field == "title":
        return f'<a href="{_attr(page.url)}">{html.escape(page.title)}</a>'
    if field == "tags":
        return " ".join(f'<span class="tag">{html.escape(t)}</span>' for t in page.tags)
    if field == "domain":
        return html.escape(page.domain_label)
    if field == "type":
        return html.escape(page.type_label)
    if field == "date":
        return html.escape(content_fr_date(page.date))
    if field == "updated":
        return html.escape(content_fr_date(page.updated))
    if field == "summary":
        return html.escape(page.summary)
    return ""


def content_fr_date(value: Any) -> str:
    """Human date for a page field, via content's own formatter (lazy import)."""
    from avallon.web import content

    return content._fr_date(value)


def query_fence(source: str, language, css_class, options, md, **kwargs) -> str:
    """Render a ``query`` block: a live table of notes matching a filter.

    The body is YAML. Recognized keys::

        domain: informatique        # scalar or list; page domain must be one
        type: [fiche, cr]           # scalar or list; page type must be one
        tag: smartg                 # scalar or list; page must carry all of them
        sort: updated               # title | date | updated (default updated)
        order: desc                 # asc | desc (default desc)
        limit: 10                   # cap the number of rows
        fields: [title, type, updated, tags]   # columns (title is a link)

    Notes are read through ``content.all_pages()``, so private pages stay
    hidden and the table always reflects what is on disk.
    """
    from avallon.web import content

    try:
        config = yaml.safe_load(source) or {}
    except yaml.YAMLError as exc:
        return _error(f"Query invalide : {exc}")
    if not isinstance(config, dict):
        return _error("Invalid query: a key: value block is expected.")

    domains = set(_as_list(config.get("domain")))
    types = set(_as_list(config.get("type")))
    tags = [content._normalize_tag(t) for t in _as_list(config.get("tag"))]

    pages = []
    for page in content.all_pages():
        if domains and page.domain not in domains:
            continue
        if types and page.type not in types:
            continue
        if tags and not all(t in page.tags for t in tags):
            continue
        pages.append(page)

    def _updated_key(p: Any) -> str:
        return content._as_date_str(p.updated) or content._as_date_str(p.date)

    sort = str(config.get("sort", "updated"))
    key = {
        "title": lambda p: p.title.lower(),
        "date": lambda p: content._as_date_str(p.date),
        "updated": _updated_key,
    }.get(sort, _updated_key)
    pages.sort(key=key, reverse=str(config.get("order", "desc")).lower() != "asc")

    limit = config.get("limit")
    if isinstance(limit, int) and limit > 0:
        pages = pages[:limit]

    fields = [f for f in _as_list(config.get("fields")) if f in _QUERY_FIELDS]
    if not fields:
        fields = ["title", "domain", "type", "updated"]

    if not pages:
        return '<p class="query-empty">No page matches this query.</p>'

    _labels = {
        "title": "Title",
        "domain": "Domain",
        "type": "Type",
        "date": "Date",
        "updated": "Updated",
        "tags": "Tags",
        "summary": "Summary",
    }
    head = "".join(f"<th>{html.escape(_labels[f])}</th>" for f in fields)
    body = "".join(
        "<tr>" + "".join(f"<td>{_query_cell(p, f)}</td>" for f in fields) + "</tr>"
        for p in pages
    )
    return (
        '<div class="data-table-wrap"><table class="query-table sortable">'
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )


# --------------------------------------------------------------------------- #
# Plot (inline SVG chart)                                                     #
# --------------------------------------------------------------------------- #

# Canvas and inner margins, in SVG user units. The viewBox is fixed and the
# element is sized to 100% width in CSS, so the chart scales with the column.
_W, _H = 640.0, 380.0


def _nice_ticks(lo: float, hi: float, count: int = 5) -> tuple[list[float], float]:
    """Return about *count* evenly spaced "nice" tick values within [lo, hi].

    Steps are chosen from the 1/2/5 x 10^n family so labels read as round
    numbers. Returns the ticks together with the step used.
    """
    if lo == hi:
        lo, hi = lo - 1.0, hi + 1.0
    raw = (hi - lo) / max(1, count)
    mag = 10.0 ** math.floor(math.log10(raw))
    norm = raw / mag
    step = (1 if norm < 1.5 else 2 if norm < 3 else 5 if norm < 7 else 10) * mag
    start = math.ceil(lo / step) * step
    ticks = []
    value = start
    while value <= hi + step * 1e-9:
        ticks.append(round(value, 12))
        value += step
    return ticks, step


def _fmt(value: float) -> str:
    """Compact tick label: integers without a dot, the rest via %g."""
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:g}"


def _series(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract the series list from a plot config, accepting the ``y:`` shorthand."""
    if config.get("series"):
        return [dict(s) for s in config["series"]]
    if config.get("y") is not None:
        return [{"y": config["y"]}]
    return []


def plot_fence(source: str, language, css_class, options, md, **kwargs) -> str:
    """Render a ``plot`` block into an inline SVG chart.

    The body is YAML::

        kind: line              # line | scatter | bar (default line)
        title: Réflectance TOA
        xlabel: λ (nm)
        ylabel: réflectance
        x: [400, 450, 500, 550] # shared x; omit to use 0..n-1
        y: [0.31, 0.28, ...]    # single-series shorthand
        series:                 # or several named series
          - {name: TOA, y: [...]}
          - {name: BOA, y: [...]}

    Colors come from CSS classes (``plot-s0``..``plot-s5``), so the chart
    follows the light/dark theme like the rest of the site.
    """
    try:
        config = yaml.safe_load(source) or {}
    except yaml.YAMLError as exc:
        return _error(f"Plot invalide : {exc}")
    if not isinstance(config, dict):
        return _error("Invalid plot: a key: value block is expected.")

    series = _series(config)
    if not series:
        return _error("Plot vide : renseigne `y:` ou `series:`.")
    try:
        for s in series:
            s["y"] = [float(v) for v in s["y"]]
    except (KeyError, TypeError, ValueError):
        return _error("Invalid plot: every series needs a `y` list.")

    n = max(len(s["y"]) for s in series)
    kind = str(config.get("kind", "line")).lower()
    raw_x = config.get("x")

    if kind == "bar":
        # Categorical x: labels are the given x (or indices), evenly spaced.
        labels = [str(v) for v in (raw_x or range(n))]
        svg_html = _bar_svg(config, series, labels)
    else:
        if raw_x is not None:
            try:
                xs = [float(v) for v in raw_x]
            except (TypeError, ValueError):
                return _error("Invalid plot: `x` must be a list of numbers.")
        else:
            xs = [float(i) for i in range(n)]
        svg_html = _xy_svg(config, series, xs, scatter=(kind == "scatter"))

    from avallon.web import content

    export = content.current_export()
    if export is not None:
        return _export_plot(svg_html, config, export)
    return svg_html


def _frame(config: dict[str, Any]) -> tuple[dict[str, float], list[str]]:
    """Compute plot margins from which optional labels are present, and start
    the SVG element. Returns the margin dict and the list of SVG fragments."""
    has_title = bool(config.get("title"))
    m = {
        "left": 62.0,
        "right": 16.0,
        "top": 40.0 if has_title else 20.0,
        "bottom": 54.0 if config.get("xlabel") else 40.0,
    }
    out = [
        f'<svg class="plot" viewBox="0 0 {_W:g} {_H:g}" '
        f'role="img" preserveAspectRatio="xMidYMid meet">'
    ]
    if has_title:
        out.append(
            f'<text class="plot-title" x="{_W / 2:g}" y="22" '
            f'text-anchor="middle">{html.escape(str(config["title"]))}</text>'
        )
    return m, out


def _axis_labels(config: dict[str, Any], m: dict[str, float]) -> str:
    """SVG for the x/y axis titles, placed just outside the plot area."""
    out = []
    if config.get("xlabel"):
        out.append(
            f'<text class="plot-axis-label" x="{(m["left"] + _W - m["right"]) / 2:g}" '
            f'y="{_H - 8:g}" text-anchor="middle">'
            f"{html.escape(str(config['xlabel']))}</text>"
        )
    if config.get("ylabel"):
        cy = (m["top"] + _H - m["bottom"]) / 2
        out.append(
            f'<text class="plot-axis-label" '
            f'transform="translate(14 {cy:g}) rotate(-90)" '
            f'text-anchor="middle">{html.escape(str(config["ylabel"]))}</text>'
        )
    return "".join(out)


def _legend(series: list[dict[str, Any]], m: dict[str, float]) -> str:
    """A small legend at the top-right, only when a series is named."""
    named = [s for s in series if s.get("name")]
    if not named:
        return ""
    out = []
    x = _W - m["right"] - 110
    y = m["top"] + 6
    for i, s in enumerate(series):
        if not s.get("name"):
            continue
        out.append(
            f'<rect class="plot-fill plot-s{i % 6}" x="{x:g}" y="{y - 8:g}" '
            f'width="10" height="10" rx="2"/>'
            f'<text class="plot-legend" x="{x + 15:g}" y="{y + 1:g}">'
            f"{html.escape(str(s['name']))}</text>"
        )
        y += 16
    return "".join(out)


def _xy_svg(
    config: dict[str, Any],
    series: list[dict[str, Any]],
    xs: list[float],
    *,
    scatter: bool,
) -> str:
    """Render a line or scatter chart over a shared numeric x axis."""
    m, out = _frame(config)
    left, right, top, bottom = m["left"], m["right"], m["top"], m["bottom"]
    plot_w, plot_h = _W - left - right, _H - top - bottom

    all_y = [v for s in series for v in s["y"]]
    ylo, yhi = min(all_y), max(all_y)
    pad = (yhi - ylo) * 0.08 or (abs(yhi) * 0.08 or 1.0)
    ylo, yhi = ylo - pad, yhi + pad
    xlo, xhi = min(xs), max(xs)
    if xlo == xhi:
        xlo, xhi = xlo - 0.5, xhi + 0.5

    def sx(x: float) -> float:
        return left + plot_w * (x - xlo) / (xhi - xlo)

    def sy(y: float) -> float:
        return top + plot_h * (1 - (y - ylo) / (yhi - ylo))

    # Gridlines + tick labels.
    yticks, _ = _nice_ticks(ylo, yhi)
    for t in yticks:
        if t < ylo or t > yhi:
            continue
        yy = sy(t)
        out.append(
            f'<line class="plot-grid" x1="{left:g}" y1="{yy:g}" '
            f'x2="{_W - right:g}" y2="{yy:g}"/>'
            f'<text class="plot-tick plot-tick-y" x="{left - 6:g}" y="{yy + 3:g}" '
            f'text-anchor="end">{_fmt(t)}</text>'
        )
    xticks, _ = _nice_ticks(xlo, xhi)
    for t in xticks:
        if t < xlo or t > xhi:
            continue
        xx = sx(t)
        out.append(
            f'<text class="plot-tick" x="{xx:g}" y="{_H - bottom + 16:g}" '
            f'text-anchor="middle">{_fmt(t)}</text>'
        )

    # Axes.
    out.append(
        f'<line class="plot-axis" x1="{left:g}" y1="{top:g}" '
        f'x2="{left:g}" y2="{_H - bottom:g}"/>'
        f'<line class="plot-axis" x1="{left:g}" y1="{_H - bottom:g}" '
        f'x2="{_W - right:g}" y2="{_H - bottom:g}"/>'
    )

    # Series.
    for i, s in enumerate(series):
        pts = [(sx(xs[j]), sy(s["y"][j])) for j in range(min(len(xs), len(s["y"])))]
        cls = f"plot-s{i % 6}"
        if not scatter:
            points = " ".join(f"{px:g},{py:g}" for px, py in pts)
            out.append(f'<polyline class="plot-line {cls}" points="{points}"/>')
        for px, py in pts:
            out.append(
                f'<circle class="plot-dot plot-fill {cls}" '
                f'cx="{px:g}" cy="{py:g}" r="3"/>'
            )

    out.append(_axis_labels(config, m))
    out.append(_legend(series, m))
    out.append("</svg>")
    return '<div class="plot-wrap">' + "".join(out) + "</div>"


def _bar_svg(
    config: dict[str, Any], series: list[dict[str, Any]], labels: list[str]
) -> str:
    """Render a bar chart; several series are drawn as grouped bars per label."""
    m, out = _frame(config)
    left, right, top, bottom = m["left"], m["right"], m["top"], m["bottom"]
    plot_w, plot_h = _W - left - right, _H - top - bottom

    n = len(labels)
    all_y = [v for s in series for v in s["y"]] + [0.0]
    ylo, yhi = min(all_y), max(all_y)
    if yhi == ylo:
        yhi = ylo + 1.0
    yhi += (yhi - ylo) * 0.08

    def sy(y: float) -> float:
        return top + plot_h * (1 - (y - ylo) / (yhi - ylo))

    yticks, _ = _nice_ticks(ylo, yhi)
    for t in yticks:
        if t < ylo or t > yhi:
            continue
        yy = sy(t)
        out.append(
            f'<line class="plot-grid" x1="{left:g}" y1="{yy:g}" '
            f'x2="{_W - right:g}" y2="{yy:g}"/>'
            f'<text class="plot-tick plot-tick-y" x="{left - 6:g}" y="{yy + 3:g}" '
            f'text-anchor="end">{_fmt(t)}</text>'
        )

    band = plot_w / max(1, n)
    groups = len(series)
    bar_w = band * 0.7 / max(1, groups)
    y0 = sy(max(0.0, ylo))
    for j in range(n):
        for i, s in enumerate(series):
            if j >= len(s["y"]):
                continue
            v = s["y"][j]
            x = left + band * j + (band - bar_w * groups) / 2 + bar_w * i
            yv = sy(v)
            out.append(
                f'<rect class="plot-fill plot-s{i % 6}" x="{x:g}" '
                f'y="{min(yv, y0):g}" width="{bar_w:g}" '
                f'height="{abs(yv - y0):g}" rx="1.5"/>'
            )
        out.append(
            f'<text class="plot-tick" x="{left + band * (j + 0.5):g}" '
            f'y="{_H - bottom + 16:g}" text-anchor="middle">'
            f"{html.escape(labels[j])}</text>"
        )

    out.append(
        f'<line class="plot-axis" x1="{left:g}" y1="{top:g}" '
        f'x2="{left:g}" y2="{_H - bottom:g}"/>'
        f'<line class="plot-axis" x1="{left:g}" y1="{y0:g}" '
        f'x2="{_W - right:g}" y2="{y0:g}"/>'
    )
    out.append(_axis_labels(config, m))
    out.append(_legend(series, m))
    out.append("</svg>")
    return '<div class="plot-wrap">' + "".join(out) + "</div>"


# --------------------------------------------------------------------------- #
# Plot export (self-contained SVG file for Pandoc)                            #
# --------------------------------------------------------------------------- #

# Per-series light-theme palette, matching the site's `.plot-s0..5` classes.
_EXPORT_SERIES = ("#2a6db3", "#cc2222", "#2e7d46", "#c06a12", "#7a45b0", "#1f8a8a")

# A document has no site stylesheet, so an exported plot carries its own: a
# <style> with the light-theme palette, spelled out per series (no dependence
# on `currentColor`, which not every SVG rasterizer resolves). The per-series
# rules use compound selectors (`.plot-fill.plot-s0`); Pandoc's PNG rasterizer
# ignores those, so the colors are *also* inlined as presentation attributes
# by `_inline_series_colors` below. Single-class rules (grid, ticks, title)
# are honored, so they stay in the stylesheet.
_EXPORT_SVG_STYLE = (
    "<style>"
    "text{font-family:Calibri,Helvetica,sans-serif}"
    ".plot-title{fill:#23211e;font-size:15px;font-weight:600}"
    ".plot-axis{stroke:#6b645b;stroke-width:1}"
    ".plot-grid{stroke:#e6e1d8;stroke-width:1}"
    ".plot-tick{fill:#6b645b;font-size:11px}"
    ".plot-axis-label{fill:#6b645b;font-size:12px}"
    ".plot-legend{fill:#23211e;font-size:12px}"
    ".plot-line{fill:none;stroke-width:2}"
    ".plot-dot{stroke:#ffffff;stroke-width:1}"
    + "".join(
        f".plot-line.plot-s{i}{{stroke:{c}}}.plot-fill.plot-s{i}{{fill:{c}}}"
        for i, c in enumerate(_EXPORT_SERIES)
    )
    + "</style>"
)


def _inline_series_colors(svg: str) -> str:
    """Add explicit ``fill``/``stroke`` attributes to the series-colored shapes.

    The site styles series with compound CSS selectors (``.plot-fill.plot-s0``),
    which the export rasterizer drops, leaving bars and points black. Spelling
    the color out as a presentation attribute is honored by every renderer and,
    being lower priority than CSS, changes nothing where the stylesheet already
    applies.
    """
    for i, color in enumerate(_EXPORT_SERIES):
        svg = svg.replace(
            f'class="plot-line plot-s{i}"',
            f'class="plot-line plot-s{i}" fill="none" '
            f'stroke="{color}" stroke-width="2"',
        )
        # Bars, dots and legend swatches all end their class with the series.
        svg = svg.replace(
            f'plot-fill plot-s{i}"', f'plot-fill plot-s{i}" fill="{color}"'
        )
    return svg


_PLOT_OPEN = (
    '<svg class="plot" viewBox="0 0 640 380" role="img" '
    'preserveAspectRatio="xMidYMid meet">'
)
_PLOT_OPEN_STANDALONE = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="380" '
    'viewBox="0 0 640 380">'
)


def _export_plot(svg_html: str, config: dict[str, Any], export: Any) -> str:
    """Write the plot as a self-contained SVG file and return an ``<img>``.

    Pandoc reads the image from *export.assets_dir* (on its resource path) and
    embeds it in the document, rasterizing the SVG on the way if the target
    needs it.
    """
    inner = svg_html
    if inner.startswith('<div class="plot-wrap">'):
        inner = inner[len('<div class="plot-wrap">') :]
    if inner.endswith("</div>"):
        inner = inner[: -len("</div>")]
    standalone = inner.replace(_PLOT_OPEN, _PLOT_OPEN_STANDALONE + _EXPORT_SVG_STYLE, 1)
    standalone = _inline_series_colors(standalone)

    export.count += 1
    name = f"__plot{export.count}.svg"
    (export.assets_dir / name).write_text(standalone, encoding="utf-8")

    title = str(config.get("title", "")).strip()
    caption = f"<figcaption>{html.escape(title)}</figcaption>" if title else ""
    return f'<figure><img src="{name}" alt="{_attr(title)}">{caption}</figure>'
