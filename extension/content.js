// PyDM Sniffer — in-page floating button + panel.
// All network traffic goes through background.js (extension origin), never
// from the page itself.
(() => {
  if (window.top !== window || document.getElementById("pydm-root")) return;
  if (/(^|\.)youtube\.com$/.test(location.hostname)) return;   // youtube.js handles YouTube

  const MIN_DOM_PX = 120;                 // ignore tiny <img> (icons, avatars)
  const sentDom = new Set();
  let items = [], online = false, enabled = true, open = false, filter = "all";
  let pollTimer = null;

  // ── DOM ──────────────────────────────────────────────────────────────
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const root = el("div"); root.id = "pydm-root"; root.hidden = true;
  const fab = el("button", "pydm-fab");
  fab.title = "PyDM — detected media & pictures";
  const fabIcon = el("span", "pydm-fab-icon", "⬇");
  const fabCount = el("span", "pydm-fab-count", "0");
  fab.append(fabIcon, fabCount);

  const panel = el("div", "pydm-panel"); panel.hidden = true;
  const head = el("div", "pydm-head");
  const title = el("span", "pydm-title", "PyDM");
  const status = el("span", "pydm-status");
  const close = el("button", "pydm-x", "×");
  head.append(title, status, close);

  const tools = el("div", "pydm-tools");
  const filters = ["all", "image", "media"].map(f => {
    const b = el("button", "pydm-chip", { all: "All", image: "Images", media: "Video/Audio" }[f]);
    b.dataset.f = f;
    b.onclick = () => { filter = f; render(); };
    return b;
  });
  const allImgs = el("button", "pydm-btn", "Download all images");
  tools.append(...filters, allImgs);

  const list = el("div", "pydm-list");
  const msg = el("div", "pydm-msg");
  panel.append(head, tools, list, msg);
  root.append(panel, fab);
  document.documentElement.appendChild(root);

  // ── messaging ────────────────────────────────────────────────────────
  function send(message) {
    return new Promise(resolve => {
      if (!chrome.runtime?.id) { stop(); return resolve(null); }  // extension reloaded
      try {
        chrome.runtime.sendMessage(message, resp => {
          if (chrome.runtime.lastError) return resolve(null);
          resolve(resp);
        });
      } catch { stop(); resolve(null); }
    });
  }

  function scanDom() {
    const found = [];
    for (const img of document.images) {
      const url = img.currentSrc || img.src;
      if (!url || !/^https?:/i.test(url) || sentDom.has(url)) continue;
      if (img.naturalWidth < MIN_DOM_PX || img.naturalHeight < MIN_DOM_PX) continue;
      sentDom.add(url);
      found.push({ url, type: "image" });
    }
    for (const v of document.querySelectorAll("video[src], audio[src], video source[src], audio source[src]")) {
      const url = v.src;
      if (!url || !/^https?:/i.test(url) || sentDom.has(url)) continue;  // blob: = MSE stream, skip
      sentDom.add(url);
      found.push({ url, type: "media" });
    }
    if (found.length) send({ cmd: "dom", items: found });
  }

  async function refresh() {
    if (document.visibilityState !== "visible") return;
    scanDom();
    const r = await send({ cmd: "list" });
    if (!r) return;
    items = r.items || []; online = r.online; enabled = r.enabled;
    root.hidden = !enabled || items.length === 0;
    fabCount.textContent = items.length > 99 ? "99+" : String(items.length);
    fab.classList.toggle("pydm-offline", !online);
    if (open) render();
  }

  function stop() { if (pollTimer) clearInterval(pollTimer); pollTimer = null; root.remove(); }

  // ── rendering ────────────────────────────────────────────────────────
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

  function render() {
    const shown = items.filter(i => filter === "all" || i.type === filter);
    title.textContent = `PyDM — ${items.length} detected`;
    status.textContent = online ? "● connected" : "● PyDM not running";
    status.className = "pydm-status " + (online ? "pydm-on" : "pydm-off");
    filters.forEach(b => b.classList.toggle("pydm-active", b.dataset.f === filter));
    allImgs.disabled = !online || !items.some(i => i.type === "image" && !i.queued);

    list.replaceChildren();
    for (const it of shown.slice(-200).reverse()) {
      const row = el("div", "pydm-row");
      const thumb = el("div", "pydm-thumb");
      if (it.type === "image") {
        const img = el("img"); img.src = it.url; img.loading = "lazy"; img.alt = "";
        thumb.append(img);
      } else {
        thumb.textContent = "▶";
      }
      const info = el("div", "pydm-info");
      const name = el("div", "pydm-name", nameOf(it.url)); name.title = it.url;
      const meta = el("div", "pydm-meta", [it.mime || it.type, human(it.size)].filter(Boolean).join(" · "));
      info.append(name, meta);
      const btn = el("button", "pydm-btn", it.queued ? "✓ Sent" : "Download");
      btn.disabled = !online;
      btn.onclick = () => download([it.url], btn);
      row.append(thumb, info, btn);
      list.append(row);
    }
    if (!shown.length) list.append(el("div", "pydm-empty", "Nothing here yet."));
  }

  async function download(urls, btn) {
    if (btn) { btn.disabled = true; btn.textContent = "…"; }
    const r = await send({ cmd: "download", urls });
    msg.textContent = r?.ok ? `Sent ${r.count} to PyDM` : (r?.error || "Failed");
    setTimeout(() => (msg.textContent = ""), 3000);
    refresh();
  }

  // ── events ───────────────────────────────────────────────────────────
  fab.onclick = () => { open = !open; panel.hidden = !open; if (open) { scanDom(); refresh(); } };
  close.onclick = () => { open = false; panel.hidden = true; };
  allImgs.onclick = () => {
    const urls = items.filter(i => i.type === "image" && !i.queued).map(i => i.url);
    if (urls.length > 20 && !confirm(`Send ${urls.length} images to PyDM?`)) return;
    download(urls, allImgs);
  };
  chrome.storage.onChanged.addListener(ch => { if (ch.enabled) refresh(); });
  document.addEventListener("visibilitychange", refresh);

  refresh();
  pollTimer = setInterval(refresh, 3000);
})();
