# Documents : étendre le site aux fichiers non-Markdown

Note de conception. Décrit comment kevin-website peut devenir un **espace de
connaissance complet**, consultable depuis n'importe quel appareil dans un
navigateur, et pas seulement un site de notes Markdown.

Objectif visé : ouvrir depuis le navigateur une note, une image, un PDF, un
bouquin, un scan administratif, avec la même navigation, la même taxonomie et
la même recherche que les notes actuelles.

Rien de ce qui suit n'est implémenté. Le document sert à figer les décisions
avant d'écrire du code.

## Principe : un document est une page

Le modèle actuel s'étend sans être modifié. Une page est déjà un **dossier**
contenant `index.md` et ses fichiers co-localisés. Un document est simplement
une page dont le sujet est un fichier joint au lieu d'être du texte.

```
content/administratif/doc/passeport/
├── index.md          # métadonnées + notes libres
└── passeport.png     # le fichier
```

Aucun nouveau dépôt, aucun nouvel index, aucun nouveau modèle de données. Un
seul type de page dans le code : une page document est un **sur-ensemble**
d'une page normale (corps Markdown + rendu du fichier), pas un objet différent.

## Trois niveaux, pas un

L'erreur à éviter est de vouloir tout promouvoir en document. Un fichier peut
entretenir trois relations différentes avec le contenu :

| Niveau | Forme | Critère |
|---|---|---|
| **Fichier ordinaire** | hors du dépôt de contenu, aucun outil | ni métadonnées, ni URL, ni besoin de le retrouver dans six mois |
| **Illustration** | co-localisée dans la page, `![](figure.png)` | n'existe que dans sa page, pas d'identité propre |
| **Document** | dossier + `index.md` | mérite une identité, des métadonnées, une URL |

Le test qui tranche : **« est-ce que je chercherais ce fichier tout seul ? »**
Si non, illustration. Si oui, document.

Le dépôt de contenu n'est pas un système de fichiers de remplacement, c'est
l'endroit où vivent les choses jugées dignes d'être décrites. La population de
dossiers-documents doit rester petite et croître lentement.

Cas particulier : une image **réutilisée dans plusieurs notes** est un document,
par définition. La réutilisabilité est le signe de l'existence indépendante, et
la promouvoir évite la duplication (une seule source de vérité, mise à jour
propagée). Bénéfice annexe, le dossier accueille aussi la **source** à côté de
l'export :

```
content/dev/doc/diagram-flux/
├── index.md
├── diagram.drawio    # la source
└── diagram.png       # l'export
```

Nuance : le vrai critère de promotion n'est pas « utilisé deux fois » mais
**« va évoluer et doit rester synchronisé »**. Une capture figée réutilisée
dans deux notes peut rester dupliquée sans dommage.

## La commande d'ajout

```
pixi run add-file <chemin> [--domain …] [--type …] [--title …] [--tags …]
```

Même ergonomie que `pixi run new` (gum, sinon fzf, sinon menu numéroté ; tous
les champs passables en options pour rester scriptable). Elle crée le dossier,
**déplace ou copie le fichier dedans**, et écrit `index.md`.

Le type est déclaré dans la taxonomie comme les autres (`pixi run add-type doc`),
donc rien de spécial côté vocabulaire.

Deux commandes de confort à prévoir, qui font disparaître entièrement la gêne
liée à la profondeur des dossiers. Le but est de **ne jamais taper le chemin à
la main** :

```
pixi run path <requête>     # imprime le chemin résolu (composable : cp, xdg-open…)
pixi run open <requête>     # ouvre directement
```

## Frontmatter

Champs existants inchangés (`title`, `date`, `updated`, `tags`, `summary`),
plus :

```yaml
---
id: k7f3a9cq          # identifiant opaque, posé une fois, jamais recalculé
title: Passeport
file: passeport.png   # le fichier joint
date: 2026-07-20      # classement (comme aujourd'hui)
doc_date: 2019-03-14  # date du document lui-même
expires: 2029-03-14   # optionnel, utile sur les papiers administratifs
tags: [identité]
---
```

Deux pièges de modélisation à ne pas rater.

**Ne pas surcharger `date`.** Pour un document, la date utile est celle *du
document* (émission d'une facture, délivrance d'un passeport), pas celle du
classement. D'où `doc_date` séparé.

**`expires` se connecte naturellement aux routines de neverland** (rappel
annuel « vérifier le passeport »). Ne rien coder pour ça maintenant, mais le
champ ne coûte rien à poser.

## L'identifiant `id`

C'est l'unique mécanisme qui rend les liens résilients au renommage. Trois
règles, chacune corrige une erreur classique.

