from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


def upload_path_to_gcs(*, local_path: Path, gcs_uri: str) -> None:
    try:
        from google.cloud import storage
    except ModuleNotFoundError:
        upload_path_to_gcs_with_gcloud(local_path=local_path, gcs_uri=gcs_uri)
        return

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
    try:
        from google.cloud import storage
    except ModuleNotFoundError:
        upload_text_to_gcs_with_gcloud(text=text, gcs_uri=gcs_uri)
        return

    bucket_name, blob_name = parse_gcs_uri(gcs_uri)
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_string(text, content_type=content_type)


def download_gcs_to_path(*, gcs_uri: str, local_path: Path) -> None:
    try:
        from google.cloud import storage
    except ModuleNotFoundError:
        download_gcs_to_path_with_gcloud(gcs_uri=gcs_uri, local_path=local_path)
        return

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


def upload_path_to_gcs_with_gcloud(*, local_path: Path, gcs_uri: str) -> None:
    require_gcloud()
    if local_path.is_file():
        run_gcloud_storage(["cp", str(local_path), gcs_uri])
        return
    run_gcloud_storage(["cp", "--recursive", str(local_path), gcs_uri])


def upload_text_to_gcs_with_gcloud(*, text: str, gcs_uri: str) -> None:
    require_gcloud()
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as file:
        file.write(text)
        temp_path = Path(file.name)
    try:
        run_gcloud_storage(["cp", str(temp_path), gcs_uri])
    finally:
        temp_path.unlink(missing_ok=True)


def download_gcs_to_path_with_gcloud(*, gcs_uri: str, local_path: Path) -> None:
    require_gcloud()
    local_path.parent.mkdir(parents=True, exist_ok=True)
    run_gcloud_storage(["cp", gcs_uri, str(local_path)])


def require_gcloud() -> None:
    if shutil.which("gcloud") is None:
        raise ModuleNotFoundError(
            "google-cloud-storage is not installed and gcloud is not available on PATH."
        )


def run_gcloud_storage(args: list[str]) -> None:
    subprocess.run(["gcloud", "storage", *args], check=True)
