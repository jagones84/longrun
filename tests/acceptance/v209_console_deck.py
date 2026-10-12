#!/usr/bin/env python3
"""v209 — Command Deck regression gate (JAG-209).

Deterministic, no server. Guarantees the sci-fi deck ships correctly and stays
self-contained/public:
  A) the file exists and is a real single-file app;
  B) it wires the live endpoints and is accessible/responsive;
  C) it loads NO external resource (works offline / no CDN leak);
  D) the server registers /console and serves the SHELL before the auth gate,
     while the data endpoints underneath remain auth-gated.

Run:  python3 tests/v209_console_deck.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DECK = os.path.join(REPO, "webui", "console.html")
SERVER = os.path.join(REPO, "src", "longrun", "core/httpapi.py")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


html = ""
try:
    with open(DECK, "r", encoding="utf-8") as f:
        html = f.read()
except OSError:
    html = ""

# ---- A: exists, self-contained app ----
check("A1 deck file exists", os.path.isfile(DECK), DECK)
check("A2 non-trivial single file (>10KB)", len(html) > 10000, "bytes=%d" % len(html))
check("A3 no external <script src>", "<script src=" not in html, "")
check("A4 no external stylesheet link", "<link rel=\"stylesheet\"" not in html, "")

# ---- B: live wiring + a11y/responsive ----
check("B1 declares the deck title", "ORBITAL COMMAND DECK" in html, "")
for ep in ("/api/status", "/api/feed", "/api/sessions", "/api/sessions/", "/api/context"):
    check("B2 wires %s" % ep, ep in html, "")
check("B3 responsive viewport meta", 'name="viewport"' in html, "")
check("B4 honours prefers-reduced-motion", "prefers-reduced-motion" in html, "")
check("B5 live regions (aria-live)", "aria-live" in html, "")
check("B6 keyboard-focusable nodes (tabindex)", "tabindex" in html, "")

# ---- C: no external network dependency (no CDN / offline demo) ----
check("C1 no CDN references", "cdn." not in html.lower() and "unpkg" not in html.lower()
      and "jsdelivr" not in html.lower(), "")
check("C2 has an offline/demo fallback", "enterDemo" in html and "OFFLINE" in html.upper(), "")

# ---- D: server route, public shell, gated data ----
srv = ""
try:
    with open(SERVER, "r", encoding="utf-8") as f:
        srv = f.read()
except OSError:
    srv = ""
route_pos = srv.find('"/console", "/console.html", "/deck"')
auth_pos = srv.find("if not check_auth(self.headers, qs):")
check("D1 server registers the /console route", route_pos != -1, "")
check("D2 shell served BEFORE the auth gate (public)",
      route_pos != -1 and auth_pos != -1 and route_pos < auth_pos,
      "route=%d auth=%d" % (route_pos, auth_pos))

ok = sum(results)
print("\nv209: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

