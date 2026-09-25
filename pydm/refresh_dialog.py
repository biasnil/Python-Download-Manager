"""Refresh Download Address dialog."""

from __future__ import annotations

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices, QGuiApplication
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QMessageBox

from .config import APP_NAME
from .models import DownloadTask
from .utils import is_http_url


class RefreshAddressDialog(QDialog):
    """Give a paused/failed download a fresh link and continue where it stopped."""

    def __init__(self, task: DownloadTask, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Refresh Download Address")
        self.setMinimumWidth(620)
        self.catch = False
        form = QFormLayout(self)
        form.addRow("File:", QLabel(task.filename))
        old = QLineEdit(task.url)
        old.setReadOnly(True)
        old.setCursorPosition(0)
        form.addRow("Current address:", old)
        self.new = QLineEdit()
        clip = QGuiApplication.clipboard().text().strip()
        if is_http_url(clip) and clip != task.url:
            self.new.setText(clip)
        self.new.setPlaceholderText("Paste the new download link")
        form.addRow("New address:", self.new)
        hint = QLabel("Or open the download page, start the download again in the browser, "
                      "and PyDM will catch it and continue this file instead of starting over.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        form.addRow("", hint)
        buttons = QDialogButtonBox()
        ok = buttons.addButton("Use New Address", QDialogButtonBox.ButtonRole.AcceptRole)
        catch = buttons.addButton("Catch From Browser…", QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        ok.clicked.connect(self._ok)
        catch.clicked.connect(self._catch)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.page = task.referer

    def _ok(self) -> None:
        if not is_http_url(self.url):
            QMessageBox.warning(self, APP_NAME, "Please paste a valid http(s) link.")
            return
        self.accept()

    def _catch(self) -> None:
        self.catch = True
        if self.page:
            QDesktopServices.openUrl(QUrl(self.page))
        self.accept()

    @property
    def url(self) -> str:
        return self.new.text().strip()
