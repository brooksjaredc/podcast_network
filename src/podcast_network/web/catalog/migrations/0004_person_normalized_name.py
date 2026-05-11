from __future__ import annotations

from django.db import migrations, models


def populate_normalized_names(apps, schema_editor):
    person_model = apps.get_model("catalog", "Person")
    seen = set()
    for person in person_model.objects.order_by("id"):
        normalized = normalize_name(person.name) or f"person-{person.id}"
        candidate = normalized
        suffix = 2
        while candidate in seen or person_model.objects.filter(normalized_name=candidate).exclude(
            id=person.id
        ).exists():
            candidate = f"{normalized}-{suffix}"
            suffix += 1
        person.normalized_name = candidate
        person.save(update_fields=["normalized_name"])
        seen.add(candidate)


def normalize_name(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0003_extractionrun_episodeguestextraction_guestcandidate_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="person",
            name="normalized_name",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.RunPython(populate_normalized_names, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="person",
            name="normalized_name",
            field=models.CharField(max_length=500, unique=True),
        ),
    ]
