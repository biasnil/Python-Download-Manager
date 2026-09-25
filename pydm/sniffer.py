"""Browser-extension API (aiohttp) and the store of sniffed media."""

from __future__ import annotations

import asyncio
import re
import threading
import time
import uuid

from collections import deque
from pathlib import Path

from .config import APP_NAME, APP_VERSION, CONFIG, EXTENSION_ORIGINS, FFMPEG_AVAILABLE, HOST, PORT, SNIFFER_MAX_ITEMS, YTDLP_AVAILABLE
from .models import DetectedItem, TaskState
from .utils import classify_media, clean_error, is_http_url, safe_filename
from .ytdlp_backend import IsPlaylist, YtDlp


try:
    from aiohttp import web
except ImportError:          # optional dependency
    web = None


class SnifferStore:
    """Thread-safe in-memory ring buffer of sniffed items.

    Written from the asyncio thread (API) and the GUI thread (panel), so every
    access goes through a lock."""

    def __init__(self, max_items: int = SNIFFER_MAX_ITEMS):
        self.items: deque[DetectedItem] = deque()
        self.max = max_items
        self._by_url: dict[str, DetectedItem] = {}
        self._lock = threading.Lock()

    def add(self, url: str, kind: str, mime: str | None = None,
            page: str | None = None, size: int | None = None) -> DetectedItem | None:
        with self._lock:
            if url in self._by_url:
                return None
            item = DetectedItem(id=uuid.uuid4().hex, url=url, kind=kind, mime=mime,
                                page=page, ts=time.time(), size=size)
            self.items.append(item)
            self._by_url[url] = item
            while len(self.items) > self.max:
                old = self.items.popleft()
                self._by_url.pop(old.url, None)
            return item

    def find(self, item_id: str | None = None, url: str | None = None) -> DetectedItem | None:
        with self._lock:
            if url and url in self._by_url:
                return self._by_url[url]
            if item_id:
                return next((i for i in self.items if i.id == item_id), None)
            return None

    def mark_queued(self, item_id: str) -> DetectedItem | None:
        item = self.find(item_id=item_id)
        if item:
            item.queued = True
        return item

    def snapshot(self, page: str | None = None, limit: int = 200) -> list[DetectedItem]:
        with self._lock:
            items = [i for i in self.items if page is None or i.page == page]
        return items[-limit:]

    def remove(self, item_ids: set[str]) -> None:
        with self._lock:
            keep = deque(i for i in self.items if i.id not in item_ids)
            for i in self.items:
                if i.id in item_ids:
                    self._by_url.pop(i.url, None)
            self.items = keep

    def clear(self) -> None:
        with self._lock:
            self.items.clear()
            self._by_url.clear()

    def __len__(self) -> int:
        return len(self.items)


