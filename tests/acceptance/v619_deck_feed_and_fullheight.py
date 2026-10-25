#!/usr/bin/env python3
"""v619 — Control deck: feed never void, lone panels fill the page.

  A  Feed paints the backlog first (SSE `backlog` replay + GET
     /api/feed/recent fallback), live events prepend through ONE line()
     helper, and an explicit empty state replaces the void.
  B  Single-panel view lifts every stacked-board height cap (agents
     scroll, routines, feed, org canvas, constellation body) so a lone
     diagram fills the page; row grips are gone and charts get a resize
     refit on every view switch.
  C  Stacked board keeps its order (agents, routines, jobs, org, const,
     feed) and its row resizing — the grip builder looks inside
     .deckBody (the v617 rail moved rows there; the old selector matched
     nothing).

Deterministic: static source contract, no server, no model, no network.
Run: python3 tests/acceptance/v619_deck_feed_and_fullheight.py
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


ORBIT = _read("src", "longrun", "orbit", "web", "orbit.html")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---------------- A: feed never void ----------------------
check("A1 SSE backlog replay is consumed",
      'addEventListener("backlog"' in ORBIT and "paintBacklog" in ORBIT)
check("A2 JSON backlog fallback on open and on stream error",
      ORBIT.count("/api/feed/recent?limit=40") >= 2)
check("A3 ONE line helper for backlog + live (no second truth)",
      "line(kind, d)" in ORBIT and ORBIT.count("insertAdjacentHTML(\"afterbegin\"") == 1)
check("A4 explicit empty states, never a bare void",
      "no events yet" in ORBIT and "feed unreachable" in ORBIT)

# ---------------- B: lone panel fills the page ----------------------
for label, frag in [
    ("agents scroll cap lifted", "main.view-one .panel.ag .scroll{max-height:none}"),
    ("routines cap lifted", "main.view-one #routines{max-height:none !important}"),
    ("feed cap lifted", "main.view-one #feed{max-height:none}"),
    ("org canvas fills", "main.view-one .orgwrap{min-height:calc(100vh - 230px)}"),
    ("constellation body fills", "main.view-one .panel.cpanel .cbody{height:calc(100vh - 270px)"),
    ("saved row heights ignored alone", "main.view-one .grid2{height:auto !important}"),
]:
    check("B " + label, frag in ORBIT)
check("B charts refit after every view switch",
      'window.dispatchEvent(new Event("resize"))' in ORBIT)

# ---------------- C: ordered stack + grips ----------------------
panels = [m for m in ['data-panel="agents"', 'data-panel="routines"',
                      'data-panel="jobs"', 'data-panel="org"',
                      'data-panel="const"', 'data-panel="feed"']]
pos = [ORBIT.index(m) for m in panels]
check("C1 stacked order agents, routines, jobs, org, const, feed",
      pos == sorted(pos), pos)
check("C2 rail names the same six panes in the same order",
      [ORBIT.index('data-view="%s"' % v) for v in
       ["agents", "routines", "jobs", "org", "const", "feed"]] ==
      sorted([ORBIT.index('data-view="%s"' % v) for v in
              ["agents", "routines", "jobs", "org", "const", "feed"]]))
check("C3 row grips build inside .deckBody (v617 rail moved rows)",
      "main .deckBody > .grid2" in ORBIT)

print("---")
ok = sum(results)
print("\nv619: %d/%d PASS" % (ok, len(results)))
raise SystemExit(0 if ok == len(results) else 1)
