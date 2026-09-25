"""Data classes: download tasks, chunks, sniffed items, remote info."""

from __future__ import annotations

import time

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .config import DEFAULT_THREADS


class TaskState(Enum):
    QUEUED = "Queued"
    CONNECTING = "Connecting"
    DOWNLOADING = "Downloading"
    MERGING = "Merging"
    PAUSED = "Paused"
    COMPLETED = "Completed"
    ERROR = "Error"
    CANCELLED = "Cancelled"
    SCHEDULED = "Scheduled"


ACTIVE_STATES = {TaskState.CONNECTING, TaskState.DOWNLOADING, TaskState.MERGING}


RESUMABLE_STATES = {TaskState.PAUSED, TaskState.ERROR, TaskState.CANCELLED,
                    TaskState.SCHEDULED}


QUIET_SOURCES = {"sniffer", "batch", "playlist"}   # bulk downloads: no pop-up windows


@dataclass
class ChunkInfo:
    index: int
    start: int
    end: int | None               # inclusive; None = unknown size (stream to EOF)
    downloaded: int = 0
    part_path: Path | None = None
    completed: bool = False

    @property
    def length(self) -> int | None:
        return None if self.end is None else self.end - self.start + 1


@dataclass
class DownloadTask:
    id: str
    url: str
    save_dir: Path
    filename: str
    total_size: int = 0
    downloaded: int = 0
    state: TaskState = TaskState.QUEUED
    num_threads: int = DEFAULT_THREADS
    chunks: list[ChunkInfo] = field(default_factory=list)
    resumable: bool = False
    etag: str | None = None
    last_modified: str | None = None
    speed_bps: float = 0.0
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    error: str | None = None
    auto_name: bool = False       # filename may be replaced by Content-Disposition
    referer: str | None = None    # page the item was sniffed on (hotlink checks)
    source: str = "manual"        # "manual" | "sniffer" | "browser" | "youtube"
    user_agent: str | None = None # browser's UA for intercepted downloads
    cookies: str | None = None    # browser cookies — kept in memory only, never saved
    engine: str = "http"          # "http" (segmented) | "ytdlp"
    yt_choice: str | None = None  # yt-dlp quality choice: v1080, v720, a_m4a, a_mp3, best
    overwrite: bool = False       # replace an existing file with the same name
    refreshed: bool = False       # new address just set → skip the ETag check once
    cookie_jar: list | None = None  # browser cookies for yt-dlp (memory only)

    @property
    def headers(self) -> dict[str, str]:
        h = {}
        if self.referer:
            h["Referer"] = self.referer
        if self.user_agent:
            h["User-Agent"] = self.user_agent
        if self.cookies:
            h["Cookie"] = self.cookies
        return h

    @property
    def final_path(self) -> Path:
        return self.save_dir / self.filename

    @property
    def progress(self) -> float:
        if self.state == TaskState.COMPLETED:
            return 1.0
        if self.total_size <= 0:
            return 0.0
        return min(1.0, self.downloaded / self.total_size)

    @property
    def eta_seconds(self) -> float | None:
        if self.total_size <= 0 or self.speed_bps <= 0:
            return None
        return max(0.0, (self.total_size - self.downloaded) / self.speed_bps)


@dataclass
class DetectedItem:
    id: str
    url: str
    kind: str                     # "media" | "image"
    mime: str | None
    page: str | None
    ts: float
    size: int | None = None
    queued: bool = False          # already sent to Downloads?

    def to_json(self) -> dict:
        return {"id": self.id, "url": self.url, "type": self.kind,
                "mime": self.mime, "page": self.page, "ts": self.ts,
                "size": self.size, "queued": self.queued}


@dataclass
class RemoteInfo:
    final_url: str
    total_size: int = 0
    resumable: bool = False
    filename: str | None = None
    etag: str | None = None
    last_modified: str | None = None