**1. L'identifiant ne doit rien signifier.** Surtout pas un hash des
métadonnées : corriger une faute de frappe changerait l'identifiant et casserait
tous les liens. Un `uuid4`, ou 8 caractères aléatoires en base32 pour la
lisibilité. Posé à la création, jamais retouché.

**2. L'identifiant vit dans le fichier, pas dans une table.** C'est le mécanisme
`id:` d'org-mode : l'identité est stockée dans la cible. Conséquence décisive,
un `mv` fait à la main hors de l'application ne casse rien, puisqu'un scan de
l'arbre reconstruit l'index en entier.

**3. L'index `id -> chemin` est un cache dérivé, jamais une source de vérité.**
Reconstructible par scan, donc incorruptible : au pire il est périmé et on le
régénère. Corollaire, la « table du passé » (`chemin -> id`) envisagée un moment
est **inutile** : elle ne sert qu'à répondre « cet ancien chemin, c'était
quoi ? », question que personne ne pose si les liens ne contiennent pas de
chemin.

À poser dès la première page créée, même sans écrire une ligne de résolution
par `id`. C'est une ligne de frontmatter, et c'est impossible à rétro-ajouter
proprement une fois qu'il y a trois cents pages. C'est aussi ce qui permettra à
**neverland** de pointer vers un document de façon durable.

## Liens : bâtir sur `[[slug]]`

Le site résout déjà `[[slug]]`, `[[domaine/type/slug]]` et `[[slug|texte]]`, et
signale les cibles introuvables au lieu de les perdre. C'est déjà une
indirection : déplacer une page d'un domaine à l'autre ne casse rien, seul le
renommage du slug casse.

L'extension naturelle est donc **l'embarquement d'un fichier de document** dans
une note, avec la même syntaxe :

```markdown
![[diagram-flux]]                  # embarque le fichier `file:` du document
![[diagram-flux/diagram.png]]      # embarque un fichier précis du dossier
[[passeport]]                      # simple lien vers la page du document
```

À préférer nettement à un chemin absolu `![](/dev/doc/diagram-flux/diagram.png)`,
qui casse au moindre déplacement et contourne le mécanisme existant.

Ordre de résolution, du moins cher au plus robuste :

1. le slug (comportement actuel) ;
2. si le slug ne résout pas, l'`id` dans l'index dérivé ;
3. si résolu par `id`, une commande `fix-links` peut **réécrire le fichier**
   avec le slug à jour. Le système s'auto-répare et les fichiers restent
   lisibles.

Filet de sécurité déterministe à ajouter, dans la lignée du hook `pre-commit`
qui tamponne déjà les dates : un `check-links` qui parcourt les pages, extrait
les cibles internes et **refuse le commit** sur un lien mort.

Alternative plus simple, à considérer avant de coder la résolution par `id` :
une commande `mv-page ancien nouveau` qui déplace **et** réécrit les
références, plus `check-links` comme filet. Une cinquantaine de lignes, zéro
concept nouveau, et ça couvre le cas nominal (les renommages de slug se
comptent en quelques-uns par an).

## Rendu par extension

Brancher sur la **présence de `file:` dans le frontmatter**, pas sur le type de
la taxonomie : c'est le fait structurel, il reste vrai si d'autres types de
documents apparaissent.

```
si le frontmatter a `file:` :
    rendre le corps Markdown        # les notes, comme aujourd'hui
    puis rendre le fichier selon son extension
sinon :
    rendre le corps Markdown        # comportement actuel, inchangé
```

| Extension | Rendu | Note |
|---|---|---|
| `png` `jpg` `webp` `svg` | `<img>` | trivial |
| `pdf` | `<embed>` | Firefox et Chrome les rendent nativement |
| `txt` `py` `md` `csv` | Pygments | l'outillage existe déjà (`gen_pygments.py`) |
| `epub` | lecteur JS auto-hébergé | à évaluer, voir ci-dessous |
| `docx` `xlsx` `pptx` | lien de téléchargement | rendre en HTML demande un LibreOffice headless, disproportionné |

Tout le reste tombe sur le lien de téléchargement. C'est un mode de repli
acceptable, pas un échec.

Pour un document **multi-fichiers** (recto-verso, contrat en trois pages), la
règle naturelle est « tous les fichiers du dossier sauf `index.md` ». Garder
quand même `file:` explicite au début : c'est plus lisible dans le frontmatter,
et ça évite qu'un fichier temporaire oublié se retrouve affiché sur le site.

## Décision à trancher : les fichiers lourds

C'est le point le plus structurant, et l'objectif « ouvrir un bouquin » le rend
urgent.

