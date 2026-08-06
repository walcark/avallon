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

## 5. Search: measured before touched

Numbers first, on synthetic corpora, current implementation:

| Corpus | `all_pages()` | search, 1 term | search, 2 terms | backlinks |
| --- | --- | --- | --- | --- |
| 50 pages | 3 ms | 117 ms | 114 ms | 6 ms |
| 500 pages | 29 ms | **1 144 ms** | 1 138 ms | 65 ms |
| 2 000 pages | 129 ms | **4 739 ms** | 4 886 ms | 249 ms |

The home page debounces at 180 ms and searches as you type. At 500 pages the
answer arrives six times later than the next keystroke: the feature is already
past its budget, on a corpus this site will reach.

A profile says where it goes, and it is not where one would guess:

```
6.35 s  search
6.34 s  └─ _hit_for (500 calls)
6.10 s     └─ _fold (2001 calls, 3M unicodedata.normalize)
3.10 s        └─ _highlight → _fold_text again
```

**96 % of the time is accent folding**, character by character, in Python. Not
YAML, not disk I/O, not the regex. Two defects, both cheap to fix:

1. `_fold` normalizes one character at a time and rebuilds an index map. A
   precomputed `str.translate` table does the same job in C. Measured on a
   6 540-character sample: **1.931 ms → 0.058 ms, 33x**, identical output, and
   the length is preserved, which makes the index map the identity and deletes
   the code that maintains it.
2. The same blob is folded twice, once to test the terms and once to highlight.

A third, invisible until it bites: **ripgrep is not a dependency**. It is
optional by design, the pure-Python fallback exists, and that fallback is what
ran in every measurement above, because `rg` is not in the project environment.
On a deployment started by systemd, with a minimal `PATH`, the same will be
true. Either it is a real dependency, or the fallback must be fast enough to be
the normal path. Given the fix above, the second is now defensible.

Order, by return on effort:

| Fix | Effort | Expected |
| --- | --- | --- |
| `translate` table in `_fold` | 20 lines | ~30x on the dominant cost |
| Fold the blob once, reuse for highlight | 10 lines | ~2x on what remains |
| `ripgrep` as a declared dependency | 1 line | shortlist before Python runs |
| Cache the folded text per file mtime | 30 lines | repeated searches free |
| Inverted index on disk | days | only past ~5 000 pages |

The last line is the one to *not* do now. An index is a second source of truth
that can disagree with the tree, and the tree is the product. Revisit when the
first four are in and a measurement still hurts.

## 6. Scoped search

"Search inside this dossier" is one parameter, not a feature: `/search/?q=…&
project=<slug>`, filtered where the pages are already loaded. On a dossier page
the search field pre-fills it, so typing from a dossier searches the dossier
first and offers "search everywhere" as one click.

It composes with the rest: the same parameter serves a domain or a type, and
the facets on the home page already speak that language.

## 7. What not to do

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

## 8. Order of work

1. **Search performance** (`_fold`, single fold, ripgrep). Independent of
   everything else, and the only item that is already hurting.
2. **Scoped search**, which is one parameter and closes the "dossier as a place
   you search from" gap.
3. **`file:` and the viewers** (`documents.md` step 3). This is what gives a
   document its own identity, and nothing about collections works before it.
4. **`as: gallery|list` on queries**, which turns tags into readable
   collections.
5. **Per-type templates**, `recueil` and `galerie` first.

Steps 1 and 2 are worth doing whatever happens to the rest. Steps 3 to 5 only
pay off together: a collection of documents needs documents to exist and a view
to show them.
