"""yt-dlp integration (optional dependency)."""

from __future__ import annotations

import os
import re
import tempfile

from urllib.parse import urlparse

from .config import FFMPEG_AVAILABLE
from .errors import PyDMError


try:
    import yt_dlp
    from yt_dlp.utils import DownloadCancelled
except ImportError:          # optional dependency
    yt_dlp = None
    DownloadCancelled = Exception


class QuietLogger:
    """yt-dlp talks to PyDM through hooks/exceptions, not the console."""
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


class IsPlaylist(Exception):
    """The URL is an album / set / playlist page rather than a single video."""


class YtDlp:
    """yt-dlp backend: quality lists, playlists, cookies (YouTube + 1000 other sites)."""

    YOUTUBE_HOSTS = re.compile(r"(^|\.)(youtube\.com|youtu\.be|youtube-nocookie\.com)$", re.I)

    CHOICE_RE = re.compile(r"best|v\d{3,4}|a_m4a|a_mp3")

    HEIGHTS = (2160, 1440, 1080, 720, 480, 360, 240, 144)

    AUDIO_SITES = ("soundcloud", "bandcamp", "mixcloud", "audiomack")

    QUALITIES = {"v2160": "MP4 2160p (4K)", "v1440": "MP4 1440p", "v1080": "MP4 1080p",
                    "v720": "MP4 720p", "v480": "MP4 480p", "v360": "MP4 360p",
                    "a_m4a": "Audio M4A", "a_mp3": "Audio MP3 320kbps"}


    @staticmethod
    def is_youtube(url: str) -> bool:
        try:
            return bool(YtDlp.YOUTUBE_HOSTS.search(urlparse(url).hostname or ""))
        except ValueError:
            return False

    @staticmethod
    def selector(choice: str | None, ffmpeg: bool = FFMPEG_AVAILABLE) -> tuple[str, dict]:
        """Quality choice → (yt-dlp format selector, extra options)."""
        choice = choice or "best"
        if choice == "a_mp3":
            if not ffmpeg:
                raise PyDMError("MP3 needs ffmpeg installed")
            return "ba/b", {"postprocessors": [{"key": "FFmpegExtractAudio",
                                                "preferredcodec": "mp3",
                                                "preferredquality": "320"}]}
        if choice == "a_m4a":
            return "ba[ext=m4a]/ba", {}
        m = re.fullmatch(r"v(\d{3,4})", choice)
        hf = f"[height<={m.group(1)}]" if m else ""
        if ffmpeg:   # best video + best audio, merged into MP4
            # last resort ("/bv*+ba/b"): sites that don't report the resolution
            return (f"bv*{hf}[ext=mp4]+ba[ext=m4a]/bv*{hf}+ba/b{hf}/bv*+ba/b",
                    {"merge_output_format": "mp4"})
        return f"b{hf}[acodec!=none][vcodec!=none]/b{hf}/b", {}   # single-file only

    @staticmethod
    def probe(url: str, cookiefile: str | None = None) -> dict:
        """Blocking: list the qualities offered for a video (run in a thread)."""
        opts = {"quiet": True, "no_warnings": True, "noplaylist": True,
                "skip_download": True, "no_color": True, "logger": QuietLogger()}
        if cookiefile:
            opts["cookiefile"] = cookiefile
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if info.get("_type") in ("playlist", "multi_video") and not info.get("formats"):
            raise IsPlaylist()

        fmts = info.get("formats") or []
        duration = info.get("duration") or 0
        has = lambda f, k: f.get(k) not in (None, "none")          # noqa: E731

        def size(f) -> tuple[int, bool]:
            """(bytes, is_estimate). Many YouTube formats (HLS) have no size, so
            fall back to bitrate × duration, like yt-dlp's own estimate."""
            if not f:
                return 0, False
            if f.get("filesize"):
                return f["filesize"], False
            if f.get("filesize_approx"):
                return f["filesize_approx"], True
            rate = f.get("tbr") or ((f.get("vbr") or 0) + (f.get("abr") or 0))
            return (int(rate * 125 * duration), True) if rate and duration else (0, True)
        audio = [f for f in fmts if has(f, "acodec") and not has(f, "vcodec")]
        best_audio = max(audio, key=lambda f: (f.get("ext") == "m4a", f.get("abr") or 0),
                         default=None)

        choices = []
        for h in YtDlp.HEIGHTS:
            vids = [f for f in fmts if f.get("height") == h and has(f, "vcodec")]
            if not FFMPEG_AVAILABLE:
                vids = [f for f in vids if has(f, "acodec")]
            if not vids:
                continue
            best = max(vids, key=lambda f: (f.get("ext") == "mp4", f.get("fps") or 0,
                                            f.get("tbr") or 0))
            total, approx = size(best)
            if total and FFMPEG_AVAILABLE and not has(best, "acodec"):
                a, a_approx = size(best_audio)
                total, approx = total + a, approx or a_approx
            # unknown video size → show no size rather than just the audio's
            fps = best.get("fps") or 0
            choices.append({"id": f"v{h}", "kind": "video", "size": total or None,
                            "approx": approx, "label": f"MP4 {h}p{'60' if fps >= 50 else ''}"})
        if best_audio:
            a, a_approx = size(best_audio)
            ext = (best_audio.get("ext") or "audio").upper()
            choices.append({"id": "a_m4a", "kind": "audio", "size": a or None, "approx": a_approx,
                            "label": "Audio M4A" if ext == "M4A" else f"Audio {ext} (original)"})
        if FFMPEG_AVAILABLE and (best_audio or choices):
            # MP3 320 kbps size is exactly predictable from the duration
            choices.append({"id": "a_mp3", "kind": "audio",
                            "size": int(320 * 125 * duration) or None, "approx": True,
                            "label": "Audio MP3 320kbps"})
        if not choices:
            choices = [{"id": "best", "kind": "video", "size": None, "label": "Best available"}]
        return {"title": info.get("title") or "video", "id": info.get("id"),
                "uploader": info.get("uploader"), "duration": info.get("duration"),
                "thumbnail": info.get("thumbnail"), "ffmpeg": FFMPEG_AVAILABLE,
                "formats": choices}

    @staticmethod
    def playlist(url: str, cookiefile: str | None = None) -> dict:
        """Blocking: list a playlist's videos without downloading them."""
        opts = {"quiet": True, "no_warnings": True, "skip_download": True, "no_color": True,
                "extract_flat": "in_playlist", "playlistend": 1000, "logger": QuietLogger()}
        if cookiefile:
            opts["cookiefile"] = cookiefile
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        entries = []
        for e in info.get("entries") or []:
            if not e:
                continue
            title = e.get("title") or e.get("id") or "video"
            if title in ("[Private video]", "[Deleted video]"):
                continue
            u = e.get("webpage_url") or e.get("url") or ""
            if not u.startswith("http"):
                if (e.get("ie_key") or "").lower() == "youtube" and e.get("id"):
                    u = f"https://www.youtube.com/watch?v={e['id']}"
                else:
                    continue
            entries.append({"url": u, "title": title})
        key = (info.get("extractor_key") or info.get("extractor") or "").lower()
        return {"title": info.get("title") or "Playlist", "entries": entries,
                "audio_only": any(a in key for a in YtDlp.AUDIO_SITES)}

    @staticmethod
    def playlist_choices(audio_only: bool) -> list[dict]:
        choices = [] if audio_only else [{"id": "v1080", "kind": "video", "label": "MP4 1080p"},
                                         {"id": "v720", "kind": "video", "label": "MP4 720p"}]
        choices.append({"id": "a_m4a", "kind": "audio", "label": "Audio (original quality)"})
        if FFMPEG_AVAILABLE:
            choices.append({"id": "a_mp3", "kind": "audio", "label": "Audio MP3 320kbps"})
        return choices

    @staticmethod
    def write_cookiefile(cookies: list) -> str | None:
        """Browser cookies → temporary Netscape cookies.txt for yt-dlp."""
        lines = ["# Netscape HTTP Cookie File"]
        for c in (cookies or [])[:1000]:
            if not isinstance(c, dict) or not isinstance(c.get("name"), str):
                continue
            domain = str(c.get("domain") or "")
            host_only = bool(c.get("hostOnly"))
            if not host_only and domain and not domain.startswith("."):
                domain = "." + domain
            clean = lambda v: str(v).replace("\t", " ").replace("\n", " ")  # noqa: E731
            lines.append("\t".join([
                clean(domain), "FALSE" if host_only else "TRUE", clean(c.get("path") or "/"),
                "TRUE" if c.get("secure") else "FALSE", str(int(c.get("expirationDate") or 0)),
                clean(c["name"]), clean(c.get("value") or "")]))
        if len(lines) == 1:
            return None
        fd, path = tempfile.mkstemp(prefix="pydm-cookies-", suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return path

    @staticmethod
    def ext_for(choice: str | None) -> str:
        return {"a_mp3": ".mp3", "a_m4a": ".m4a"}.get(choice or "", ".mp4")
