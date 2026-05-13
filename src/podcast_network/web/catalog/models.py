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


class PersonObservation(models.Model):
    class Provider(models.TextChoices):
        APPEARANCE = "appearance", "Appearance"

    observation_id = models.CharField(max_length=64, primary_key=True)
    provider = models.CharField(
        max_length=50,
        choices=Provider.choices,
        default=Provider.APPEARANCE,
    )
    record_id = models.CharField(max_length=64)
    appearance = models.OneToOneField(
        Appearance,
        on_delete=models.CASCADE,
        related_name="person_observation",
    )
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="observations")
    episode = models.ForeignKey(
        Episode,
        on_delete=models.CASCADE,
        related_name="person_observations",
    )
    podcast = models.ForeignKey(
        Podcast,
        on_delete=models.CASCADE,
        related_name="person_observations",
    )
    role = models.CharField(max_length=20, choices=Appearance.Role.choices)
    observed_name = models.CharField(max_length=500)
    normalized_name = models.CharField(max_length=500)
    source = models.CharField(max_length=100, blank=True)
    confidence = models.FloatField(default=1.0)
    context = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["record_id"]),
            models.Index(fields=["normalized_name", "role"]),
            models.Index(fields=["podcast", "role"]),
        ]
        ordering = ["normalized_name", "observation_id"]

    def __str__(self) -> str:
        return f"{self.observed_name} {self.role} observation"


class CanonicalPersonEntity(models.Model):
    am_entity_id = models.CharField(max_length=64, primary_key=True)
    display_name = models.CharField(max_length=500)
    normalized_name = models.CharField(max_length=500, unique=True)
    aliases = models.JSONField(default=list, blank=True)
    roles = models.JSONField(default=list, blank=True)
    observation_count = models.PositiveIntegerField(default=0)
    first_seen_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    resolution_method = models.CharField(max_length=100, default="exact_normalized_name")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["normalized_name"]),
            models.Index(fields=["display_name"]),
        ]
        ordering = ["display_name"]

    def __str__(self) -> str:
        return self.display_name


class PersonEntityLink(models.Model):
    observation = models.OneToOneField(
        PersonObservation,
        on_delete=models.CASCADE,
        related_name="entity_link",
        primary_key=True,
    )
    canonical = models.ForeignKey(
        CanonicalPersonEntity,
        on_delete=models.CASCADE,
        related_name="linked_observations",
    )
    match_method = models.CharField(max_length=100)
    match_probability = models.FloatField(default=1.0)
    dbt_updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["canonical"]),
            models.Index(fields=["match_method"]),
            models.Index(fields=["dbt_updated_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.observation_id} -> {self.canonical_id}"


class PersonEntityCandidatePair(models.Model):
    class Status(models.TextChoices):
        CANDIDATE = "candidate", "Candidate"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"

    pair_id = models.CharField(max_length=64, primary_key=True)
    left = models.ForeignKey(
        CanonicalPersonEntity,
        on_delete=models.CASCADE,
        related_name="left_candidate_pairs",
    )
    right = models.ForeignKey(
        CanonicalPersonEntity,
        on_delete=models.CASCADE,
        related_name="right_candidate_pairs",
    )
    blocking_keys = models.JSONField(default=list, blank=True)
    features = models.JSONField(default=dict, blank=True)
    model_name = models.CharField(max_length=100, blank=True)
    match_probability = models.FloatField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CANDIDATE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["left", "right"],
                name="unique_person_entity_candidate_pair",
            ),
            models.CheckConstraint(
                condition=models.Q(left__lt=models.F("right")),
                name="person_entity_candidate_pair_ordered",
            ),
        ]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["match_probability"]),
        ]
        ordering = ["-match_probability", "left_id", "right_id"]

    def __str__(self) -> str:
        return f"{self.left_id} ? {self.right_id}"


class PersonEntityPairLabel(models.Model):
    class Label(models.TextChoices):
        MATCH = "match", "Match"
        NOT_MATCH = "not_match", "Not match"
        SKIP = "skip", "Skip"

    pair = models.ForeignKey(
        PersonEntityCandidatePair,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="labels",
    )
    pair_id_snapshot = models.CharField(max_length=64, blank=True)
    label = models.CharField(max_length=20, choices=Label.choices)
    source = models.CharField(max_length=100, default="human_active_learning")
    model_name = models.CharField(max_length=100, blank=True)
    match_probability = models.FloatField(null=True, blank=True)
    features = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["label"]),
            models.Index(fields=["source"]),
            models.Index(fields=["created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.pair_id_snapshot}: {self.label}"


class NetworkMetricRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RUNNING)
    graph_version = models.CharField(max_length=50, default="network-metrics-v1")
    person_nodes = models.PositiveIntegerField(default=0)
    person_edges = models.PositiveIntegerField(default=0)
    podcast_nodes = models.PositiveIntegerField(default=0)
    podcast_edges = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"NetworkMetricRun #{self.pk or 'new'} {self.status}"


class PersonNetworkMetric(models.Model):
    run = models.ForeignKey(
        NetworkMetricRun,
        on_delete=models.CASCADE,
        related_name="person_metrics",
    )
    canonical = models.ForeignKey(
        CanonicalPersonEntity,
        on_delete=models.CASCADE,
        related_name="network_metrics",
    )
    display_name = models.CharField(max_length=500)
    representative_person = models.ForeignKey(
        Person,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="represented_network_metrics",
    )
    pagerank = models.FloatField(default=0.0)
    hub = models.FloatField(default=0.0)
    authority = models.FloatField(default=0.0)
    closeness = models.FloatField(default=0.0)
    betweenness = models.FloatField(default=0.0)
    degree_centrality = models.FloatField(default=0.0)
    pagerank_rank = models.PositiveIntegerField(default=0)
    hub_rank = models.PositiveIntegerField(default=0)
    authority_rank = models.PositiveIntegerField(default=0)
    closeness_rank = models.PositiveIntegerField(default=0)
    betweenness_rank = models.PositiveIntegerField(default=0)
    degree_rank = models.PositiveIntegerField(default=0)
    guest_appearances = models.PositiveIntegerField(default=0)
    host_appearances = models.PositiveIntegerField(default=0)
    podcast_count = models.PositiveIntegerField(default=0)
    latest_episode_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["run", "canonical"],
                name="unique_person_network_metric_per_run",
            )
        ]
        indexes = [
            models.Index(fields=["run", "pagerank_rank"]),
            models.Index(fields=["run", "hub_rank"]),
            models.Index(fields=["run", "authority_rank"]),
            models.Index(fields=["run", "closeness_rank"]),
            models.Index(fields=["run", "betweenness_rank"]),
            models.Index(fields=["run", "degree_rank"]),
            models.Index(fields=["canonical"]),
        ]
        ordering = ["pagerank_rank", "display_name"]

    def __str__(self) -> str:
        return f"{self.display_name} metrics for run {self.run_id}"


