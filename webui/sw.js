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
 */
const CACHE = "longrun-shell-v4";
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
        c.put(url.pathname, res.clone());
      }
      return res;
    } catch (_) {
      const hit = await caches.match(req);
      return hit || (await caches.match("/")) || Response.error();
    }
  })());
});
