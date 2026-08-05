from django.urls import path

from . import security, views

urlpatterns = [
    path("", views.home, name="home"),
    path("deverrouiller/", security.unlock, name="unlock"),
    path("search/", views.search, name="search"),
    path("stream/", views.markdown_stream, name="stream"),
    path("nouvelle/", views.new_page, name="new"),
    path("source/", views.page_source, name="source"),
    path("save/", views.save_page, name="save"),
    path("move/", views.move_page, name="move"),
    path("export/", views.export_page, name="export"),
    # Catch-all (kept last): resolves a hierarchical URL to a page or a
    # co-located asset in the content tree.
    path("<path:relpath>", views.serve_content, name="content"),
]
