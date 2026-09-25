"""MainWindow: ties the engine, queue, API and all widgets together."""

from __future__ import annotations

import asyncio
import time
import traceback
import uuid

from PyQt6.QtCore import QByteArray, QTimer, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QDesktopServices
from PyQt6.QtWidgets import QApplication, QDialog, QLabel, QMainWindow, QMenu, QMessageBox, QSpinBox, QTabWidget, QToolBar
from pathlib import Path
from urllib.parse import urlparse

from .add_dialog import AddDownloadDialog
from .async_worker import AsyncWorker
from .batch_dialog import BatchDialog
from .checksum_dialog import ChecksumDialog
from .clipboard_monitor import ClipboardMonitor
from .config import AIOHTTP_AVAILABLE, APP_NAME, APP_VERSION, CONFIG, DATA_DIR, FFMPEG_AVAILABLE, HOST, PORT, Settings, YTDLP_AVAILABLE, download_root
from .database import Database
from .download_queue import DownloadQueue
from .download_window import DownloadWindow
from .downloads_table import DownloadsTable
from .engine import DownloadEngine
from .icons import Icons
from .models import ACTIVE_STATES, DetectedItem, DownloadTask, QUIET_SOURCES, RESUMABLE_STATES, TaskState
from .part_files import PartFiles
from .power import PowerManager
from .refresh_dialog import RefreshAddressDialog
from .schedule import ScheduleManager
from .settings_dialog import SettingsDialog
from .sniffed_panel import SniffedPanel
from .sniffer import SnifferAPI, SnifferStore
from .tray import TrayController
from .utils import category_dir, clean_error, human_speed, name_for, safe_filename, unique_filename
from .ytdlp_backend import YtDlp


