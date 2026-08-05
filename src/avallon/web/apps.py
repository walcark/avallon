from django.apps import AppConfig


class WebConfig(AppConfig):
    name = "avallon.web"
    # Without this, Django would derive the label "web" from the last path
    # segment; the templates and the static namespace both say "avallon".
    label = "avallon_web"
