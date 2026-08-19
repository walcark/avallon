"""python-markdown extension: ``{couleur}(texte)`` -> colored inline span.

A light way to tint a run of text beyond bold and italic::

    {rouge}(attention)
    {vert}(ok, **validé**)                  # nested markup still renders
    {bleu}(une phrase (avec incise) suite)  # nested parentheses too

Only the declared color names are recognized; anything else is left as literal
text, so a stray brace never turns into markup. The span carries a class
(``c-rouge`` ...) and the actual colors live in the stylesheet, so they adapt to
the light/dark theme instead of being burned into the HTML.

The closing parenthesis is *found*, not matched: the pattern stops at the
opening one and the rest is scanned counting depth, so a parenthesis inside the
text closes nothing. Prose has parentheses in it, and the alternative was a rule
the writer had to remember at the moment of writing. An opening that never
closes is left as the literal text it is.

Nested inline markup is fine: the returned element's text is handed back to the
inline treeprocessor, exactly as a link's text is.
"""

from __future__ import annotations

import xml.etree.ElementTree as etree

from markdown.extensions import Extension
from markdown.inlinepatterns import InlineProcessor

# Declared colors. Kept in sync with the `.c-*` rules in style.css.
COLORS = ("rouge", "orange", "vert", "bleu", "violet")

# {name}( : a known color name and the opening parenthesis. Where the text ends
# is a question of depth, which no regular expression answers.
COLOR_RE = r"\{(" + "|".join(COLORS) + r")\}\("


def closing_paren(data: str, start: int) -> int | None:
    """Index of the ``)`` closing the one opened just before *start*, or None.

    *start* is the first character of the content. Escaped parentheses never
    reach here: the escape pattern has a higher priority and has already turned
    ``\\)`` into a placeholder, so it cannot be miscounted.
    """
    depth = 1
    for index in range(start, len(data)):
        char = data[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


class ColorInlineProcessor(InlineProcessor):
    def handleMatch(self, m, data):
        start = m.end(0)
        end = closing_paren(data, start)
        if end is None:
            # Nothing to colour: an unclosed opening is text, and saying so by
            # leaving it alone beats swallowing the rest of the paragraph.
            return None, None, None
        el = etree.Element("span")
        el.set("class", f"c-{m.group(1)}")
        el.text = data[start:end]
        return el, m.start(0), end + 1


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
