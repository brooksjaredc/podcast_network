from django.urls import path

from podcast_network.web.explorer import db_views, views

app_name = "explorer"

urlpatterns = [
    path("", db_views.home, name="home"),
    path("podcasts/", db_views.podcasts, name="podcasts"),
    path("podcasts/<int:podcast_id>/", db_views.podcast_detail, name="podcast_detail"),
    path("people/", db_views.people, name="people"),
    path("people/<int:person_id>/", db_views.person_detail, name="person_detail"),
    path("rankings/", db_views.rankings, name="rankings"),
    path("recommendations/", db_views.recommendations, name="recommendations"),
    path("common/", db_views.common, name="common"),
    path("path/", db_views.path, name="path"),
    path("advanced/", views.advanced, name="advanced"),
    path("advanced/<slug:page>/", views.advanced, name="advanced_page"),
]
