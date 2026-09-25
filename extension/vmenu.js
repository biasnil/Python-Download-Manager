// PyDM — shared "Download this video" button + quality menu.
// Used by youtube.js (button inside the YouTube player) and video.js (any site).
window.PyDMVideoMenu = window.PyDMVideoMenu || (() => {
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const human = n => {
    if (!n) return "";
    const u = ["B", "KB", "MB", "GB"]; let i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return (i ? n.toFixed(1) : n) + " " + u[i];
  };
  const nameOf = url => {
    try { return decodeURIComponent(new URL(url).pathname.split("/").pop()) || url; }
    catch { return url; }
  };

  function send(message) {
    return new Promise(resolve => {
      if (!chrome.runtime?.id) return resolve(null);          // extension reloaded
      try {
        chrome.runtime.sendMessage(message, r => resolve(chrome.runtime.lastError ? null : r));
      } catch { resolve(null); }
    });
  }

  /** ctx = { url, playlist?, withCookies?, directUrls?, error? } */
  function create({ fixed = false, label = "Download this video" } = {}) {
    const root = el("div", "pydm-vm" + (fixed ? " pydm-vm-fixed" : ""));
    const btn = el("button", "pydm-vm-btn");
    const btnText = el("span", null, label);
    btn.append(el("span", "pydm-vm-arrow", "⬇"), btnText);
    const menu = el("div", "pydm-vm-menu"); menu.hidden = true;
    const head = el("div", "pydm-vm-head", "PyDM");
    const list = el("div", "pydm-vm-list");
    const foot = el("div", "pydm-vm-foot");
    menu.append(head, list, foot);
    root.append(btn, menu);
    // keep clicks away from the site's player (it would pause/play)
    for (const ev of ["click", "mousedown", "mouseup", "pointerdown", "pointerup", "dblclick"]) {
      root.addEventListener(ev, e => e.stopPropagation());
    }

    const cache = new Map();
    let ctx = null;

    const msg = (text, err = false) =>
      list.replaceChildren(el("div", "pydm-vm-msg" + (err ? " pydm-vm-err" : ""), text));

    function item(icon, label, size, action, okText) {
      const b = el("button", "pydm-vm-item");
      b.append(el("span", "pydm-vm-kind", icon), el("span", "pydm-vm-label", label),
               el("span", "pydm-vm-size", size || ""));
      b.addEventListener("click", async () => {
        b.disabled = true;
        const res = await action();
        if (res?.ok) {
          foot.textContent = okText || `✓ ${label} sent to PyDM`;
          setTimeout(api.close, 1500);
        } else {
          foot.textContent = res?.error || "PyDM is not running";
        }
        b.disabled = false;
      });
      return b;
    }

    function directFallback(c) {
      for (const u of c.directUrls || []) {
        list.append(item("⬇", "Video file: " + nameOf(u), "",
                         () => send({ cmd: "download", urls: [u] })));
      }
    }

    function render(r, c) {
      foot.textContent = "";
      if (!r) return msg("PyDM is not running — open PyDM and try again.", true);
      if (!r.ok) {
        head.textContent = "PyDM";
        msg(r.error || "Couldn't read this video.", true);
        directFallback(c);
        return;
      }
      head.textContent = r.title;
      head.title = r.title;
      list.replaceChildren();
      for (const f of r.formats) {
        const size = f.size ? (f.approx ? "~" : "") + human(f.size) : "";
        list.append(item(f.kind === "audio" ? "♪" : "▶", f.label, size,
          () => send({ cmd: "ytDownload", url: c.url, choice: f.id, title: r.title,
                       withCookies: c.withCookies })));
      }
      if (r.playlist) {
        const p = r.playlist;
        const what = p.audio_only ? "tracks" : "videos";
        const single = r.formats.length > 0;          // a video that is also in a playlist
        list.append(el("div", "pydm-vm-sep",
          single ? `Whole playlist — ${p.count} ${what}`
                 : `${p.audio_only ? "Album / set" : "Playlist"} — ${p.count} ${what}`));
        const picks = p.choices || r.formats;
        for (const f of picks) {
          list.append(item("▤", single ? `Playlist · ${f.label}` : f.label, "",
            () => send({ cmd: "ytPlaylist", url: p.url, choice: f.id, withCookies: c.withCookies }),
            `✓ ${p.count} ${what} sent to PyDM`));
        }
      } else if (!r.formats.length) {
        msg("No downloadable formats found.", true);
        directFallback(c);
      }
      if (!r.ffmpeg) foot.textContent = "Install ffmpeg in PyDM for HD & MP3";
    }

    const api = {
      root, btn, menu,
      isOpen: () => !menu.hidden,
      setLabel(text) { btnText.textContent = text; },
      close() { menu.hidden = true; root.classList.remove("pydm-open"); },
      async open(c) {
        ctx = c;
        menu.hidden = false;
        root.classList.add("pydm-open");
        if (c.error) {                                     // e.g. "open the post first"
          head.textContent = "PyDM";
          foot.textContent = "";
          msg(c.error, true);
          directFallback(c);
          return;
        }
        const key = c.url + "|" + (c.playlist || "");
        let r = cache.get(key);
        if (!r) {
          head.textContent = "PyDM";
          foot.textContent = "";
          msg("Getting available qualities…");
          r = await send({ cmd: "ytFormats", url: c.url, playlist: c.playlist,
                           withCookies: c.withCookies });
          if (r?.ok) cache.set(key, r);
        }
        if (ctx !== c || menu.hidden) return;              // user moved on
        render(r, c);
      },
      toggle(c) { menu.hidden ? api.open(c) : api.close(); },
    };

    document.addEventListener("click", e => {
      if (!menu.hidden && !root.contains(e.target)) api.close();
    }, true);
    return api;
  }

  return { create, send };
})();