class MainWindow(QMainWindow):
    # All emitted from the worker thread → Qt queues them onto the GUI thread
    task_updated = pyqtSignal(object)          # DownloadTask
    sniffed_items_added = pyqtSignal(object)   # list[DetectedItem]
    sniffed_item_changed = pyqtSignal(object)  # DetectedItem
    download_requested = pyqtSignal(object)    # dict from POST /download, /yt/…
    sniffer_state = pyqtSignal(str, str)       # ("on"|"off"|"error", text)
    message = pyqtSignal(str)                  # status-bar text from the worker

    def __init__(self, db: Database, cfg: Settings = CONFIG):
        super().__init__()
        self.db = db
        self.cfg = cfg
        self.tasks: dict[str, DownloadTask] = {}
        self.windows: dict[str, DownloadWindow] = {}
        self._persisted: dict[str, tuple] = {}
        self._last_state: dict[str, TaskState] = {}
        self._aliases: dict[str, str] = {}          # API task id → existing task
        self._awaiting_refresh: set[str] = set()
        self._really_quit = False
        self._tray_hint_shown = False

        self.worker = AsyncWorker()
        self.worker.start_and_wait()
        self.engine = DownloadEngine(on_update=self.task_updated.emit,
                                     on_complete=self.task_updated.emit,
                                     on_error=self.task_updated.emit)
        self.engine.dynamic = cfg.dynamic_segmentation
        self.engine.limiter.set_rate(cfg.speed_limit_kbps * 1024)
        self.queue = DownloadQueue(self.engine, cfg.max_concurrent)
        self.task_updated.connect(self._on_task_updated)

        self.store = SnifferStore()
        self.sniffer_api = SnifferAPI(
            store=self.store,
            on_new_items=self.sniffed_items_added.emit,
            on_item_changed=self.sniffed_item_changed.emit,
            on_download_request=self.download_requested.emit,
            get_status=self._status_snapshot,
            get_intercept=lambda: self.cfg.intercept_enabled,
        ) if AIOHTTP_AVAILABLE else None

        self.setWindowTitle(f"{APP_NAME} — Download Manager")
        self.setWindowIcon(Icons.app())
        self.resize(1100, 580)
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self.table = DownloadsTable(self.tasks)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.itemSelectionChanged.connect(self._refresh_actions)
        self.table.cellDoubleClicked.connect(
            lambda r, _c: self._double_click(self.table.task_at(r)))
        self.sniffed_panel = SniffedPanel(self.store)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.table, "Downloads")
        self.tabs.addTab(self.sniffed_panel, "Sniffed")
        self.setCentralWidget(self.tabs)

        self.sniffed_items_added.connect(self.sniffed_panel.add_items)
        self.sniffed_item_changed.connect(self.sniffed_panel.update_item)
        self.sniffed_panel.request_download.connect(self._download_detected)
        self.sniffed_panel.count_changed.connect(
            lambda n: self.tabs.setTabText(1, f"Sniffed ({n})" if n else "Sniffed"))
        self.download_requested.connect(self._on_api_download)
        self.sniffer_state.connect(self._on_sniffer_state)
        self.message.connect(lambda m: self.statusBar().showMessage(m, 6000))

        self.sniffer_label = QLabel()
        self.status_label = QLabel()
        self.statusBar().addWidget(self.sniffer_label)
        self.statusBar().addPermanentWidget(self.status_label)
        self._on_sniffer_state("off", "off" if AIOHTTP_AVAILABLE
                               else "off (pip install aiohttp)")

        self.tray = TrayController(self, [self.act_add, None, self.act_resume_all,
                                          self.act_pause_all, self.act_settings, None,
                                          self.act_exit], cfg)
        self.schedule = ScheduleManager(self, cfg)
        self.clipboard = ClipboardMonitor(cfg, lambda: [t.url for t in self.tasks.values()], self)
        self.clipboard.file_link_copied.connect(
            lambda url: QTimer.singleShot(0, lambda: self.add_download(url=url,
                                                                      from_clipboard=True)))
        self._load_history()

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start(1000)
        self._refresh_actions()
        self._refresh_status()

        if cfg.window_geometry:
            self.restoreGeometry(QByteArray.fromBase64(cfg.window_geometry.encode()))
        if cfg.sniffer_enabled and self.sniffer_api:
            self.start_sniffer()

    # ── UI construction ─────────────────────────────────────────────────
    def _build_actions(self) -> None:
        def act(text, slot, icon_name=None, shortcut=None):
            a = QAction(Icons.get(icon_name), text, self)
            if shortcut:
                a.setShortcut(shortcut)
            a.triggered.connect(lambda _=False: slot())
            return a

        self.act_add = act("Add URL", self.add_download, "add", "Ctrl+N")
        self.act_batch = act("Batch Download…", self.batch_download, "batch", "Ctrl+B")
        self.act_resume = act("Resume", self.resume_selected, "resume")
        self.act_pause = act("Pause", self.pause_selected, "pause")
        self.act_resume_all = act("Resume All", self.resume_all)
        self.act_pause_all = act("Pause All", self.pause_all, "pause_all")
        self.act_remove = act("Remove", self.remove_selected, "remove", "Delete")
        self.act_clear = act("Clear Completed", self.clear_completed, "clear")
        self.act_refresh = act("Refresh Download Address…", self.refresh_address, "refresh")
        self.act_checksum = act("Verify Checksum…", self.verify_checksum, "checksum")
        self.act_schedule = act("Add to Schedule", self.schedule_selected)
        self.act_unschedule = act("Remove from Schedule", self.unschedule_selected)
        self.act_window = act("Show Progress Window", self.show_selected_window, "window")
        self.act_settings = act("Settings…", self.open_settings, "settings", "Ctrl+,")
        self.act_start_sched = act("Start Scheduled Queue", lambda: self.schedule.start(),
                                   "schedule")
        self.act_stop_sched = act("Stop Scheduled Queue", lambda: self.schedule.stop())
        self.act_exit = act("Exit", self.quit_app, "exit", "Ctrl+Q")

        self.act_sniffer = QAction(Icons.get("sniffer"), "Sniffer", self)
        self.act_sniffer.setCheckable(True)
        self.act_sniffer.setToolTip(f"Start/Stop the browser-extension API on {HOST}:{PORT}")
        self.act_sniffer.setEnabled(AIOHTTP_AVAILABLE)
        self.act_sniffer.toggled.connect(self._toggle_sniffer)
        self.act_intercept = QAction(Icons.get("catch"), "Catch Browser Downloads", self)
        self.act_intercept.setCheckable(True)
        self.act_intercept.setChecked(self.cfg.intercept_enabled)
        self.act_intercept.setEnabled(AIOHTTP_AVAILABLE)
        self.act_intercept.setToolTip("While on, downloads started in the browser are "
                                      "cancelled there and downloaded by PyDM instead")
        self.act_intercept.toggled.connect(lambda on: self._set_cfg(intercept_enabled=on))

    def _build_menus(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu("&Tasks")
        for a in (self.act_add, self.act_batch, None, self.act_resume_all,
                  self.act_pause_all, None, self.act_exit):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu("&Downloads")
        for a in (self.act_resume, self.act_pause, self.act_remove, None, self.act_window,
                  self.act_refresh, self.act_checksum, None, self.act_schedule,
                  self.act_unschedule, None, self.act_clear):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu("T&ools")
        m.addAction(self.act_settings)
        m.addSeparator()
        m.addAction(self.act_start_sched)
        m.addAction(self.act_stop_sched)
        done_menu = m.addMenu("When All Downloads Finish")
        group = QActionGroup(self)
        self.when_done_actions = {}
        for key, text in PowerManager.ACTIONS.items():
            a = QAction(text, self, checkable=True)
            a.setChecked(key == "nothing")
            a.triggered.connect(lambda _=False, k=key: setattr(self.schedule, "when_done_once", k))
            group.addAction(a)
            done_menu.addAction(a)
            self.when_done_actions[key] = a
        m = mb.addMenu("&Help")
        m.addAction(Icons.get("about"), "About PyDM", lambda: QMessageBox.about(
            self, APP_NAME, f"<b>{APP_NAME} {APP_VERSION}</b><br>Single-file download "
            f"manager.<br><br>Data &amp; settings: {DATA_DIR}"))

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(tb)
        for a in (self.act_add, self.act_resume, self.act_pause, self.act_pause_all,
                  self.act_remove, self.act_clear):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.act_settings)
        tb.addAction(self.act_start_sched)
        tb.addSeparator()
        tb.addWidget(QLabel(" Max: "))
        self.concurrent_spin = QSpinBox()
        self.concurrent_spin.setRange(1, 10)
        self.concurrent_spin.setValue(self.cfg.max_concurrent)
        self.concurrent_spin.setToolTip("Downloads at the same time")
        self.concurrent_spin.valueChanged.connect(self._set_max_concurrent)
        tb.addWidget(self.concurrent_spin)
        tb.addWidget(QLabel("  Limit: "))
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(0, 1_000_000)
        self.limit_spin.setSingleStep(100)
        self.limit_spin.setSuffix(" KB/s")
        self.limit_spin.setSpecialValueText("Unlimited")
        self.limit_spin.setValue(self.cfg.speed_limit_kbps)
        self.limit_spin.valueChanged.connect(self._set_speed_limit)
        tb.addWidget(self.limit_spin)
        tb.addSeparator()
        tb.addAction(self.act_sniffer)
        tb.addAction(self.act_intercept)

    # ── helpers ─────────────────────────────────────────────────────────
    def _submit(self, coro) -> None:
        fut = self.worker.submit(coro)
        fut.add_done_callback(self._log_future_error)

    @staticmethod
    def _log_future_error(fut) -> None:
        if not fut.cancelled() and fut.exception() is not None:
            traceback.print_exception(fut.exception())

    def _set_cfg(self, **changes) -> None:
        for k, v in changes.items():
            setattr(self.cfg, k, v)
        self.cfg.save()

    def _set_speed_limit(self, kbps: int) -> None:
        self._set_cfg(speed_limit_kbps=kbps)

        async def apply():
            self.engine.limiter.set_rate(kbps * 1024)
        self._submit(apply())

    def _set_max_concurrent(self, n: int) -> None:
        self._set_cfg(max_concurrent=n)
        self._submit(self.queue.set_max_concurrent(n))

    def set_show_complete_dialog(self, dont_show: bool) -> None:
        self._set_cfg(show_complete_dialog=not dont_show)

    def show_window(self) -> None:
        self.show()
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def _select_task(self, task: DownloadTask) -> None:
        self.tabs.setCurrentIndex(0)
        self.table.select_task(task)

    # ── rows ────────────────────────────────────────────────────────────

    # ── history / persistence ───────────────────────────────────────────
    def _load_history(self) -> None:
        for task in self.db.all():
            if task.state in ACTIVE_STATES or task.state == TaskState.QUEUED:
                task.state = TaskState.PAUSED
            if task.state in (TaskState.PAUSED, TaskState.ERROR, TaskState.SCHEDULED):
                PartFiles.load(task)
            self.tasks[task.id] = task
            self._last_state[task.id] = task.state
            self.table.add_task(task)
            self._persist(task, force=True)

    def _persist(self, task: DownloadTask, force: bool = False) -> None:
        now = time.monotonic()
        key = (task.state, task.filename, task.error, task.url)
        last = self._persisted.get(task.id)
        if force or last is None or last[0] != key or now - last[1] > 3:
            self.db.upsert(task)
            self._persisted[task.id] = (key, now)

    def _on_task_updated(self, task: DownloadTask) -> None:
        if task.id not in self.tasks:
            return
        prev = self._last_state.get(task.id)
        self._last_state[task.id] = task.state

        # scheduled queue: tasks paused by "stop at" go back to the schedule
        if self.schedule.take_rescheduled(task):
            self._last_state[task.id] = task.state

        self.table.update_task(task)
        self._persist(task)
        win = self.windows.get(task.id)
        if win:
            win.refresh()

        if task.state != prev and task.state in (TaskState.COMPLETED, TaskState.ERROR):
            if task.state == TaskState.COMPLETED:
                self.db.mark_completed(task.id)
                self._on_completed(task)
            elif task.source not in QUIET_SOURCES:
                self.tray.notify("Download failed", f"{task.filename}\n{task.error or ''}")
            self.schedule.check_all_done()
        self._refresh_actions()

    def _on_completed(self, task: DownloadTask) -> None:
        if task.source in QUIET_SOURCES:
            return
        if self.cfg.show_complete_dialog:
            self.show_download_window(task)
        elif not self.isVisible() or self.isMinimized():
            self.tray.notify("Download complete", task.filename)

    # ── adding downloads ────────────────────────────────────────────────
    def add_download(self, url: str | None = None, from_clipboard: bool = False) -> None:
        dlg = AddDownloadDialog(self, None, self.cfg.default_threads, url=url)
        if from_clipboard:
            dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
            dlg.setWindowTitle("Add Download — link copied to clipboard")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        u = dlg.url
        if dlg.is_video_site and "/playlist" in urlparse(u).path:
            self._submit(self._expand_playlist(u, self.cfg.yt_default_quality))
            self.statusBar().showMessage("Reading playlist…", 5000)
            return
        self._start_download(u, save_dir=dlg.save_dir, filename=dlg.filename,
                             threads=dlg.threads, auto_name=dlg.auto_name,
                             later=dlg.later)

    async def _expand_playlist(self, url: str, choice: str) -> None:
        try:
            info = await asyncio.to_thread(YtDlp.playlist, url)
        except Exception as e:  # noqa: BLE001
            self.message.emit(f"Playlist failed: {clean_error(e)}")
            return
        self.download_requested.emit({"type": "playlist", "title": info["title"],
                                      "entries": info["entries"], "choice": choice})

    def batch_download(self) -> None:
        dlg = BatchDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        n = 0
        for u in dlg.urls:
            if self._start_download(u, save_dir=dlg.save_dir, source="batch", later=dlg.later):
                n += 1
        self.statusBar().showMessage(
            f"Added {n} downloads{' to the schedule' if dlg.later else ''}", 5000)

    def _resolve_existing(self, url: str, save_dir: Path, name: str, engine: str,
                          source: str) -> tuple[str, str, bool] | DownloadTask | None:
        """Returns (name, 'ok', overwrite), an existing task to reuse, or None (cancel)."""
        quiet = source in QUIET_SOURCES
        if not quiet:
            dup = next((t for t in self.tasks.values()
                        if t.url == url and t.state != TaskState.COMPLETED), None)
            if dup:
                box = QMessageBox(QMessageBox.Icon.Question, APP_NAME,
                                  f"“{dup.filename}” is already in the download list "
                                  f"({dup.state.value}).", parent=self)
                box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
                resumable = dup.state in RESUMABLE_STATES
                b_existing = box.addButton("Resume It" if resumable else "Show It",
                                           QMessageBox.ButtonRole.AcceptRole)
                b_new = box.addButton("Download Again", QMessageBox.ButtonRole.ActionRole)
                box.addButton(QMessageBox.StandardButton.Cancel)
                box.exec()
                if box.clickedButton() == b_existing:
                    if resumable:
                        self.resume_task(dup)
                    self._select_task(dup)
                    return dup
                if box.clickedButton() != b_new:
                    return None
        overwrite = False
        if engine == "http" and (save_dir / name).exists():
            action = self.cfg.existing_file_action
            if action == "ask" and quiet:
                action = "rename"
            if action == "ask":
                box = QMessageBox(QMessageBox.Icon.Question, APP_NAME,
                                  f"“{name}” already exists in\n{save_dir}", parent=self)
                box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
                b_rename = box.addButton(f"Save as “{unique_filename(save_dir, name)}”",
                                         QMessageBox.ButtonRole.AcceptRole)
                b_over = box.addButton("Overwrite", QMessageBox.ButtonRole.DestructiveRole)
                box.addButton(QMessageBox.StandardButton.Cancel)
                box.exec()
                if box.clickedButton() == b_over:
                    action = "overwrite"
                elif box.clickedButton() == b_rename:
                    action = "rename"
                else:
                    return None
            overwrite = action == "overwrite"
        return name, "ok", overwrite

    def _start_download(self, url: str, *, save_dir: Path | None = None,
                        filename: str | None = None, threads: int | None = None,
                        auto_name: bool = True, referer: str | None = None,
                        mime: str | None = None, kind: str | None = None,
                        task_id: str | None = None, source: str = "manual",
                        user_agent: str | None = None, cookies: str | None = None,
                        cookie_jar: list | None = None,
                        immediate: bool = False, engine: str | None = None,
                        yt_choice: str | None = None, later: bool = False,
                        show_window: bool = True) -> DownloadTask | None:
        """Single entry point for every kind of download (GUI thread)."""
        if engine is None:   # a YouTube link pasted into "Add URL" → use yt-dlp
            engine = "ytdlp" if YTDLP_AVAILABLE and YtDlp.is_youtube(url) else "http"
            if engine == "ytdlp":
                yt_choice = yt_choice or self.cfg.yt_default_quality
                filename, auto_name = "YouTube video" + YtDlp.ext_for(yt_choice), False
        name = safe_filename(filename or name_for(url, mime))
        save_dir = save_dir or category_dir(url, kind, mime, name)

        resolved = self._resolve_existing(url, save_dir, name, engine, source)
        if resolved is None:
            return None
        if isinstance(resolved, DownloadTask):
            if task_id:
                self._aliases[task_id] = resolved.id
            return resolved
        name, _, overwrite = resolved

        taken = {t.filename for t in self.tasks.values()
                 if t.save_dir == save_dir and t.state != TaskState.COMPLETED}
        if not overwrite:
            name = unique_filename(save_dir, name, taken)
        task = DownloadTask(id=task_id or uuid.uuid4().hex, url=url, save_dir=save_dir,
                            filename=name, num_threads=threads or self.cfg.default_threads,
                            auto_name=auto_name, referer=referer, source=source,
                            user_agent=user_agent, cookies=cookies, cookie_jar=cookie_jar,
                            engine=engine, yt_choice=yt_choice, overwrite=overwrite)
        if later:
            task.state = TaskState.SCHEDULED
        self.tasks[task.id] = task
        self._last_state[task.id] = task.state
        self.table.add_task(task)
        self._persist(task, force=True)
        if not later:
            self._submit(self.queue.enqueue(task, immediate=immediate))
            if show_window and self.cfg.show_progress_window and source not in QUIET_SOURCES:
                self.show_download_window(task)
        return task

    # ── clipboard ───────────────────────────────────────────────────────

    # ── sniffer / browser ───────────────────────────────────────────────
    def _toggle_sniffer(self, on: bool) -> None:
        self._set_cfg(sniffer_enabled=on)
        self.start_sniffer() if on else self.stop_sniffer()

    def start_sniffer(self) -> None:
        if not self.sniffer_api:
            return

        async def go():
            try:
                await self.sniffer_api.start()
                self.sniffer_state.emit("on", f"listening on {HOST}:{PORT}")
            except OSError as e:
                self.sniffer_state.emit("error", f"port {PORT} unavailable ({e.strerror or e})")
        self._submit(go())

    def stop_sniffer(self) -> None:
        if not self.sniffer_api:
            return

        async def go():
            await self.sniffer_api.stop()
            self.sniffer_state.emit("off", "off")
        self._submit(go())

    def _on_sniffer_state(self, state: str, text: str) -> None:
        color = {"on": "#2e9d4f", "error": "#d64545"}.get(state, "#888888")
        self.sniffer_label.setText(f'Sniffer: <span style="color:{color}">●</span> {text}')
        self.act_sniffer.blockSignals(True)
        self.act_sniffer.setChecked(state == "on")
        self.act_sniffer.blockSignals(False)

    def _download_detected(self, items: list[DetectedItem]) -> None:
        for item in items:
            self._start_download(item.url, referer=item.page, mime=item.mime,
                                 kind=item.kind, source="sniffer")
            item.queued = True
            self.sniffed_panel.update_item(item)
        self.statusBar().showMessage(f"Queued {len(items)} sniffed item(s)", 3000)

    def _on_api_download(self, req: dict) -> None:
        if req.get("type") == "playlist":
            self._add_playlist(req)
            return
        if req["task_id"] in self.tasks or req["task_id"] in self._aliases:
            return
        source = req["source"] if req["source"] in ("sniffer", "youtube", "video") else "browser"

        # "Refresh download address": a re-started browser download continues an old one
        if source == "browser" and self._awaiting_refresh:
            target = self._match_refresh(req)
            if target:
                self._aliases[req["task_id"]] = target.id
                self._apply_new_address(target, req["url"], req.get("cookies"),
                                        req.get("user_agent"), req.get("referer"))
                self.tray.notify("Download address refreshed", target.filename)
                return

        task = self._start_download(
            req["url"], referer=req.get("referer"), mime=req.get("mime"),
            kind=req.get("kind"), task_id=req["task_id"], filename=req.get("filename"),
            auto_name=not req.get("filename"), source=source,
            user_agent=req.get("user_agent"), cookies=req.get("cookies"),
            cookie_jar=req.get("cookie_jar"), immediate=req.get("immediate", False),
            engine=req.get("engine", "http"), yt_choice=req.get("yt_choice"))
        if task and source != "sniffer":
            self._select_task(task)
            QApplication.alert(self)
            what = {"youtube": "YouTube", "video": "video page"}.get(source, "browser")
            self.statusBar().showMessage(f"Caught from {what}: {task.filename}", 5000)

    def _add_playlist(self, req: dict) -> None:
        choice = req.get("choice") or "best"
        ext = ".m4a" if req.get("audio_only") and choice.startswith("v") else YtDlp.ext_for(choice)
        folder = category_dir("", filename="x" + ext) / safe_filename(req["title"][:100])
        n = 0
        for e in req["entries"]:
            if self._start_download(e["url"], save_dir=folder, engine="ytdlp",
                                    yt_choice=choice, auto_name=False, source="playlist",
                                    filename=safe_filename(e["title"][:150]) + ext):
                n += 1
        self.tabs.setCurrentIndex(0)
        self.statusBar().showMessage(f"Playlist “{req['title']}”: {n} videos queued", 6000)
        self.tray.notify("Playlist added", f"{req['title']} — {n} videos")

    def _status_snapshot(self) -> list[dict]:
        """Called on the worker thread by GET /status — read-only copies."""
        snap = [{"id": t.id, "url": t.url, "filename": t.filename,
                 "state": t.state.value, "progress": round(t.progress, 4),
                 "downloaded": t.downloaded, "total": t.total_size,
                 "speed": t.speed_bps, "error": t.error}
                for t in list(self.tasks.values())]
        by_id = {d["id"]: d for d in snap}
        for alias, real in list(self._aliases.items()):
            if real in by_id:
                snap.append({**by_id[real], "id": alias})
        return snap

    # ── refresh download address ────────────────────────────────────────
    def refresh_address(self) -> None:
        tasks = [t for t in self.table.selected_tasks() if t.engine == "http"
                 and t.state not in ACTIVE_STATES and t.state != TaskState.COMPLETED]
        if not tasks:
            QMessageBox.information(self, APP_NAME, "Select a paused or failed download first.\n"
                                    "(Pause it if it's still running.)")
            return
        task = tasks[0]
        dlg = RefreshAddressDialog(task, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if dlg.catch:
            self._awaiting_refresh.add(task.id)
            self.statusBar().showMessage(
                f"Start “{task.filename}” again in the browser — PyDM will continue it", 10000)
        else:
            self._apply_new_address(task, dlg.url)

    def _match_refresh(self, req: dict) -> DownloadTask | None:
        names = {name_for(req["url"], req.get("mime"))}
        if req.get("filename"):
            names.add(safe_filename(req["filename"]))
        for tid in list(self._awaiting_refresh):
            t = self.tasks.get(tid)
            if t is None:
                self._awaiting_refresh.discard(tid)
            elif t.filename in names or name_for(t.url) in names:
                return t
        return None

    def _apply_new_address(self, task: DownloadTask, url: str, cookies: str | None = None,
                           user_agent: str | None = None, referer: str | None = None) -> None:
        self._awaiting_refresh.discard(task.id)
        if not task.chunks:
            PartFiles.load(task)            # must load with the old URL first
        task.url = url
        task.refreshed = True
        task.error = None
        if cookies:
            task.cookies = cookies
        if user_agent:
            task.user_agent = user_agent
        if referer:
            task.referer = referer
        PartFiles.save(task)
        self._persist(task, force=True)
        self.table.update_task(task)
        self.resume_task(task, immediate=True)
        self._select_task(task)

    # ── per-task actions ────────────────────────────────────────────────
    def pause_task(self, t: DownloadTask) -> None:
        if t.state in ACTIVE_STATES or t.state == TaskState.QUEUED:
            self._submit(self.queue.pause(t))

    def enqueue_task(self, t: DownloadTask, immediate: bool = False) -> None:
        """Send a task to the download queue regardless of its current state."""
        self._submit(self.queue.enqueue(t, immediate=immediate))

    def resume_task(self, t: DownloadTask, immediate: bool = False) -> None:
        if t.state in RESUMABLE_STATES:
            self._submit(self.queue.enqueue(t, immediate=immediate))

    def cancel_task(self, t: DownloadTask) -> None:
        if t.state in ACTIVE_STATES or t.state == TaskState.QUEUED:
            self._submit(self.queue.cancel(t))
        elif t.state in (TaskState.PAUSED, TaskState.ERROR, TaskState.SCHEDULED):
            PartFiles.delete(t)
            t.chunks, t.downloaded, t.state = [], 0, TaskState.CANCELLED
            self._on_task_updated(t)

    def pause_selected(self) -> None:
        for t in self.table.selected_tasks():
            self.pause_task(t)

    def resume_selected(self) -> None:
        for t in self.table.selected_tasks():
            self.resume_task(t)

    def pause_all(self) -> None:
        for t in self.tasks.values():
            self.pause_task(t)

    def resume_all(self) -> None:
        for t in self.tasks.values():
            if t.state in (TaskState.PAUSED, TaskState.ERROR):
                self.resume_task(t)

    def show_download_window(self, task: DownloadTask) -> None:
        w = self.windows.get(task.id)
        if w is None:
            w = DownloadWindow(task, self)
            self.windows[task.id] = w
            w.destroyed.connect(lambda _=None, i=task.id: self.windows.pop(i, None))
        w.refresh()
        w.show()
        w.raise_()

    def show_selected_window(self) -> None:
        for t in self.table.selected_tasks()[:5]:
            self.show_download_window(t)

    def _double_click(self, task: DownloadTask | None) -> None:
        if not task:
            return
        if task.state == TaskState.COMPLETED:
            self._open_task(task)
        else:
            self.show_download_window(task)

    def verify_checksum(self) -> None:
        done = [t for t in self.table.selected_tasks()
                if t.state == TaskState.COMPLETED and t.final_path.exists()]
        if not done:
            QMessageBox.information(self, APP_NAME, "Select a completed download first.")
            return
        ChecksumDialog(done[0].final_path, self).exec()

    def schedule_selected(self) -> None:
        for t in self.table.selected_tasks():
            if t.state == TaskState.QUEUED:
                self._submit(self.queue.pause(t))
                self.schedule.reschedule.add(t.id)
            elif t.state in (TaskState.PAUSED, TaskState.ERROR, TaskState.CANCELLED):
                t.state = TaskState.SCHEDULED
                self._on_task_updated(t)

    def unschedule_selected(self) -> None:
        for t in self.table.selected_tasks():
            if t.state == TaskState.SCHEDULED:
                t.state = TaskState.PAUSED
                self._on_task_updated(t)

    def remove_selected(self) -> None:
        tasks = self.table.selected_tasks()
        if not tasks:
            return
        delete_files = False
        finished = [t for t in tasks if t.state == TaskState.COMPLETED
                    and t.final_path.exists()]
        if finished:
            ans = QMessageBox.question(
                self, APP_NAME,
                f"Remove {len(tasks)} item(s) from the list.\n\n"
                f"Also delete {len(finished)} downloaded file(s) from disk?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel)
            if ans == QMessageBox.StandardButton.Cancel:
                return
            delete_files = ans == QMessageBox.StandardButton.Yes
        elif QMessageBox.question(
                self, APP_NAME, f"Remove {len(tasks)} item(s)? "
                "Unfinished data will be deleted.") != QMessageBox.StandardButton.Yes:
            return

        for t in tasks:
            if t.state in ACTIVE_STATES or t.state == TaskState.QUEUED:
                self._submit(self.queue.cancel(t))
            elif t.state != TaskState.COMPLETED:
                PartFiles.delete(t)
            elif delete_files:
                try:
                    t.final_path.unlink(missing_ok=True)
                except OSError as e:
                    QMessageBox.warning(self, APP_NAME, f"Couldn't delete file:\n{e}")
            self._forget(t)

    def clear_completed(self) -> None:
        for t in [t for t in self.tasks.values() if t.state == TaskState.COMPLETED]:
            self._forget(t)

    def _forget(self, task: DownloadTask) -> None:
        self.table.remove_task(task.id)
        w = self.windows.pop(task.id, None)
        if w:
            w.close()
        self.tasks.pop(task.id, None)
        self._persisted.pop(task.id, None)
        self._last_state.pop(task.id, None)
        self.schedule.forget(task.id)
        self._awaiting_refresh.discard(task.id)
        self.db.delete(task.id)
        self._refresh_actions()

    def _open_task(self, task: DownloadTask | None) -> None:
        if not task:
            return
        if task.state == TaskState.COMPLETED and task.final_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(task.final_path)))
        else:
            self._open_folder(task)

    @staticmethod
    def _open_folder(task: DownloadTask) -> None:
        task.save_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(task.save_dir)))

    def _context_menu(self, pos) -> None:
        task = self.table.task_at(self.table.rowAt(pos.y()))
        if not task:
            return
        menu = QMenu(self)
        if task.state == TaskState.COMPLETED:
            menu.addAction("Open File", lambda: self._open_task(task))
        menu.addAction("Open Folder", lambda: self._open_folder(task))
        menu.addAction("Copy URL", lambda: self.clipboard.copy(task.url))
        if task.error:
            menu.addAction("Show Error", lambda: QMessageBox.warning(
                self, APP_NAME, f"{task.filename}\n\n{task.error}"))
        menu.addSeparator()
        for a in (self.act_resume, self.act_pause, self.act_window, self.act_refresh,
                  self.act_checksum, self.act_schedule, self.act_unschedule):
            if a.isEnabled():
                menu.addAction(a)
        menu.addSeparator()
        menu.addAction(self.act_remove)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _refresh_actions(self) -> None:
        sel = self.table.selected_tasks()
        busy = ACTIVE_STATES | {TaskState.QUEUED}
        self.act_pause.setEnabled(any(t.state in busy for t in sel))
        self.act_resume.setEnabled(any(t.state in RESUMABLE_STATES for t in sel))
        self.act_remove.setEnabled(bool(sel))
        self.act_window.setEnabled(bool(sel))
        self.act_refresh.setEnabled(any(
            t.engine == "http" and t.state not in busy and t.state != TaskState.COMPLETED
            for t in sel))
        self.act_checksum.setEnabled(any(t.state == TaskState.COMPLETED for t in sel))
        self.act_schedule.setEnabled(any(
            t.state in (TaskState.PAUSED, TaskState.ERROR, TaskState.CANCELLED,
                        TaskState.QUEUED) for t in sel))
        self.act_unschedule.setEnabled(any(t.state == TaskState.SCHEDULED for t in sel))
        self.act_clear.setEnabled(any(
            t.state == TaskState.COMPLETED for t in self.tasks.values()))
        self.act_stop_sched.setEnabled(bool(getattr(self, "schedule", None) and self.schedule.running))

    def _refresh_status(self) -> None:
        active = [t for t in self.tasks.values() if t.state == TaskState.DOWNLOADING]
        queued = sum(t.state == TaskState.QUEUED for t in self.tasks.values())
        sched = sum(t.state == TaskState.SCHEDULED for t in self.tasks.values())
        speed = sum(t.speed_bps for t in active)
        extra = f"   Scheduled: {sched}" if sched else ""
        self.status_label.setText(
            f"Active: {len(active)}   Queued: {queued}{extra}   "
            f"Speed: {human_speed(speed)}   "
            f"yt-dlp {'✓' if YTDLP_AVAILABLE else '✗'}  ffmpeg {'✓' if FFMPEG_AVAILABLE else '✗'}  ")
        self.tray.set_tooltip(f"{APP_NAME} — {len(active)} active, {human_speed(speed)}"
                              if active else APP_NAME)

    # ── settings ────────────────────────────────────────────────────────
    def open_settings(self) -> None:
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.apply_settings(dlg.result_settings())

    def apply_settings(self, new: Settings) -> None:
        old = self.cfg.copy()
        self.cfg.__dict__.update(new.__dict__)
        self.cfg.save()
        self.engine.dynamic = self.cfg.dynamic_segmentation
        for spin, value in ((self.concurrent_spin, self.cfg.max_concurrent),
                            (self.limit_spin, self.cfg.speed_limit_kbps)):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        self._submit(self.queue.set_max_concurrent(self.cfg.max_concurrent))
        rate = self.cfg.speed_limit_kbps * 1024

        async def apply_rate():
            self.engine.limiter.set_rate(rate)
        self._submit(apply_rate())
        self.act_intercept.blockSignals(True)
        self.act_intercept.setChecked(self.cfg.intercept_enabled)
        self.act_intercept.blockSignals(False)
        if self.cfg.sniffer_enabled != old.sniffer_enabled:
            self.start_sniffer() if self.cfg.sniffer_enabled else self.stop_sniffer()
        try:
            download_root().mkdir(parents=True, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Can't use the download folder:\n{e}")

    # ── scheduler ───────────────────────────────────────────────────────

    # ── shutdown ────────────────────────────────────────────────────────
    def quit_app(self) -> None:
        self._really_quit = True
        self.close()

    def _save_everything(self) -> None:
        self.cfg.window_geometry = bytes(self.saveGeometry().toBase64()).decode()
        self.cfg.save()
        for t in self.tasks.values():
            self.db.upsert(t)

    def closeEvent(self, event) -> None:
        if self.tray.available and self.cfg.minimize_to_tray and not self._really_quit:
            event.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.notify(APP_NAME, "PyDM is still running here. "
                                 "Right-click the tray icon → Exit to quit.", force=True)
            return
        self.statusBar().showMessage("Saving download state…")
        QApplication.processEvents()
        for w in list(self.windows.values()):
            w.close()
        if self.sniffer_api:
            try:
                self.worker.submit(self.sniffer_api.stop()).result(timeout=3)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
        try:
            self.worker.submit(self.queue.shutdown()).result(timeout=60)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        for t in self.tasks.values():
            if t.state in ACTIVE_STATES or t.state == TaskState.QUEUED:
                t.state = TaskState.SCHEDULED if t.id in self.schedule.running else TaskState.PAUSED
        self._save_everything()
        self.worker.stop()
        self.worker.wait(5000)
        self.db.close()
        self.tray.hide()
        event.accept()
        QTimer.singleShot(0, QApplication.quit)
