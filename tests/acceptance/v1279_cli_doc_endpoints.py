#!/usr/bin/env python3
"""v1279 — every endpoint docs/CLI.md names is served by the server.

`v588` checks `forge.py`'s routes against the server. The **doc**'s endpoint column was the
unchecked third leg of that triangle: rename a route and update `forge.py`, and 113 rows in
the CLI reference go on describing an endpoint that no longer exists — while the gate stays
green, because nothing read them.

Scope is deliberately PRECISE. A first pass over *every* markdown file reported 15 "dead"
endpoints; all 15 were artefacts of the measurement, not drift:

  * external URLs        `https://docs.ollama.com/api/openai-compatibility`
  * filenames            `/api.py`, `/mcp_clients.local.json`
  * provider kinds       `kind: openai-compatible`
  * a route idiom the detector did not model:
        `path[len("/api/teams/"):]`  — 14 such families (`/api/agents/`, `/api/jobs/`, …)

So this pin reads **table rows and command examples** only, strips URLs and filenames, and
models the slice idiom. A guard whose false positives outnumber its true findings gets
ignored, so precision is the point.

Anti-vacuity: a synthetic unknown path is proven to be reported, and floors guard both the
extraction (>=50 endpoints) and the server's route surface (>=150 exact routes).

Deterministic: no server, no model, no network.
Run: python3 tests/acceptance/v1279_cli_doc_endpoints.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROUTE_FILES = [
    ("src", "longrun", "core", "httpapi.py"),
    ("src", "longrun", "core", "api_v02.py"),
    ("src", "longrun", "orchestrate", "orchestration.py"),
    ("src", "longrun", "orbit", "api.py"),
]

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


server = ""
for parts in ROUTE_FILES:
    with open(os.path.join(REPO, *parts), encoding="utf-8") as fh:
        server += fh.read() + "\n"

exact = set(re.findall(r'path\s*==\s*"([^"]+)"', server))
exact |= set(re.findall(r'_is\(\s*path\s*,\s*"([^"]+)"', server))
for tup in re.findall(r'path\s+in\s*\(([^)]+)\)', server):
    exact |= set(re.findall(r'"([^"]+)"', tup))
prefixes = set(re.findall(r'path\.startswith\(\s*"([^"]+)"', server))
# `/api/teams/<tid>` families, sliced as path[len("/api/teams/"):]
slices = set(re.findall(r'path\[len\("([^"]+)"\)', server))
for s in slices:
    exact.add(s.rstrip("/"))
    prefixes.add(s)


def served(c, exact_set, prefix_set):
    """The helper, separately callable so a stub can prove it still bites."""
    if c in exact_set:
        return True
    if any(c.startswith(q) or q == c for q in prefix_set):
        return True
    if c.endswith("/") and any(e.startswith(c) for e in exact_set):
        return True
    if "{" in c or "<" in c:
        head = re.split(r"[{<]", c)[0]
        return any(e.startswith(head) for e in exact_set) or any(head.startswith(q) for q in prefix_set)
    return False


with open(os.path.join(REPO, "docs", "CLI.md"), encoding="utf-8") as fh:
    lines = fh.read().splitlines()

cands = set()
for ln in lines:
    if not (ln.lstrip().startswith(("|", "python3 forge.py", "curl", "$ "))
            or "`/api" in ln or "`/mcp" in ln):
        continue
    stripped = re.sub(r"https?://\S+", " ", ln)                              # external URLs
    stripped = re.sub(r"`?/?[\w.-]+\.(json|yaml|yml|py|md|log)`?", " ", stripped)   # filenames
    for p in re.findall(r"/(?:api|mcp)[A-Za-z0-9_/{}<>.-]*", stripped):
        p = p.rstrip(".,)`\"'")
        if len(p) > 5:
            cands.add(p)

# ---- 0. anti-vacuity --------------------------------------------------------
check("self-test: an unknown endpoint is reported",
      served("/api/definitely-not-here", exact, prefixes) is False)
check("self-test: a known endpoint is accepted",
      served("/api/status", {"/api/status"}, set()) is True)
check("self-test: a prefix family is accepted",
      served("/api/teams/abc/reset", set(), {"/api/teams/"}) is True)

# ---- 1. floors --------------------------------------------------------------
check("the doc names a substantial endpoint surface (>=50)", len(cands) >= 50, "n=%d" % len(cands))
check("the server exposes a routable surface (>=150 exact)", len(exact) >= 150, "exact=%d" % len(exact))
check("the slice idiom is modelled (>=5 families)", len(slices) >= 5, "slices=%d" % len(slices))

# ---- 2. the requirement -----------------------------------------------------
dead = sorted(c for c in cands if not served(c, exact, prefixes))
check("every endpoint docs/CLI.md names is served", not dead,
      "dead=%s" % dead if dead else "endpoints=%d exact=%d prefixes=%d"
      % (len(cands), len(exact), len(prefixes)))

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
