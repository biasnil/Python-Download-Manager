// PyDM — background service worker (MV3)
//  1. Catch browser downloads and hand them to PyDM (like IDM) while PyDM is open.
//  2. Sniff media/image URLs the browser is ALREADY loading.
// No DRM bypass, no YouTube signature decoding.

const PYDM = "http://127.0.0.1:8765";
const MIN_IMAGE_BYTES = 10 * 1024;               // skip icons / tracking pixels
const IMAGE_EXT = /\.(jpe?g|png|gif|webp|avif|svg|bmp)$/i;
const MEDIA_EXT = /\.(mp4|webm|m3u8|mpd|mp3|m4a|ogg|wav|mkv|mov|flac|aac)$/i;
const SEGMENT_EXT = /\.(ts|m4s)$/i;              // HLS/DASH fragments: too noisy
const STREAM_MIMES = ["application/vnd.apple.mpegurl", "application/x-mpegurl", "application/dash+xml"];
const SKIP_HOSTS = [/(^|\.)googlevideo\.com$/i]; // YouTube fragments: not supported

let settings = { enabled: true, intercept: true };  // enabled = media sniffing
let health = null;          // last /health response (null = PyDM not running)
let lastHealth = 0;
const tabItems = new Map(); // tabId -> Map(url -> item)
const tabPages = new Map(); // tabId -> page url
const bypass = new Set();   // URLs we deliberately give back to the browser
let pending = [];           // batched POST /sniff
let flushTimer = null;

const ready = chrome.storage.local.get(settings).then(v => { settings = v; updateBadges(); syncMenus(); });

// ════════════════════════════════════════════════════════════════════════
// PyDM API
// ════════════════════════════════════════════════════════════════════════
async function api(path, body, timeoutMs = 5000) {
  const opts = { signal: AbortSignal.timeout(timeoutMs) };
  if (body !== undefined) {
    Object.assign(opts, { method: "POST", headers: { "Content-Type": "application/json" },
                          body: JSON.stringify(body) });
  }
  const r = await fetch(PYDM + path, opts);
  return r.json();
}

/** Returns the /health object, or null if PyDM isn't running. Cached briefly. */
async function pyHealth({ force = false, timeoutMs = 1000 } = {}) {
  if (!force && Date.now() - lastHealth < 3000) return health;
  lastHealth = Date.now();
  try { health = await api("/health", undefined, timeoutMs); if (!health.ok) health = null; }
  catch { health = null; }
  return health;
}

async function cookieList(url) {
  try {
    return (await chrome.cookies.getAll({ url })).map(c => ({
      domain: c.domain, hostOnly: c.hostOnly, path: c.path, secure: c.secure,
      expirationDate: c.expirationDate || 0, name: c.name, value: c.value }));
  } catch { return []; }
}

async function cookieHeader(url) {
  try {
    const list = await chrome.cookies.getAll({ url });
    return list.map(c => `${c.name}=${c.value}`).join("; ") || null;
  } catch { return null; }
}

const basename = p => (p || "").split(/[\\/]/).pop() || null;

/** Send a URL to PyDM. Resolves to {ok, task_id} or null. */
async function handToPyDM(url, { referrer, filename, mime, source }) {
  try {
    const r = await api("/download", {
      url, page: referrer || null, filename: filename || null, mime: mime || null,
      cookies: await cookieHeader(url), user_agent: navigator.userAgent, source,
    });
    return r.ok ? r : null;
  } catch { return null; }
}

function browserDownload(url) {
  bypass.add(url);
  chrome.downloads.download({ url }).catch(() => bypass.delete(url));
}

/** If PyDM fails before receiving a single byte (e.g. link needs a POST or
 *  expired), give the download back to the browser so nothing is lost. */
async function watchStart(taskId, url) {
  for (let i = 0; i < 25; i++) {
    await new Promise(r => setTimeout(r, 1000));
    let t;
    try { t = (await api(`/status?task_id=${taskId}`)).tasks?.[taskId]; } catch { return; }
    if (!t) return;
    if (t.state === "Error" && !t.downloaded) { browserDownload(url); return; }
    if (t.downloaded > 0 || ["Downloading", "Completed", "Paused", "Cancelled"].includes(t.state)) return;
  }
}

