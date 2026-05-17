from __future__ import annotations

from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.request import Request, urlopen

DEFAULT_MAX_FEED_BYTES = 25 * 1024 * 1024


@dataclass(frozen=True)
class FetchResult:
    url: str
    status_code: int
    content: bytes
    etag: str = ""
    last_modified: str = ""

    @property
    def changed(self) -> bool:
        return self.status_code != 304


class FeedTooLargeError(ValueError):
    def __init__(self, url: str, max_bytes: int, size_bytes: int | None = None) -> None:
        size = f" ({size_bytes} bytes)" if size_bytes is not None else ""
        super().__init__(f"Feed exceeds max size {max_bytes} bytes{size}: {url}")
        self.url = url
        self.max_bytes = max_bytes
        self.size_bytes = size_bytes


def fetch_feed(
    url: str,
    *,
    etag: str = "",
    last_modified: str = "",
    timeout_seconds: int = 20,
    max_bytes: int = DEFAULT_MAX_FEED_BYTES,
    user_agent: str = "podcast-network-ingest/0.1",
) -> FetchResult:
    headers = {"User-Agent": user_agent}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            content_length = response.headers.get("Content-Length")
            if content_length and max_bytes > 0 and int(content_length) > max_bytes:
                raise FeedTooLargeError(
                    url=response.url,
                    max_bytes=max_bytes,
                    size_bytes=int(content_length),
                )
            return FetchResult(
                url=response.url,
                status_code=response.status,
                content=read_bounded(response, max_bytes=max_bytes, url=response.url),
                etag=response.headers.get("ETag", ""),
                last_modified=response.headers.get("Last-Modified", ""),
            )
    except HTTPError as exc:
        if exc.code == 304:
            return FetchResult(url=url, status_code=304, content=b"")
        raise


def read_bounded(response, *, max_bytes: int, url: str) -> bytes:
    if max_bytes <= 0:
        return response.read()
    chunks = []
    total = 0
    while True:
        chunk = response.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise FeedTooLargeError(url=url, max_bytes=max_bytes, size_bytes=total)
        chunks.append(chunk)
    return b"".join(chunks)
