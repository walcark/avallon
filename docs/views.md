# Views, collections and search

`model.md` says what a page *is*, `documents.md` says how a file becomes one.
This file answers a different question: once there are three hundred pages and
two hundred files, **how does anything get found again**, and what should the
site show for each kind of thing.

The question that drives it, stated as a user would:

> I want to find my ID card on its own, and I want a collection of all my
> identity documents, or of everything about my bank contract.

## 1. What the model already answers

Before inventing anything, what the site can do today:

| Brick | What it groups | Nature |
| --- | --- | --- |
| `project:` | the pages archived with one dossier | exclusive, one per page |
| `tags:` | pages sharing a subject | many per page, flat |
| `recueil` | a page that links to others, written by hand | editorial |
| ` ```query ` | a live table filtered by domain, type or tag | derived |
| ` ```gallery ` | a thumbnail grid of images in a page's folder | presentational |

Run the driving question against that list. "All my identity documents" is
`tag: identité`, which ` ```query ` already renders. "Everything about my bank
contract" is either a tag or a dossier. **The grouping problem is largely
solved.** What is missing is upstream: a scanned ID card is an asset inside
somebody else's page, so it has no title, no tags, no URL and no existence of
its own. Nothing can collect what does not exist.

That reframes the work. The interesting gap is not collections, it is that
**files are second-class**, and that the display is identical whatever the page
holds.

## 2. Decision: no second grouping system

The temptation is a "collections" object, or nested folders per theme
(`administratif/identite/…`). Both are wrong here, for the same reason: an ID
card belongs to *identity documents* **and** to *the flat rental file* **and**
to *the passport renewal dossier*. A tree forces one parent, and a collection
object duplicates what tags already do.

The two existing axes are enough, and they answer different questions:

- **`project`** answers "will this be archived with that?" It is exclusive by
  construction, and a page leaves it only when the dossier dies.
- **`tags`** answer "what is this about?" They are many-to-many, which is
  exactly the shape of the question above.

So: the ID card is a page, tagged `identité, officiel`, in **no** dossier (it
outlives every dossier), and the rental dossier *cites* it with `[[…]]`. The
"identity documents" page is a `recueil` holding one query.

**The objection I take seriously:** tags are flat, and administrative filing
often wants hierarchy (`banque/contrat`, `banque/releves`). My answer is that
hierarchy is a naming convention, not a feature: `banque-contrat` and
`banque-releves` sort together, and a query can already match either. Adding a
tag tree would double the model to save typing a prefix. If a real hierarchy is
ever needed, it belongs to the query language, not to the storage.

### The driving question, answered in full

```
administratif/doc/carte-identite/          tags: [identité, officiel]
    index.md                               no project: it outlives every dossier
    carte-identite-recto.jpg
    carte-identite-verso.jpg

administratif/recueil/papiers-identite/    the collection, five lines:
    index.md                               ```query
                                           tag: identité
                                           as: gallery
                                           ```

administratif/recueil/contrat-bancaire/    a dossier, this time:
    index.md                               project of the pages filed under it
```

Three ways in, all correct at once: the card has its own URL and is found by
search; the identity page lists it without naming it, so adding a passport
tomorrow updates it; and the rental dossier cites `[[carte-identite]]` without
owning it.

What makes this work is that **nothing is written twice**. The only hand-written
thing is the tag on the document. Every listing derives from it.

## 3. Decision: display follows the shape, not the label

Two independent things decide what a page looks like, and conflating them is
the classic mistake:

| Axis | Decided by | Example |
| --- | --- | --- |
| **Structure** | the presence of `file:` in the frontmatter | a PDF gets a viewer, an image gets an `<img>` |
| **Layout** | the `type` | a `recueil` lists its dossier, a `galerie` shows a grid |

The rule that keeps them apart: **the type must never decide how a file is
rendered.** A `cr` that carries a scan renders that scan the same way a `doc`
would. This is already the rule stated in `documents.md`, restated here because
the layout work is where it would get broken.

Practically, the page template becomes a lookup: `page/<type>.html` when the
package ships one, `page/default.html` otherwise. Three are worth shipping:

- **default**: what exists today (body, backlinks, dossier navigation);
- **recueil**: the body, then the dossier contents as cards rather than a list,
  since a recueil is read as an entry point and not as prose;
- **galerie**: the images of the folder as a grid, with no block to write. A
  page whose point is its pictures should not need a ` ```gallery ` fence
  repeating what the folder already says.