// ════════════════════════════════════════════════════════════════════════
// 1. Catch browser downloads
// ════════════════════════════════════════════════════════════════════════
chrome.downloads.onCreated.addListener(async item => {
  await ready;
  const url = item.finalUrl || item.url;
  if (bypass.delete(url) || bypass.delete(item.url)) return;      // our own fallback
  if (!settings.intercept || item.incognito || item.state !== "in_progress") return;
  if (!/^https?:/i.test(url)) return;          // blob:, data:, file: stay in the browser

  const h = await pyHealth({ timeoutMs: 800 });
  if (!h || !h.intercept) return;              // PyDM closed or catching turned off → normal download
  const size = Math.max(item.totalBytes || 0, item.fileSize || 0);
  if (h.min_intercept_kb && size > 0 && size < h.min_intercept_kb * 1024) return;  // small file

  try {
    await chrome.downloads.cancel(item.id);
    await chrome.downloads.erase({ id: item.id });
  } catch { /* already finished — let PyDM fetch it anyway */ }

  const res = await handToPyDM(url, {
    referrer: item.referrer, filename: basename(item.filename), mime: item.mime, source: "browser",
  });
  if (!res) { browserDownload(url); return; }  // PyDM refused → hand it back
  watchStart(res.task_id, url);
});

// ════════════════════════════════════════════════════════════════════════
// 2. Right-click menus
// ════════════════════════════════════════════════════════════════════════
// Menu rebuilds are chained so two calls can never overlap (overlapping calls
// caused "Cannot create item with duplicate id" errors).
let menuChain = Promise.resolve();
function syncMenus() {
  menuChain = menuChain.then(() => new Promise(resolve => {
    chrome.contextMenus.removeAll(() => {
      const ok = () => void chrome.runtime.lastError;   // swallow harmless errors
      chrome.contextMenus.create({ id: "pydm-link", title: "Download with PyDM",
                                   contexts: ["link", "image", "video", "audio"] }, ok);
      chrome.contextMenus.create({ id: "pydm-intercept", type: "checkbox", contexts: ["action"],
                                   title: "Catch browser downloads", checked: settings.intercept }, ok);
      chrome.contextMenus.create({ id: "pydm-sniff", type: "checkbox", contexts: ["action"],
                                   title: "Sniff media & pictures", checked: settings.enabled }, ok);
      resolve();
    });
  }));
  return menuChain;
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === "pydm-intercept" || info.menuItemId === "pydm-sniff") {
    const key = info.menuItemId === "pydm-intercept" ? "intercept" : "enabled";
    settings[key] = info.checked;
    await chrome.storage.local.set({ [key]: info.checked });
    updateBadges();
  } else if (info.menuItemId === "pydm-link") {
    const url = info.linkUrl || info.srcUrl;
    if (!url || !/^https?:/i.test(url)) return;
    const res = (await pyHealth({ force: true })) &&
                await handToPyDM(url, { referrer: tab?.url, source: "link" });
    if (!res) browserDownload(url);            // PyDM not running → normal download
  }
});

chrome.action.onClicked.addListener(async () => {
  settings.enabled = !settings.enabled;
  await chrome.storage.local.set({ enabled: settings.enabled });
  syncMenus();
  updateBadges();
});

// ════════════════════════════════════════════════════════════════════════
// 3. Media / picture sniffing
// ════════════════════════════════════════════════════════════════════════
function header(details, name) {
  const h = (details.responseHeaders || []).find(x => x.name.toLowerCase() === name);
  return h ? h.value : null;
}

function classify(url, mime, type) {
  mime = (mime || "").split(";")[0].trim().toLowerCase();
  let path;
  try { path = new URL(url).pathname; } catch { return null; }
  if (SEGMENT_EXT.test(path) || mime === "video/mp2t") return null;
  if (mime.startsWith("image/")) return "image";
  if (mime.startsWith("video/") || mime.startsWith("audio/") || STREAM_MIMES.includes(mime)) return "media";
  if (IMAGE_EXT.test(path)) return "image";
  if (MEDIA_EXT.test(path)) return "media";
  if (type === "media" && !mime) return "media";
  return null;
}

async function pageOf(tabId) {
  if (tabPages.has(tabId)) return tabPages.get(tabId);
  try {
    const tab = await chrome.tabs.get(tabId);
    tabPages.set(tabId, tab.url);
    return tab.url;
  } catch { return null; }
}

function flushSoon() {
  if (flushTimer) return;
  flushTimer = setTimeout(async () => {
    flushTimer = null;
    const batch = pending.splice(0, pending.length);
    if (!batch.length) return;
    try { await api("/sniff", { items: batch }); } catch { health = null; }
  }, 400);
}

async function record(tabId, item) {
  const page = await pageOf(tabId);
  let map = tabItems.get(tabId);
  if (!map) tabItems.set(tabId, map = new Map());
  if (map.has(item.url)) return;
  item.page = page;
  item.queued = false;
  map.set(item.url, item);
  setBadge(tabId);
  pending.push({ url: item.url, type: item.type, mime: item.mime, page, size: item.size });
  flushSoon();
}

