"""Icons: loads one SVG per icon from the project's ./icon folder."""

from __future__ import annotations

import sys

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap, QPolygonF
from PyQt6.QtWidgets import QApplication, QStyle
from pathlib import Path


# Source run: <project>/icon.  Built with PyInstaller: <bundle>/icon (sys._MEIPASS).
_BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
ICON_DIR = _BASE / "icon"


class Icons:
    """Loads the SVG icons from ./icon, falling back to Qt's built-in icons
    if a file is missing (so a broken icon never breaks the app)."""

    _cache: dict[str, QIcon] = {}
    SOURCES = {"sniffer": "sniffer", "youtube": "video", "video": "video",
               "playlist": "playlist", "browser": "browser", "batch": "batch"}
    FALLBACK = {
        "add": "SP_FileDialogNewFolder", "batch": "SP_FileDialogDetailedView",
        "resume": "SP_MediaPlay", "pause": "SP_MediaPause", "pause_all": "SP_MediaStop",
        "remove": "SP_TrashIcon", "clear": "SP_DialogResetButton",
        "settings": "SP_FileDialogInfoView", "schedule": "SP_MediaSeekForward",
        "sniffer": "SP_DriveNetIcon", "catch": "SP_ArrowDown", "video": "SP_MediaPlay",
        "playlist": "SP_FileDialogListView", "browser": "SP_ArrowDown",
        "refresh": "SP_BrowserReload", "checksum": "SP_DialogApplyButton",
        "window": "SP_TitleBarNormalButton", "folder": "SP_DirIcon",
        "exit": "SP_DialogCloseButton", "about": "SP_MessageBoxInformation",
    }

    @classmethod
    def get(cls, name: str | None) -> QIcon:
        if not name:
            return QIcon()
        if name not in cls._cache:
            path = ICON_DIR / f"{name}.svg"
            icon = QIcon(str(path)) if path.exists() else QIcon()
            if icon.isNull() or icon.pixmap(16, 16).isNull():
                icon = cls._fallback(name)
            cls._cache[name] = icon
        return cls._cache[name]

    @classmethod
    def app(cls) -> QIcon:
        return cls.get("app")

    @classmethod
    def for_source(cls, source: str) -> QIcon:
        return cls.get(cls.SOURCES.get(source))

    @classmethod
    def _fallback(cls, name: str) -> QIcon:
        if name == "app":
            return cls._drawn_app_icon()
        sp = cls.FALLBACK.get(name)
        app = QApplication.instance()
        if sp and app:
            return app.style().standardIcon(getattr(QStyle.StandardPixmap, sp))
        return QIcon()

    @staticmethod
    def _drawn_app_icon() -> QIcon:
        """Blue rounded square with a white download arrow."""
        pm = QPixmap(64, 64)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#2e7dd7"))
        p.drawRoundedRect(QRectF(2, 2, 60, 60), 13, 13)
        p.setBrush(QColor("white"))
        p.drawRect(QRectF(26, 11, 12, 22))
        p.drawPolygon(QPolygonF([QPointF(14, 30), QPointF(50, 30), QPointF(32, 48)]))
        p.drawRect(QRectF(14, 51, 36, 5))
        p.end()
        return QIcon(pm)
