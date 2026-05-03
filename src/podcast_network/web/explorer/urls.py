from django.urls import path

from podcast_network.web.explorer import views

app_name = "explorer"

urlpatterns = [
    path("", views.home, name="home"),
    path("podcasts/", views.podcasts, name="podcasts"),
    path("podcasts/<int:podcast_id>/", views.podcast_detail, name="podcast_detail"),
    path("people/", views.people, name="people"),
    path("path/", views.path, name="path"),
]

