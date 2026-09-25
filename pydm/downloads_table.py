"""DownloadsTable: the list of downloads on the Downloads tab."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QAbstractItemView, QHeaderView, QProgressBar, QTableWidget, QTableWidgetItem

from .icons import Icons
from .models import DownloadTask, TaskState
from .utils import human_bytes, human_eta, human_speed



class DownloadsTable(QTableWidget):
    """One row per task. The task id is stored in column 0 (UserRole)."""

    COL_NAME, COL_SIZE, COL_PROGRESS, COL_SPEED, COL_ETA, COL_STATUS = range(6)
    HEADERS = ["Name", "Size", "Progress", "Speed", "ETA", "Status"]
    STATE_COLORS = {TaskState.COMPLETED: "#2e9d4f", TaskState.ERROR: "#d64545",
                    TaskState.PAUSED: "#c88a12", TaskState.CANCELLED: "#888888",
                    TaskState.SCHEDULED: "#7b5cd6"}

    def __init__(self, tasks: dict[str, DownloadTask], parent=None):
        super().__init__(0, len(self.HEADERS), parent)
        self.tasks = tasks
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        h = self.horizontalHeader()
        h.setSectionResizeMode(self.COL_NAME, QHeaderView.ResizeMode.Stretch)
        for col, w in ((self.COL_SIZE, 170), (self.COL_PROGRESS, 170), (self.COL_SPEED, 100),
                       (self.COL_ETA, 80), (self.COL_STATUS, 110)):
            h.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            self.setColumnWidth(col, w)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    # ── lookup ──────────────────────────────────────────────────────────
    def row_of(self, task_id: str) -> int:
        for r in range(self.rowCount()):
            item = self.item(r, self.COL_NAME)
            if item and item.data(Qt.ItemDataRole.UserRole) == task_id:
                return r
        return -1

    def task_at(self, row: int) -> DownloadTask | None:
        item = self.item(row, self.COL_NAME)
        return self.tasks.get(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def selected_tasks(self) -> list[DownloadTask]:
        rows = sorted({i.row() for i in self.selectionModel().selectedRows()})
        return [t for r in rows if (t := self.task_at(r))]

    def select_task(self, task: DownloadTask) -> None:
        r = self.row_of(task.id)
        if r >= 0:
            self.selectRow(r)
            self.scrollToItem(self.item(r, self.COL_NAME))

    # ── rows ────────────────────────────────────────────────────────────
    def add_task(self, task: DownloadTask) -> None:
        r = self.rowCount()
        self.insertRow(r)
        name = QTableWidgetItem(task.filename)
        name.setData(Qt.ItemDataRole.UserRole, task.id)
        name.setIcon(Icons.for_source(task.source))
        self.setItem(r, self.COL_NAME, name)
        for col in (self.COL_SIZE, self.COL_SPEED, self.COL_ETA, self.COL_STATUS):
            item = QTableWidgetItem()
            if col != self.COL_STATUS:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                      | Qt.AlignmentFlag.AlignVCenter)
            self.setItem(r, col, item)
        bar = QProgressBar()
        bar.setRange(0, 1000)
        bar.setTextVisible(True)
        self.setCellWidget(r, self.COL_PROGRESS, bar)
        self._fill(r, task)

    def update_task(self, task: DownloadTask) -> None:
        r = self.row_of(task.id)
        if r >= 0:
            self._fill(r, task)

    def remove_task(self, task_id: str) -> None:
        r = self.row_of(task_id)
        if r >= 0:
            self.removeRow(r)

    def _fill(self, r: int, task: DownloadTask) -> None:
        self.item(r, self.COL_NAME).setText(task.filename)
        tip = f"{task.url}\n→ {task.final_path}"
        if task.referer:
            tip += f"\nfrom page: {task.referer}"
        self.item(r, self.COL_NAME).setToolTip(tip)

        if task.total_size > 0:
            size = f"{human_bytes(task.downloaded)} / {human_bytes(task.total_size)}"
        else:
            size = human_bytes(task.downloaded) if task.downloaded else "Unknown"
        if task.state == TaskState.COMPLETED:
            size = human_bytes(task.total_size)
        self.item(r, self.COL_SIZE).setText(size)

        bar: QProgressBar = self.cellWidget(r, self.COL_PROGRESS)
        if task.total_size <= 0 and task.state == TaskState.DOWNLOADING:
            bar.setRange(0, 0)
        else:
            bar.setRange(0, 1000)
            bar.setValue(int(task.progress * 1000))
            bar.setFormat(f"{task.progress * 100:.1f}%")

        downloading = task.state == TaskState.DOWNLOADING
        self.item(r, self.COL_SPEED).setText(human_speed(task.speed_bps) if downloading else "")
        self.item(r, self.COL_ETA).setText(human_eta(task.eta_seconds) if downloading else "")

        status = self.item(r, self.COL_STATUS)
        status.setText(task.state.value)
        status.setToolTip(task.error or "")
        color = self.STATE_COLORS.get(task.state)
        status.setForeground(QColor(color) if color else self.palette().text().color())
