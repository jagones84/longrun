#!/usr/bin/env python3
"""v621 — Control page has PWA parity with the main app.

The main WebUI is installable (manifest + worker + icons); /orbit had none
of it, so "Add to Home Screen" from Control was broken and a standalone
launch opened unauthenticated. Now the deck injects the same token-carrying
manifest, registers the same worker (which never touches /api), and honors
notch safe-areas. One installable app, scope /.

Deterministic: static source contract, no server, no model, no network.
Run: python3 tests/acceptance/v621_orbit_pwa.py
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


ORBIT = _read("src", "longrun", "orbit", "web", "orbit.html")
MANIFEST = _read("webui", "manifest.webmanifest")
SW = _read("webui", "sw.js")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


check("P1 viewport covers notches", "viewport-fit=cover" in ORBIT)
check("P2 theme-color matches the app shell",
      '<meta name="theme-color" content="#06070c">' in ORBIT)
check("P3 iOS icon present",
      'rel="apple-touch-icon" href="/assets/apple-touch-icon.png"' in ORBIT
      and os.path.exists(os.path.join(REPO, "webui", "assets", "apple-touch-icon.png")))
check("P4 token-carrying manifest injected (same route as the main app)",
      "/manifest.webmanifest" in ORBIT and "?token=" in ORBIT
      and '"start_url"' in MANIFEST)
check("P5 same worker registered (install flow, never /api)",
      'navigator.serviceWorker.register("/sw.js")' in ORBIT
      and 'url.pathname.startsWith("/api/")' in SW)
check("P6 notch safe-areas honored", "env(safe-area-inset-top" in ORBIT)
check("P7 narrow layout keeps the rail usable (top strip, no row grips)",
      "@media (max-width:1100px)" in ORBIT and "@media (max-width:640px)" in ORBIT)

print("---")
ok = sum(results)
print("\nv621: %d/%d PASS" % (ok, len(results)))
raise SystemExit(0 if ok == len(results) else 1)
