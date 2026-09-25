"""DownloadEngine: segmented HTTP downloads + the yt-dlp engine."""

from __future__ import annotations

import asyncio
import httpx
import os
import shutil
import threading
import time

from collections import deque
from pathlib import Path

from .chunk_worker import ChunkWorker
from .config import DISK_SPACE_MARGIN, HTTP2_AVAILABLE, MAX_THREADS, MIN_CHUNK_SIZE, MIN_SPLIT_SIZE, SPEED_WINDOW, STATE_SAVE_INTERVAL, UI_UPDATE_INTERVAL, USER_AGENT, YTDLP_AVAILABLE
from .errors import PyDMError
from .limiter import TokenBucketLimiter
from .models import ChunkInfo, DownloadTask, TaskState
from .part_files import PartFiles
from .remote_probe import RemoteProbe
from .utils import clean_error, human_bytes, part_path, safe_filename, sidecar_path, unique_filename
from .ytdlp_backend import DownloadCancelled, QuietLogger, YtDlp, yt_dlp


class DownloadEngine:
    def __init__(self, on_update, on_complete, on_error):
        self.on_update = on_update
        self.on_complete = on_complete
        self.on_error = on_error
        self.limiter = TokenBucketLimiter(0)
        self._client: httpx.AsyncClient | None = None
        self._jobs: dict[str, asyncio.Task] = {}
        self._tasks: dict[str, DownloadTask] = {}
        self._workers: dict[str, list[ChunkWorker]] = {}
        self._stop_reason: dict[str, TaskState] = {}
        self._last_emit: dict[str, float] = {}
        self._last_save: dict[str, float] = {}
        self._samples: dict[str, deque] = {}
        self._final_url: dict[str, str] = {}
        self._yt_stop: dict[str, threading.Event] = {}
        self.dynamic = True        # IDM-style dynamic segmentation

    # ── lifecycle ───────────────────────────────────────────────────────
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                http2=HTTP2_AVAILABLE,
                follow_redirects=True,
                timeout=httpx.Timeout(30.0, connect=15.0),
                limits=httpx.Limits(max_connections=64, max_keepalive_connections=32),
                headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def shutdown(self) -> None:
        for task_id in list(self._jobs):
            await self.pause(task_id)

    # ── public API ──────────────────────────────────────────────────────
    async def start(self, task: DownloadTask) -> None:
        pre = self._stop_reason.pop(task.id, None)
        if pre is not None:                      # paused before it began
            self._finish_stopped(task, pre)
            return

        job = asyncio.create_task(self._execute_ytdlp(task) if task.engine == "ytdlp"
                                  else self._execute(task))
        self._jobs[task.id] = job
        self._tasks[task.id] = task
        try:
            await job
        except asyncio.CancelledError:
            reason = self._stop_reason.pop(task.id, None)
            if reason is None:
                raise
            self._finish_stopped(task, reason)
        except Exception as e:  # noqa: BLE001
            reason = self._stop_reason.pop(task.id, None)
            if reason is not None:      # yt-dlp stops by raising from its hook
                self._finish_stopped(task, reason)
                return
            task.state = TaskState.ERROR
            task.error = clean_error(e)
            if task.resumable:
                PartFiles.save(task)
            self.on_error(task)
        finally:
            task.speed_bps = 0.0
            for d in (self._jobs, self._tasks, self._workers, self._last_emit,
                      self._last_save, self._samples, self._final_url, self._yt_stop,
                      self._stop_reason):
                d.pop(task.id, None)

    async def pause(self, task_id: str) -> None:
        await self._stop(task_id, TaskState.PAUSED)

    async def cancel(self, task_id: str) -> None:
        await self._stop(task_id, TaskState.CANCELLED)

    # ── internals ───────────────────────────────────────────────────────
    async def _stop(self, task_id: str, reason: TaskState) -> None:
        job = self._jobs.get(task_id)
        if job is None:
            self._stop_reason[task_id] = reason  # start() hasn't run yet
            return
        task = self._tasks.get(task_id)
        if task and task.state == TaskState.MERGING:
            return  # merging can't be interrupted safely; it's nearly done
        self._stop_reason[task_id] = reason
        if task and task.engine == "ytdlp":
            # yt-dlp runs in a thread: flag it; its progress hook raises and exits
            ev = self._yt_stop.get(task_id)
            if ev:
                ev.set()
            return
        for w in self._workers.get(task_id, []):
            w.cancel()
        job.cancel()

    def _finish_stopped(self, task: DownloadTask, reason: TaskState) -> None:
        task.state = reason
        task.speed_bps = 0.0
        if reason == TaskState.PAUSED:
            if task.chunks:
                PartFiles.sync(task)
                PartFiles.save(task)
        else:
            PartFiles.delete(task)
            task.chunks = []
            task.downloaded = 0
        self.on_update(task)

    async def _execute(self, task: DownloadTask) -> None:
        task.error = None
        task.state = TaskState.CONNECTING
        self.on_update(task)

        await self._prepare(task)

        task.state = TaskState.DOWNLOADING
        self._samples[task.id] = deque([(time.monotonic(), task.downloaded)])
        self.on_update(task)

        await self._download_all(task)

        task.state = TaskState.MERGING
        task.speed_bps = 0.0
        self.on_update(task)
        await self._merge(task)

        task.state = TaskState.COMPLETED
        task.completed_at = time.time()
        if task.total_size <= 0:
            task.total_size = task.downloaded
        task.downloaded = task.total_size
        self.on_complete(task)

    # ── yt-dlp engine ──────────────────────────────────────────────────
    async def _execute_ytdlp(self, task: DownloadTask) -> None:
        if not YTDLP_AVAILABLE:
            raise PyDMError("yt-dlp is not installed (pip install yt-dlp)")
        stop = threading.Event()
        self._yt_stop[task.id] = stop
        task.error = None
        task.state = TaskState.CONNECTING
        self.on_update(task)

        loop = asyncio.get_running_loop()
        tmp = PartFiles.yt_temp_dir(task)
        tmp.mkdir(parents=True, exist_ok=True)
        fmt, extra = YtDlp.selector(task.yt_choice)
        streams: dict[str, tuple[int, int]] = {}   # video & audio are separate files

        def on_progress(d):
            if stop.is_set():
                raise DownloadCancelled("stopped by PyDM")
            if d.get("status") == "downloading":
                key = d.get("tmpfilename") or d.get("filename") or "?"
                streams[key] = (d.get("downloaded_bytes") or 0,
                                d.get("total_bytes") or d.get("total_bytes_estimate") or 0)
                loop.call_soon_threadsafe(self._yt_progress, task, dict(streams),
                                          d.get("speed") or 0.0)

        def on_postprocess(d):
            if d.get("status") == "started":
                loop.call_soon_threadsafe(self._yt_merging, task)

        opts = {
            "format": fmt, "outtmpl": str(tmp / "%(title).150B.%(ext)s"),
            "noplaylist": True, "quiet": True, "no_warnings": True, "no_color": True,
            "noprogress": True, "logger": QuietLogger(),
            "continuedl": True, "windowsfilenames": True,
            "concurrent_fragment_downloads": 4,
            "progress_hooks": [on_progress], "postprocessor_hooks": [on_postprocess],
            **extra,
        }
        if self.limiter.rate > 0:
            opts["ratelimit"] = int(self.limiter.rate)

        cookiefile = YtDlp.write_cookiefile(task.cookie_jar) if task.cookie_jar else None
        if cookiefile:
            opts["cookiefile"] = cookiefile

        def run():
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.extract_info(task.url, download=True)
            finally:
                if cookiefile:
                    Path(cookiefile).unlink(missing_ok=True)

        await asyncio.to_thread(run)
        await asyncio.to_thread(self._yt_finalize, task, tmp)
        task.state = TaskState.COMPLETED
        task.completed_at = time.time()
        task.speed_bps = 0.0
        self.on_complete(task)

    def _yt_progress(self, task: DownloadTask, streams: dict, speed: float) -> None:
        if task.state not in (TaskState.CONNECTING, TaskState.DOWNLOADING):
            return
        first = task.state == TaskState.CONNECTING
        task.state = TaskState.DOWNLOADING
        task.downloaded = sum(d for d, _ in streams.values())
        task.total_size = sum(max(t, d) for d, t in streams.values())
        task.speed_bps = float(speed)
        now = time.monotonic()
        if first or now - self._last_emit.get(task.id, 0) >= UI_UPDATE_INTERVAL:
            self._last_emit[task.id] = now
            self.on_update(task)

    def _yt_merging(self, task: DownloadTask) -> None:
        task.state = TaskState.MERGING
        task.speed_bps = 0.0
        self.on_update(task)

    @staticmethod
    def _yt_finalize(task: DownloadTask, tmp: Path) -> None:
        junk = (".part", ".ytdl", ".temp")
        files = [p for p in tmp.iterdir() if p.is_file()
                 and not p.name.endswith(junk) and ".part-Frag" not in p.name]
        if not files:
            raise PyDMError("yt-dlp finished but produced no file")
        src = max(files, key=lambda p: p.stat().st_size)
        name = unique_filename(task.save_dir, safe_filename(src.name))
        shutil.move(str(src), task.save_dir / name)
        shutil.rmtree(tmp, ignore_errors=True)
        task.filename = name
        task.total_size = task.downloaded = (task.save_dir / name).stat().st_size

    async def _prepare(self, task: DownloadTask) -> None:
        task.save_dir.mkdir(parents=True, exist_ok=True)
        info = await RemoteProbe.run(self.client(), task.url, task.headers)
        self._final_url[task.id] = info.final_url

        if not task.chunks:
            PartFiles.load(task)

        # Adopt server-suggested name for fresh downloads the user didn't rename
        if task.auto_name and not task.chunks and info.filename:
            suggested = safe_filename(info.filename)
            if suggested != task.filename:
                taken = {t.filename for t in self._tasks.values()
                         if t.id != task.id and t.save_dir == task.save_dir}
                task.filename = unique_filename(task.save_dir, suggested, taken)

        same_file = True
        if task.refreshed:
            task.refreshed = False
            if task.chunks and task.total_size and info.total_size != task.total_size:
                raise PyDMError("The new address points to a different file "
                                f"({human_bytes(info.total_size)} ≠ {human_bytes(task.total_size)})")
            if task.chunks and not info.resumable:
                raise PyDMError("The new address can't resume (server has no range support)")
        elif task.etag and info.etag:
            same_file = task.etag == info.etag
        elif task.last_modified and info.last_modified:
            same_file = task.last_modified == info.last_modified

        reuse = (bool(task.chunks) and info.resumable and task.resumable
                 and info.total_size > 0 and info.total_size == task.total_size
                 and same_file)

        if reuse:
            PartFiles.sync(task)
        else:
            PartFiles.delete(task)
            task.total_size = info.total_size
            task.resumable = info.resumable and info.total_size > 0
            task.etag, task.last_modified = info.etag, info.last_modified
            task.chunks = self._build_chunks(task)
            task.downloaded = 0

        needed = max(0, task.total_size - task.downloaded) + DISK_SPACE_MARGIN
        if task.total_size and shutil.disk_usage(task.save_dir).free < needed:
            raise PyDMError(f"Not enough disk space (need {human_bytes(needed)})")
        PartFiles.save(task)

    def _build_chunks(self, task: DownloadTask) -> list[ChunkInfo]:
        total = task.total_size
        if not task.resumable:
            end = total - 1 if total > 0 else None
            chunks = [ChunkInfo(0, 0, end)]
        else:
            n = max(1, min(task.num_threads, MAX_THREADS, total // MIN_CHUNK_SIZE))
            size = total // n
            chunks = []
            for i in range(n):
                start = i * size
                end = total - 1 if i == n - 1 else start + size - 1
                chunks.append(ChunkInfo(i, start, end))
        for c in chunks:
            c.part_path = part_path(task.save_dir, task.filename, c.index)
        return chunks

    async def _download_all(self, task: DownloadTask) -> None:
        """Run chunk workers. With dynamic segmentation, whenever a thread is
        idle the largest remaining piece is split in two and the idle thread
        takes the second half — so all threads stay busy until the end."""
        url = self._final_url.get(task.id, task.url)
        running: dict[asyncio.Task, ChunkWorker] = {}
        self._workers[task.id] = []

        def spawn(c: ChunkInfo) -> None:
            w = ChunkWorker(self.client(), url, c, task.headers, c.part_path,
                            use_range=task.resumable, limiter=self.limiter,
                            progress_cb=lambda n, t=task: self._tick(t, n))
            self._workers[task.id].append(w)
            running[asyncio.create_task(w.run())] = w

        def fill() -> None:
            if not (task.resumable and self.dynamic):
                return
            while len(running) < max(1, task.num_threads):
                c = self._split_largest(task)
                if c is None:
                    break
                spawn(c)

        for c in task.chunks:
            if not c.completed:
                spawn(c)
        fill()     # e.g. resumed with fewer unfinished chunks than threads
        try:
            while running:
                done, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
                for t in done:
                    w = running.pop(t)
                    self._workers[task.id].remove(w)
                    if not t.result():          # raises the worker's error, if any
                        raise PyDMError("Download incomplete")
                fill()
        except BaseException:
            for t in running:
                t.cancel()
            await asyncio.gather(*running, return_exceptions=True)
            raise
        if not all(c.completed for c in task.chunks):
            raise PyDMError("Download incomplete")

    def _split_largest(self, task: DownloadTask) -> ChunkInfo | None:
        best, remaining = None, 0
        for c in task.chunks:
            if c.completed or c.length is None:
                continue
            r = c.length - c.downloaded
            if r > remaining:
                best, remaining = c, r
        if best is None or remaining < 2 * MIN_SPLIT_SIZE:
            return None
        # The running worker checks c.end on every block, so shrinking it is safe;
        # the split point is ≥ MIN_SPLIT_SIZE past anything already in flight.
        pos = best.start + best.downloaded + remaining // 2
        new = ChunkInfo(index=max(c.index for c in task.chunks) + 1, start=pos, end=best.end)
        new.part_path = part_path(task.save_dir, task.filename, new.index)
        best.end = pos - 1
        task.chunks.append(new)
        PartFiles.save(task)
        return new

    def _tick(self, task: DownloadTask, n: int) -> None:
        task.downloaded += n
        now = time.monotonic()

        samples = self._samples.setdefault(task.id, deque())
        samples.append((now, task.downloaded))
        while len(samples) > 2 and now - samples[0][0] > SPEED_WINDOW:
            samples.popleft()

        if now - self._last_save.get(task.id, 0) >= STATE_SAVE_INTERVAL:
            self._last_save[task.id] = now
            PartFiles.save(task)

        if now - self._last_emit.get(task.id, 0) >= UI_UPDATE_INTERVAL:
            self._last_emit[task.id] = now
            t0, d0 = samples[0]
            task.speed_bps = (task.downloaded - d0) / (now - t0) if now > t0 else 0.0
            self.on_update(task)

    async def _merge(self, task: DownloadTask) -> None:
        def merge_sync() -> None:
            ordered = sorted(task.chunks, key=lambda c: c.start)
            for a, b in zip(ordered, ordered[1:]):
                if a.end is not None and a.end + 1 != b.start:
                    raise PyDMError("Segment map is inconsistent — restart the download")
            parts = [part_path(task.save_dir, task.filename, c.index) for c in ordered]
            for p in parts:
                if not p.exists():
                    if task.total_size == 0 and len(parts) == 1:
                        p.touch()  # legit empty file
                    else:
                        raise PyDMError(f"Missing part file {p.name}")
            # Append parts into part0 (deleting as we go) → low extra disk use
            head = parts[0]
            with open(head, "ab") as out:
                for p in parts[1:]:
                    with open(p, "rb") as src:
                        shutil.copyfileobj(src, out, 1024 * 1024)
                    p.unlink()
            size = head.stat().st_size
            if task.total_size and size != task.total_size:
                raise PyDMError(f"Size mismatch after merge "
                                f"({size} != {task.total_size})")
            final = task.final_path
            if final.exists() and not task.overwrite:
                task.filename = unique_filename(task.save_dir, task.filename)
                final = task.final_path
            os.replace(head, final)
            old_sidecar = sidecar_path(task.save_dir, task.filename)
            old_sidecar.unlink(missing_ok=True)

        old_name = task.filename
        await asyncio.to_thread(merge_sync)
        sidecar_path(task.save_dir, old_name).unlink(missing_ok=True)
