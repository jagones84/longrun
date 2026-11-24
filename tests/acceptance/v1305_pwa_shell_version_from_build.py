#!/usr/bin/env python3
"""v1305 — the PWA shell cache can never go stale again (2026-11-24).

Operator, verbatim: *"Again stale pwa ...fix forever please"*.

The service worker made the WebUI installable, but its cache NAME was a literal a
human had to bump after every shell change (`longrun-shell-v3` … `v16`). `install`
only re-runs when the worker BODY changes, so every forgotten bump left an
installed phone showing the "/" copy captured at ITS OWN install — and the bumps
that did happen were made only AFTER the stale shell had already been seen (v5,
v9, v16 all say so in their own comments).

Pins the replacement contract:
  A: the cache name is DERIVED from the served build — `/sw.js` injects a digest of
     the SAME fingerprint `/api/build` returns (`httpapi.shell_build`), so a shell
     change changes the worker body AND the cache name with no human in the loop.
  B: the page adopts a new worker on resume (`updateViaCache: "none"`, `reg.update()`)
     and recovers a launch that raced the net and painted the cached shell: the boot
     probe hits a tiny public URL and reloads ONCE, bounded and throttled.

Deterministic: source contracts only. No browser, no server, no model.
Run: python3 tests/acceptance/v1305_pwa_shell_version_from_build.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SW = open(os.path.join(REPO, "webui", "sw.js"), encoding="utf-8").read()
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
API = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"),
           encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ---------------- A: the worker's cache name is derived, not hand-bumped ------
check("A1 the worker carries a version PLACEHOLDER, not a hand-bumped literal",
      'const SHELL_VERSION = "__SHELL_VERSION__";' in SW
      and not re.search(r'const CACHE = "longrun-shell-v\d+";', SW),
      SW[SW.find("const SHELL_VERSION"):][:120])
check("A2 the cache name is built from that version and never crashes when raw",
      'const CACHE = "longrun-shell-" +' in SW
      and ".test(SHELL_VERSION)" in SW and '"static"' in SW, "")
check("A3 /sw.js injects a digest of the SERVED build before replying",
      '_sw_src.replace("__SHELL_VERSION__", _sw_ver)' in API
      and "hashlib.sha1(shell_build(" in API, "")
check("A4 ONE truth: /api/build and /sw.js share `shell_build`",
      "def shell_build(index_path=None):" in API
      and '{"build": shell_build(_active_idx)}' in API, "")
check("A5 the fingerprint covers orbit.html AND webui/assets (a script fix counts)",
      "orbit.html" in API.split("def shell_build", 1)[-1].split("def ", 1)[0]
      and "assets" in API.split("def shell_build", 1)[-1].split("def ", 1)[0]
      and '(".js", ".css", ".html")' in API, "")

# ---------------- B: the page adopts and recovers without a manual reload -----
check("B1 registration bypasses the HTTP cache for the worker script",
      'register("/sw.js", { updateViaCache: "none" })' in UI, "")
check("B2 a NEW worker taking over reloads the page ONCE (a first install does not)",
      "hadController" in UI and 'addEventListener("controllerchange"' in UI
      and "if (!hadController || adopted) return;" in UI, "")
check("B3 a cached launch probes a tiny public URL and reloads when the server answers",
      "function _shellAlive()" in UI and 'fetch("/sw.js", { cache: "no-store" })' in UI
      and "function _shellRecover(n)" in UI and "location.reload();" in UI, "")
check("B4 the recovery is bounded and throttled (no reload loop)",
      "n > 60" in UI and "lr_shell_reload_ts" in UI and "30000" in UI, "")
check("B5 the probe is armed at boot, on every launch",
      re.search(r"function setupPWA\(\)[\s\S]*?_shellAlive\(\)\.then\(", UI) is not None, "")
check("B6 a resuming app asks for a fresh worker instead of waiting 24 h",
      "reg.update()" in UI and 'addEventListener("visibilitychange"' in UI
      and 'addEventListener("online", update)' in UI, "")

print("---")
passed = sum(results)
print("v1305: %d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
