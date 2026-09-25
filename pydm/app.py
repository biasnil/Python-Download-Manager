"""PyDMApplication: start-up (settings, folders, Qt app, main window)."""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from .config import APP_NAME, CONFIG, DATA_DIR, DB_PATH, download_root, load_config
from .database import Database
from .icons import Icons
from .main_window import MainWindow



class PyDMApplication:
    def __init__(self, argv: list[str]):
        self.argv = argv

    @staticmethod
    def ensure_dirs() -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        download_root().mkdir(parents=True, exist_ok=True)

    def run(self) -> int:
        load_config()
        self.ensure_dirs()
        app = QApplication(self.argv)
        app.setApplicationName(APP_NAME)
        app.setWindowIcon(Icons.app())
        app.setQuitOnLastWindowClosed(False)      # keeps running in the tray
        window = MainWindow(Database(DB_PATH), CONFIG)
        if not (CONFIG.start_minimized and window.tray.available):
            window.show()
        return app.exec()


def main() -> None:
    sys.exit(PyDMApplication(sys.argv).run())
