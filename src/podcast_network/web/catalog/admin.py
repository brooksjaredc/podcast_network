from __future__ import annotations

from django.contrib import admin

from podcast_network.web.catalog.models import (
    Appearance,
    Episode,
    EpisodeGuestExtraction,
    ExtractionRun,
    Feed,
    GuestCandidate,
    HostCandidate,
    Person,
    Podcast,
    PodcastHostExtraction,
    RawFeedSnapshot,
    ScrapeError,
    ScrapeRun,
)


@admin.register(Podcast)
class PodcastAdmin(admin.ModelAdmin):
    search_fields = ["name"]
    list_display = ["name", "website_url", "updated_at"]


@admin.register(Feed)
class FeedAdmin(admin.ModelAdmin):
    search_fields = ["url", "podcast__name"]
    list_display = ["podcast", "url", "active", "parser_hint", "last_status", "last_fetched_at"]
    list_filter = ["active", "last_status"]


@admin.register(Episode)
class EpisodeAdmin(admin.ModelAdmin):
    search_fields = ["title", "guid", "podcast__name"]
    list_display = ["title", "podcast", "published_at", "last_seen_at"]
    list_filter = ["podcast"]


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    search_fields = ["name"]
    list_display = ["name", "updated_at"]


@admin.register(Appearance)
class AppearanceAdmin(admin.ModelAdmin):
    search_fields = ["person__name", "episode__title"]
    list_display = ["person", "role", "episode", "confidence"]
    list_filter = ["role"]


@admin.register(ScrapeRun)
class ScrapeRunAdmin(admin.ModelAdmin):
    list_display = ["id", "status", "started_at", "finished_at", "feeds_succeeded", "feeds_failed"]
    list_filter = ["status"]


@admin.register(RawFeedSnapshot)
class RawFeedSnapshotAdmin(admin.ModelAdmin):
    search_fields = ["content_hash", "storage_uri", "feed__url"]
    list_display = ["feed", "content_hash", "http_status", "size_bytes", "fetched_at"]


@admin.register(ScrapeError)
class ScrapeErrorAdmin(admin.ModelAdmin):
    search_fields = ["message", "feed__url"]
    list_display = ["stage", "feed", "created_at"]
    list_filter = ["stage"]


@admin.register(ExtractionRun)
class ExtractionRunAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "status",
        "provider",
        "model",
        "prompt_version",
        "episodes_succeeded",
        "episodes_failed",
        "started_at",
    ]
    list_filter = ["status", "provider", "model", "prompt_version"]


@admin.register(EpisodeGuestExtraction)
class EpisodeGuestExtractionAdmin(admin.ModelAdmin):
    search_fields = ["episode__title", "error"]
    list_display = ["episode", "status", "model", "prompt_version", "created_at"]
    list_filter = ["status", "model", "prompt_version"]


@admin.register(GuestCandidate)
class GuestCandidateAdmin(admin.ModelAdmin):
    search_fields = ["name", "evidence", "extraction__episode__title"]
    list_display = ["name", "confidence", "accepted", "extraction"]
    list_filter = ["accepted"]


@admin.register(PodcastHostExtraction)
class PodcastHostExtractionAdmin(admin.ModelAdmin):
    search_fields = ["podcast__name", "error"]
    list_display = ["podcast", "status", "model", "prompt_version", "created_at"]
    list_filter = ["status", "model", "prompt_version"]


@admin.register(HostCandidate)
class HostCandidateAdmin(admin.ModelAdmin):
    search_fields = ["name", "evidence", "extraction__podcast__name"]
    list_display = ["name", "kind", "confidence", "accepted", "extraction"]
    list_filter = ["kind", "accepted"]
