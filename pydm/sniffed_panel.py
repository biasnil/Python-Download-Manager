"""The Sniffed tab (media & pictures found by the browser extension)."""

from __future__ import annotations

from PyQt6.QtCore import QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QGuiApplication
from PyQt6.QtWidgets import QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QMenu, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from .config import APP_NAME
from .models import DetectedItem
from .sniffer import SnifferStore
from .utils import human_bytes, name_for


class SniffedPanel(QWidget):
    request_download = pyqtSignal(object)   # list[DetectedItem]
    cleared = pyqtSignal()
    count_changed = pyqtSignal(int)

    C_KIND, C_NAME, C_MIME, C_SIZE, C_PAGE, C_ACTION = range(6)

    def __init__(self, store: SnifferStore):
        super().__init__()
        self.store = store
        self.items: dict[str, DetectedItem] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        bar = QHBoxLayout()
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All", "Images", "Video & audio"])
        self.filter_combo.currentIndexChanged.connect(self._apply_filter)
        self.btn_dl = QPushButton("Download Selected")
        self.btn_imgs = QPushButton("Download All Images")
        self.btn_clear = QPushButton("Clear List")
        self.hint = QLabel()
        self.hint.setStyleSheet("color: gray;")
        bar.addWidget(QLabel("Show:"))
        bar.addWidget(self.filter_combo)
        bar.addWidget(self.btn_dl)
        bar.addWidget(self.btn_imgs)
        bar.addWidget(self.btn_clear)
        bar.addStretch()
        bar.addWidget(self.hint)
        layout.addLayout(bar)

        t = QTableWidget(0, 6)
        t.setHorizontalHeaderLabels(["Kind", "Name / URL", "MIME", "Size", "Page", ""])
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.verticalHeader().setVisible(False)
        t.setAlternatingRowColors(True)
        t.setWordWrap(False)
        t.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        h = t.horizontalHeader()
        h.setSectionResizeMode(self.C_NAME, QHeaderView.ResizeMode.Stretch)
        for col, w in ((self.C_KIND, 60), (self.C_MIME, 120), (self.C_SIZE, 80),
                       (self.C_PAGE, 200), (self.C_ACTION, 100)):
            t.setColumnWidth(col, w)
        t.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        t.customContextMenuRequested.connect(self._context_menu)
        t.cellDoubleClicked.connect(lambda r, _c: self._emit([self._item_at(r)]))
        layout.addWidget(t)
        self.table = t

        self.btn_dl.clicked.connect(lambda: self._emit(self._selected()))
        self.btn_imgs.clicked.connect(self._download_all_images)
        self.btn_clear.clicked.connect(self.clear)
        self._update_hint()

    # ── rows ────────────────────────────────────────────────────────────
    def add_items(self, items: list[DetectedItem]) -> None:
        for item in items:
            if item.id in self.items:
                continue
            self.items[item.id] = item
            r = self.table.rowCount()
            self.table.insertRow(r)
            kind = QTableWidgetItem("🖼 Image" if item.kind == "image" else "🎬 Media")
            kind.setData(Qt.ItemDataRole.UserRole, item.id)
            self.table.setItem(r, self.C_KIND, kind)
            name = QTableWidgetItem(f"{name_for(item.url, item.mime)}   —   {item.url}")
            name.setToolTip(item.url)
            self.table.setItem(r, self.C_NAME, name)
            self.table.setItem(r, self.C_MIME, QTableWidgetItem(item.mime or "—"))
            size = QTableWidgetItem(human_bytes(item.size) if item.size else "—")
            size.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, self.C_SIZE, size)
            page = QTableWidgetItem(item.page or "—")
            page.setToolTip(item.page or "")
            self.table.setItem(r, self.C_PAGE, page)
            btn = QPushButton()
            btn.clicked.connect(lambda _=False, i=item: self._emit([i]))
            self.table.setCellWidget(r, self.C_ACTION, btn)
            self._style_row(r, item)
            self._apply_filter_row(r, item)
        self.count_changed.emit(len(self.items))
        self._update_hint()

    def update_item(self, item: DetectedItem) -> None:
        r = self._row_of(item.id)
        if r >= 0:
            self._style_row(r, item)

    def _style_row(self, r: int, item: DetectedItem) -> None:
        btn: QPushButton = self.table.cellWidget(r, self.C_ACTION)
        btn.setText("✓ Queued" if item.queued else "Download")
        btn.setToolTip("Download again" if item.queued else "Send to Downloads")
        color = QColor("#888888") if item.queued else self.palette().text().color()
        for c in range(self.C_ACTION):
            cell = self.table.item(r, c)
            if cell:
                cell.setForeground(color)

    def _row_of(self, item_id: str) -> int:
        for r in range(self.table.rowCount()):
            cell = self.table.item(r, self.C_KIND)
            if cell and cell.data(Qt.ItemDataRole.UserRole) == item_id:
                return r
        return -1

    def _item_at(self, r: int) -> DetectedItem | None:
        cell = self.table.item(r, self.C_KIND)
        return self.items.get(cell.data(Qt.ItemDataRole.UserRole)) if cell else None

    def _selected(self) -> list[DetectedItem]:
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        return [it for r in rows if (it := self._item_at(r))]

    # ── actions ─────────────────────────────────────────────────────────
    def _emit(self, items: list) -> None:
        items = [i for i in items if i]
        if items:
            self.request_download.emit(items)

    def _download_all_images(self) -> None:
        todo = [i for i in self.items.values() if i.kind == "image" and not i.queued]
        if not todo:
            return
        if len(todo) > 20 and QMessageBox.question(
                self, APP_NAME, f"Download {len(todo)} images?") != QMessageBox.StandardButton.Yes:
            return
        self._emit(todo)

    def clear(self) -> None:
        self.table.setRowCount(0)
        self.items.clear()
        self.store.clear()
        self.cleared.emit()
        self.count_changed.emit(0)
        self._update_hint()

    def _remove(self, items: list[DetectedItem]) -> None:
        ids = {i.id for i in items}
        for r in reversed(range(self.table.rowCount())):
            it = self._item_at(r)
            if it and it.id in ids:
                self.table.removeRow(r)
        for i in ids:
            self.items.pop(i, None)
        self.store.remove(ids)
        self.count_changed.emit(len(self.items))
        self._update_hint()

    def _context_menu(self, pos) -> None:
        item = self._item_at(self.table.rowAt(pos.y()))
        if not item:
            return
        sel = self._selected() or [item]
        menu = QMenu(self)
        menu.addAction(f"Download ({len(sel)})", lambda: self._emit(sel))
        menu.addAction("Copy URL", lambda: QGuiApplication.clipboard().setText(
            "\n".join(i.url for i in sel)))
        menu.addAction("Open in Browser", lambda: QDesktopServices.openUrl(QUrl(item.url)))
        if item.page:
            menu.addAction("Open Source Page", lambda: QDesktopServices.openUrl(QUrl(item.page)))
        menu.addSeparator()
        menu.addAction("Remove from List", lambda: self._remove(sel))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _apply_filter(self) -> None:
        for r in range(self.table.rowCount()):
            it = self._item_at(r)
            if it:
                self._apply_filter_row(r, it)

    def _apply_filter_row(self, r: int, item: DetectedItem) -> None:
        f = self.filter_combo.currentIndex()
        hide = (f == 1 and item.kind != "image") or (f == 2 and item.kind != "media")
        self.table.setRowHidden(r, hide)

    def _update_hint(self) -> None:
        n = len(self.items)
        imgs = sum(i.kind == "image" for i in self.items.values())
        self.hint.setText(f"{n} detected  ·  {imgs} images  ·  {n - imgs} media"
                          if n else "Nothing sniffed yet — browse a page with the "
                                    "PyDM extension installed")
        self.btn_imgs.setEnabled(imgs > 0)
        self.btn_clear.setEnabled(n > 0)
