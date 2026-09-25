# PyDM — Download Manager

A single-file Python download manager (multi-threaded, pause/resume, queue,
SQLite history, PyQt6 GUI) with an embedded local API that an optional
browser extension uses to send it the media and pictures your browser loads.

## Install & run

```bash
pip install -r requirements.txt
python main.py            # or: python -m pydm
```

`aiohttp` (browser extension) and `yt-dlp` (video sites) are optional; without
them PyDM runs as a normal manual download manager. Install **ffmpeg** for HD
video and MP3.

## Project structure

Never more than one folder deep:

```
PyDM/
├── main.py                 start here
├── requirements.txt
├── README.md · LICENSE
├── icon/                   one SVG per icon (app, add, pause, resume, …)
├── extension/              Chrome/Edge extension (load unpacked)
└── pydm/                   the application package
    ├── app.py              PyDMApplication — start-up
    ├── config.py           constants, feature flags, Settings (config.json)
    ├── errors.py · utils.py · models.py
    ├── remote_probe.py     RemoteProbe — size / resume support of a URL
    ├── limiter.py          TokenBucketLimiter
    ├── chunk_worker.py     ChunkWorker — one byte range
    ├── part_files.py       PartFiles — .partN files + JSON sidecar
    ├── engine.py           DownloadEngine — segmented HTTP + yt-dlp jobs
    ├── ytdlp_backend.py    YtDlp — qualities, playlists, cookies
    ├── download_queue.py   DownloadQueue — max-concurrent queue
    ├── database.py         Database — SQLite history
    ├── sniffer.py          SnifferStore, SnifferAPI (127.0.0.1:8765)
    ├── async_worker.py     AsyncWorker — asyncio loop in a QThread
    ├── icons.py            Icons — loads ./icon/*.svg
    ├── downloads_table.py  DownloadsTable
    ├── sniffed_panel.py    SniffedPanel
    ├── download_window.py  DownloadWindow, SegmentBar
    ├── add_dialog.py · settings_dialog.py · batch_dialog.py
    ├── checksum_dialog.py · refresh_dialog.py
    ├── tray.py             TrayController
    ├── clipboard_monitor.py ClipboardMonitor
    ├── schedule.py         ScheduleManager
    ├── power.py            PowerManager, PowerCountdownDialog
    └── main_window.py      MainWindow — wires everything together
```

To change an icon, replace the SVG in `icon/` with one of the same name. A missing
or broken file falls back to Qt's built-in icon.

## Settings

Everything is saved to `config.json` in PyDM's data folder (next to
`downloads.db`) — **Tools → Settings** shows the exact path with a link.
Windows: `%LOCALAPPDATA%\PyDM\config.json`.

| Tab | What's there |
|-----|--------------|
| General | download folder, sort into type sub-folders, what to do if a file exists (ask / add number / overwrite), clipboard monitoring, close-to-tray, start minimized |
| Connection | threads per download, downloads at once, speed limit, dynamic segmentation |
| Browser | extension API on/off, catch browser downloads, leave small files to the browser, default YouTube quality |
| Notifications | progress window, "Download complete" window, tray notifications |
| Scheduler | start/stop time, days, what to do when the queue finishes |

The toolbar's Max / Limit boxes and Sniffer / Catch toggles save automatically.

## IDM-style features

- **Dynamic segmentation** — when a thread finishes early, it takes half of the
  biggest remaining piece, so all threads stay busy until the very end.
- **Refresh download address** — link expired (HTTP 403/404/410)? Pause it,
  right-click → *Refresh Download Address*, then paste a new link or click
  *Catch From Browser…* and start the download again in the browser. PyDM
  continues the same file from where it stopped (the size must match).
- **Progress window** per download with a segment bar and per-connection list;
  it turns into a **Download complete** window (Open / Open Folder / Close).
  Double-click a row to open it.
- **System tray** — closing the window keeps PyDM running; tray menu has
  Add URL, Resume/Pause All, Settings, Exit.
- **Clipboard monitoring** — copy a link to a file (.zip, .exe, .iso, .pdf,
  .mp4 …) and the Add Download dialog pops up.
- **Scheduler** — *Download Later* (Add dialog / Batch dialog) or right-click →
  *Add to Schedule*. The queue starts at your chosen time and days, can stop at
  a set time (unfinished items go back to the schedule), and can then do
  nothing / exit PyDM / sleep / hibernate / shut down (with a 60 s cancel
  countdown). *Tools → Start Scheduled Queue* runs it now.
  *Tools → When All Downloads Finish* is a one-time version for everything.
- **Existing file prompt** — rename, overwrite, or resume the copy that's
  already in the list.
- **Batch download** (Ctrl+B) — `img_[001-120].jpg`, `[a-z]`, `[0-100:10]`,
  several ranges, or paste a list of URLs.
- **Verify checksum** — right-click a finished download → MD5 / SHA-1 /
  SHA-256 / SHA-512; paste the expected value and it tells you if it matches.
- **YouTube playlists** — the video menu shows *Whole playlist — N videos*
  when you're watching inside a playlist; pasting a `youtube.com/playlist?list=`
  link into Add URL works too. Videos go into a folder named after the playlist.
- **"Download this video" on other sites** — hover any video. In feeds
  (X/Twitter, Instagram, TikTok, Facebook, Reddit, Threads, Bluesky, Tumblr,
  Pinterest) PyDM works out which *post* the video belongs to, so it works
  while scrolling; if it can't tell, it asks you to open the post. Twitch/Kick
  live streams are refused (download the VOD afterwards). Vimeo, Dailymotion,
  Bilibili, Rumble, Niconico, Twitch VODs/clips, embedded YouTube and 1,000+
  other yt-dlp sites use the page itself.
