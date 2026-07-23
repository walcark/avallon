# mysite

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

## Emplacement du contenu (dépôt externe)

Le contenu (arbre Markdown **et** `taxonomy.toml`) vit dans un **dépôt séparé**,
hors de ce repo applicatif — comme les données de `pytodo`. L'emplacement actif
est stocké dans un fichier local non versionné
(`~/.config/mysite/config.toml`, `content_dir = "…"`).

```
pixi run content-init <chemin>   # crée/adopte le dépôt de contenu, l'active,
                                 # (propose de migrer le contenu in-repo),
                                 # y installe le hook de dates + commit initial
pixi run content-set  <chemin>   # active un dépôt de contenu existant
pixi run content-where           # affiche le dépôt actif et sa provenance
```

Résolution de l'emplacement (le premier qui répond gagne) :

1. la variable d'environnement **`MYSITE_CONTENT_DIR`** (override, utile en test/CI) ;
2. **`content_dir`** dans `~/.config/mysite/config.toml` ;
3. le dossier **`content/`** de ce repo (repli de dev, pour qu'un clone tourne
   sans configuration).

Après un changement d'emplacement, **redémarre le serveur** (`pixi run serve`).

## Synchronisation du contenu

```
pixi run sync                    # pull (rebase) -> commit -> push
pixi run sync -- --local         # commit seulement, sans réseau
pixi run sync -- -m "message"    # message de commit personnalisé
```

Le dépôt de contenu **gère lui-même son origine** : l'application ne connaît
pas GitHub, elle pousse seulement si un remote `origin` existe. Sans remote, la
commande se contente de commiter en local. Pour en ajouter un, une seule fois :

```
git -C <dépôt de contenu> remote add origin <url>
```

Deux garanties, reprises de `neverland` :

- **le commit local est immédiat**, jamais différé. Hors-ligne, le pull et le
  push échouent en avertissement, la note est commitée quand même ;
- **tout est scopé au dépôt de contenu** (`git add -A -- .`), donc un dépôt
  imbriqué dans un autre n'embarque jamais son parent.

### Groupage des commits

Douze enregistrements en dix minutes doivent se lire comme un seul changement.
Tant que `HEAD` a moins de **15 minutes**, porte le marqueur `mysite-batch:` et
n'a pas été poussé, l'édition suivante y est repliée par `git commit --amend`.

Ce qui n'est **pas** fait : différer l'écriture. Seul l'historique est compacté.
Conséquence à connaître, le **push est retenu** tant que le lot est ouvert
(pousser un commit interdit de l'amender ensuite), donc une note peut mettre
jusqu'à 15 minutes à atteindre le remote. `pixi run sync -- --no-batch` force un
commit isolé et un envoi immédiat ; `MYSITE_SYNC_WINDOW` (en secondes, `0` pour
désactiver) change la fenêtre.

Un commit que tu écris **à la main** dans le dépôt de contenu n'a pas le
marqueur, donc il n'est jamais réécrit.

## Taxonomie déclarée

`taxonomy.toml` (à la racine du dépôt de contenu) est la **source de vérité** des
domaines et types autorisés. On l'étend avec :

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
- Un **hook `pre-commit`** (installé dans le **dépôt de contenu** par
  `content-init` / `content-set`) tamponne `updated` (et remplit `date` si
  absent) sur chaque page `**/index.md` stagée, puis la ré-ajoute au commit. Le
  hook n'appelle que la bibliothèque standard, donc il tourne sans l'env pixi.
- `pixi run stamp` remplit les dates manquantes de toutes les notes (depuis
  l'historique git, repli sur le `mtime`).
- Le frontmatter est édité **au fil du texte** (seules les lignes de date
  bougent), donc les diffs restent propres.

## Navigation, recherche et thème

- **Shell commun** (`templates/base.html`) : une **sidebar gauche
  rétractable** (bouton ☰) présente l'arbre `domaine ▸ type ▸ pages` (via des
  `<details>` natifs, sans JS) ; la page courante y est mise en évidence. Une
  topbar fine porte le titre de contexte et la bascule de **thème clair/sombre**
  (persistée, sinon suit l'OS ; implémentée avec `light-dark()` en CSS).
- **Accueil** (`/`) : toutes les pages, les plus récentes d'abord, avec des
  filtres à facettes **adaptatifs** — les types proposés suivent le domaine
  choisi, les tags suivent le couple domaine + type.
- **Recherche plein-texte** (`/search/?q=`) : `ripgrep` multi-termes en **ET**
  (repli Python pur si `rg` absent), extraits surlignés tirés du texte lisible.
- Les liens `/?domaine=…`, `/?type=…`, `/?tag=…` préactivent les filtres.
- **Renvois entre pages** : `[[slug]]` (ou `[[domaine/type/slug]]`, ou
  `[[slug|texte affiché]]`) dans le Markdown devient un vrai lien vers la page.
  Une cible introuvable s'affiche signalée (barrée), pas silencieusement perdue.

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
| `pixi run content-init <chemin>` | Crée/adopte et active le dépôt de contenu externe |
| `pixi run content-set <chemin>` | Active un dépôt de contenu existant |
| `pixi run content-where` | Affiche le dépôt de contenu actif |
| `pixi run sync` | Synchronise le dépôt de contenu (pull, commit, push) |

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
