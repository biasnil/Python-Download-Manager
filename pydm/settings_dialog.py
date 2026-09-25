"""The Settings dialog (5 tabs)."""

from __future__ import annotations

from PyQt6.QtCore import QTime, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QTabWidget, QTimeEdit, QVBoxLayout, QWidget

from .config import APP_NAME, CONFIG_PATH, DEFAULT_DOWNLOAD_DIR, HOST, MAX_THREADS, PORT, Settings
from .power import PowerManager
from .ytdlp_backend import YtDlp


DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class SettingsDialog(QDialog):
    def __init__(self, cfg: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} Settings")
        self.setMinimumWidth(560)
        self.cfg = cfg.copy()
        tabs = QTabWidget()
        tabs.addTab(self._general(), "General")
        tabs.addTab(self._connection(), "Connection")
        tabs.addTab(self._browser(), "Browser")
        tabs.addTab(self._notifications(), "Notifications")
        tabs.addTab(self._scheduler(), "Scheduler")
        path = QLabel(f'Settings file: <a href="file">{CONFIG_PATH}</a>')
        path.setStyleSheet("color: gray;")
        path.linkActivated.connect(lambda _: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(CONFIG_PATH.parent))))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(path)
        lay.addWidget(buttons)

    # ── pages ───────────────────────────────────────────────────────────
    def _general(self) -> QWidget:
        w, form = QWidget(), QFormLayout()
        w.setLayout(form)
        self.dir_edit = QLineEdit(self.cfg.download_dir)
        browse = QPushButton("Browse…")
        browse.clicked.connect(lambda: (d := QFileDialog.getExistingDirectory(
            self, "Download folder", self.dir_edit.text())) and self.dir_edit.setText(d))
        row = QHBoxLayout()
        row.addWidget(self.dir_edit)
        row.addWidget(browse)
        form.addRow("Download folder:", row)
        self.categories = QCheckBox("Sort into sub-folders by type "
                                    "(Programs, Videos, Documents, Compressed…)")
        self.categories.setChecked(self.cfg.use_categories)
        form.addRow("", self.categories)
        self.existing = QComboBox()
        for key, text in (("ask", "Ask me"), ("rename", "Add a number: name (1).ext"),
                          ("overwrite", "Overwrite it")):
            self.existing.addItem(text, key)
        self.existing.setCurrentIndex(max(0, self.existing.findData(self.cfg.existing_file_action)))
        form.addRow("If the file already exists:", self.existing)
        self.clipboard = QCheckBox("Offer to download file links I copy (clipboard monitoring)")
        self.clipboard.setChecked(self.cfg.monitor_clipboard)
        self.tray = QCheckBox("Closing the window keeps PyDM running in the system tray")
        self.tray.setChecked(self.cfg.minimize_to_tray)
        self.start_min = QCheckBox("Start minimized to the tray")
        self.start_min.setChecked(self.cfg.start_minimized)
        for cb in (self.clipboard, self.tray, self.start_min):
            form.addRow("", cb)
        return w

    def _connection(self) -> QWidget:
        w, form = QWidget(), QFormLayout()
        w.setLayout(form)
        self.threads = QSpinBox()
        self.threads.setRange(1, MAX_THREADS)
        self.threads.setValue(self.cfg.default_threads)
        form.addRow("Threads per download:", self.threads)
        self.concurrent = QSpinBox()
        self.concurrent.setRange(1, 10)
        self.concurrent.setValue(self.cfg.max_concurrent)
        form.addRow("Downloads at the same time:", self.concurrent)
        self.limit = QSpinBox()
        self.limit.setRange(0, 1_000_000)
        self.limit.setSingleStep(100)
        self.limit.setSuffix(" KB/s")
        self.limit.setSpecialValueText("Unlimited")
        self.limit.setValue(self.cfg.speed_limit_kbps)
        form.addRow("Speed limit:", self.limit)
        self.dynamic = QCheckBox("Dynamic segmentation (idle threads take over the "
                                 "biggest remaining piece — faster finish)")
        self.dynamic.setChecked(self.cfg.dynamic_segmentation)
        form.addRow("", self.dynamic)
        return w

    def _browser(self) -> QWidget:
        w, form = QWidget(), QFormLayout()
        w.setLayout(form)
        self.sniffer = QCheckBox(f"Run the browser-extension API on {HOST}:{PORT}")
        self.sniffer.setChecked(self.cfg.sniffer_enabled)
        self.intercept = QCheckBox("Catch downloads started in the browser")
        self.intercept.setChecked(self.cfg.intercept_enabled)
        form.addRow("", self.sniffer)
        form.addRow("", self.intercept)
        self.min_kb = QSpinBox()
        self.min_kb.setRange(0, 10_000_000)
        self.min_kb.setSuffix(" KB")
        self.min_kb.setSpecialValueText("Catch everything")
        self.min_kb.setValue(self.cfg.min_intercept_kb)
        form.addRow("Leave files smaller than this to the browser:", self.min_kb)
        self.quality = QComboBox()
        for key, text in YtDlp.QUALITIES.items():
            self.quality.addItem(text, key)
        self.quality.setCurrentIndex(max(0, self.quality.findData(self.cfg.yt_default_quality)))
        form.addRow("YouTube links added with Add URL:", self.quality)
        return w

    def _notifications(self) -> QWidget:
        w, form = QWidget(), QFormLayout()
        w.setLayout(form)
        self.progress_win = QCheckBox("Show the progress window when a download starts")
        self.progress_win.setChecked(self.cfg.show_progress_window)
        self.complete_win = QCheckBox("Show the 'Download complete' window")
        self.complete_win.setChecked(self.cfg.show_complete_dialog)
        self.notify = QCheckBox("Tray notification when a download finishes")
        self.notify.setChecked(self.cfg.notify_on_complete)
        for cb in (self.progress_win, self.complete_win, self.notify):
            form.addRow("", cb)
        note = QLabel("Bulk downloads (sniffed items, batch, playlists) never pop up windows.")
        note.setStyleSheet("color: gray;")
        form.addRow("", note)
        return w

    def _scheduler(self) -> QWidget:
        w, form = QWidget(), QFormLayout()
        w.setLayout(form)
        self.sched_on = QCheckBox("Start the scheduled queue automatically")
        self.sched_on.setChecked(self.cfg.sched_enabled)
        form.addRow("", self.sched_on)
        self.start_time = QTimeEdit(QTime.fromString(self.cfg.sched_start, "HH:mm"))
        self.start_time.setDisplayFormat("HH:mm")
        form.addRow("Start at:", self.start_time)
        self.stop_on = QCheckBox("Stop at:")
        self.stop_on.setChecked(bool(self.cfg.sched_stop))
        self.stop_time = QTimeEdit(QTime.fromString(self.cfg.sched_stop or "07:00", "HH:mm"))
        self.stop_time.setDisplayFormat("HH:mm")
        self.stop_time.setEnabled(self.stop_on.isChecked())
        self.stop_on.toggled.connect(self.stop_time.setEnabled)
        form.addRow(self.stop_on, self.stop_time)
        days = QHBoxLayout()
        self.day_boxes = []
        for i, d in enumerate(DAY_NAMES):
            cb = QCheckBox(d)
            cb.setChecked(i in self.cfg.sched_days)
            self.day_boxes.append(cb)
            days.addWidget(cb)
        form.addRow("On:", days)
        self.when_done = QComboBox()
        for key, text in PowerManager.ACTIONS.items():
            self.when_done.addItem(text, key)
        self.when_done.setCurrentIndex(max(0, self.when_done.findData(self.cfg.sched_when_done)))
        form.addRow("When the queue finishes:", self.when_done)
        note = QLabel("Put downloads in the queue with “Download Later”, or right-click →\n"
                      "Add to Schedule. Tools → Start Scheduled Queue runs it right now.")
        note.setStyleSheet("color: gray;")
        form.addRow("", note)
        return w

    def result_settings(self) -> Settings:
        c = self.cfg
        c.download_dir = self.dir_edit.text().strip() or str(DEFAULT_DOWNLOAD_DIR)
        c.use_categories = self.categories.isChecked()
        c.existing_file_action = self.existing.currentData()
        c.monitor_clipboard = self.clipboard.isChecked()
        c.minimize_to_tray = self.tray.isChecked()
        c.start_minimized = self.start_min.isChecked()
        c.default_threads = self.threads.value()
        c.max_concurrent = self.concurrent.value()
        c.speed_limit_kbps = self.limit.value()
        c.dynamic_segmentation = self.dynamic.isChecked()
        c.sniffer_enabled = self.sniffer.isChecked()
        c.intercept_enabled = self.intercept.isChecked()
        c.min_intercept_kb = self.min_kb.value()
        c.yt_default_quality = self.quality.currentData()
        c.show_progress_window = self.progress_win.isChecked()
        c.show_complete_dialog = self.complete_win.isChecked()
        c.notify_on_complete = self.notify.isChecked()
        c.sched_enabled = self.sched_on.isChecked()
        c.sched_start = self.start_time.time().toString("HH:mm")
        c.sched_stop = self.stop_time.time().toString("HH:mm") if self.stop_on.isChecked() else ""
        c.sched_days = [i for i, cb in enumerate(self.day_boxes) if cb.isChecked()]
        c.sched_when_done = self.when_done.currentData()
        return c