function setBadge(tabId) {
  const n = tabItems.get(tabId)?.size || 0;
  chrome.action.setBadgeBackgroundColor({ tabId, color: "#2e7dd7" }).catch(() => {});
  chrome.action.setBadgeText({ tabId, text: settings.enabled ? (n ? String(n) : "") : "off" }).catch(() => {});
}

async function updateBadges() {
  for (const t of await chrome.tabs.query({})) setBadge(t.id);
}

chrome.webRequest.onHeadersReceived.addListener(details => {
  if (!settings.enabled || details.tabId < 0 || details.statusCode >= 400) return;
  if (!/^https?:/i.test(details.url)) return;
  let host;
  try { host = new URL(details.url).hostname; } catch { return; }
  if (SKIP_HOSTS.some(r => r.test(host))) return;

  const mime = header(details, "content-type");
  const type = classify(details.url, mime, details.type);
  if (!type) return;

  let size = parseInt(header(details, "content-length") || "0", 10) || null;
  const range = header(details, "content-range");            // "bytes 0-99/12345"
  if (range && /\/(\d+)$/.test(range)) size = parseInt(range.match(/\/(\d+)$/)[1], 10);
  if (type === "image" && size && size < MIN_IMAGE_BYTES) return;

  record(details.tabId, { url: details.url, type, mime: mime ? mime.split(";")[0] : null, size });
}, { urls: ["<all_urls>"], types: ["main_frame", "image", "media", "object", "xmlhttprequest", "other"] },
   ["responseHeaders"]);

chrome.tabs.onUpdated.addListener((tabId, info) => {
  if (info.url) {                      // navigated → new page, new list
    tabPages.set(tabId, info.url);
    tabItems.delete(tabId);
    setBadge(tabId);
  }
});
chrome.tabs.onRemoved.addListener(tabId => { tabItems.delete(tabId); tabPages.delete(tabId); });

// ── messages from content.js ─────────────────────────────────────────────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  const tabId = sender.tab?.id;
  if (tabId === undefined) return;
  (async () => {
    await ready;
    if (msg.cmd === "list") {
      const online = !!(await pyHealth());
      const items = [...(tabItems.get(tabId)?.values() || [])];
      sendResponse({ enabled: settings.enabled, online, items });
    } else if (msg.cmd === "dom") {
      // pictures already on the page (may have come from cache)
      for (const it of (msg.items || []).slice(0, 300)) {
        if (/^https?:/i.test(it.url)) record(tabId, { url: it.url, type: it.type, mime: null, size: null });
      }
      sendResponse({ ok: true });
    } else if (msg.cmd === "ytFormats") {
      if (!(await pyHealth({ force: true }))) { sendResponse(null); return; }
      try {
        // yt-dlp may need several seconds to read the video page.
        // Cookies are sent for non-YouTube sites so logged-in videos work.
        const cookies = msg.withCookies ? await cookieList(msg.url) : undefined;
        sendResponse(await api("/yt/formats",
          { url: msg.url, playlist: msg.playlist || null, cookies }, 90000));
      } catch { sendResponse({ ok: false, error: "PyDM took too long to answer — try again" }); }
    } else if (msg.cmd === "ytDownload") {
      try {
        const cookies = msg.withCookies ? await cookieList(msg.url) : undefined;
        sendResponse(await api("/yt/download",
          { url: msg.url, choice: msg.choice, title: msg.title, cookies }));
      } catch { sendResponse({ ok: false, error: "PyDM is not running" }); }
    } else if (msg.cmd === "ytPlaylist") {
      try {
        const cookies = msg.withCookies ? await cookieList(msg.url) : undefined;
        sendResponse(await api("/yt/playlist", { url: msg.url, choice: msg.choice, cookies }, 120000));
      } catch { sendResponse({ ok: false, error: "PyDM took too long to answer — try again" }); }
    } else if (msg.cmd === "download") {
      if (!(await pyHealth({ force: true }))) { sendResponse({ ok: false, error: "PyDM is not running" }); return; }
      const map = tabItems.get(tabId);
      let ok = 0;
      for (const url of msg.urls || []) {
        const it = map?.get(url);
        try {
          const r = await api("/download", { url, page: it?.page || sender.tab.url });
          if (r.ok) { ok++; if (it) it.queued = true; }
        } catch { health = null; }
      }
      sendResponse({ ok: ok > 0, count: ok, error: ok ? null : "Download request failed" });
    }
  })();
  return true;  // async sendResponse
});
