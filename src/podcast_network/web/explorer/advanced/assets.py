from __future__ import annotations

import mimetypes
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.http import Http404, HttpRequest, HttpResponse
from django.views.decorators.clickjacking import xframe_options_sameorigin

from podcast_network.cloud_artifacts import parse_gcs_uri


@xframe_options_sameorigin
def plot_asset(request: HttpRequest, asset_path: str) -> HttpResponse:
    if not is_safe_plot_asset_path(asset_path):
        raise Http404("Plot asset not found")
    gcs_uri = str(getattr(settings, "PLOT_ARTIFACT_GCS_URI", ""))
    if gcs_uri:
        try:
            return gcs_plot_asset_response(asset_path=asset_path, gcs_uri=gcs_uri)
        except Exception:
            if not settings.DEBUG:
                raise Http404("Plot asset not found") from None
    static_path = f"plots/{asset_path}"
    local_path = finders.find(static_path)
    if not local_path:
        raise Http404("Plot asset not found")
    return HttpResponse(
        Path(local_path).read_bytes(),
        content_type=plot_content_type(asset_path),
    )


def gcs_plot_asset_response(*, asset_path: str, gcs_uri: str) -> HttpResponse:
    from google.cloud import storage

    bucket_name, blob_prefix = parse_gcs_uri(gcs_uri)
    blob_name = f"{blob_prefix.rstrip('/')}/{asset_path}"
    blob = storage.Client().bucket(bucket_name).blob(blob_name)
    if not blob.exists():
        raise Http404("Plot asset not found")
    response = HttpResponse(blob.download_as_bytes(), content_type=plot_content_type(asset_path))
    response["Cache-Control"] = "public, max-age=300"
    return response


def is_safe_plot_asset_path(asset_path: str) -> bool:
    path = Path(asset_path)
    return (
        bool(asset_path)
        and not path.is_absolute()
        and ".." not in path.parts
        and path.suffix in {".html", ".svg", ".js"}
    )


def plot_content_type(asset_path: str) -> str:
    return mimetypes.guess_type(asset_path)[0] or "application/octet-stream"
