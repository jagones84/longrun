/* Longrun service worker (JAG-390).
 *
 * Minimal on purpose: it makes the WebUI INSTALLABLE (Chrome needs a service
 * worker with a fetch handler for the rich "Install app" flow) and keeps a
 * tiny offline shell. The harness is LIVE-ONLY — /api (including the SSE
 * streams) is never intercepted or cached, so the app can never show stale
 * data or a frozen stream.
 *
 * 2026-11-01 — the cache name is a VERSION, and it must be bumped whenever the
 * shell changes shape. `install` only runs once per worker body, so an unchanged
 * name kept the "/" copy captured at install time alive forever: the phone PWA
 * opened offline (Tailscale not up yet) fell back to that copy and rendered a
 * MONTHS-OLD shell — new sections missing, controls in the old places — while
 * /api/diagnostics answered 200 from the same page. A recovery reload fixed it,
 * which is exactly what a version bump makes unnecessary.
 * 2026-11-03 (RH-20) — bumped to v4: the Subagents draft control and the landscape
 * rail changed the shell's shape, and an unchanged name would have kept a phone PWA
 * on the v3 copy captured at its own install. BUMP THIS WHENEVER THE SHELL CHANGES.
 * 2026-11-16 — bumped to v5, measured on the tablet over Tailscale: its installed
 * PWA still held the 2026-11-09 "/" copy (1,052,587 B vs 1,203,162 B served) while
 * a week of shell changes shipped. A failed launch (Tailscale not up yet) therefore
 * rendered a week-old shell, and every failed script/style was answered with that
 * HTML — "not working PWA". The cache name is the ONLY thing that retires an old
 * copy for an already-installed app.
 * 2026-11-16 — bumped to v6: the Tools page gained its search field and the Rules
 * row moved the ✨ onto the path row, so the "/" shell changed shape again.
 * 2026-11-17 — bumped to v7 (JAG-933): the chat header gained the session-file
 * copy button, so the shell changed shape again.
 * 2026-11-17 — bumped to v8 (JAG-934): the phone transcript gutter changed, so the
 * "/" shell changed shape again.
 * 2026-11-17 — bumped to v9 (JAG-935/936): the composer doc bar closes on a
 * rejected document and the sessions rail head wraps instead of clipping.
 * 2026-11-23 — bumped to v10: 2026-11-21 shipped the compact status strip, the
 * themed selects, the Rules/Skills editors and the session-queue changes, but
 * the cache name stayed at v9, so an installed phone PWA could still render the
 * 2026-11-17 shell whenever the tailnet was not up yet.
 * 2026-11-24 — bumped to v11: the Rules panel now lists every loaded rules folder
 * (and each row names its own folder) instead of one wrong path, so the shell changed.
 * 2026-11-24 — bumped to v12: the active session's live context meter no longer
 * overwrites its per-session snapshot in the LH rail; all rail rows stay stable
 * across focus changes.
 * 2026-11-24 — bumped to v13: the Rules panel lists the GLOBAL files too (harness
 * `AGENTS.md` + optional `Global_rules.md`), so the shell changed shape.
 * 2026-11-24 — bumped to v14: a `/` command is pinned to the session it was typed in
 * (never the one selected afterwards), and a trailing space no longer turns it into
 * prose for the model.
 */
const CACHE = "longrun-shell-v14";
const SHELL = ["/", "/orbit", "/assets/dragsort.js", "/assets/icon-192.png",
               "/assets/icon-512.png", "/assets/apple-touch-icon.png",
               "/assets/icon-maskable-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(
    // `cache: "reload"` — the install must store what the server serves NOW, not
    // a heuristically fresh HTTP copy from before the deploy.
    caches.open(CACHE).then((c) => Promise.all(
      SHELL.map((u) => c.add(new Request(u, { cache: "reload" })))
    )).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  let url;
  try { url = new URL(req.url); } catch (_) { return; }
  // Never touch non-GET, cross-origin, the API (SSE/data must be live), or the
  // worker itself: those go straight to the network, unintercepted.
  if (req.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname === "/sw.js") return;
  // Network-first for the shell; fall back to the cached copy when offline.
  e.respondWith((async () => {
    try {
      const res = await fetch(req);
      if (res && res.ok && (url.pathname === "/" || url.pathname === "/index.html"
                            || url.pathname === "/orbit")) {
        const c = await caches.open(CACHE);
        // `waitUntil` owns the write: a detached `c.put` is aborted when the
        // worker is stopped right after the response, so the cached copy can stay
        // frozen at an older deploy even though every launch was live (measured:
        // a week). Keeping the event alive is what makes the copy follow the shell.
        e.waitUntil(c.put(url.pathname, res.clone()).catch(() => {}));
      }
      return res;
    } catch (_) {
      const hit = await caches.match(req);
      if (hit) return hit;
      // ONLY a navigation may fall back to the cached shell. Answering a failed
      // script/style with that HTML made the browser refuse it as `text/html`
      // (MIME) and left the app half-booted; a real network error is honest and
      // lets the page be retried.
      if (req.mode === "navigate") return (await caches.match("/")) || Response.error();
      return Response.error();
    }
  })());
});
