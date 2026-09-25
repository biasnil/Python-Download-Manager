"""ClipboardMonitor: offers to download file links you copy."""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from pathlib import Path

from .config import Settings
from .utils import FILE_CATEGORIES, default_name, is_http_url


# only links that look like real files (not images / web pages)
CLIPBOARD_EXTS = set().union(*(v for k, v in FILE_CATEGORIES.items()
                               if k not in ("Images", "Streams")))


class ClipboardMonitor(QObject):
    """Emits `file_link_copied(url)` when a new file link lands on the clipboard."""

    file_link_copied = pyqtSignal(str)

    def __init__(self, cfg: Settings, known_urls, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.known_urls = known_urls            # callable → URLs already in the list
        self._last = QGuiApplication.clipboard().text().strip()
        QGuiApplication.clipboard().dataChanged.connect(self._changed)

    def copy(self, text: str) -> None:
        """Copy from inside PyDM without triggering ourselves."""
        self._last = text
        QGuiApplication.clipboard().setText(text)

    def _changed(self) -> None:
        text = QGuiApplication.clipboard().text().strip()
        if not self.cfg.monitor_clipboard or text == self._last:
            return
        self._last = text
        if not is_http_url(text) or any(c.isspace() for c in text):
            return
        if Path(default_name(text)).suffix.lower() not in CLIPBOARD_EXTS:
            return
        if text in set(self.known_urls()):
            return
        self.file_link_copied.emit(text)
