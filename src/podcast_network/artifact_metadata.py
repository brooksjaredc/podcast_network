from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


def local_file_artifact_metadata(path: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    size_bytes = 0
    with path.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            size_bytes += len(chunk)
            digest.update(chunk)
    return {
        "sha256": digest.hexdigest(),
        "size_bytes": size_bytes,
    }


def current_git_sha(*, cwd: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return ""
    return result.stdout.strip()
