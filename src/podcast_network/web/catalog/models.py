from __future__ import annotations

from django.db import models


class Podcast(models.Model):
    name = models.CharField(max_length=500, unique=True)
    description = models.TextField(blank=True)
    website_url = models.URLField(max_length=1000, blank=True)
    image_url = models.URLField(max_length=1000, blank=True)
    external_id = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Feed(models.Model):
    podcast = models.ForeignKey(Podcast, on_delete=models.CASCADE, related_name="feeds")
    url = models.URLField(max_length=1000, unique=True)
    active = models.BooleanField(default=True)
    parser_hint = models.CharField(max_length=100, blank=True)
    etag = models.CharField(max_length=500, blank=True)
    last_modified = models.CharField(max_length=500, blank=True)
    last_status = models.PositiveIntegerField(null=True, blank=True)
    last_fetched_at = models.DateTimeField(null=True, blank=True)
    last_content_hash = models.CharField(max_length=64, blank=True)
    failure_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["podcast__name", "url"]

    def __str__(self) -> str:
        return self.url


class ScrapeRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        PARTIAL = "partial", "Partial"
        FAILED = "failed", "Failed"

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RUNNING)
    feeds_requested = models.PositiveIntegerField(default=0)
    feeds_succeeded = models.PositiveIntegerField(default=0)
    feeds_failed = models.PositiveIntegerField(default=0)
    parser_version = models.CharField(max_length=50, default="rss-v1")

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"ScrapeRun #{self.pk or 'new'} {self.status}"


class RawFeedSnapshot(models.Model):
    feed = models.ForeignKey(Feed, on_delete=models.CASCADE, related_name="snapshots")
    scrape_run = models.ForeignKey(
        ScrapeRun,
        on_delete=models.CASCADE,
        related_name="raw_snapshots",
    )
    storage_uri = models.CharField(max_length=1000)
    content_hash = models.CharField(max_length=64)
    fetched_at = models.DateTimeField()
    http_status = models.PositiveIntegerField()
    etag = models.CharField(max_length=500, blank=True)
    last_modified = models.CharField(max_length=500, blank=True)
    size_bytes = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["feed", "content_hash"],
                name="unique_raw_snapshot_per_feed_hash",
            )
        ]
        ordering = ["-fetched_at"]

    def __str__(self) -> str:
        return f"{self.feed_id}:{self.content_hash[:12]}"


class Episode(models.Model):
    podcast = models.ForeignKey(Podcast, on_delete=models.CASCADE, related_name="episodes")
    guid = models.CharField(max_length=1000)
    title = models.CharField(max_length=1000)
    description = models.TextField(blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    episode_url = models.URLField(max_length=1000, blank=True)
    enclosure_url = models.URLField(max_length=1000, blank=True)
    duration_raw = models.CharField(max_length=100, blank=True)
    explicit = models.BooleanField(null=True, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["podcast", "guid"], name="unique_episode_guid")
        ]
        indexes = [
            models.Index(fields=["podcast", "published_at"]),
            models.Index(fields=["guid"]),
        ]
        ordering = ["-published_at", "title"]

    def __str__(self) -> str:
        return self.title


class Person(models.Model):
    name = models.CharField(max_length=500, unique=True)
    normalized_name = models.CharField(max_length=500, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Appearance(models.Model):
    class Role(models.TextChoices):
        HOST = "host", "Host"
        GUEST = "guest", "Guest"

    episode = models.ForeignKey(Episode, on_delete=models.CASCADE, related_name="appearances")
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="appearances")
    role = models.CharField(max_length=20, choices=Role.choices)
    source = models.CharField(max_length=100, blank=True)
    confidence = models.FloatField(default=1.0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["episode", "person", "role"],
                name="unique_episode_person_role",
            )
        ]

    def __str__(self) -> str:
        return f"{self.person} {self.role} on {self.episode}"


class ScrapeError(models.Model):
    class Stage(models.TextChoices):
        FETCH = "fetch", "Fetch"
        PARSE = "parse", "Parse"
        PERSIST = "persist", "Persist"

    scrape_run = models.ForeignKey(ScrapeRun, on_delete=models.CASCADE, related_name="errors")
    feed = models.ForeignKey(Feed, on_delete=models.CASCADE, related_name="errors")
    stage = models.CharField(max_length=20, choices=Stage.choices)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.stage}: {self.message[:80]}"


class ExtractionRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        PARTIAL = "partial", "Partial"
        FAILED = "failed", "Failed"

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RUNNING)
    model = models.CharField(max_length=100)
    prompt_version = models.CharField(max_length=50)
    provider = models.CharField(max_length=50, default="openai")
    episodes_requested = models.PositiveIntegerField(default=0)
    episodes_succeeded = models.PositiveIntegerField(default=0)
    episodes_failed = models.PositiveIntegerField(default=0)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"ExtractionRun #{self.pk or 'new'} {self.prompt_version} {self.model}"


class EpisodeGuestExtraction(models.Model):
    class Status(models.TextChoices):
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    episode = models.ForeignKey(Episode, on_delete=models.CASCADE, related_name="guest_extractions")
    extraction_run = models.ForeignKey(
        ExtractionRun,
        on_delete=models.CASCADE,
        related_name="episode_extractions",
    )
    status = models.CharField(max_length=20, choices=Status.choices)
    prompt_version = models.CharField(max_length=50)
    model = models.CharField(max_length=100)
    input_text = models.TextField()
    raw_response = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["episode", "prompt_version", "model"],
                name="unique_episode_guest_extraction_model_prompt",
            )
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.episode_id} {self.prompt_version} {self.status}"


class GuestCandidate(models.Model):
    extraction = models.ForeignKey(
        EpisodeGuestExtraction,
        on_delete=models.CASCADE,
        related_name="guest_candidates",
    )
    name = models.CharField(max_length=500)
    confidence = models.FloatField(default=0)
    evidence = models.TextField(blank=True)
    normalized_name = models.CharField(max_length=500, blank=True)
    accepted = models.BooleanField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-confidence", "name"]

    def __str__(self) -> str:
        return self.name


class PodcastHostExtraction(models.Model):
    class Status(models.TextChoices):
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    podcast = models.ForeignKey(Podcast, on_delete=models.CASCADE, related_name="host_extractions")
    extraction_run = models.ForeignKey(
        ExtractionRun,
        on_delete=models.CASCADE,
        related_name="podcast_host_extractions",
    )
    status = models.CharField(max_length=20, choices=Status.choices)
    prompt_version = models.CharField(max_length=50)
    model = models.CharField(max_length=100)
    input_text = models.TextField()
    raw_response = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["podcast", "prompt_version", "model"],
                name="unique_podcast_host_extraction_model_prompt",
            )
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.podcast_id} {self.prompt_version} {self.status}"


class HostCandidate(models.Model):
    class Kind(models.TextChoices):
        HOST = "host", "Host"
        COHOST = "cohost", "Co-host"

    extraction = models.ForeignKey(
        PodcastHostExtraction,
        on_delete=models.CASCADE,
        related_name="host_candidates",
    )
    name = models.CharField(max_length=500)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    confidence = models.FloatField(default=0)
    evidence = models.TextField(blank=True)
    normalized_name = models.CharField(max_length=500, blank=True)
    accepted = models.BooleanField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["kind", "-confidence", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.kind})"