**Git ne pardonne rien avec les binaires.** Un fichier de 40 Mo ajouté puis
supprimé reste dans l'historique pour toujours. Des scans administratifs et des
PDF de quelques Mo, aucun problème. Une bibliothèque de livres, en particulier
des PDF scannés à 50-100 Mo, tue le dépôt en deux ans, et c'est irréversible
sans réécriture d'historique.

Trois options, à choisir **avant** d'ajouter le premier livre :

1. **Plafond dur** dans `add-file` (par exemple 20 Mo) avec un message
   d'erreur explicite. Simple, protège le dépôt, mais exclut les livres.
2. **git-lfs** sur le dépôt de contenu. Garde tout au même endroit, au prix
   d'une dépendance supplémentaire et d'une configuration à ne pas rater.
3. **Séparer la médiathèque** : le dossier du document est versionné (donc
   `index.md`, les métadonnées, l'`id`), mais les fichiers lourds vivent dans
   un espace non versionné, référencé par un champ `media:`. Le dépôt reste
   léger et diffable ; la sauvegarde des médias devient un problème distinct,
   à traiter séparément (rsync, disque externe).

Recommandation : **option 1 maintenant** (elle ne ferme aucune porte), et
basculer vers 3 le jour où la bibliothèque de livres arrive réellement.

## Confidentialité

Un scan de passeport ou de pièce d'identité dans un dépôt git est parfaitement
sûr **tant que ce dépôt reste local**. S'il est poussé un jour sur un remote,
même privé, les pièces d'identité sont chez un tiers, et l'historique git rend
le retrait très pénible.

À trancher avant d'ajouter le premier document sensible, pas après :

- remote strictement local (autre disque, machine du réseau), ou
- chiffrement (`git-crypt`, `age`) sur le dépôt de contenu, ou
- le domaine `administratif` reste hors remote.

## Recherche

La recherche plein-texte actuelle fonctionne sur du Markdown. **Une image ou un
PDF scanné est opaque pour elle.** Conséquence directe : les métadonnées
saisies à l'ajout *sont* l'index. Si la saisie est bâclée, le document est
perdu.

Deux implications pratiques :

- prompter **peu de champs mais bien choisis**, et laisser le corps de
  `index.md` en texte libre, puisque c'est lui qui est indexé, pas le
  frontmatter ;
- à terme, une extraction de texte à l'ajout, qui rendrait les documents
  réellement cherchables sans écrire une ligne de code de recherche :
  - `pdftotext` (paquet `poppler-utils`) pour les PDF ayant déjà une couche
    texte, ce qui est le cas le plus fréquent : extraction exacte, instantanée ;
  - `tesseract` (OCR) uniquement pour les images et les PDF purement scannés ;
    `ocrmypdf` fait cet arbitrage automatiquement.

Le texte extrait irait dans le corps de `index.md`, dans une section repliée
pour ne pas polluer l'affichage.

## Accès multi-appareil

L'objectif « consulter depuis n'importe quel appareil » suppose que le site
tourne en permanence quelque part, et pas seulement en `pixi run serve` local.

Le chemin est le même que pour neverland, et les deux services peuvent partager
l'infrastructure : un serveur sur le réseau, exposé via **WireGuard**, avec une
authentification applicative en défense en profondeur. Points d'attention
spécifiques à ce site :

- servir en **ASGI** (le SSE du live reload ne survit pas au WSGI) ;
- le live reload par polling de `mtime` n'a de sens qu'en édition locale, il
  faut pouvoir le désactiver en mode servi ;
- les polices et MathJax sont déjà auto-hébergées, donc rien à changer côté
  hors-ligne.

## Étapes proposées

Chacune a de la valeur seule et ne dépend pas des suivantes.

1. Poser `id:` dans le frontmatter de toute nouvelle page (une ligne, gratuit,
   impossible à rétro-ajouter plus tard).
2. `check-links` en `pre-commit`, sur les `[[slug]]` existants.
3. `add-file` + le champ `file:` + le rendu image / PDF / téléchargement.
4. `pixi run path` et `pixi run open`.
5. `![[…]]` pour embarquer un document dans une note.
6. Extraction de texte (`pdftotext`, puis OCR).
7. Résolution par `id` et `fix-links`, seulement si `mv-page` s'avère
   insuffisant à l'usage.

## Questions ouvertes

- Nom du type dans la taxonomie : `doc` ? `piece` ? `media` ?
- `add-file` déplace-t-il le fichier source ou le copie-t-il ? (le déplacement
  garantit l'unicité, la copie est moins brutale en cas d'erreur)
- Option retenue pour les fichiers lourds (voir plus haut).
- Faut-il un lecteur EPUB embarqué, ou le téléchargement suffit-il ?
