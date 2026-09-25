// PyDM — IDM-style "Download this video" button inside the YouTube player.
(() => {
  const M = window.PyDMVideoMenu;
  if (!M) return;
  const vm = M.create();
  vm.root.id = "pydm-yt";
  let currentId = null;

  function videoId() {
    const u = new URL(location.href);
    if (u.pathname === "/watch") return u.searchParams.get("v");
    const m = u.pathname.match(/^\/(shorts|live)\/([\w-]{6,})/);
    return m ? m[2] : null;
  }
  const canonical = id => `https://www.youtube.com/watch?v=${id}`;

  function findPlayer() {
    if (location.pathname.startsWith("/shorts/")) {
      return document.querySelector("ytd-reel-video-renderer[is-active] .html5-video-player") ||
             document.querySelector("#shorts-player");
    }
    return document.querySelector("#movie_player.html5-video-player") ||
           document.querySelector(".html5-video-player");
  }

  vm.btn.addEventListener("click", () => {
    if (!currentId) return;
    vm.toggle({ url: canonical(currentId),
                playlist: new URL(location.href).searchParams.get("list") });
  });

  // YouTube is a single-page app: keep the button attached as you navigate
  function ensure() {
    const id = videoId();
    const player = id && findPlayer();
    if (!player) { vm.root.remove(); return; }
    if (vm.root.parentElement !== player) player.appendChild(vm.root);
    if (id !== currentId) { currentId = id; vm.close(); }
  }
  document.addEventListener("yt-navigate-finish", ensure);
  setInterval(ensure, 1000);
  ensure();
})();
