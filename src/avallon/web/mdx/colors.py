"""python-markdown extension: ``{couleur}(texte)`` -> colored inline span.

A light way to tint a run of text beyond bold and italic::

    {rouge}(attention)
    {vert}(ok, **validé**)      # nested markup still renders

Only the declared color names are recognized; anything else is left as literal
text, so a stray brace never turns into markup. The span carries a class
(``c-rouge`` ...) and the actual colors live in the stylesheet, so they adapt to
the light/dark theme instead of being burned into the HTML.

The captured text may not contain a closing parenthesis (keeps the match simple
and unambiguous). Nested inline markup is fine: the returned element's text is
handed back to the inline treeprocessor, exactly as a link's text is.
"""

from __future__ import annotations

import xml.etree.ElementTree as etree

from markdown.extensions import Extension
from markdown.inlinepatterns import InlineProcessor

# Declared colors. Kept in sync with the `.c-*` rules in style.css.
COLORS = ("rouge", "orange", "vert", "bleu", "violet")

# {name}(content): a known color name, then the text in parentheses.
COLOR_RE = r"\{(" + "|".join(COLORS) + r")\}\(([^)]+)\)"


class ColorInlineProcessor(InlineProcessor):
    def handleMatch(self, m, data):
        el = etree.Element("span")
        el.set("class", f"c-{m.group(1)}")
        el.text = m.group(2)
        return el, m.start(0), m.end(0)


class ColorExtension(Extension):
    def extendMarkdown(self, md):
        # 174: below the built-in link (160) is not required since the syntaxes
        # don't overlap, but a high priority keeps it clear of attr_list's later
        # `{: .cls}` handling.
        md.inlinePatterns.register(
            ColorInlineProcessor(COLOR_RE, md), "color_span", 174
        )


def makeExtension(**kwargs):
    return ColorExtension(**kwargs)
