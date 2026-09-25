"""MD5 / SHA checksum verification."""

from __future__ import annotations

import hashlib
import re

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton
from pathlib import Path


class HashWorker(QThread):
    progress = pyqtSignal(int)
    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, path: Path, algo: str):
        super().__init__()
        self.path, self.algo, self._stop = path, algo, False

    def run(self) -> None:
        try:
            h = hashlib.new(self.algo)
            total = self.path.stat().st_size or 1
            done = 0
            with open(self.path, "rb") as f:
                while chunk := f.read(4 * 1024 * 1024):
                    if self._stop:
                        return
                    h.update(chunk)
                    done += len(chunk)
                    self.progress.emit(int(done * 1000 / total))
            self.done.emit(h.hexdigest())
        except OSError as e:
            self.failed.emit(str(e))


class ChecksumDialog(QDialog):
    ALGOS = {"md5": 32, "sha1": 40, "sha256": 64, "sha512": 128}

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Verify Checksum — {path.name}")
        self.setMinimumWidth(620)
        self.path = path
        self.worker: HashWorker | None = None
        form = QFormLayout(self)
        form.addRow("File:", QLabel(str(path)))
        self.algo = QComboBox()
        self.algo.addItems(["SHA-256", "SHA-1", "MD5", "SHA-512"])
        form.addRow("Algorithm:", self.algo)
        self.expected = QLineEdit()
        self.expected.setPlaceholderText("Paste the checksum from the website (optional)")
        self.expected.textChanged.connect(self._guess_algo)
        form.addRow("Expected:", self.expected)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        form.addRow(self.bar)
        self.result = QLineEdit()
        self.result.setReadOnly(True)
        form.addRow("Result:", self.result)
        self.verdict = QLabel()
        form.addRow("", self.verdict)
        row = QHBoxLayout()
        self.btn = QPushButton("Calculate")
        self.btn.clicked.connect(self._start)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        row.addStretch()
        row.addWidget(self.btn)
        row.addWidget(close)
        form.addRow(row)

    def _key(self) -> str:
        return self.algo.currentText().replace("-", "").lower()

    def _guess_algo(self, text: str) -> None:
        text = text.strip().lower()
        for i in range(self.algo.count()):
            key = self.algo.itemText(i).replace("-", "").lower()
            if len(text) == self.ALGOS[key] and re.fullmatch(r"[0-9a-f]+", text):
                self.algo.setCurrentIndex(i)
        self._compare()

    def _start(self) -> None:
        self.btn.setEnabled(False)
        self.result.clear()
        self.verdict.clear()
        self.worker = HashWorker(self.path, self._key())
        self.worker.progress.connect(self.bar.setValue)
        self.worker.done.connect(self._done)
        self.worker.failed.connect(lambda e: (self.verdict.setText(f"Error: {e}"),
                                              self.btn.setEnabled(True)))
        self.worker.start()

    def _done(self, digest: str) -> None:
        self.result.setText(digest)
        self.btn.setEnabled(True)
        self._compare()

    def _compare(self) -> None:
        exp = self.expected.text().strip().lower()
        got = self.result.text().strip().lower()
        if not exp or not got:
            return
        if exp == got:
            self.verdict.setText("<b style='color:#2e9d4f'>✓ Match — the file is intact</b>")
        else:
            self.verdict.setText("<b style='color:#d64545'>✗ Doesn't match — the file is "
                                 "corrupted or different</b>")

    def closeEvent(self, e) -> None:
        if self.worker and self.worker.isRunning():
            self.worker._stop = True
            self.worker.wait(2000)
        super().closeEvent(e)
