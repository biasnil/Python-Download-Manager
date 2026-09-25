"""Power actions after downloads finish, with a countdown dialog."""

from __future__ import annotations

import platform
import subprocess

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout

from .config import APP_NAME


class PowerManager:
    """Sleep / hibernate / shut down the computer."""

    ACTIONS = {"nothing": "Do nothing", "exit": "Exit PyDM", "sleep": "Sleep",
                     "hibernate": "Hibernate", "shutdown": "Shut down"}


    @staticmethod
    def perform(action: str) -> None:
        system = platform.system()
        cmds = {
            "Windows": {"shutdown": ["shutdown", "/s", "/t", "0"],
                        "hibernate": ["shutdown", "/h"],
                        "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"]},
            "Darwin": {"shutdown": ["osascript", "-e", 'tell app "System Events" to shut down'],
                       "sleep": ["pmset", "sleepnow"], "hibernate": ["pmset", "sleepnow"]},
            "Linux": {"shutdown": ["systemctl", "poweroff"], "sleep": ["systemctl", "suspend"],
                      "hibernate": ["systemctl", "hibernate"]},
        }
        cmd = cmds.get(system, cmds["Linux"]).get(action)
        if cmd:
            try:
                subprocess.Popen(cmd)
            except OSError as e:
                QMessageBox.warning(None, APP_NAME, f"Couldn't {action}: {e}")


class PowerCountdownDialog(QDialog):
    """60-second warning before PyDM sleeps/shuts down the PC."""

    def __init__(self, action: str, on_confirm, seconds: int = 60, parent=None):
        super().__init__(parent)
        self.setWindowTitle(APP_NAME)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.action, self.on_confirm, self.left = action, on_confirm, seconds
        lay = QVBoxLayout(self)
        self.label = QLabel()
        lay.addWidget(self.label)
        row = QHBoxLayout()
        now = QPushButton(f"{PowerManager.ACTIONS[action]} now")
        cancel = QPushButton("Cancel")
        cancel.setDefault(True)
        row.addStretch()
        row.addWidget(now)
        row.addWidget(cancel)
        lay.addLayout(row)
        now.clicked.connect(self._fire)
        cancel.clicked.connect(self.reject)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)
        self._render()

    def _render(self):
        self.label.setText(f"All downloads are finished.\n\n"
                           f"{PowerManager.ACTIONS[self.action]} in {self.left} seconds…")

    def _tick(self):
        self.left -= 1
        if self.left <= 0:
            self._fire()
        else:
            self._render()

    def _fire(self):
        self.timer.stop()
        self.accept()
        self.on_confirm(self.action)
