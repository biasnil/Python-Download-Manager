"""App constants, optional-feature flags and the Settings (config.json)."""

from __future__ import annotations

import importlib.util
import json
import os
import platformdirs
import re
import shutil
import traceback

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


APP_NAME = "PyDM"

APP_VERSION = "1.0"

DATA_DIR = Path(platformdirs.user_data_dir(APP_NAME, appauthor=False))

DB_PATH = DATA_DIR / "downloads.db"

DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads" / "PyDM"

DEFAULT_THREADS = 8

MAX_THREADS = 16

MAX_CONCURRENT = 3

USER_AGENT = f"PyDM/{APP_VERSION}"

BLOCK_SIZE = 64 * 1024

MIN_CHUNK_SIZE = 1024 * 1024        # never split below 1 MiB per thread

MIN_SPLIT_SIZE = 512 * 1024         # dynamic segmentation: smallest piece to hand off

MAX_RETRIES = 5                     # per chunk, for network hiccups

UI_UPDATE_INTERVAL = 0.3            # seconds between progress signals per task

STATE_SAVE_INTERVAL = 2.0           # seconds between JSON sidecar saves

SPEED_WINDOW = 3.0                  # seconds of samples used for speed

DISK_SPACE_MARGIN = 10 * 1024 * 1024

CONFIG_PATH = DATA_DIR / "config.json"

HOST = "127.0.0.1"

PORT = 8765

SNIFFER_MAX_ITEMS = 500               # ring buffer size

MEDIA_EXT = re.compile(r"\.(mp4|webm|m3u8|ts|mpd|mp3|m4a|ogg|wav|mkv|mov|flac|aac)$", re.I)

IMAGE_EXT = re.compile(r"\.(jpe?g|png|gif|webp|avif|svg|bmp)$", re.I)

STREAM_MIMES = {"application/vnd.apple.mpegurl", "application/x-mpegurl",
                "application/dash+xml"}

EXTENSION_ORIGINS = ("chrome-extension://", "moz-extension://",
                     "safari-web-extension://")


# ── optional features (detected without importing the heavy packages) ──
HTTP2_AVAILABLE = importlib.util.find_spec("h2") is not None        # httpx[http2]
AIOHTTP_AVAILABLE = importlib.util.find_spec("aiohttp") is not None  # browser extension API
YTDLP_AVAILABLE = importlib.util.find_spec("yt_dlp") is not None     # video sites
FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None                # >360p & MP3


@dataclass
class Settings:
    # General
    download_dir: str = str(DEFAULT_DOWNLOAD_DIR)
    use_categories: bool = True           # Programs / Videos / Documents … sub-folders
    existing_file_action: str = "ask"     # ask | rename | overwrite
    monitor_clipboard: bool = True
    minimize_to_tray: bool = True         # the X button hides PyDM to the tray
    start_minimized: bool = False
    # Connection
    default_threads: int = DEFAULT_THREADS
    max_concurrent: int = MAX_CONCURRENT
    speed_limit_kbps: int = 0
    dynamic_segmentation: bool = True
    # Browser
    sniffer_enabled: bool = True
    intercept_enabled: bool = True
    min_intercept_kb: int = 0             # smaller browser downloads stay in the browser
    yt_default_quality: str = "v1080"
    # Notifications
    show_progress_window: bool = True
    show_complete_dialog: bool = True
    notify_on_complete: bool = True
    # Scheduler
    sched_enabled: bool = False
    sched_start: str = "02:00"
    sched_stop: str = ""                  # "" = run until done
    sched_days: list = field(default_factory=lambda: list(range(7)))   # 0 = Monday
    sched_when_done: str = "nothing"      # nothing | exit | sleep | hibernate | shutdown
    # Window
    window_geometry: str = ""

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or CONFIG_PATH
        s = cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return s
        for f in fields(cls):
            if f.name in data:
                default = getattr(s, f.name)
                value = data[f.name]
                if isinstance(default, bool):
                    ok = isinstance(value, bool)
                elif isinstance(default, int):
                    ok = isinstance(value, int) and not isinstance(value, bool)
                else:
                    ok = isinstance(value, type(default))
                if ok:
                    setattr(s, f.name, value)
        return s

    def save(self, path: Path | None = None) -> None:
        path = path or CONFIG_PATH
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            traceback.print_exc()

    def copy(self) -> "Settings":
        return Settings(**{k: (list(v) if isinstance(v, list) else v)
                           for k, v in asdict(self).items()})


CONFIG = Settings()          # replaced in place by load_config() at start-up


def load_config() -> Settings:
    CONFIG.__dict__.update(Settings.load().__dict__)
    return CONFIG


def download_root() -> Path:
    return Path(CONFIG.download_dir or DEFAULT_DOWNLOAD_DIR).expanduser()
