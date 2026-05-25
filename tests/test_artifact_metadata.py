from __future__ import annotations

import hashlib

from podcast_network.artifact_metadata import local_file_artifact_metadata


def test_local_file_artifact_metadata_records_sha256_and_size(tmp_path) -> None:
    path = tmp_path / "model.joblib"
    content = b"example model bytes"
    path.write_bytes(content)

    metadata = local_file_artifact_metadata(path)

    assert metadata == {
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }
