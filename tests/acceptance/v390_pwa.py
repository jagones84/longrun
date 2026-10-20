#!/usr/bin/env python3
"""v390 — the WebUI ships PWA scaffolding, so it can be installed as an app (JAG-390).

Static assertions (no browser, no server): the WebUI must expose a manifest, a
service worker, real icons and the head metadata — and the server must serve the
manifest (with the caller's token folded into `start_url`) and the service worker
PUBLICLY, at the root, without the API token.

Run: python3 tests/acceptance/v390_pwa.py
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = os.path.join(REPO, "webui", "index.html")
MAN = os.path.join(REPO, "webui", "manifest.webmanifest")
SW = os.path.join(REPO, "webui", "sw.js")
API = os.path.join(REPO, "src", "longrun", "core/httpapi.py")
ASSETS = os.path.join(REPO, "webui", "assets")

with open(UI, encoding="utf-8") as f:
    html = f.read()
with open(MAN, encoding="utf-8") as f:
    man = json.load(f)
with open(SW, encoding="utf-8") as f:
    sw = f.read()
with open(API, encoding="utf-8") as f:
    api = f.read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --- A: the page wires the PWA ------------------------------------------------
check("A1 the manifest is injected at boot (so start_url can carry the token)",
      "function setupPWA()" in html and "setupPWA();" in html
      and "/manifest.webmanifest" in html, "")
check("A2 the service worker is registered",
      'navigator.serviceWorker.register("/sw.js")' in html, "")
check("A3 the icon + apple-touch-icon + standalone meta are present",
      'rel="icon" href="/assets/icon-192.png"' in html
      and 'rel="apple-touch-icon" href="/assets/apple-touch-icon.png"' in html
      and 'name="apple-mobile-web-app-capable"' in html, "")

# --- B: the manifest ----------------------------------------------------------
check("B1 the manifest is standalone with any + maskable 192/512 icons",
      man.get("display") == "standalone"
      and any(i["sizes"] == "192x192" for i in man["icons"])
      and any(i["sizes"] == "512x512" and i["purpose"] == "maskable" for i in man["icons"]),
      str(man.get("icons")))
check("B2 the icon files exist on disk",
      all(os.path.isfile(os.path.join(ASSETS, n)) for n in (
          "icon-192.png", "icon-512.png", "icon-maskable-512.png",
          "apple-touch-icon.png")), "")

# --- C: the service worker ----------------------------------------------------
check("C1 the SW has a fetch handler that SKIPS /api (live data is never cached)",
      'addEventListener("fetch"' in sw and 'startsWith("/api/")' in sw, "")

# --- D: the server serves both, publicly -------------------------------------
check("D1 httpapi serves /manifest.webmanifest and folds the token into start_url",
      '== "/manifest.webmanifest"' in api and 'man["start_url"] = "/?token="' in api, "")
check("D2 httpapi serves /sw.js publicly as JavaScript",
      '== "/sw.js"' in api and 'ctype="text/javascript; charset=utf-8"' in api, "")

# --- E: JAG-499 — a rotated server token must not brick an installed PWA -------
check("E1 the URL token is probed before it can overwrite the stored token",
      "async function tokenState(" in html
      and 'return (r.status === 401 || r.status === 403) ? "rejected" : "unknown";' in html
      and "function stripTokenParam()" in html, "")
check("E2 a REJECTED URL token falls back to a WORKING stored token",
      'if (stored && stored !== qt && (await tokenState(stored)) === "ok")' in html, "")
check("E3 an unreachable server decides nothing (the token is kept)",
      'if (qstate === "unreachable")' in html, "")
check("E4 a rejected token never paints a false EMPTY session list",
      "function authErrorCard()" in html
      and '/unauthorized|401|forbidden/i.test(String(out.error))' in html, "")

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

