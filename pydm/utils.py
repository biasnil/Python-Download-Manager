"""Small pure helpers: formatting, file names, URLs, categories, batch patterns."""

from __future__ import annotations

import itertools
import mimetypes
import re

from pathlib import Path
from urllib.parse import unquote, urlparse

from .config import CONFIG, IMAGE_EXT, MEDIA_EXT, STREAM_MIMES, download_root
from .errors import PyDMError


def human_bytes(n: float | int | None) -> str:
    if n is None or n < 0:
        return "—"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(n)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def human_speed(bps: float) -> str:
    return "—" if bps <= 0 else f"{human_bytes(bps)}/s"


def human_eta(sec: float | None) -> str:
    if sec is None or sec < 0:
        return "—"
    sec = int(sec)
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m {sec % 60}s"
    if sec < 86400:
        return f"{sec // 3600}h {(sec % 3600) // 60}m"
    return f"{sec // 86400}d {(sec % 86400) // 3600}h"


def default_name(url: str) -> str:
    """Last path segment of the URL, or 'download'."""
    try:
        path = urlparse(url.strip()).path
    except ValueError:
        return "download"
    name = unquote(path.rstrip("/").split("/")[-1]) if path else ""
    return safe_filename(name) if name else "download"


_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL",
                 *(f"COM{i}" for i in range(1, 10)),
                 *(f"LPT{i}" for i in range(1, 10))}


def safe_filename(name: str) -> str:
    """Strip characters that are illegal on Windows/macOS/Linux."""
    name = _ILLEGAL_CHARS.sub("_", name).strip().rstrip(". ")
    if not name:
        return "download"
    if Path(name).stem.upper() in _WIN_RESERVED:
        name = "_" + name
    if len(name) > 200:
        p = Path(name)
        name = p.stem[: 200 - len(p.suffix)] + p.suffix
    return name


def unique_filename(save_dir: Path, name: str, taken: set[str] | None = None) -> str:
    """Return name, or 'name (1).ext', 'name (2).ext' ... if already in use."""
    taken = taken or set()
    stem, suffix = Path(name).stem, Path(name).suffix
    candidate, i = name, 1
    while (candidate in taken
           or (save_dir / candidate).exists()
           or sidecar_path(save_dir, candidate).exists()):
        candidate = f"{stem} ({i}){suffix}"
        i += 1
    return candidate


def sidecar_path(save_dir: Path, filename: str) -> Path:
    return save_dir / f".{filename}.pydm.json"


def part_path(save_dir: Path, filename: str, index: int) -> Path:
    return save_dir / f".{filename}.part{index}"


def parse_content_disposition(value: str | None) -> str | None:
    if not value:
        return None
    m = re.search(r"filename\*\s*=\s*([^']*)'[^']*'([^;]+)", value, re.I)
    if m:
        try:
            return unquote(m.group(2).strip().strip('"'), encoding=m.group(1) or "utf-8")
        except LookupError:
            return unquote(m.group(2).strip().strip('"'))
    m = re.search(r'filename\s*=\s*"([^"]+)"', value, re.I) or \
        re.search(r"filename\s*=\s*([^;]+)", value, re.I)
    return m.group(1).strip() if m else None


def classify_media(url: str, mime: str | None = None, hint: str | None = None) -> str | None:
    """Return 'image', 'media' or None (not something we sniff)."""
    m = (mime or "").split(";")[0].strip().lower()
    if m.startswith("image/"):
        return "image"
    if m.startswith(("video/", "audio/")) or m in STREAM_MIMES:
        return "media"
    try:
        path = urlparse(url).path
    except ValueError:
        return None
    if IMAGE_EXT.search(path):
        return "image"
    if MEDIA_EXT.search(path):
        return "media"
    return hint if hint in ("image", "media") and not m else None


FILE_CATEGORIES = {   # IDM-style sub-folders of DEFAULT_DOWNLOAD_DIR
    "Programs": {".exe", ".msi", ".iso", ".img", ".dmg", ".pkg", ".apk", ".deb",
                 ".rpm", ".appimage", ".msix", ".appx", ".bin"},
    "Compressed": {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz",
                   ".zst", ".cab"},
    "Documents": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                  ".odt", ".ods", ".txt", ".csv", ".epub", ".rtf"},
    "Audio": {".mp3", ".m4a", ".ogg", ".wav", ".flac", ".aac", ".opus", ".wma"},
    "Videos": {".mp4", ".mkv", ".webm", ".mov", ".avi", ".wmv", ".flv", ".m4v"},
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".svg", ".bmp"},
    "Streams": {".m3u8", ".mpd"},
}


