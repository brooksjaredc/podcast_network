from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from django.utils import timezone

from podcast_network.paths import PROJECT_ROOT


@dataclass(frozen=True)
class StoredObject:
    uri: str
    content_hash: str
    size_bytes: int


class LocalRawFeedStorage:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or PROJECT_ROOT / "data" / "raw"

    def save_feed_snapshot(
        self,
        *,
        feed_id: int,
        content: bytes,
        fetched_at: datetime | None = None,
    ) -> StoredObject:
        fetched_at = fetched_at or timezone.now()
        content_hash = hashlib.sha256(content).hexdigest()
        relative_path = Path("rss") / str(feed_id) / snapshot_filename(fetched_at, content_hash)
        path = self.base_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(content)
        return StoredObject(
            uri=f"file://{path}",
            content_hash=content_hash,
            size_bytes=len(content),
        )


def snapshot_filename(fetched_at: datetime, content_hash: str) -> str:
    timestamp = fetched_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}_{content_hash[:16]}.xml"
