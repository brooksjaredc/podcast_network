from django.http import HttpResponse
from django.urls import include, path


def healthcheck(_request):
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    path("", include("podcast_network.web.explorer.urls")),
    path("health/", healthcheck, name="healthcheck"),
]
