from django.urls import path

from podcast_network.web.explorer import db_views
from podcast_network.web.explorer.advanced import views as advanced_views
from podcast_network.web.explorer.advanced.assets import plot_asset

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
    path("map/", advanced_views.advanced, {"page": "map"}, name="map"),
    path("advanced/plots/<path:asset_path>", plot_asset, name="plot_asset"),
    path("advanced/", advanced_views.advanced, name="advanced"),
    path("advanced/<slug:page>/", advanced_views.advanced, name="advanced_page"),
]
