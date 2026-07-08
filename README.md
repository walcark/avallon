# kevin-website

Site personnel de notes en **Markdown** : chaque page est un fichier Markdown
rendu en HTML, rangé dans une arborescence qui encode à la fois l'URL et la
taxonomie. Une page centrale permet de filtrer par domaine / type / tags et de
faire une recherche plein-texte.

## Structure du contenu

```
content/<domaine>/<type>/<slug>/index.md   ->   /<domaine>/<type>/<slug>/
```

- Chaque page est un **dossier** contenant `index.md` et ses **images
  co-localisées** (référencées en chemin *relatif*, ex. `![](figure.png)`),
  servies sous l'URL de la page.
- Deux axes de taxonomie viennent du chemin : le **domaine** et le **type** ;
  les **tags** viennent du frontmatter.

### Frontmatter

```yaml
---
title: Titre de la page
date: 2026-07-01        # création (posée une fois)
updated: 2026-07-08     # dernière modif (tamponnée à chaque commit)
tags: [smartg, flux]
summary: Une phrase de résumé affichée sur la page d'accueil.
---
```

## Taxonomie déclarée

`taxonomy.toml` (à la racine) est la **source de vérité** des domaines et types
autorisés. On l'étend avec :

```
pixi run add-domain maison      # ajoute un domaine + commit taxonomy.toml
pixi run add-type   recette     # ajoute un type    + commit taxonomy.toml
pixi run check-taxo             # vérifie que toutes les pages sont conformes
```

Comme le vocabulaire est committé, une page ne peut pas naître sous un
domaine / type non déclaré.

## Créer une page

```
pixi run new
```

Choix du **domaine** puis du **type** parmi la taxonomie (via `gum`, sinon
`fzf`, sinon un menu numéroté), puis saisie du **titre** et des **tags** (texte
libre). La commande crée `content/<domaine>/<type>/<slug>/index.md` avec un
frontmatter prêt (`date`/`updated` du jour). Tout peut aussi être passé en
options (`--domain`, `--type`, `--title`, `--tags`, `--summary`) pour scripter.

## Dates de modification

- `date` = création, `updated` = dernière modification.
- Un **hook `pre-commit`** tamponne `updated` (et remplit `date` si absent) sur
  chaque page `content/**/index.md` stagée, puis la ré-ajoute au commit.
  À installer une fois par clone :

  ```
  pixi run setup-hooks          # git config core.hooksPath scripts/git-hooks
  ```

- `pixi run stamp` remplit les dates manquantes de toutes les notes (depuis
  l'historique git, repli sur le `mtime`).
- Le frontmatter est édité **au fil du texte** (seules les lignes de date
  bougent), donc les diffs restent propres.

## Recherche et page d'accueil

- **Accueil** (`/`) : toutes les pages, les plus récentes d'abord, avec des
  filtres à facettes **adaptatifs** — les types proposés suivent le domaine
  choisi, les tags suivent le couple domaine + type.
- **Recherche plein-texte** (`/search/?q=`) : `ripgrep` multi-termes en **ET**
  (repli Python pur si `rg` absent), extraits surlignés tirés du texte lisible.
- Les liens `/?domaine=…`, `/?type=…`, `/?tag=…` préactivent les filtres (le
  fil d'Ariane des pages pointe dessus).

## Live reload (édition du Markdown)

La page se met à jour dès que le fichier Markdown change sur le disque, sans
rechargement complet et sans perdre la position de défilement.

- **Vue SSE asynchrone** (`pages/views.py` → `markdown_stream`, route
  `stream/?path=<relpath>`) : surveille le `mtime` de l'`index.md`
  (`POLL_INTERVAL` = 0,3 s) et, à chaque changement, re-rend le Markdown et
  pousse le HTML en Server-Sent Events.
- **Côté client** (`templates/index.html`) : un `EventSource` remplace le
  `innerHTML` de `.prose` et relance MathJax.

Les polices (Roboto) et **MathJax** (build SVG) sont **auto-hébergées** sous
`static/` : le rendu fonctionne hors-ligne, sans CDN.

## Commandes

| Commande | Rôle |
|---|---|
| `pixi run serve` | Lance le site (ASGI / uvicorn) sur `http://127.0.0.1:8000` |
| `pixi run new` | Crée une nouvelle page |
| `pixi run add-domain <nom>` | Ajoute un domaine à la taxonomie (+ commit) |
| `pixi run add-type <nom>` | Ajoute un type à la taxonomie (+ commit) |
| `pixi run check-taxo` | Vérifie la conformité des pages à la taxonomie |
| `pixi run stamp` | Remplit les `date`/`updated` manquants |
| `pixi run setup-hooks` | Installe le hook de tampon des dates |

## Lancer

```
pixi run serve
```

Sert l'app en **ASGI** (uvicorn, `--reload`, y compris les templates et le CSS)
sur `http://127.0.0.1:8000`. Le streaming SSE **ne fonctionne pas** sous
`pixi run runserver` (le WSGI met les réponses asynchrones en tampon au lieu de
les diffuser).

## À venir

- [ ] Outil d'export d'une note (pandoc → Word / docx, etc.)
- [ ] Outil pour récupérer des images de sortie de code (rendu adaptatif des
      évolutions)
