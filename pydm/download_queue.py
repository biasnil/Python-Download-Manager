"""DownloadQueue: runs queued tasks with a max-concurrent limit."""

from __future__ import annotations

import asyncio

from collections import deque

from .config import MAX_CONCURRENT
from .engine import DownloadEngine
from .models import DownloadTask, TaskState


class DownloadQueue:
    def __init__(self, engine: DownloadEngine, max_concurrent: int = MAX_CONCURRENT):
        self.engine = engine
        self.max_concurrent = max_concurrent
        self.queue: deque[DownloadTask] = deque()
        self.running: dict[str, asyncio.Task] = {}
        self.closing = False

    async def enqueue(self, task: DownloadTask, immediate: bool = False) -> None:
        """immediate=True starts right away even if all slots are busy
        (used for downloads taken over from the browser)."""
        if self.closing or task.id in self.running or task in self.queue:
            return
        task.state = TaskState.QUEUED
        task.error = None
        self.engine.on_update(task)
        if immediate:
            self.running[task.id] = asyncio.create_task(self._run(task))
            return
        self.queue.append(task)
        await self._pump()

    async def pause(self, task: DownloadTask) -> None:
        if task in self.queue:
            self.queue.remove(task)
            task.state = TaskState.PAUSED
            self.engine.on_update(task)
        elif task.id in self.running:
            await self.engine.pause(task.id)

    async def cancel(self, task: DownloadTask) -> None:
        if task in self.queue:
            self.queue.remove(task)
            task.state = TaskState.CANCELLED
            self.engine.on_update(task)
        elif task.id in self.running:
            await self.engine.cancel(task.id)

    async def set_max_concurrent(self, n: int) -> None:
        self.max_concurrent = max(1, n)
        await self._pump()

    async def shutdown(self) -> None:
        self.closing = True
        while self.queue:
            t = self.queue.popleft()
            t.state = TaskState.PAUSED
        await self.engine.shutdown()
        if self.running:
            await asyncio.gather(*self.running.values(), return_exceptions=True)
        await self.engine.close()

    async def _pump(self) -> None:
        while not self.closing and self.queue and len(self.running) < self.max_concurrent:
            task = self.queue.popleft()
            self.running[task.id] = asyncio.create_task(self._run(task))

    async def _run(self, task: DownloadTask) -> None:
        try:
            await self.engine.start(task)
        finally:
            self.running.pop(task.id, None)
            await self._pump()