- **Music pages** — SoundCloud, Bandcamp, Mixcloud and Audiomack track, album
  and set pages get a fixed *Download this track / album / set* button.
  Albums, sets and other playlist pages on any site show
  *Album / set — N tracks* and download every item into its own folder. Your browser
  cookies for that site are passed to yt-dlp (in memory / a temp file that's
  deleted right after) so logged-in videos work. If yt-dlp doesn't support the
  site, direct video files found on the page are offered instead.

## Browser extension (optional)

1. Open `chrome://extensions` (or `edge://extensions`), turn on **Developer mode**.
2. Click **Load unpacked** and select the `extension/` folder inside PyDM.
3. Keep PyDM running. Browse a page with pictures or video.

- A blue **⬇ N** button appears bottom-right of pages where something was detected.
  Click it for thumbnails and per-item **Download**, or **Download all images**.
- Everything detected also appears live in PyDM's **Sniffed** tab.
- Click the extension's toolbar icon to turn sniffing on/off (badge shows `off`).
- If PyDM isn't running the button turns grey and shows "PyDM not running".

Sniffed downloads are saved to `Downloads/PyDM/Images`, `Videos`, `Audio` or `Streams`,
and are sent with the source page as `Referer` so hotlink-protected images work.

## Catching browser downloads (IDM-style)

While PyDM is open, any download you start in the browser (e.g. a Windows ISO
from microsoft.com) is cancelled in the browser and started **immediately** in
PyDM — it skips the queue, jumps to the Downloads tab and saves into
`Downloads/PyDM/Programs`, `Compressed`, `Documents`, `Videos`, `Audio`,
`Images` or `General` by file type.

- PyDM closed → the browser downloads normally.
- Turn off in PyDM with **Catch Browser Downloads** on the toolbar, or in the
  browser by right-clicking the extension icon → **Catch browser downloads**.
- Right-click any link, image or video → **Download with PyDM**.
- The browser's cookies, User-Agent and Referer are passed along, so
  login-protected downloads work. Cookies stay in memory only and are never
  written to PyDM's database.
- If PyDM fails before receiving any data (expired link, a download that needs
  a form POST), the extension hands it back to the browser automatically.
- `blob:` / `data:` downloads (files generated by the page itself) and
  incognito downloads always stay in the browser.

## YouTube: "Download this video"

Hover a YouTube video (normal or Shorts) and a blue **⬇ Download this video**
button appears top-right of the player. Click it to pick a quality
(e.g. MP4 1080p60, 720p, 360p, Audio M4A, Audio MP3 320kbps); the download
starts in PyDM immediately and saves to `Downloads/PyDM/Videos` or `Audio`.
Pasting a YouTube link into **Add URL** also works (defaults to 1080p).

- Powered by **yt-dlp** (`pip install yt-dlp`). Keep it updated —
  `pip install -U yt-dlp` — YouTube changes often and old versions break.
- **ffmpeg** is needed for anything above 360p (YouTube serves HD video and
  audio separately and they must be merged) and for MP3.
  Windows: `winget install Gyan.FFmpeg`, then restart PyDM.
- Recent yt-dlp versions also want a JavaScript runtime for full YouTube
  support. If only low qualities show up, install Deno
  (`winget install DenoLand.Deno`).
- Pause/resume work; partial data lives in a hidden `.pydm-yt-…` folder until done.
- PyDM's status bar shows `yt-dlp ✓/✗  ffmpeg ✓/✗`.

## Local API (127.0.0.1:8765)

| Method | Path        | Body / query                    | Returns                         |
|--------|-------------|---------------------------------|---------------------------------|
| POST   | `/sniff`    | `{url,type,mime,page,size}` or `{items:[…]}` | `{ok, added}`      |
| GET    | `/detected` | `?page=<url>` (optional)        | `{items:[…]}`                   |
| POST   | `/download` | `{url, id?, page?, filename?, mime?, cookies?, user_agent?, source?}` | `{ok, task_id}` |
| GET    | `/status`   | `?task_id=<id>` (optional)      | `{ok, tasks:{id:{state,progress,…}}}` |
| GET    | `/yt/formats` | `?url=<video url>`            | `{ok, title, formats:[{id,label,size}]}` |
| POST   | `/yt/download` | `{url, choice, title}`       | `{ok, task_id}`                 |
| GET    | `/health`   |                                 | `{ok:true, app:"PyDM", intercept}` |

Security: the server listens on localhost only and rejects any request whose
`Origin` is a web page (only `chrome-extension://`, `moz-extension://` or no
Origin, e.g. curl, are accepted), so websites cannot make PyDM download things.

## Limitations

- HLS/DASH (`.m3u8` / `.mpd`) are detected, but PyDM downloads the playlist
  file itself, not the stream segments.
- `blob:` URLs (MSE streaming players) aren't sniffed; YouTube goes through
  the yt-dlp button instead.
- Downloads caught after a login keep working until you restart PyDM; resuming them
  after a restart may fail because cookies aren't saved.

## Legal notice

The sniffer only sees URLs your browser is already fetching, and PyDM does
**not** bypass DRM or decrypt protected streams. YouTube downloads go through
the open-source yt-dlp project. Downloading from YouTube may be against its
Terms of Service; you are responsible for complying with copyright law and
each website's terms. Only download content you own, that is freely licensed,
or that you have permission to download.

## License

MIT
