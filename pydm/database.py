"""SQLite download history."""

from __future__ import annotations

import sqlite3
import time

from pathlib import Path

from .config import DEFAULT_THREADS
from .models import DownloadTask, TaskState


class Database:
    COLUMNS = ("id", "url", "filename", "save_dir", "total_size", "downloaded",
               "state", "num_threads", "etag", "last_modified",
               "created_at", "completed_at", "error", "referer", "source",
               "user_agent", "engine", "yt_choice", "overwrite")

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS downloads (
                id TEXT PRIMARY KEY, url TEXT NOT NULL, filename TEXT NOT NULL,
                save_dir TEXT NOT NULL, total_size INTEGER DEFAULT 0,
                downloaded INTEGER DEFAULT 0, state TEXT NOT NULL,
                num_threads INTEGER DEFAULT 8, etag TEXT, last_modified TEXT,
                created_at REAL, completed_at REAL, error TEXT,
                referer TEXT, source TEXT DEFAULT 'manual', user_agent TEXT,
                engine TEXT DEFAULT 'http', yt_choice TEXT,
                overwrite INTEGER DEFAULT 0)""")
        # migrate databases created by PyDM 1.0
        have = {r[1] for r in self.conn.execute("PRAGMA table_info(downloads)")}
        for col, decl in (("referer", "TEXT"), ("source", "TEXT DEFAULT 'manual'"),
                          ("user_agent", "TEXT"), ("engine", "TEXT DEFAULT 'http'"),
                          ("yt_choice", "TEXT"), ("overwrite", "INTEGER DEFAULT 0")):
            if col not in have:
                self.conn.execute(f"ALTER TABLE downloads ADD COLUMN {col} {decl}")
        self.conn.commit()

    def upsert(self, task: DownloadTask) -> None:
        values = (task.id, task.url, task.filename, str(task.save_dir),
                  task.total_size, task.downloaded, task.state.name,
                  task.num_threads, task.etag, task.last_modified,
                  task.created_at, task.completed_at, task.error,
                  task.referer, task.source, task.user_agent,
                  task.engine, task.yt_choice, int(task.overwrite))
        cols = ", ".join(self.COLUMNS)
        marks = ", ".join("?" * len(self.COLUMNS))
        updates = ", ".join(f"{c}=excluded.{c}" for c in self.COLUMNS[1:])
        self.conn.execute(f"INSERT INTO downloads ({cols}) VALUES ({marks}) "
                          f"ON CONFLICT(id) DO UPDATE SET {updates}", values)
        self.conn.commit()

    def all(self) -> list[DownloadTask]:
        rows = self.conn.execute(
            f"SELECT {', '.join(self.COLUMNS)} FROM downloads ORDER BY created_at")
        tasks = []
        for r in rows:
            d = dict(zip(self.COLUMNS, r))
            try:
                state = TaskState[d["state"]]
            except KeyError:
                state = TaskState.PAUSED
            tasks.append(DownloadTask(
                id=d["id"], url=d["url"], filename=d["filename"],
                save_dir=Path(d["save_dir"]), total_size=d["total_size"] or 0,
                downloaded=d["downloaded"] or 0, state=state,
                num_threads=d["num_threads"] or DEFAULT_THREADS,
                etag=d["etag"], last_modified=d["last_modified"],
                created_at=d["created_at"] or time.time(),
                completed_at=d["completed_at"], error=d["error"],
                referer=d["referer"], source=d["source"] or "manual",
                user_agent=d["user_agent"], engine=d["engine"] or "http",
                yt_choice=d["yt_choice"], overwrite=bool(d["overwrite"])))
        return tasks

    def delete(self, task_id: str) -> None:
        self.conn.execute("DELETE FROM downloads WHERE id=?", (task_id,))
        self.conn.commit()

    def mark_completed(self, task_id: str) -> None:
        self.conn.execute("UPDATE downloads SET state=?, completed_at=? WHERE id=?",
                          (TaskState.COMPLETED.name, time.time(), task_id))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
