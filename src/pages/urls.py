from django.urls import path

from . import views

urlpatterns = [path("", views.MarkDown.as_view(), name="pages")]
