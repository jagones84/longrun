#!/usr/bin/env python3
"""v1043 — the installed-PWA shell cache must FOLLOW the shell (2026-11-16).

Measured on the tablet over Tailscale: the WebAPK had been installed since 09 Nov and
its service worker still held the "/" copy of that day (1,052,587 B) while the server
served 1,203,162 B. A launch that raced the tailnet (network fetch fails) therefore
painted a WEEK-OLD shell, and because the offline fallback answered EVERY failed
request with that HTML, the browser refused the scripts/styles as `text/html` (MIME)
and the app booted half-dead — the operator's "not working PWA".

Pins, on `webui/sw.js`:
  A: the cache name is a NEW version — the only thing that retires an installed app's
     stale shell (v4 was captured 2026-11-09).
  B: the shell write is owned by the fetch event (`e.waitUntil`), so the worker being
     stopped right after the response cannot drop it (which froze the copy for a week
     although every launch was live).
  C: only a NAVIGATION may fall back to the cached shell; a failed asset must be a
     real network error, never the shell HTML.

Run: python3 tests/acceptance/v1043_pwa_shell_cache.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SW = os.path.join(REPO, "webui", "sw.js")

with open(SW, encoding="utf-8") as f:
    sw = f.read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


m = re.search(r'const CACHE = "longrun-shell-v(\d+)";', sw)
version = int(m.group(1)) if m else 0

check("A1 the shell cache carries a NEW version (an installed app retires its old copy)",
      version >= 5, "longrun-shell-v%d" % version)

check("B1 the shell cache write is owned by the fetch event (e.waitUntil), not detached",
      "e.waitUntil(c.put(" in sw, "")

fallback = sw.split('} catch (_) {')[-1] if "} catch (_) {" in sw else ""
check("C1 a failed NAVIGATION falls back to the cached shell",
      'req.mode === "navigate"' in sw and 'caches.match("/")' in sw, "")
check("C2 a failed asset is a network error, never the shell HTML",
      "if (hit) return hit;" in sw and fallback.count("Response.error()") >= 1
      and not re.search(r"return hit \|\| \(await caches\.match\(\"/\"\)\)", sw),
      "")

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
