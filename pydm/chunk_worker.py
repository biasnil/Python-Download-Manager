"""Downloads one byte range of a file into its own .partN file."""

from __future__ import annotations

import aiofiles
import asyncio
import httpx

from pathlib import Path

from .config import BLOCK_SIZE, MAX_RETRIES
from .errors import PyDMError, RetryableError
from .limiter import TokenBucketLimiter
from .models import ChunkInfo
from .utils import http_error


class ChunkWorker:
    """Downloads one byte range into its own .partN file."""

    def __init__(self, client: httpx.AsyncClient, url: str, chunk: ChunkInfo,
                 headers: dict[str, str] | None, part_path: Path, use_range: bool,
                 limiter: TokenBucketLimiter | None = None, progress_cb=None):
        self.client = client
        self.url = url
        self.chunk = chunk
        self.headers = headers or {}
        self.part_path = part_path
        self.use_range = use_range
        self.limiter = limiter
        self.progress_cb = progress_cb or (lambda n: None)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    async def run(self) -> bool:
        """True when the chunk is complete, False if cancelled."""
        attempt = 0
        while not self._cancelled:
            try:
                return await self._download_once()
            except (httpx.TransportError, RetryableError) as e:
                attempt += 1
                if attempt > MAX_RETRIES:
                    raise PyDMError(f"Chunk {self.chunk.index}: {e or type(e).__name__}") from e
                if not self.use_range and self.chunk.downloaded:
                    # Server can't resume mid-file: throw away and restart
                    self.progress_cb(-self.chunk.downloaded)
                    self.chunk.downloaded = 0
                await asyncio.sleep(min(2 ** attempt, 30))
        return False

    async def _download_once(self) -> bool:
        c = self.chunk
        if c.length is not None and c.downloaded >= c.length:
            c.completed = True
            return True

        headers = dict(self.headers)
        offset = c.start + c.downloaded
        if self.use_range:
            end = "" if c.end is None else str(c.end)
            headers["Range"] = f"bytes={offset}-{end}"

        async with self.client.stream("GET", self.url, headers=headers) as r:
            if r.status_code in (429, 500, 502, 503, 504):
                raise RetryableError(f"HTTP {r.status_code}")
            if r.status_code >= 400:
                raise http_error(r.status_code)
            if self.use_range and r.status_code != 206:
                raise PyDMError("Server stopped honouring Range requests")

            mode = "ab" if c.downloaded else "wb"
            async with aiofiles.open(self.part_path, mode) as f:
                async for block in r.aiter_bytes(BLOCK_SIZE):
                    if self._cancelled:
                        return False
                    if c.length is not None:
                        remaining = c.length - c.downloaded
                        if len(block) > remaining:
                            block = block[:remaining]
                    if self.limiter:
                        await self.limiter.consume(len(block))
                    await f.write(block)
                    c.downloaded += len(block)
                    self.progress_cb(len(block))
                    if c.length is not None and c.downloaded >= c.length:
                        break

        if self._cancelled:
            return False
        if c.length is not None and c.downloaded < c.length:
            raise RetryableError("connection closed early")
        c.completed = True
        return True
