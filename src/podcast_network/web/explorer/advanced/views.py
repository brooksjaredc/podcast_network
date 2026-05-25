from __future__ import annotations

from copy import deepcopy
from typing import Any

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse

from podcast_network.web.explorer.advanced.predictions import advanced_prediction_context
from podcast_network.web.explorer.content import advanced_pages


def advanced(request: HttpRequest, page: str = "overview") -> HttpResponse:
    pages = advanced_pages_with_asset_urls()
    if page not in pages:
        raise Http404("Advanced page not found")
    return render(
        request,
        "explorer/advanced.html",
        {
            "page": pages[page],
            "pages": pages,
            **(advanced_prediction_context() if page == "predictions" else {}),
        },
    )


def advanced_pages_with_asset_urls() -> dict[str, dict[str, Any]]:
    pages = deepcopy(advanced_pages())
    for item in pages.values():
        for section in item["sections"]:
            if section.get("plot"):
                section["plot_url"] = reverse(
                    "explorer:plot_asset",
                    kwargs={"asset_path": section["plot"].removeprefix("plots/")},
                )
            if section.get("image"):
                section["image_url"] = reverse(
                    "explorer:plot_asset",
                    kwargs={"asset_path": section["image"].removeprefix("plots/")},
                )
    return pages
