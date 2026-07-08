from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("search/", views.search, name="search"),
    path("stream/", views.markdown_stream, name="stream"),
    # Catch-all (kept last): resolves a hierarchical URL to a page or a
    # co-located asset in the content tree.
    path("<path:relpath>", views.serve_content, name="content"),
]
