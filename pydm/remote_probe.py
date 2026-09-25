"""HEAD / Range probing of a download URL."""

from __future__ import annotations

import httpx
import re

from .models import RemoteInfo
from .utils import http_error, parse_content_disposition


class RemoteProbe:
    """Finds out size, resume support, file name and validators of a URL."""

    @staticmethod
    async def run(client: httpx.AsyncClient, url: str,
                    headers: dict[str, str] | None = None) -> RemoteInfo:
        """HEAD the URL; fall back to GET with Range: bytes=0-0 when needed."""
        info = RemoteInfo(final_url=url)
        headers = headers or {}

        try:
            r = await client.head(url, headers=headers)
            if r.status_code < 400:
                info.final_url = str(r.url)
                info.total_size = int(r.headers.get("content-length") or 0)
                info.resumable = r.headers.get("accept-ranges", "").lower() == "bytes"
                info.filename = parse_content_disposition(r.headers.get("content-disposition"))
                info.etag = r.headers.get("etag")
                info.last_modified = r.headers.get("last-modified")
        except httpx.HTTPError:
            pass  # many servers reject HEAD — the GET below decides

        if info.total_size > 0 and info.resumable:
            return info

        # Range test: 206 → ranges supported, 200 → server ignores ranges
        async with client.stream("GET", url, headers={**headers, "Range": "bytes=0-0"}) as r:
            if r.status_code == 206:
                info.resumable = True
                m = re.search(r"/(\d+)\s*$", r.headers.get("content-range", ""))
                if m:
                    info.total_size = int(m.group(1))
                else:  # "bytes 0-0/*" → unknown size, can't split
                    info.resumable = False
                    info.total_size = 0
            elif r.status_code == 200:
                info.resumable = False
                info.total_size = int(r.headers.get("content-length") or 0)
            else:
                raise http_error(r.status_code)
            info.final_url = str(r.url)
            info.filename = info.filename or parse_content_disposition(
                r.headers.get("content-disposition"))
            info.etag = info.etag or r.headers.get("etag")
            info.last_modified = info.last_modified or r.headers.get("last-modified")
        return info
