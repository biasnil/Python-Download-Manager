"""The Add Download dialog."""

from __future__ import annotations

import re

from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QWidget
from pathlib import Path
from urllib.parse import urlparse

from .config import APP_NAME, CONFIG, DEFAULT_THREADS, MAX_THREADS, YTDLP_AVAILABLE, download_root
from .utils import category_dir, default_name, is_http_url, safe_filename
from .ytdlp_backend import YtDlp


class AddDownloadDialog(QDialog):
    def __init__(self, parent=None, save_dir: Path | None = None,
                 threads: int = DEFAULT_THREADS, url: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Add Download")
        self.setMinimumWidth(600)
        self._name_edited = False
        self._dir_edited = save_dir is not None
        self.later = False

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://example.com/file.zip  (YouTube links work too)")
        self.dir_edit = QLineEdit(str(save_dir or download_root()))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        dir_row = QHBoxLayout()
        dir_row.setContentsMargins(0, 0, 0, 0)
        dir_row.addWidget(self.dir_edit)
        dir_row.addWidget(browse)
        dir_widget = QWidget()
        dir_widget.setLayout(dir_row)

        self.name_edit = QLineEdit()
        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(1, MAX_THREADS)
        self.threads_spin.setValue(threads)
        self.info = QLabel()
        self.info.setStyleSheet("color: gray;")

        form = QFormLayout(self)
        form.addRow("URL:", self.url_edit)
        form.addRow("Save to:", dir_widget)
        form.addRow("File name:", self.name_edit)
        form.addRow("Threads:", self.threads_spin)
        form.addRow("", self.info)
        buttons = QDialogButtonBox()
        start = buttons.addButton("Start Download", QDialogButtonBox.ButtonRole.AcceptRole)
        later = buttons.addButton("Download Later", QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        start.setDefault(True)
        start.clicked.connect(self._validate)
        later.clicked.connect(self._later)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        self.url_edit.textChanged.connect(self._url_changed)
        self.name_edit.textEdited.connect(lambda _: setattr(self, "_name_edited", True))
        self.dir_edit.textEdited.connect(lambda _: setattr(self, "_dir_edited", True))

        if url is None:
            clip = QGuiApplication.clipboard().text().strip()
            url = clip if re.match(r"^https?://\S+$", clip) else ""
        if url:
            self.url_edit.setText(url)
            self.url_edit.selectAll()

    @property
    def is_video_site(self) -> bool:
        return YTDLP_AVAILABLE and YtDlp.is_youtube(self.url)

    def _url_changed(self, text: str) -> None:
        video = self.is_video_site
        self.name_edit.setEnabled(not video)
        self.threads_spin.setEnabled(not video)
        if video:
            q = YtDlp.QUALITIES.get(CONFIG.yt_default_quality, "best quality")
            playlist = "/playlist" in urlparse(self.url).path
            self.name_edit.setText("(video title)")
            self.info.setText(f"YouTube {'playlist' if playlist else 'video'} → "
                              f"downloads as {q} (change in Settings → Browser)")
        else:
            self.info.setText("")
            if not self._name_edited:
                self.name_edit.setText(default_name(text) if text.strip() else "")
        if not self._dir_edited and text.strip():
            ext = ".mp4" if video else ""
            self.dir_edit.setText(str(category_dir(
                self.url, filename=(self.name_edit.text() if not video else "v" + ext))))

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Save to", self.dir_edit.text())
        if d:
            self.dir_edit.setText(d)
            self._dir_edited = True

    def _later(self) -> None:
        self.later = True
        self._validate()

    def _validate(self) -> None:
        if not is_http_url(self.url):
            QMessageBox.warning(self, APP_NAME, "Please enter a valid http(s) URL.")
            self.later = False
            return
        if not self.is_video_site and not self.name_edit.text().strip():
            QMessageBox.warning(self, APP_NAME, "Please enter a file name.")
            self.later = False
            return
        self.accept()

    @property
    def url(self) -> str:
        return self.url_edit.text().strip()

    @property
    def save_dir(self) -> Path:
        return Path(self.dir_edit.text().strip() or download_root()).expanduser()

    @property
    def filename(self) -> str | None:
        return None if self.is_video_site else safe_filename(self.name_edit.text().strip())

    @property
    def threads(self) -> int:
        return self.threads_spin.value()

    @property
    def auto_name(self) -> bool:
        return not self._name_edited
