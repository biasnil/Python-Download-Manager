"""Batch download dialog (URL patterns or a list)."""

from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget
from pathlib import Path

from .config import APP_NAME, download_root
from .utils import expand_pattern, is_http_url


class BatchDialog(QDialog):
    """Batch download: a URL pattern like file[001-100].jpg, or a pasted list."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Batch Download")
        self.setMinimumSize(620, 420)
        self.later = False
        self.tabs = QTabWidget()

        pat = QWidget()
        pl = QVBoxLayout(pat)
        pl.addWidget(QLabel("URL with a range in square brackets:"))
        self.pattern = QLineEdit()
        self.pattern.setPlaceholderText("https://example.com/photos/img_[001-120].jpg")
        pl.addWidget(self.pattern)
        help_ = QLabel("[1-50] numbers · [001-050] zero-padded · [a-z] letters · "
                       "[0-100:10] step 10 · several ranges allowed")
        help_.setStyleSheet("color: gray;")
        pl.addWidget(help_)
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        pl.addWidget(self.preview)
        pl.addStretch()
        self.tabs.addTab(pat, "Pattern")

        lst = QWidget()
        ll = QVBoxLayout(lst)
        ll.addWidget(QLabel("One URL per line:"))
        self.list_edit = QPlainTextEdit()
        ll.addWidget(self.list_edit)
        self.tabs.addTab(lst, "List of URLs")

        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText("(automatic — sorted by file type)")
        browse = QPushButton("Browse…")
        browse.clicked.connect(lambda: (d := QFileDialog.getExistingDirectory(
            self, "Save to", str(download_root()))) and self.dir_edit.setText(d))
        row = QHBoxLayout()
        row.addWidget(QLabel("Save to:"))
        row.addWidget(self.dir_edit)
        row.addWidget(browse)

        buttons = QDialogButtonBox()
        start = buttons.addButton("Start Downloads", QDialogButtonBox.ButtonRole.AcceptRole)
        later = buttons.addButton("Download Later", QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        start.clicked.connect(self._validate)
        later.clicked.connect(lambda: (setattr(self, "later", True), self._validate()))
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(self.tabs)
        lay.addLayout(row)
        lay.addWidget(buttons)
        self.pattern.textChanged.connect(self._update_preview)
        self._update_preview()

    def _update_preview(self) -> None:
        text = self.pattern.text().strip()
        if not text:
            self.preview.setText("")
            return
        try:
            urls = expand_pattern(text)
        except ValueError as e:
            self.preview.setText(f"<span style='color:#d64545'>{e}</span>")
            return
        if len(urls) == 1:
            self.preview.setText("No [range] found — this is a single URL.")
        else:
            self.preview.setText(f"<b>{len(urls):,} files</b><br>first: {urls[0]}<br>"
                                 f"last: {urls[-1]}")

    @property
    def urls(self) -> list[str]:
        if self.tabs.currentIndex() == 0:
            try:
                raw = expand_pattern(self.pattern.text().strip())
            except ValueError:
                raw = []
        else:
            raw = [line.strip() for line in self.list_edit.toPlainText().splitlines()]
        seen, out = set(), []
        for u in raw:
            if is_http_url(u) and u not in seen:
                seen.add(u)
                out.append(u)
        return out

    @property
    def save_dir(self) -> Path | None:
        t = self.dir_edit.text().strip()
        return Path(t).expanduser() if t else None

    def _validate(self) -> None:
        if not self.urls:
            QMessageBox.warning(self, APP_NAME, "No valid http(s) URLs to download.")
            self.later = False
            return
        if len(self.urls) > 200 and QMessageBox.question(
                self, APP_NAME, f"Add {len(self.urls):,} downloads?") != QMessageBox.StandardButton.Yes:
            self.later = False
            return
        self.accept()