class PodcastNetworkMetric(models.Model):
    run = models.ForeignKey(
        NetworkMetricRun,
        on_delete=models.CASCADE,
        related_name="podcast_metrics",
    )
    podcast = models.ForeignKey(
        Podcast,
        on_delete=models.CASCADE,
        related_name="network_metrics",
    )
    closeness = models.FloatField(default=0.0)
    betweenness = models.FloatField(default=0.0)
    degree_centrality = models.FloatField(default=0.0)
    closeness_rank = models.PositiveIntegerField(default=0)
    betweenness_rank = models.PositiveIntegerField(default=0)
    degree_rank = models.PositiveIntegerField(default=0)
    shared_guest_edges = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["run", "podcast"],
                name="unique_podcast_network_metric_per_run",
            )
        ]
        indexes = [
            models.Index(fields=["run", "closeness_rank"]),
            models.Index(fields=["run", "betweenness_rank"]),
            models.Index(fields=["run", "degree_rank"]),
            models.Index(fields=["podcast"]),
        ]
        ordering = ["degree_rank", "podcast__name"]

    def __str__(self) -> str:
        return f"{self.podcast} metrics for run {self.run_id}"


class NetworkEvolutionRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        SKIPPED = "skipped", "Skipped"
        FAILED = "failed", "Failed"

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RUNNING)
    graph_version = models.CharField(max_length=50, default="network-evolution-v1")
    weeks_requested = models.PositiveIntegerField(default=0)
    weeks_calculated = models.PositiveIntegerField(default=0)
    start_week = models.DateField(null=True, blank=True)
    end_week = models.DateField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"NetworkEvolutionRun #{self.pk or 'new'} {self.status}"


class NetworkEvolutionSnapshot(models.Model):
    run = models.ForeignKey(
        NetworkEvolutionRun,
        on_delete=models.CASCADE,
        related_name="snapshots",
    )
    week_start = models.DateField()
    cutoff_at = models.DateTimeField()
    person_nodes = models.PositiveIntegerField(default=0)
    person_edges = models.PositiveIntegerField(default=0)
    podcast_count = models.PositiveIntegerField(default=0)
    guest_appearance_count = models.PositiveIntegerField(default=0)
    largest_component_nodes = models.PositiveIntegerField(default=0)
    largest_component_edges = models.PositiveIntegerField(default=0)
    density = models.FloatField(default=0.0)
    average_clustering = models.FloatField(default=0.0)
    transitivity = models.FloatField(default=0.0)
    average_shortest_path_length = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["week_start"],
                name="unique_network_evolution_snapshot_week",
            )
        ]
        indexes = [
            models.Index(fields=["week_start"]),
            models.Index(fields=["run", "week_start"]),
        ]
        ordering = ["week_start"]

    def __str__(self) -> str:
        return f"Network evolution snapshot {self.week_start}"


class PersonNetworkEvolutionMetric(models.Model):
    snapshot = models.ForeignKey(
        NetworkEvolutionSnapshot,
        on_delete=models.CASCADE,
        related_name="person_metrics",
    )
    canonical = models.ForeignKey(
        CanonicalPersonEntity,
        on_delete=models.CASCADE,
        related_name="network_evolution_metrics",
    )
    display_name = models.CharField(max_length=500)
    pagerank = models.FloatField(default=0.0)
    hub = models.FloatField(default=0.0)
    authority = models.FloatField(default=0.0)
    closeness = models.FloatField(default=0.0)
    pagerank_rank = models.PositiveIntegerField(default=0)
    hub_rank = models.PositiveIntegerField(default=0)
    authority_rank = models.PositiveIntegerField(default=0)
    closeness_rank = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot", "canonical"],
                name="unique_person_network_evolution_metric_per_snapshot",
            )
        ]
        indexes = [
            models.Index(fields=["canonical", "snapshot"]),
            models.Index(fields=["snapshot", "pagerank_rank"]),
            models.Index(fields=["snapshot", "hub_rank"]),
            models.Index(fields=["snapshot", "authority_rank"]),
            models.Index(fields=["snapshot", "closeness_rank"]),
        ]
        ordering = ["snapshot__week_start", "pagerank_rank", "display_name"]

    def __str__(self) -> str:
        return f"{self.display_name} evolution metric for {self.snapshot.week_start}"


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
