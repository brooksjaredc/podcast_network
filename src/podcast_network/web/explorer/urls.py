from django.urls import path

from podcast_network.web.explorer import views

app_name = "explorer"

urlpatterns = [
    path("", views.home, name="home"),
    path("podcasts/", views.podcasts, name="podcasts"),
    path("podcasts/<int:podcast_id>/", views.podcast_detail, name="podcast_detail"),
    path("people/", views.people, name="people"),
    path("people/<int:person_id>/", views.person_detail, name="person_detail"),
    path("rankings/", views.rankings, name="rankings"),
    path("common/", views.common, name="common"),
    path("path/", views.path, name="path"),
    path("advanced/", views.advanced, name="advanced"),
    path("advanced/<slug:page>/", views.advanced, name="advanced_page"),
]
