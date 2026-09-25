// PyDM — "Download this video" on sites other than YouTube.
//  • Hover a video: X/Twitter, Instagram, TikTok, Facebook, Reddit, Threads, Bluesky,
//    Tumblr, Pinterest, Twitch, Kick, Vimeo, Dailymotion, Bilibili, Rumble, … and
//    YouTube players embedded in other pages.
//  • Music pages (SoundCloud, Bandcamp, Mixcloud, Audiomack) get a fixed button.
// Qualities come from yt-dlp in PyDM. If the site isn't supported, direct video
// files found on the page are offered instead.
(() => {
  const M = window.PyDMVideoMenu;
  if (!M) return;
  const host = location.hostname.replace(/^www\./, "");
  const ytEmbed = location.pathname.match(/^\/embed\/([\w-]{6,})/);
  if (/(^|\.)youtube(-nocookie)?\.com$/.test(host) && !ytEmbed) return;   // youtube.js

  // ── helpers ────────────────────────────────────────────────────────────
  const parentDeep = el => el.parentElement ||
    (el.getRootNode && el.getRootNode() instanceof ShadowRoot ? el.getRootNode().host : null);
  const closestDeep = (el, sel) => {
    for (; el; el = parentDeep(el)) if (el.matches?.(sel)) return el;
    return null;
  };
  /** Walk up from the video; return the nearest link matching `re` (first capture group if any). */
  function nearestLink(v, re, depth = 14) {
    for (let el = v, i = 0; el && i < depth; el = parentDeep(el), i++) {
      const links = el.matches?.("a[href]") ? [el] : [...(el.querySelectorAll?.("a[href]") || [])];
      for (const a of links) {
        const m = a.href.match(re);
        if (m) return m[1] || m[0];
      }
    }
    return null;
  }
  const here = re => { const m = location.href.match(re); return m ? (m[1] || m[0]) : null; };
  const LIVE = "Live streams can't be downloaded while they're live — download the VOD after the stream ends.";
  const OPEN_POST = "Couldn't tell which post this video belongs to — open the post (click it) and try again.";

  // For each site: which post does the hovered video belong to?
  // Return a URL, { error }, or null (null = use this page's URL).
  const SITES = [
    { re: /(^|\.)(x|twitter)\.com$/, feed: true, post: v => {
        const art = closestDeep(v, "article");
        const t = art?.querySelector("a[href*='/status/'] time")?.closest("a");
        const own = t?.href.match(/^(https:\/\/[^/]+\/[^/]+\/status\/\d+)/);
        return own?.[1] || nearestLink(v, /^(https:\/\/[^/]+\/[^/]+\/status\/\d+)/) ||
               here(/^(https:\/\/[^/]+\/[^/]+\/status\/\d+)/); } },
    { re: /(^|\.)instagram\.com$/, feed: true, post: v => {
        const u = nearestLink(v, /^(https:\/\/[^/]+(?:\/[^/]+)?\/(?:p|reels?|tv)\/[\w-]+)/) ||
                  here(/^(https:\/\/[^/]+(?:\/[^/]+)?\/(?:p|reels?|tv)\/[\w-]+)/) ||
                  here(/^(https:\/\/[^/]+\/stories\/[^/]+\/\d+)/);
        return u && u.replace("/reels/", "/reel/"); } },
    { re: /(^|\.)tiktok\.com$/, feed: true, post: v => {
        const link = nearestLink(v, /^(https:\/\/[^/]+\/@[^/]+\/(?:video|photo)\/\d+)/) ||
                     here(/^(https:\/\/[^/]+\/@[^/]+\/(?:video|photo)\/\d+)/);
        if (link) return link;
        // For You feed: the player's id contains the video id; pair it with the author link
        const wrap = closestDeep(v, "[id^='xgwrapper-']");
        const id = wrap?.id.match(/(\d{15,})$/)?.[1];
        const author = id && nearestLink(v, /^(https:\/\/[^/]+\/@[\w.-]+)\/?$/);
        return author ? `${author}/video/${id}` : null; } },
    { re: /(^|\.)facebook\.com$/, feed: true, post: v =>
        nearestLink(v, /^(https:\/\/[^/]+\/(?:[^/]+\/videos\/\d+|reel\/\d+|watch\/?\?v=\d+|share\/[rv]\/\w+))/) ||
        here(/^(https:\/\/[^/]+\/(?:[^/]+\/videos\/\d+|reel\/\d+|watch\/?\?v=\d+|share\/[rv]\/\w+))/) },
    { re: /(^|\.)reddit\.com$/, feed: true, post: v => {
        const perma = closestDeep(v, "shreddit-post")?.getAttribute("permalink");
        return (perma && new URL(perma, location.origin).href) ||
               nearestLink(v, /^(https:\/\/[^/]+\/r\/\w+\/comments\/\w+)/) ||
               here(/^(https:\/\/[^/]+\/r\/\w+\/comments\/\w+)/); } },
    { re: /(^|\.)threads\.(net|com)$/, feed: true, post: v =>
        nearestLink(v, /^(https:\/\/[^/]+\/@[^/]+\/post\/[\w-]+)/) ||
        here(/^(https:\/\/[^/]+\/@[^/]+\/post\/[\w-]+)/) },
    { re: /(^|\.)bsky\.app$/, feed: true, post: v =>
        nearestLink(v, /^(https:\/\/[^/]+\/profile\/[^/]+\/post\/\w+)/) ||
        here(/^(https:\/\/[^/]+\/profile\/[^/]+\/post\/\w+)/) },
    { re: /(^|\.)tumblr\.com$/, feed: true, post: v =>
        nearestLink(v, /^(https:\/\/[^?#]+\/post\/\d+)/) || here(/^(https:\/\/[^?#]+\/post\/\d+)/) },
    { re: /(^|\.)pinterest\.[a-z.]+$/, feed: true, post: v =>
        nearestLink(v, /^(https:\/\/[^/]+\/pin\/\d+)/) || here(/^(https:\/\/[^/]+\/pin\/\d+)/) },
    { re: /(^|\.)twitch\.tv$/, post: () =>
        here(/^(https:\/\/[^?#]*(?:\/videos\/\d+|\/clip\/[\w-]+))/) ||
        (host.startsWith("clips.") ? location.href : { error: LIVE }) },
    { re: /(^|\.)kick\.com$/, post: () =>
        here(/^(https:\/\/[^?#]*\/(?:videos?|clips?)\/[\w-]+)/) || { error: LIVE } },
  ];
  const site = SITES.find(s => s.re.test(host));

  function postUrl(v) {
    if (ytEmbed) return `https://www.youtube.com/watch?v=${ytEmbed[1]}`;
    if (!site) return location.href;
    const r = site.post(v);
    if (r) return r;
    return site.feed ? { error: OPEN_POST } : location.href;
  }

  // Reddit keeps its player inside a shadow root, so look there too
  const allVideos = () => [
    ...document.querySelectorAll("video"),
    ...[...document.querySelectorAll("shreddit-player, shreddit-player-2")]
      .flatMap(h => h.shadowRoot ? [...h.shadowRoot.querySelectorAll("video")] : []),
  ];

  // ── hover button over videos ───────────────────────────────────────────
  const MIN_W = 200, MIN_H = 120;
  const vm = M.create({ fixed: true });
  let active = null, hideTimer = null, lastMove = 0;

  function visibleBig(v) {
    const r = v.getBoundingClientRect();
    return r.width >= MIN_W && r.height >= MIN_H && r.bottom > 0 && r.right > 0 &&
           r.top < innerHeight && r.left < innerWidth;
  }
  function place(v) {
    const r = v.getBoundingClientRect();
    vm.root.style.top = Math.max(4, r.top + 10) + "px";
    vm.root.style.right = Math.max(4, innerWidth - r.right + 10) + "px";
  }
  function directSources(v) {
    if (!v) return [];
    const urls = [v.currentSrc, v.src, ...[...v.querySelectorAll("source")].map(s => s.src)];
    return [...new Set(urls.filter(u => u && /^https?:/i.test(u)))];   // blob: = stream, skip
  }
  function show(v) {
    active = v;
    if (!vm.root.isConnected) document.documentElement.appendChild(vm.root);
    place(v);
    vm.root.classList.add("pydm-vm-show");
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => { if (!vm.isOpen()) vm.root.classList.remove("pydm-vm-show"); }, 2500);
  }

  document.addEventListener("mousemove", e => {
    const now = Date.now();
    if (now - lastMove < 100 || vm.isOpen()) return;
    lastMove = now;
    for (const v of allVideos()) {
      if (!visibleBig(v)) continue;
      const r = v.getBoundingClientRect();
      if (e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom) {
        show(v);
        return;
      }
    }
  }, { passive: true, capture: true });

  const follow = () => { if (active && vm.root.classList.contains("pydm-vm-show")) place(active); };
  addEventListener("scroll", follow, { passive: true, capture: true });
  addEventListener("resize", follow, { passive: true });

  vm.btn.addEventListener("click", () => {
    const target = postUrl(active);
    const ctx = typeof target === "string"
      ? { url: target, withCookies: !ytEmbed, directUrls: directSources(active) }
      : { url: location.href, error: target.error, directUrls: directSources(active) };
    vm.toggle(ctx);
  });

  // ── fixed button on music pages (no <video> to hover) ─────────────────
  const segs = () => location.pathname.split("/").filter(Boolean);
  const pageUrl = () => location.origin + location.pathname;
  const AUDIO_PAGES = [
    [/(^|\.)soundcloud\.com$/, () => {
      const p = segs();
      const reserved = ["discover", "stream", "you", "search", "upload", "feed", "charts",
                        "settings", "messages", "notifications", "pages", "jobs", "mobile",
                        "people", "tags", "signin", "terms-of-use", "pro", "artists"];
      const userTabs = ["tracks", "albums", "sets", "reposts", "likes", "followers",
                        "following", "comments", "popular-tracks", "spotlight"];
      if (p.length < 2 || reserved.includes(p[0])) return null;
      if (p[1] === "sets" && p[2]) return "Download this set";
      if (p.length === 2 && !userTabs.includes(p[1])) return "Download this track";
      return null; }],
    [/\.bandcamp\.com$/, () => {
      const p = segs();
      return p[0] === "track" && p[1] ? "Download this track"
           : p[0] === "album" && p[1] ? "Download this album" : null; }],
    [/(^|\.)mixcloud\.com$/, () => {
      const p = segs();
      const reserved = ["discover", "upload", "select", "settings", "dashboard", "live",
                        "search", "categories", "messages", "notifications"];
      const userTabs = ["uploads", "favorites", "listens", "playlists", "reposts", "stream",
                        "followers", "following", "stats"];
      return p.length === 2 && !reserved.includes(p[0]) && !userTabs.includes(p[1])
        ? "Download this mix" : null; }],
    [/(^|\.)audiomack\.com$/, () => {
      const p = segs();
      return p[1] === "song" && p[2] ? "Download this song"
           : (p[1] === "album" || p[1] === "playlist") && p[2] ? "Download this album" : null; }],
  ];
  const audio = window.top === window && AUDIO_PAGES.find(([re]) => re.test(host));
  if (audio) {
    const pm = M.create({ fixed: true, label: "Download this track" });
    pm.root.classList.add("pydm-vm-show", "pydm-vm-page");
    let lastUrl = null;
    const check = () => {
      const label = audio[1]();
      if (!label) { pm.root.remove(); lastUrl = null; return; }
      if (!pm.root.isConnected) document.documentElement.appendChild(pm.root);
      if (pageUrl() !== lastUrl) { lastUrl = pageUrl(); pm.close(); pm.setLabel(label); }
    };
    pm.btn.addEventListener("click", () => pm.toggle({ url: pageUrl(), withCookies: true }));
    setInterval(check, 1000);   // these sites are single-page apps
    check();
  }
})();
