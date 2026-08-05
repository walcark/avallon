"""Django settings for avallon.

Everything a deployment needs to change is read from the environment, with
loopback-only, debug-off defaults: the site must be safe when someone runs it
without reading this file. `avallon setup` writes the env file that overrides
them.

    AVALLON_CONTENT_DIR     the notes repository (else the config pointer)
    AVALLON_DEBUG           0 by default
    AVALLON_SECRET_KEY      generated per process when unset
    AVALLON_ALLOWED_HOSTS   comma separated, loopback by default
    AVALLON_SHOW_PRIVATE    follows debug by default
"""

import os
import secrets
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Root of the Markdown content tree (<domaine>/<type>/<slug>/index.md), plus
# taxonomy.toml. Its location is user-configurable and lives *outside* this
# repo (see avallon.notes.config): the env var, else the config pointer.
from avallon.notes.config import resolve_content_dir  # noqa: E402

CONTENT_DIR = resolve_content_dir()

# Custom Markdown fences (gallery/plot/csv/query). Imported here because
# SuperFences needs the actual callables in its config below, not import
# strings.
from avallon.web.mdx import fences as _fences  # noqa: E402


def _flag(name: str, default: bool) -> bool:
    """Read a boolean from the environment, absent meaning *default*."""
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().lower() not in ("0", "", "false")


# Debug is off unless asked for: it is the one setting whose wrong value turns
# an error page into a dump of the settings, the paths and the source.
DEBUG = _flag("AVALLON_DEBUG", False)

# Generated per process when unset, which is exactly right for a single local
# instance (it only invalidates its own signed cookies on restart) and exactly
# wrong for a deployment, where `avallon setup` writes one into the env file.
SECRET_KEY = os.environ.get("AVALLON_SECRET_KEY") or secrets.token_urlsafe(50)

# Pages carrying `visibility: private` in their frontmatter are personal notes
# that must never leave this machine. When SHOW_PRIVATE is false they vanish
# from the listings, the navigation, the search *and* their own URL (404), so
# publishing the site cannot leak them by a direct link. Shown locally and
# hidden anywhere else, so the default follows debug rather than being a third
# thing to remember.
SHOW_PRIVATE = _flag("AVALLON_SHOW_PRIVATE", DEBUG)

# Loopback by default. Binding elsewhere means saying which name answers there,
# and `avallon setup` fills this in from the address it was given.
ALLOWED_HOSTS: list[str] = [
    host.strip()
    for host in os.environ.get(
        "AVALLON_ALLOWED_HOSTS", "127.0.0.1,localhost,[::1]"
    ).split(",")
    if host.strip()
]

# The shared secret that guards the site. Empty means no guard, which is only
# safe on loopback: `avallon serve` refuses any other bind without one.
ACCESS_TOKEN = os.environ.get("AVALLON_TOKEN", "").strip()


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "markdownify.apps.MarkdownifyConfig",
    "avallon.web",
]

# django-markdownify configuration, tuned for scientific writing.
#
# BLEACH is turned OFF: the Markdown is authored by the site owner (trusted
# content), not submitted by visitors. Disabling the sanitizer lets the rich
# HTML produced by the extensions below (syntax-highlight spans, MathJax
# wrappers, admonition divs) pass through without whitelisting dozens of
# tags/classes. /!\ If this site ever renders user-submitted Markdown, turn
# BLEACH back on and whitelist tags/attrs explicitly.
MARKDOWNIFY = {
    "default": {
        "BLEACH": False,
        "MARKDOWN_EXTENSIONS": [
            # Core python-markdown extensions
            "markdown.extensions.tables",  # tables
            "markdown.extensions.footnotes",  # [^1] footnotes
            "markdown.extensions.attr_list",  # {: .class #id } on elements
            "markdown.extensions.def_list",  # definition lists
            "markdown.extensions.abbr",  # abbreviations
            "markdown.extensions.md_in_html",  # markdown inside raw HTML blocks
            "markdown.extensions.sane_lists",  # predictable list numbering
            "markdown.extensions.toc",  # heading anchors / [TOC]
            "markdown.extensions.admonition",  # !!! note / warning boxes
            # pymdown-extensions
            "pymdownx.superfences",  # ```lang fenced code boxes
            "pymdownx.highlight",  # Pygments syntax highlighting
            "pymdownx.inlinehilite",  # `#!python inline` code
            "pymdownx.arithmatex",  # LaTeX math -> MathJax
            "pymdownx.tasklist",  # - [ ] task lists
            "pymdownx.caret",  # ^superscript^ and <ins>
            "pymdownx.tilde",  # ~subscript~ and ~~strike~~
            "pymdownx.smartsymbols",  # (c) (tm) --> etc.
            # Local extension: [[slug]] cross-references between pages.
            "avallon.web.mdx.wikilinks",
            # Local extension: {rouge}(texte) inline color spans.
            "avallon.web.mdx.colors",
        ],
        "MARKDOWN_EXTENSION_CONFIGS": {
            # generic=True emits \(...\) / \[...\] spans for MathJax to render
            "pymdownx.arithmatex": {"generic": True},
            # auto_title labels each code box with its lexer name ("Python"),
            # rendered server-side so the language survives with the HTML.
            "pymdownx.highlight": {
                "css_class": "highlight",
                "guess_lang": False,
                "auto_title": True,
            },
            "pymdownx.tasklist": {"custom_checkbox": True},
            "toc": {"permalink": "#"},
            # Local blocks rendered server-side (see avallon/web/mdx/fences.py). Only
            # the custom names are declared: adding custom_fences leaves the
            # generic ```lang code box (with its Pygments title) untouched, so
            # these sit alongside ordinary fenced code.
            "pymdownx.superfences": {
                "custom_fences": [
                    {
                        "name": "gallery",
                        "class": "gallery",
                        "format": _fences.gallery_fence,
                    },
                    {"name": "plot", "class": "plot", "format": _fences.plot_fence},
                    {"name": "csv", "class": "csv", "format": _fences.csv_fence},
                    {"name": "query", "class": "query", "format": _fences.query_fence},
                ],
            },
        },
    },
}

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    # After the session (it reads one) and after CSRF (so the unlock POST is
    # checked like any other), before everything that serves content.
    "avallon.web.security.TokenGateMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "avallon.settings.urls"

# Sessions in a signed cookie rather than in the database: the only thing a
# session ever holds here is "this browser knows the token", and a note site
# has no database worth starting for one boolean.
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
SESSION_COOKIE_SAMESITE = "Lax"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "avallon.web.context_processors.navigation",
            ],
        },
    },
]

WSGI_APPLICATION = "avallon.settings.wsgi.application"


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

_PASSWORD_VALIDATION = "django.contrib.auth.password_validation"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": f"{_PASSWORD_VALIDATION}.UserAttributeSimilarityValidator"},
    {"NAME": f"{_PASSWORD_VALIDATION}.MinimumLengthValidator"},
    {"NAME": f"{_PASSWORD_VALIDATION}.CommonPasswordValidator"},
    {"NAME": f"{_PASSWORD_VALIDATION}.NumericPasswordValidator"},
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = "static/"
