from __future__ import annotations

from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.request import Request, urlopen


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


def fetch_feed(
    url: str,
    *,
    etag: str = "",
    last_modified: str = "",
    timeout_seconds: int = 20,
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
            return FetchResult(
                url=response.url,
                status_code=response.status,
                content=response.read(),
                etag=response.headers.get("ETag", ""),
                last_modified=response.headers.get("Last-Modified", ""),
            )
    except HTTPError as exc:
        if exc.code == 304:
            return FetchResult(url=url, status_code=304, content=b"")
        raise
