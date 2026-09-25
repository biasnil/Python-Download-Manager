"""AsyncWorker: an asyncio event loop in a QThread (asyncio ↔ Qt bridge)."""

from __future__ import annotations

import asyncio
import threading

from PyQt6.QtCore import QThread


class AsyncWorker(QThread):
    """Runs an asyncio event loop in a background QThread."""

    def __init__(self):
        super().__init__()
        self.loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()

    def run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._ready.set()
        try:
            self.loop.run_forever()
        finally:
            pending = asyncio.all_tasks(self.loop)
            for t in pending:
                t.cancel()
            if pending:
                self.loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True))
            self.loop.close()

    def start_and_wait(self) -> None:
        self.start()
        self._ready.wait()

    def submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def stop(self) -> None:
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
