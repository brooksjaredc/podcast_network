from __future__ import annotations

from django.db import migrations, models


def backfill_podcast_flags(apps, schema_editor) -> None:
    podcast_model = apps.get_model("catalog", "Podcast")
    feed_model = apps.get_model("catalog", "Feed")

    for podcast in podcast_model.objects.all().iterator(chunk_size=1000):
        metadata = podcast.metadata or {}
        policy = metadata.get("extraction_policy") or {}
        is_non_interview = (
            policy.get("skip_guest_extraction") is True
            or policy.get("classification") == "non_interview"
        )
        has_active_feed = feed_model.objects.filter(podcast_id=podcast.id, active=True).exists()

        podcast.is_interview_podcast = False if is_non_interview else None
        # Preserve old feed-health signal for truly inactive/dead podcasts, but do
        # not make non-interview classification the only source of inactive status.
        podcast.active = has_active_feed or is_non_interview
        podcast.save(update_fields=["active", "is_interview_podcast"])


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0012_networkevolutionrun_networkevolutionsnapshot_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="podcast",
            name="active",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="podcast",
            name="is_interview_podcast",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_podcast_flags, migrations.RunPython.noop),
    ]
