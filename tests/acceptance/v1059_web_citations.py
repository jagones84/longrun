#!/usr/bin/env python3
"""v1059 — `[wN]` citations: assigned by the tool, resolved by the UI.

The tool must emit ids in the observation it gives the model; the WebUI must
build an id→URL index from the SAME persisted cards, turn `[wN]` into a link in
the answer, and mark a source as "cited" only when the id is in the answer.

  A1 the tool assigns ids and prefixes the observation
  A2 a failing call assigns none (no id drift on an empty result)
  A3 ids are unique across the session, monotonic per run
  A4 the UI index is built while rendering a web card
  A5 unknown ids stay plain text
  A6 the Sources block marks only the ids the answer contains
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1059-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR",
           "GRAPH_DIR", "ROLES_DIR", "COSTS_DIR", "THREADS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import tools as T  # noqa: E402

with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    html = f.read()

results = []


def check(name, ok):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name)


def _fake(q, n, opts=None):
    return [{"title": "T " + q, "url": "https://ex.com/" + q, "snippet": "s"}]


T._search_tavily = _fake
T._search_brave = _fake
T._search_duckduckgo = _fake
T._search_bing = _fake
T._WEB_IDS.clear()

res = T._web({"queries": ["a", "b"]}, "cite-run")
check("A1a ids in the payload",
      [r["id"] for r in res["results"]] == ["w1", "w2"])
check("A1b ids in the model text", "[w1] T a" in res["stdout"] and "[w2] T b" in res["stdout"])
check("A1c ids in the persisted data",
      [r["id"] for g in res["data"]["groups"] for r in g["results"]] == ["w1", "w2"])

T._search_tavily = lambda q, n, opts=None: None
T._search_brave = lambda q, n, opts=None: None
T._search_duckduckgo = lambda q, n, opts=None: None
T._search_bing = lambda q, n, opts=None: None
before = dict(T._WEB_IDS)
bad = T._web({"query": "empty"}, "cite-run")
check("A2a refused", bad.get("ok") is False)
check("A2b counter untouched", T._WEB_IDS == before)

T._search_tavily = _fake
res3 = T._web({"query": "c"}, "cite-run")
check("A3a monotonic", res3["results"][0]["id"] == "w3")
res4 = T._web({"query": "d"}, "other-run")
check("A3b per-run isolation", res4["results"][0]["id"] == "w1")
check("A3c numbers unique", len({r["id"] for r in res["results"] + res3["results"]}) == 3)

check("A4a index built from the card", "if (r.id) _citeIndex[r.id] =" in html)
check("A4b resolver called on every answer render", "_resolveCitations(b);" in html)
check("A5 unknown ids stay text", "const hit = _citeIndex[m[1]];" in html
      and "if (!hit) continue;" in html)
check("A6 cited flag requires the id in the answer",
      "rows.forEach(r => { r.cited = !!(r.id && cited[r.id]); });" in html)

print("\n%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
