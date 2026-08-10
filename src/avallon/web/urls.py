from django.urls import path

from . import security, views

urlpatterns = [
    path("", views.home, name="home"),
    path("deverrouiller/", security.unlock, name="unlock"),
    path("search/", views.explore, name="search"),
    path("stream/", views.markdown_stream, name="stream"),
    path("nouvelle/", views.new_page, name="new"),
    path("source/", views.page_source, name="source"),
    path("save/", views.save_page, name="save"),
    path("move/", views.move_page, name="move"),
    path("export/", views.export_page, name="export"),
    path("upload/", views.upload_document, name="upload"),
    path("tags/", views.tags_index, name="tags"),
    path("entretien/", views.upkeep, name="upkeep"),
    path("capture/", views.capture, name="capture"),
    path("history/", views.page_history, name="history"),
    path("thumb/<path:relpath>/", views.thumbnail, name="thumbnail"),
    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("sw.js", views.service_worker, name="service-worker"),
    # Catch-all (kept last): resolves a hierarchical URL to a page or a
    # co-located asset in the content tree.
    path("<path:relpath>", views.serve_content, name="content"),
]
