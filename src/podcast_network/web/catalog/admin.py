from __future__ import annotations

from django.contrib import admin

from podcast_network.web.catalog.models import (
    Appearance,
    Episode,
    Feed,
    Person,
    Podcast,
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
