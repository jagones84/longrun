#!/usr/bin/env python3
"""v1058 — the canonical `web` schemas advertise the batched forms.

`web.search` must accept `query` OR `queries` (and `web.fetch` `url` OR `urls`);
the old hard `required: ["query"]` refused a batched call before the handler saw
it. Pure registry assertions: no tool is executed, no network.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1058-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR",
           "GRAPH_DIR", "ROLES_DIR", "COSTS_DIR", "THREADS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry as R  # noqa: E402

results = []


def check(name, ok):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name)


search = R.tool_spec("web.search")["schema"]
fetch = R.tool_spec("web.fetch")["schema"]
sprops = search.get("properties") or {}
fprops = fetch.get("properties") or {}

check("A1 search required is empty", search.get("required") == [])
check("A2 search anyOf query|queries",
      {"required": ["query"]} in (search.get("anyOf") or [])
      and {"required": ["queries"]} in (search.get("anyOf") or []))
check("A3 search advertises queries", sprops.get("queries", {}).get("type") == "array")
check("A4 search options", all(k in sprops for k in
                               ("max_results", "max_total", "days",
                                "include_domains", "exclude_domains", "search_depth")))
check("A5 depth enum", sprops.get("search_depth", {}).get("enum") == ["basic", "advanced"])
check("A6 fetch anyOf url|urls",
      {"required": ["url"]} in (fetch.get("anyOf") or [])
      and {"required": ["urls"]} in (fetch.get("anyOf") or []))
check("A7 fetch advertises urls", fprops.get("urls", {}).get("type") == "array")
check("A8 fetch default 16384", fprops.get("max_bytes", {}).get("default") == 16384)
check("A9 guidance mentions queries",
      "queries" in (R.tool_spec("web.search")["schema"].get("description") or ""))
check("A10 guidance mentions urls",
      "urls" in (R.tool_spec("web.fetch")["schema"].get("description") or ""))
check("A11 subtool field map", R._SUBTOOL_FIELDS["web"]["search"][:2] == ["query", "queries"]
      and R._SUBTOOL_FIELDS["web"]["fetch"][:2] == ["url", "urls"])
check("A12 both names in the catalogue",
      any(r.get("name") == "web.search" for r in R.catalog())
      and any(r.get("name") == "web.fetch" for r in R.catalog()))

print("\n%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
