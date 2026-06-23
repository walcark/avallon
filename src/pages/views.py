from pathlib import Path

from django.views.generic import TemplateView

MARKDOWN_FILE = Path(__file__).parent / "templates" / "test.md"


class MarkDown(TemplateView):
    template_name = "index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        with MARKDOWN_FILE.open(encoding="utf-8") as f:
            context["markdowntext"] = f.read()
        return context
