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

## 7. The home page is the explorer

The home page is not a listing with a search box bolted on: **it is one
selection, rendered according to what it contains.** Facets and text are two
ways of narrowing the same thing.

The use case that states it best:

> Filter on administrative images: I want to see them all, as images. Then I
> want to narrow that down by typing.

Two consequences, and the second is the interesting one.

### Measured: why the current shape cannot do that

| Corpus | Home page | Weight | Cards in the HTML |
| --- | --- | --- | --- |
| 44 pages (today) | 32 ms | 67 Ko | 45 |
| 300 pages | 96 ms | 280 Ko | 301 |
| 1 000 pages | 305 ms | 864 Ko | 1 001 |

Nothing is slow enough to break, and that is the trap: the page will not fail,
it will quietly stop being useful. It renders **every** card and filters them in
the browser, so the weight grows with the corpus rather than with the selection.
And the search results arrive in a *separate* floating panel, which is precisely
what makes "filter, then narrow by typing" impossible: the two do not compose,
one replaces the other.

The fix is the same one: **the selection is computed server-side, from facets
and text together**, and only the selection is rendered. `/?domaine=administratif
&kind=image&q=identité` is one URL, shareable and bookmarkable, and the weight
of the page follows what was asked, not what exists.

### Do not add `type: image`

The temptation, given the use case, is a type per medium: `image`, `pdf`, `scan`.
It is the wrong axis, for a reason worth stating:

- **The type is editorial**: it says what the page *is* (a note, a compte rendu,
  an index). It is chosen by a human and cannot be checked.
- **The medium is structural**: it is already written in the file's extension.

Declaring both invites them to disagree: `type: image` on a page whose `file:`
is a PDF is a lie nothing detects. So the medium becomes a **derived facet**,
computed from `file:` and never typed:

| `kind` | From | Rendering |
| --- | --- | --- |
| `note` | no `file:` | the body, as today |
| `image` | png, jpg, webp, svg, heic | thumbnail grid, lightbox |
| `pdf` | pdf | first-page thumbnail, inline viewer |
| `text` | txt, md, csv, code | Pygments |
| `office` | docx, xlsx, pptx | icon, download |
| `archive` | zip, tar, 7z | icon, download |

Zero input, never wrong, and it filters exactly as asked:
`domaine=administratif` plus `kind=image`.

### The type vocabulary a documentation space needs

Which leaves the real question: what types, for a space meant to hold everything?

**One addition, `doc`**: a file promoted to a page of its own, per the test in
`documents.md` ("would I look for this file on its own?"). With `fiche`, `cr`,
`tutoriel` and `recueil`, that is the whole vocabulary.

The types *not* to add, and why, because the pressure to add them is constant:

| Tempting | What it really is |
| --- | --- |
| `image`, `pdf`, `scan` | a `kind`, derived from the file |
| `facture`, `contrat`, `passeport` | tags: they say the subject, not the form |
| `livre`, `article` | a `doc` with a tag; the form is identical |
| `photo` | a `doc` whose `kind` is `image` |
| `projet` | a dossier, which is a page plus `project:` on its members |
| `archive`, `todo` | a `status`, not a form |

The discriminating test: **a type you cannot define without naming a file
format or a subject is not a type.** It is a `kind` or a tag. Five types, stable
for years, is the right size; fifteen means every new page starts with a
taxonomy decision, which is exactly the friction that stops people from filing.

### The view follows the selection

A selection of images should not render as a list of titles. So the view is
chosen, not fixed:

- every result carries a thumbnail (`kind` image or pdf) → **grid**;
- otherwise → **cards**, as today;
- and an explicit switch (grid / list / table) that overrides the guess and is
  remembered, because an automatic choice that cannot be refused is an
  annoyance the third time it guesses wrong.

Thumbnails are cheap: an image is its own thumbnail (`loading="lazy"`, sized by
CSS), and a PDF's first page costs **19 ms and 18 Ko** with `pdftoppm`, measured
on a real invoice from the battery dossier. Cached next to the file and keyed on
its mtime, it is generated once.

`pdftoppm` comes from poppler, which is a system dependency, so it must degrade:
without it, a PDF falls back to an icon. The grid must never depend on a binary
being installed.

### What this gives, end to end

```
/?domaine=administratif&kind=image        every administrative image, as a grid
  + type "identité" in the search box     the same grid, narrowed
  + click a thumbnail                     the document's own page
```

Same surface, same URL grammar, three levels of narrowing. And it is the same
mechanism as ` ```query as: gallery ` from section 4: a stored query is a
selection someone decided to name.

### The objection worth keeping

Six facets (domain, type, kind, state, dossier, tags) is a lot of chrome for a
personal site. The existing code already hides a facet group when it holds a
single value, which is what keeps this bearable: on a corpus of notes with no
files, `kind` never appears. The rule to hold: **a facet that does not divide
the current selection does not show up.**

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
   cheaper, 1 144 ms → 97 ms at 500 pages.
2. **Server-side selection**: facets and text resolved together, one URL, only
   the selection rendered. This is the keystone. It closes the scoped-search
   gap, it fixes the home page's growth, and nothing below is worth building
   on the current split between a list and a floating panel.
3. **`file:` and the viewers** (`documents.md` step 3), which gives a document
   its own identity, plus the derived `kind` that comes free with it.
4. **Grid view and thumbnails**, the payoff of 2 and 3 together: filter on
   images, see images.
5. **`as: gallery|list` on queries**, so a named collection renders like a
   selection does.
6. **Per-type templates**, `recueil` and `galerie` first.

Step 2 is the one to do first and alone: it is the only one that changes the
shape of the application, and every other step is easier once a selection is a
first-class thing rather than a filter applied in a browser.
