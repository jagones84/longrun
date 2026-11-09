#!/usr/bin/env python3
"""v294 — Orbit constellation: aggregate endpoint + non-modal window + deep-link (JAG-296).

Locked here:
  * `longrun.orbit.api._constellation()` aggregates agents + jobs + every agent's graph;
  * `GET /api/orbit/constellation` is registered;
  * the Orbit deck has ONE floating, NON-modal window (no backdrop), an AGENT/ALL
    scope menu, clusters per agent, and builds deep-links with session+node;
  * the main WebUI honours `?session=` and `?node=`.

Deterministic, no live model. Run: python3 tests/v294_constellation.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


from longrun.orbit import api as oapi  # noqa: E402

check("api exposes _constellation", hasattr(oapi, "_constellation"))
c = oapi._constellation()
check("constellation shape", set(["agents", "jobs", "graphs"]) <= set(c.keys()))
check("agents is a list", isinstance(c["agents"], list))
check("jobs is a list", isinstance(c["jobs"], list))
check("graphs is a dict", isinstance(c["graphs"], dict))

with open(os.path.join(REPO, "src", "longrun", "orbit", "api.py"), encoding="utf-8") as f:
    a = f.read()
check("constellation route registered", '"/api/orbit/constellation"' in a)

with open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"), encoding="utf-8") as f:
    ui = f.read()
check("constellation DOCKED panel exists",
      'id="constPanel"' in ui and 'id="constSvg"' in ui and 'id="constBody"' in ui)
check("the constellation is NOT a floating window", ".cwin" not in ui)
check("NO modal backdrop / old modal gone",
      'class="modal"' not in ui and "tacModal" not in ui)
check("page grid reorganized (AGENTS|JOB, ORG|CONSTELLATION, ROUTINES|FEED)",
      "grid2 ab" in ui and "grid2 oc" in ui and "grid2 rf" in ui)
check("AGENT/ALL is ONE scope menu (2026-11-09)", 'id="constMode"' in ui
      and 'value="all"' in ui and 'id="constAgent"' not in ui)
check("clusters per agent", "byAgent" in ui)
check("directed arrows (markers)", "mJob" in ui and "marker-end" in ui)
check("deep-link carries session+node", "session=" in ui and "node=" in ui)

with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    gui = f.read()
check("main reads ?session param", 'searchParams.get("session")' in gui)
check("main reads ?node param", 'searchParams.get("node")' in gui)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

