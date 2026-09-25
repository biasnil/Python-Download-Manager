"""Partial-download files on disk (segments, sidecar, yt-dlp temp folder)."""

from __future__ import annotations

import json
import os
import re
import shutil

from pathlib import Path

from .models import ChunkInfo, DownloadTask
from .utils import part_path, sidecar_path


class PartFiles:
    """The .partN files + JSON sidecar that make pause/resume survive restarts."""

    @staticmethod
    def load(task: DownloadTask) -> bool:
        """Restore chunk layout from the JSON sidecar; sync offsets with part files."""
        path = sidecar_path(task.save_dir, task.filename)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if data.get("url") != task.url:
            return False
        task.total_size = int(data.get("total_size") or 0)
        task.resumable = bool(data.get("resumable"))
        task.etag = data.get("etag")
        task.last_modified = data.get("last_modified")
        task.chunks = [ChunkInfo(index=c["index"], start=c["start"], end=c["end"],
                                 downloaded=c.get("downloaded", 0))
                       for c in data.get("chunks", [])]
        PartFiles.sync(task)
        return True

    @staticmethod
    def save(task: DownloadTask) -> None:
        """Write the JSON sidecar atomically (tmp file + rename)."""
        if not task.chunks:
            return
        data = {
            "version": 1, "url": task.url, "filename": task.filename,
            "total_size": task.total_size, "resumable": task.resumable,
            "etag": task.etag, "last_modified": task.last_modified,
            "chunks": [{"index": c.index, "start": c.start, "end": c.end,
                        "downloaded": c.downloaded} for c in task.chunks],
        }
        path = sidecar_path(task.save_dir, task.filename)
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            pass

    @staticmethod
    def sync(task: DownloadTask) -> None:
        """The .partN file sizes are the source of truth for resume offsets."""
        for c in task.chunks:
            c.part_path = part_path(task.save_dir, task.filename, c.index)
            size = c.part_path.stat().st_size if c.part_path.exists() else 0
            if c.length is not None and size > c.length:
                with open(c.part_path, "r+b") as f:
                    f.truncate(c.length)
                size = c.length
            c.downloaded = size
            c.completed = c.length is not None and size >= c.length
        task.downloaded = sum(c.downloaded for c in task.chunks)

    @staticmethod
    def delete(task: DownloadTask) -> None:
        if task.engine == "ytdlp":
            shutil.rmtree(PartFiles.yt_temp_dir(task), ignore_errors=True)
            return
        for p in task.save_dir.glob(f".{PartFiles.glob_escape(task.filename)}.part*"):
            try:
                p.unlink()
            except OSError:
                pass
        try:
            sidecar_path(task.save_dir, task.filename).unlink(missing_ok=True)
        except OSError:
            pass

    @staticmethod
    def glob_escape(name: str) -> str:
        return re.sub(r"([\[\]*?])", r"[\1]", name)

    @staticmethod
    def yt_temp_dir(task: DownloadTask) -> Path:
        """yt-dlp works in its own hidden folder, so pause/cancel never touch your files."""
        return task.save_dir / f".pydm-yt-{task.id[:12]}"
