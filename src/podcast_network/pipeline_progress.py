from __future__ import annotations

from typing import Any

from django.utils import timezone

from podcast_network.web.catalog.models import PipelineRun, PipelineStepRun


def update_pipeline_step_progress(
    *,
    run_label: str,
    command: str,
    metadata: dict[str, Any],
) -> bool:
    if not run_label:
        return False
    step = (
        PipelineStepRun.objects.filter(
            pipeline_run__run_label=run_label,
            pipeline_run__status=PipelineRun.Status.RUNNING,
            command=command,
        )
        .order_by("-pipeline_run__started_at", "sequence")
        .first()
    )
    if step is None:
        return False
    step.metadata = {
        **step.metadata,
        **metadata,
        "last_progress_at": timezone.now().isoformat(),
    }
    step.save(update_fields=["metadata"])
    return True