def category_dir(url: str, kind: str | None = None, mime: str | None = None,
                 filename: str | None = None) -> Path:
    """<download folder>/<Programs|Compressed|Documents|Audio|Videos|Images|Streams|General>."""
    root = download_root()
    if not CONFIG.use_categories:
        return root
    ext = Path(filename).suffix.lower() if filename else ""
    ext = ext or Path(urlparse(url).path).suffix.lower()
    for sub, exts in FILE_CATEGORIES.items():
        if ext in exts:
            return root / sub
    m = (mime or "").split(";")[0].strip().lower()
    if kind == "image" or m.startswith("image/"):
        sub = "Images"
    elif m in STREAM_MIMES:
        sub = "Streams"
    elif m.startswith("audio/"):
        sub = "Audio"
    elif kind == "media" or m.startswith("video/"):
        sub = "Videos"
    elif m in ("application/zip", "application/x-7z-compressed", "application/x-rar-compressed"):
        sub = "Compressed"
    elif m in ("application/x-msdownload", "application/x-iso9660-image"):
        sub = "Programs"
    else:
        sub = "General"
    return root / sub


def name_for(url: str, mime: str | None = None) -> str:
    """default_name(), plus an extension guessed from the MIME type if missing."""
    name = default_name(url)
    if not Path(name).suffix and mime:
        ext = mimetypes.guess_extension(mime.split(";")[0].strip())
        if ext:
            name += {".jpe": ".jpg", ".jfif": ".jpg"}.get(ext, ext)
    return name


def is_http_url(url: object) -> bool:
    if not isinstance(url, str) or len(url) > 4096:
        return False
    try:
        p = urlparse(url)
    except ValueError:
        return False
    return p.scheme in ("http", "https") and bool(p.netloc)


def http_error(code: int) -> "PyDMError":
    if code in (401, 403, 404, 410):
        return PyDMError(f"HTTP {code} — the link may have expired. Right-click → "
                         "Refresh Download Address")
    return PyDMError(f"Server returned HTTP {code}")


def expand_pattern(url: str, limit: int = 10_000) -> list[str]:
    """Batch download patterns: file[001-100].jpg, img[a-f].png, x[0-100:5].bin"""
    pat = re.compile(r"\[([0-9]+|[A-Za-z])-([0-9]+|[A-Za-z])(?::([0-9]+))?\]")
    matches = list(pat.finditer(url))
    if not matches:
        return [url]
    pieces, choices, pos = [], [], 0
    for m in matches:
        pieces.append(url[pos:m.start()])
        a, b, step = m.group(1), m.group(2), int(m.group(3) or 1) or 1
        if a.isdigit() and b.isdigit():
            width = len(a) if len(a) > 1 and a.startswith("0") else 0
            lo, hi = int(a), int(b)
            vals = [str(i).zfill(width) for i in (range(lo, hi + 1, step) if lo <= hi
                                                  else range(lo, hi - 1, -step))]
        elif a.isalpha() and b.isalpha():
            lo, hi = ord(a), ord(b)
            vals = [chr(c) for c in (range(lo, hi + 1, step) if lo <= hi
                                     else range(lo, hi - 1, -step))]
        else:
            raise ValueError(f"Can't mix numbers and letters in {m.group(0)}")
        choices.append(vals)
        pos = m.end()
    pieces.append(url[pos:])
    total = 1
    for c in choices:
        total *= len(c)
    if total > limit:
        raise ValueError(f"Pattern makes {total:,} URLs (limit {limit:,})")
    out = []
    for combo in itertools.product(*choices):
        out.append("".join(p + v for p, v in zip(pieces, combo)) + pieces[-1])
    return out


def clean_error(e: BaseException) -> str:
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e) or type(e).__name__)
    return msg.replace("ERROR: ", "").strip()
