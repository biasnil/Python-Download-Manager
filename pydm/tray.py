"""TrayController: the system-tray icon, its menu and notifications."""

from __future__ import annotations

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from .config import APP_NAME, Settings
from .icons import Icons



class TrayController(QObject):
    """Owns the tray icon. `available` is False where the OS has no tray."""

    def __init__(self, window, actions: list, cfg: Settings):
        super().__init__(window)
        self.window, self.cfg = window, cfg
        self.icon: QSystemTrayIcon | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.icon = QSystemTrayIcon(Icons.app(), window)
        menu = QMenu(window)
        menu.addAction("Show PyDM", window.show_window)
        for a in actions:
            menu.addSeparator() if a is None else menu.addAction(a)
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self._activated)
        self.icon.messageClicked.connect(window.show_window)
        self.icon.setToolTip(APP_NAME)
        self.icon.show()

    @property
    def available(self) -> bool:
        return self.icon is not None

    def notify(self, title: str, text: str, force: bool = False) -> None:
        """Balloon message; respects the 'tray notifications' setting unless forced."""
        if self.icon and (force or self.cfg.notify_on_complete):
            self.icon.showMessage(title, text, Icons.app(), 5000)

    def set_tooltip(self, text: str) -> None:
        if self.icon:
            self.icon.setToolTip(text)

    def hide(self) -> None:
        if self.icon:
            self.icon.hide()

    def _activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            w = self.window
            if w.isVisible() and not w.isMinimized():
                w.hide()
            else:
                w.show_window()
