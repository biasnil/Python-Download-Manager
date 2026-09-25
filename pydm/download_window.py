"""Per-download progress / 'Download complete' window."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QAbstractItemView, QCheckBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from .models import ACTIVE_STATES, DownloadTask, TaskState
from .utils import human_bytes, human_eta, human_speed

if TYPE_CHECKING:            # only for type hints (avoids a circular import)
    from .main_window import MainWindow


class SegmentBar(QWidget):
    """IDM-style bar: one blue block per connection, showing what each has fetched."""

    def __init__(self):
        super().__init__()
        self.task: DownloadTask | None = None
        self.setMinimumHeight(20)

    def set_task(self, task: DownloadTask) -> None:
        self.task = task
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.fillRect(r, QColor("#dfe5ec"))
        t = self.task
        blue = QColor("#2e7dd7")
        if t and t.total_size > 0 and t.chunks and t.state != TaskState.COMPLETED:
            for c in list(t.chunks):
                x = r.x() + r.width() * c.start / t.total_size
                w = r.width() * min(c.downloaded, c.length or c.downloaded) / t.total_size
                p.fillRect(QRectF(x, r.y(), w, r.height()), blue)
            p.setPen(QColor("#ffffff"))
            for c in list(t.chunks):
                if c.start:
                    x = r.x() + r.width() * c.start / t.total_size
                    p.drawLine(QPointF(x, r.y()), QPointF(x, r.bottom()))
        elif t:
            p.fillRect(QRectF(r.x(), r.y(), r.width() * t.progress, r.height()), blue)
        p.setPen(QColor("#9aa7b5"))
        p.drawRect(r)
        p.end()


class DownloadWindow(QDialog):
    """Per-download window: live progress while running, 'complete' actions after."""

    def __init__(self, task: DownloadTask, main: "MainWindow"):
        super().__init__(main)
        self.task, self.main = task, main
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(560)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.l_url = QLabel()
        self.l_url.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.l_status = QLabel()
        self.l_size = QLabel()
        self.l_done = QLabel()
        self.l_rate = QLabel()
        self.l_eta = QLabel()
        self.l_resume = QLabel()
        form.addRow("URL:", self.l_url)
        form.addRow("Status:", self.l_status)
        form.addRow("File size:", self.l_size)
        form.addRow("Downloaded:", self.l_done)
        form.addRow("Transfer rate:", self.l_rate)
        form.addRow("Time left:", self.l_eta)
        form.addRow("Resume capability:", self.l_resume)
        lay.addLayout(form)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        lay.addWidget(self.bar)
        self.segments = SegmentBar()
        lay.addWidget(self.segments)

        self.conn_table = QTableWidget(0, 3)
        self.conn_table.setHorizontalHeaderLabels(["#", "Downloaded", "Info"])
        self.conn_table.verticalHeader().setVisible(False)
        self.conn_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.conn_table.horizontalHeader().setStretchLastSection(True)
        self.conn_table.setColumnWidth(0, 40)
        self.conn_table.setColumnWidth(1, 150)
        self.conn_table.setMaximumHeight(150)
        lay.addWidget(self.conn_table)

        # running buttons
        self.run_row = QWidget()
        rr = QHBoxLayout(self.run_row)
        rr.setContentsMargins(0, 0, 0, 0)
        self.btn_pause = QPushButton()
        self.btn_cancel = QPushButton("Cancel")
        btn_hide = QPushButton("Hide")
        rr.addStretch()
        for b in (self.btn_pause, self.btn_cancel, btn_hide):
            rr.addWidget(b)
        self.btn_pause.clicked.connect(self._pause_resume)
        self.btn_cancel.clicked.connect(lambda: self.main.cancel_task(self.task))
        btn_hide.clicked.connect(self.close)

        # completed buttons
        self.done_row = QWidget()
        dr = QHBoxLayout(self.done_row)
        dr.setContentsMargins(0, 0, 0, 0)
        self.dont_show = QCheckBox("Don't show this window again")
        btn_open = QPushButton("Open")
        btn_folder = QPushButton("Open Folder")
        btn_close = QPushButton("Close")
        btn_open.setDefault(True)
        dr.addWidget(self.dont_show)
        dr.addStretch()
        for b in (btn_open, btn_folder, btn_close):
            dr.addWidget(b)
        btn_open.clicked.connect(lambda: (self.main._open_task(self.task), self.close()))
        btn_folder.clicked.connect(lambda: (self.main._open_folder(self.task), self.close()))
        btn_close.clicked.connect(self.close)
        self.dont_show.toggled.connect(self.main.set_show_complete_dialog)

        lay.addWidget(self.run_row)
        lay.addWidget(self.done_row)
        self.refresh()

    def _pause_resume(self) -> None:
        if self.task.state in ACTIVE_STATES or self.task.state == TaskState.QUEUED:
            self.main.pause_task(self.task)
        else:
            self.main.resume_task(self.task)

    def refresh(self) -> None:
        t = self.task
        done = t.state == TaskState.COMPLETED
        pct = t.progress * 100
        self.setWindowTitle(f"Download complete — {t.filename}" if done
                            else f"{pct:.0f}% {t.filename}")
        url = t.url if len(t.url) < 90 else t.url[:60] + "…" + t.url[-25:]
        self.l_url.setText(url)
        self.l_url.setToolTip(t.url)
        self.l_status.setText(t.error if t.state == TaskState.ERROR and t.error
                              else ("Saved to " + str(t.final_path)) if done
                              else t.state.value)
        self.l_status.setWordWrap(True)
        self.l_size.setText(human_bytes(t.total_size) if t.total_size else "Unknown")
        self.l_done.setText(f"{human_bytes(t.downloaded)}  ({pct:.1f}%)")
        running = t.state == TaskState.DOWNLOADING
        self.l_rate.setText(human_speed(t.speed_bps) if running else "—")
        self.l_eta.setText(human_eta(t.eta_seconds) if running else "—")
        self.l_resume.setText("Yes (yt-dlp)" if t.engine == "ytdlp"
                              else "Yes" if t.resumable else
                              "Unknown" if t.state in (TaskState.QUEUED, TaskState.CONNECTING)
                              else "No — the server can't resume this file")
        if t.total_size <= 0 and running:
            self.bar.setRange(0, 0)
        else:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(t.progress * 1000))
        self.segments.set_task(t)
        self.segments.setVisible(not done)

        chunks = sorted(list(t.chunks), key=lambda c: c.start) if not done else []
        self.conn_table.setVisible(bool(chunks))
        self.conn_table.setRowCount(len(chunks))
        for i, c in enumerate(chunks):
            info = ("Complete" if c.completed else
                    "Receiving data…" if running else "Idle")
            for col, text in enumerate((str(i + 1), human_bytes(c.downloaded), info)):
                self.conn_table.setItem(i, col, QTableWidgetItem(text))

        self.run_row.setVisible(not done)
        self.done_row.setVisible(done)
        active = t.state in ACTIVE_STATES or t.state == TaskState.QUEUED
        self.btn_pause.setText("Pause" if active else "Resume")
        self.btn_pause.setEnabled(t.state != TaskState.MERGING)
        self.btn_cancel.setEnabled(t.state not in (TaskState.CANCELLED, TaskState.MERGING))
