from __future__ import annotations

from django.contrib import admin

from podcast_network.web.catalog.models import (
    Appearance,
    CanonicalPersonEntity,
    Episode,
    EpisodeGuestExtraction,
    ExtractionRun,
    Feed,
    GuestCandidate,
    HostCandidate,
    Person,
    PersonEntityCandidatePair,
    PersonEntityLink,
    PersonEntityPairLabel,
    PersonObservation,
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


@admin.register(PersonObservation)
class PersonObservationAdmin(admin.ModelAdmin):
    search_fields = ["observed_name", "normalized_name", "podcast__name", "episode__title"]
    list_display = ["observation_id", "observed_name", "role", "podcast", "source"]
    list_filter = ["role", "provider", "source"]
    raw_id_fields = ["appearance", "person", "episode", "podcast"]


@admin.register(CanonicalPersonEntity)
class CanonicalPersonEntityAdmin(admin.ModelAdmin):
    search_fields = ["am_entity_id", "display_name", "normalized_name"]
    list_display = ["am_entity_id", "display_name", "observation_count", "resolution_method"]
    list_filter = ["resolution_method"]


@admin.register(PersonEntityLink)
class PersonEntityLinkAdmin(admin.ModelAdmin):
    search_fields = ["observation__observed_name", "canonical__display_name"]
    list_display = ["observation", "canonical", "match_method", "match_probability"]
    list_filter = ["match_method"]
    raw_id_fields = ["observation", "canonical"]


@admin.register(PersonEntityCandidatePair)
class PersonEntityCandidatePairAdmin(admin.ModelAdmin):
    search_fields = ["left__display_name", "right__display_name", "pair_id"]
    list_display = ["left", "right", "status", "match_probability", "model_name"]
    list_filter = ["status", "model_name"]
    raw_id_fields = ["left", "right"]


@admin.register(PersonEntityPairLabel)
class PersonEntityPairLabelAdmin(admin.ModelAdmin):
    search_fields = ["pair__left__display_name", "pair__right__display_name", "notes"]
    list_display = ["pair", "label", "source", "model_name", "match_probability", "created_at"]
    list_filter = ["label", "source", "model_name"]
    raw_id_fields = ["pair"]


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