**The objection:** users can declare their own types (`avallon add-type`), and
an installed package cannot grow a template for each. Right, and that is why
the lookup falls back instead of failing. Letting the notes repository ship its
own templates is a different decision, with a real cost (a template is code),
and it is not needed to answer the question above.

## 4. Collections are queries, rendered as views

` ```query ` returns rows. For documents, rows are the wrong shape: one
recognizes a scan by its thumbnail, not by its title. So the block gains a
rendering option rather than a sibling block:

```yaml
tag: identité
as: gallery        # table (default) | list | gallery
```

`as: gallery` renders each matching page as a card: its `file:` thumbnail when
it has one, its title otherwise. The "Identity documents" page is then five
lines of frontmatter and one query, and it stays correct when a document is
added, because nothing was written by hand.

This is deliberately the *same* mechanism as the dossier contents (derived, not
maintained). Two ways of listing pages would drift apart.

## 5. Search: measured, then fixed

Numbers first, on synthetic corpora, before touching anything:

| Corpus | `all_pages()` | search, 1 term | search, no match | backlinks |
| --- | --- | --- | --- | --- |
| 50 pages | 3 ms | 117 ms | 66 ms | 6 ms |
| 500 pages | 29 ms | **1 144 ms** | 636 ms | 65 ms |
| 2 000 pages | 129 ms | **4 739 ms** | 2 510 ms | 249 ms |

The home page debounces at 180 ms and searches as you type. At 500 pages the
answer arrived six times later than the next keystroke: the feature was already
past its budget, on a corpus this site will reach.

Profiling found two defects, neither of them where one would look.

**ripgrep never ran.** The command placed `--glob '*.md'` *after* the `--`
separator, where rg reads it as a path to open. It printed the right matches,
then exited 2 for the two files it could not find, and the code treats
`returncode >= 2` as a failure and falls back to the pure-Python scan. So every
search on this site has scanned every file in Python since the day the shortlist
was written, while also paying for an rg process. The fix is moving one argument.

**Accent folding was 96% of the rest.** `_fold` normalized one character at a
time, and built an index map because folding could change a string's length.
A precomputed one-to-one `translate` table does the same work in C and cannot
change the length, which makes the map unnecessary: the same offsets index the
folded and the original text. Measured in isolation, 1.931 ms → 0.058 ms on a
6 540-character sample. The blob was also folded twice per hit, once to test the
terms and once to highlight; it is folded once now.

After both fixes:

| Corpus | search, 1 term | search, no match |
| --- | --- | --- |
| 50 pages | 117 → **13 ms** | 66 → **4 ms** |
| 500 pages | 1 144 → **97 ms** | 636 → **7 ms** |
| 2 000 pages | 4 739 → **374 ms** | 2 510 → **10 ms** |

That buys the time this site needs. What remains, in order of return:

| Fix | Effort | Expected |
| --- | --- | --- |
| Cache the folded text per file mtime | ~30 lines | repeated searches nearly free |
| `ripgrep` as a declared dependency | 1 line | the fallback stops being the norm on a minimal PATH |
| Narrow the shortlist to the rarest term | ~10 lines | fewer files to open on multi-term queries |
| Inverted index on disk | days | only past ~5 000 pages |

The last line is the one to *not* do now. An index is a second source of truth
that can disagree with the tree, and the tree is the product. The measurements
say it buys nothing before a corpus this site does not have.

**The lesson worth keeping:** the two defects had been in place for months,
invisible, because a fallback path is by definition the one nobody notices.
Anything that silently degrades needs a measurement, not a comment.

## 6. Scoped search

"Search inside this dossier" is one parameter, not a feature: `/search/?q=…&
project=<slug>`, filtered where the pages are already loaded. On a dossier page
the search field pre-fills it, so typing from a dossier searches the dossier
first and offers "search everywhere" as one click.

It composes with the rest: the same parameter serves a domain or a type, and
the facets on the home page already speak that language.

## 7. What breaks at three hundred pages

The question is about arranging documents, so the entry point matters as much
as the pages. Measured on synthetic corpora:

| Corpus | Home page | Weight | Cards in the HTML | One page |
| --- | --- | --- | --- | --- |
| 44 pages (today) | 32 ms | 67 Ko | 45 | 32 ms |
| 300 pages | 96 ms | 280 Ko | 301 | 58 ms |
| 1 000 pages | 305 ms | 864 Ko | 1 001 | 196 ms |

Nothing is slow enough to break, and that is the trap: the home page will not
fail, it will just stop being useful. It renders **every** card, and the
filtering is client-side on the whole corpus. At three hundred pages it is a
wall of cards; at a thousand it is a megabyte of HTML to say "here is
everything".

The same holds for the two other places that list everything: the sidebar tree
and the command palette, which reads its list from that tree.

Three answers, in the order I would take them:

**Make the home page an entry, not a dump.** What a reader wants on arrival is
recent work, unfinished dossiers, and the search box. Rendering the twenty most
recent cards plus the facets covers it, and the rest is one filter away. The
weight of the page stops growing with the corpus, and the facets stay accurate
because they are computed server-side from all pages regardless.

**Give the sidebar the same treatment as the dossier navigation.** Inside a
dossier it already shows the dossier instead of the whole tree, which is the
right instinct: show the neighbourhood, not the world. Outside one, the tree can
stay folded to domains and open on demand.

**Leave the palette alone.** It is keyboard-driven and prefix-filtered, which is
exactly the tool for a large corpus; it only needs its list to arrive by fetch
rather than by reading a DOM that no longer contains everything.

**The objection to pagination:** a "load more" button on a personal site is
usually a symptom of a missing filter. That is why the answer above is *recency
plus facets*, not paging: nobody scrolls to page 7 of their own notes, they
filter or they search.

## 8. What not to do

- **A database.** The tree is the product: readable, diffable, syncable by git.
  An index is acceptable as a derived cache, never as the source.
- **A rewrite in a front-end framework.** Nothing here is an interaction
  problem; it is a modelling and a folding problem.
- **Systematic OCR at import.** Extraction is right for PDFs that already carry
  a text layer (instant, exact). OCR is slow, wrong often enough to mislead a
  search, and only useful on pure scans. Make it opt-in per document.
- **A tag hierarchy**, see section 2.
- **Promoting every file to a page.** `documents.md` already sets the test
  ("would I look for this file on its own?"), and it is the rule that keeps the
  repository small.

## 9. Order of work

1. ~~**Search performance**~~ **done**: ripgrep now runs, folding is 30x
   cheaper, searches went from 1 144 ms to 97 ms at 500 pages.
2. **Scoped search**, one parameter, closes "a dossier is a place you search
   from".
3. **The home page as an entry** (recent plus facets), before the corpus makes
   it moot.
4. **`file:` and the viewers** (`documents.md` step 3): this is what gives a
   document its own identity, and nothing about collections works before it.
5. **`as: gallery|list` on queries**, which turns tags into readable
   collections.
6. **Per-type templates**, `recueil` and `galerie` first.

Steps 2 and 3 are worth doing whatever happens to the rest. Steps 4 to 6 only
pay off together: a collection of documents needs documents to exist, and a view
to show them.