class SnifferAPI:
    """Local HTTP API for the browser extension.

    POST /sniff      {url, type, mime, page, size}  or  {items: [...]}
    GET  /detected   ?page=<url>        → {items: [...]}
    POST /download   {url, id?, page?}  → {task_id}
    GET  /status     ?task_id=<id>      → {tasks: {id: {...}}}
    GET  /health                        → {ok: true, app: "PyDM"}

    Callbacks run on the asyncio thread; the GUI passes Qt-signal emitters so
    widgets are only ever touched on the GUI thread."""

    def __init__(self, store: SnifferStore, on_new_items, on_item_changed,
                 on_download_request, get_status, get_intercept=lambda: False):
        self.store = store
        self.on_new_items = on_new_items
        self.on_item_changed = on_item_changed
        self.on_download_request = on_download_request
        self.get_status = get_status
        self.get_intercept = get_intercept
        self.runner = None
        self._requested: set[str] = set()
        self._playlists: dict[str, tuple[float, dict]] = {}

    @property
    def running(self) -> bool:
        return self.runner is not None

    def build(self):
        @web.middleware
        async def guard(request, handler):
            origin = request.headers.get("Origin")
            if origin and not origin.startswith(EXTENSION_ORIGINS):
                return web.json_response({"ok": False, "error": "origin not allowed"},
                                         status=403)
            if request.method == "OPTIONS":          # CORS preflight
                resp = web.Response(status=204)
            else:
                try:
                    resp = await handler(request)
                except web.HTTPException as e:
                    resp = web.json_response({"ok": False, "error": e.reason},
                                             status=e.status)
            if origin:
                resp.headers["Access-Control-Allow-Origin"] = origin
                resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
                resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
                resp.headers["Vary"] = "Origin"
            return resp

        app = web.Application(middlewares=[guard], client_max_size=2 * 1024 * 1024)
        app.router.add_post("/sniff", self._sniff)
        app.router.add_get("/detected", self._detected)
        app.router.add_post("/download", self._download)
        app.router.add_get("/status", self._status)
        app.router.add_get("/health", self._health)
        app.router.add_get("/yt/formats", self._yt_formats)
        app.router.add_post("/yt/formats", self._yt_formats)
        app.router.add_post("/yt/download", self._yt_download)
        app.router.add_post("/yt/playlist", self._yt_playlist)
        return app

    async def start(self) -> None:
        if self.runner:
            return
        runner = web.AppRunner(self.build(), access_log=None)
        await runner.setup()
        try:
            await web.TCPSite(runner, HOST, PORT).start()
        except OSError:
            await runner.cleanup()
            raise
        self.runner = runner

    async def stop(self) -> None:
        if self.runner:
            runner, self.runner = self.runner, None
            await runner.cleanup()

    # ── handlers ────────────────────────────────────────────────────────
    @staticmethod
    async def _json(request) -> dict:
        try:
            data = await request.json()
        except (ValueError, UnicodeDecodeError):
            raise web.HTTPBadRequest(reason="invalid JSON")
        if not isinstance(data, dict):
            raise web.HTTPBadRequest(reason="expected a JSON object")
        return data

    async def _sniff(self, request):
        data = await self._json(request)
        raw = data.get("items") if isinstance(data.get("items"), list) else [data]
        added, valid = [], 0
        for d in raw[:500]:
            if not isinstance(d, dict) or not is_http_url(d.get("url")):
                continue
            valid += 1
            mime = d.get("mime") if isinstance(d.get("mime"), str) else None
            kind = classify_media(d["url"], mime, d.get("type"))
            if not kind:
                continue
            page = d.get("page") if is_http_url(d.get("page")) else None
            size = d.get("size") if isinstance(d.get("size"), int) and d["size"] > 0 else None
            item = self.store.add(d["url"], kind, mime, page, size)
            if item:
                added.append(item)
        if added:
            self.on_new_items(added)
        if not valid:
            return web.json_response({"ok": False, "error": "no usable url"}, status=400)
        return web.json_response({"ok": True, "added": len(added)})

    async def _detected(self, request):
        page = request.query.get("page") or None
        return web.json_response(
            {"items": [i.to_json() for i in self.store.snapshot(page)]})

    async def _download(self, request):
        data = await self._json(request)
        url = data.get("url")
        if not is_http_url(url):
            return web.json_response({"ok": False, "error": "no valid url"}, status=400)
        item = self.store.find(item_id=data.get("id"), url=url)
        referer = data.get("page") if is_http_url(data.get("page")) else None
        text = lambda k: data.get(k) if isinstance(data.get(k), str) and data.get(k) else None
        source = text("source") if text("source") in ("browser", "link") else "sniffer"
        mime = item.mime if item else text("mime")
        task_id = uuid.uuid4().hex
        self._requested.add(task_id)
        self.on_download_request({
            "task_id": task_id, "url": url,
            "referer": referer or (item.page if item else None),
            "mime": mime,
            "kind": item.kind if item else classify_media(url, mime),
            "item_id": item.id if item else None,
            "filename": text("filename"),
            "cookies": text("cookies"),
            "user_agent": text("user_agent"),
            "source": source,
            "immediate": source in ("browser", "link"),
        })
        if item:
            item.queued = True
            self.on_item_changed(item)
        return web.json_response({"ok": True, "task_id": task_id})

    async def _status(self, request):
        wanted = request.query.get("task_id")
        tasks = {t["id"]: t for t in self.get_status()}
        if wanted:
            if wanted in tasks:
                tasks = {wanted: tasks[wanted]}
            elif wanted in self._requested:
                tasks = {wanted: {"id": wanted, "url": None, "filename": None,
                                  "state": TaskState.QUEUED.value, "progress": 0.0,
                                  "downloaded": 0, "total": 0, "speed": 0.0,
                                  "error": None}}
            else:
                return web.json_response({"ok": False, "error": "unknown task"}, status=404)
        return web.json_response({"ok": True, "tasks": tasks})

    async def _health(self, request):
        return web.json_response({"ok": True, "app": APP_NAME, "version": APP_VERSION,
                                  "detected": len(self.store),
                                  "intercept": bool(self.get_intercept()),
                                  "min_intercept_kb": CONFIG.min_intercept_kb,
                                  "ytdlp": YTDLP_AVAILABLE, "ffmpeg": FFMPEG_AVAILABLE})

    @staticmethod
    def _playlist_url(url: str, playlist: object) -> str | None:
        if not isinstance(playlist, str) or not re.fullmatch(r"[\w-]{2,64}", playlist):
            return None
        return f"https://www.youtube.com/playlist?list={playlist}" if YtDlp.is_youtube(url) else None

    async def _yt_formats(self, request):
        data = dict(request.query) if request.method == "GET" else await self._json(request)
        url = data.get("url")
        if not is_http_url(url):
            return web.json_response({"ok": False, "error": "no valid url"}, status=400)
        if not YTDLP_AVAILABLE:
            return web.json_response({"ok": False,
                                      "error": "yt-dlp is not installed — run: pip install yt-dlp"})
        cookiefile = YtDlp.write_cookiefile(data.get("cookies")) if isinstance(data.get("cookies"), list) else None
        pl_url = self._playlist_url(url, data.get("playlist"))
        try:
            jobs = [asyncio.to_thread(YtDlp.probe, url, cookiefile)]
            if pl_url:
                jobs.append(asyncio.to_thread(YtDlp.playlist, pl_url, cookiefile))
            results = await asyncio.gather(*jobs, return_exceptions=True)
            if isinstance(results[0], IsPlaylist):      # album / set page on any site
                try:
                    info = await asyncio.to_thread(YtDlp.playlist, url, cookiefile)
                except Exception as e:  # noqa: BLE001
                    return web.json_response({"ok": False, "error": clean_error(e)})
        finally:
            if cookiefile:
                Path(cookiefile).unlink(missing_ok=True)
        if isinstance(results[0], IsPlaylist):
            if not info["entries"]:
                return web.json_response({"ok": False, "error": "This playlist is empty"})
            self._playlists[url] = (time.time(), info)
            return web.json_response({
                "ok": True, "title": info["title"], "formats": [], "ffmpeg": FFMPEG_AVAILABLE,
                "playlist": {"url": url, "title": info["title"], "count": len(info["entries"]),
                             "audio_only": info["audio_only"],
                             "choices": YtDlp.playlist_choices(info["audio_only"])}})
        if isinstance(results[0], BaseException):
            return web.json_response({"ok": False, "error": clean_error(results[0])})
        out = {"ok": True, **results[0]}
        if pl_url and len(results) > 1 and isinstance(results[1], dict) and results[1]["entries"]:
            self._playlists[pl_url] = (time.time(), results[1])
            out["playlist"] = {"url": pl_url, "title": results[1]["title"],
                               "count": len(results[1]["entries"]), "audio_only": False,
                               "choices": YtDlp.playlist_choices(False)}
        return web.json_response(out)

    async def _yt_playlist(self, request):
        data = await self._json(request)
        url, choice = data.get("url"), data.get("choice") or "best"
        if not is_http_url(url) or not isinstance(choice, str) or not YtDlp.CHOICE_RE.fullmatch(choice):
            return web.json_response({"ok": False, "error": "bad url or quality"}, status=400)
        cached = self._playlists.get(url)
        if cached and time.time() - cached[0] < 600:
            info = cached[1]
        else:
            cookies = data.get("cookies") if isinstance(data.get("cookies"), list) else None
            cookiefile = YtDlp.write_cookiefile(cookies) if cookies else None
            try:
                info = await asyncio.to_thread(YtDlp.playlist, url, cookiefile)
            except Exception as e:  # noqa: BLE001
                return web.json_response({"ok": False, "error": clean_error(e)})
            finally:
                if cookiefile:
                    Path(cookiefile).unlink(missing_ok=True)
        if not info["entries"]:
            return web.json_response({"ok": False, "error": "playlist is empty"})
        self.on_download_request({"type": "playlist", "title": info["title"],
                                  "entries": info["entries"], "choice": choice,
                                  "audio_only": info.get("audio_only", False)})
        return web.json_response({"ok": True, "count": len(info["entries"])})

    async def _yt_download(self, request):
        data = await self._json(request)
        url, choice = data.get("url"), data.get("choice") or "best"
        if not is_http_url(url) or not isinstance(choice, str) or not YtDlp.CHOICE_RE.fullmatch(choice):
            return web.json_response({"ok": False, "error": "bad url or quality"}, status=400)
        if not YTDLP_AVAILABLE:
            return web.json_response({"ok": False, "error": "yt-dlp is not installed"})
        title = data.get("title") if isinstance(data.get("title"), str) else "video"
        cookies = data.get("cookies") if isinstance(data.get("cookies"), list) else None
        task_id = uuid.uuid4().hex
        self._requested.add(task_id)
        self.on_download_request({
            "task_id": task_id, "url": url, "referer": None, "mime": None,
            "kind": "media", "item_id": None, "cookies": None, "user_agent": None,
            "filename": safe_filename(title[:150]) + YtDlp.ext_for(choice),
            "source": "youtube" if YtDlp.is_youtube(url) else "video", "immediate": True,
            "engine": "ytdlp", "yt_choice": choice, "cookie_jar": cookies,
        })
        return web.json_response({"ok": True, "task_id": task_id})
