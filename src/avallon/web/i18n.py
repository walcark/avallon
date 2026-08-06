"""Interface translations, as one dictionary per language.

Forty strings do not justify gettext: a `.po` catalogue would have to be
compiled to `.mo`, which means a build step, a system dependency and binary
files inside the wheel, all to translate what fits on one screen.

The English text *is* the key. A template reads ``{{ "Contents"|t }}``, so a
missing translation degrades to English rather than to a bare identifier, and
adding a string costs nothing until someone wants it in another language.
"""

from __future__ import annotations

FRENCH: dict[str, str] = {
    # Navigation and chrome
    "My notes": "Mes notes",
    "Contents": "Contenu",
    "Content navigation": "Navigation du contenu",
    "Dossier": "Dossier",
    "Dossier navigation": "Navigation du dossier",
    "Everything": "Tout le contenu",
    "Show or hide the menu": "Afficher ou masquer le menu",
    "Toggle the light/dark theme": "Basculer le thème clair/sombre",
    "New page": "Nouvelle page",
    "Create a new page": "Créer une nouvelle page",
    "Home": "Accueil",
    # Home page
    "Search the notes…": "Rechercher dans le contenu…",
    "Domain": "Domaine",
    "Type": "Type",
    "State": "État",
    "Tags": "Tags",
    "page": "page",
    "pages": "pages",
    "result": "résultat",
    "results": "résultats",
    "No result for": "Aucun résultat pour",
    # Page
    "Table of contents": "Sommaire",
    "private": "privé",
    "This page is only visible locally": "Cette page n'est visible qu'en local",
    "min read": "min de lecture",
    "The pages of this dossier": "Les pages de ce dossier",
    "Cited by": "Cité par",
    "Previous image": "Image précédente",
    "Next image": "Image suivante",
    "Close": "Fermer",
    "Copied": "Copié",
    "Copy": "Copier",
    # Editor
    "Edit the Markdown of this page": "Éditer le Markdown de cette page",
    "Edit (Ctrl+E)": "Éditer (Ctrl+E)",
    "Markdown source of the page": "Source Markdown de la page",
    "Save": "Enregistrer",
    "Saved and committed": "Enregistré et commité",
    "Saved (unversioned)": "Enregistré (non versionné)",
    "Saving failed (network).": "Échec de l'enregistrement (réseau).",
    "The file changed on disk. Reload before saving.": (
        "Le fichier a changé sur le disque. Recharge avant d'enregistrer."
    ),
    "Unsaved changes. Close anyway?": "Modifications non enregistrées. Fermer ?",
    "Save your changes before moving the page.": (
        "Enregistre tes modifications avant de déplacer la page."
    ),
    "Move to": "Déplacer vers",
    "Moving…": "Déplacement…",
    "Move": "Déplacer",
    "Moving failed.": "Échec du déplacement.",
    "Moving failed (network).": "Échec du déplacement (réseau).",
    "Destination domain": "Domaine de destination",
    "Destination type": "Type de destination",
    "Toggle the reading width (narrow / wide)": (
        "Basculer la largeur de lecture (restreint / étendu)"
    ),
    "Reading width": "Largeur de lecture",
    "Export this page": "Exporter cette page",
    "Export (Word or PDF)": "Exporter (Word ou PDF)",
    "Export to": "Exporter en",
    # Command palette
    "Command palette": "Palette de commandes",
    "Go to a page, search, run…": "Aller à une page, rechercher, exécuter…",
    "No result.": "Aucun résultat.",
    "navigate": "naviguer",
    "open": "ouvrir",
    "close": "fermer",
    # Creation form
    "Title": "Titre",
    "Summary": "Résumé",
    "one sentence, shown on the home page": "une phrase, affichée sur l'accueil",
    "comma separated": "séparés par des virgules",
    "Choose…": "Choisir…",
    "Create and edit": "Créer et éditer",
    "Cancel": "Annuler",
    "None": "Aucun",
    # Unlock page
    "Unlock": "Déverrouiller",
    "These notes are locked": "Ces notes sont verrouillées",
    "Enter the access token to open a session on this device.": (
        "Saisis le jeton d'accès pour ouvrir la session sur cet appareil."
    ),
    "Access token": "Jeton d'accès",
    "Invalid token.": "Jeton invalide.",
    # Creation form, the help texts that carry the model
    "The domain and the type come from": "Le domaine et le type viennent de",
    "The page is created empty and opens straight in the editor.": (
        "La page est créée vide et s'ouvre directement dans l'éditeur."
    ),
    'The first "yes" wins:': "La première réponse « oui » gagne :",
    "it points elsewhere rather than saying something": (
        "ça renvoie vers d'autres choses"
    ),
    "it has a state of progress": "ça a un état d'avancement",
    "it tells about one precise moment": "ça raconte un moment précis",
    "otherwise": "sinon",
    "Fill this in if the page will be": "À remplir si la page sera",
    "archived with the dossier": "archivée avec le dossier",
    "A reusable note stays outside, merely cited.": (
        "Une fiche réutilisable reste hors dossier, simplement citée."
    ),
    "The writing context is a tag, not a domain:": (
        "Le cadre d'écriture est un tag, pas un domaine :"
    ),
    "and both when that is true.": "et les deux quand c'est vrai.",
    "or": "ou",
    "work": "travail",
    "personal": "perso",
}

CATALOGS: dict[str, dict[str, str]] = {"fr": FRENCH}


def translate(text: str, language: str) -> str:
    """Return *text* in *language*, falling back to *text* itself."""
    return CATALOGS.get(language, {}).get(text, text)
