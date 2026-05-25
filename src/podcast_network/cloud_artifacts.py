from __future__ import annotations

from pathlib import Path


def upload_path_to_gcs(*, local_path: Path, gcs_uri: str) -> None:
    from google.cloud import storage

    bucket_name, blob_prefix = parse_gcs_uri(gcs_uri)
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    if local_path.is_file():
        blob = bucket.blob(blob_prefix)
        blob.upload_from_filename(str(local_path))
        return
    for path in local_path.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(local_path).as_posix()
        blob = bucket.blob(f"{blob_prefix.rstrip('/')}/{relative}")
        blob.upload_from_filename(str(path))


def upload_text_to_gcs(*, text: str, gcs_uri: str, content_type: str = "text/plain") -> None:
    from google.cloud import storage

    bucket_name, blob_name = parse_gcs_uri(gcs_uri)
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_string(text, content_type=content_type)


def download_gcs_to_path(*, gcs_uri: str, local_path: Path) -> None:
    from google.cloud import storage

    bucket_name, blob_name = parse_gcs_uri(gcs_uri)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.download_to_filename(str(local_path))


def parse_gcs_uri(gcs_uri: str) -> tuple[str, str]:
    if not gcs_uri.startswith("gs://"):
        raise ValueError("GCS URI must start with gs://")
    path = gcs_uri.removeprefix("gs://")
    bucket_name, _, blob_prefix = path.partition("/")
    if not bucket_name or not blob_prefix:
        raise ValueError("GCS URI must include a bucket and object prefix")
    return bucket_name, blob_prefix
