#!/usr/bin/env python3
"""v1054 — `web` returns a structured payload and batches several queries.

The model-facing text keeps its old numbered shape; the `data` payload is what
the WebUI renders (hit rows, engine, timings, `[wN]` ids). Providers are faked:
this test never touches the network.

  A1  one call, two queries -> both groups present, hits de-duplicated by URL
  A2  every hit carries an id and a host, ids are monotonic per run
  A3  the observation the MODEL reads carries `[wN]` markers
  A4  the structured payload stays under the 6 000-char cap
  A5  a second call in the same run continues the id sequence
  A6  two queries returning the same URL yield ONE hit
  A7  total failure names the whole provider chain and still ships `data`
  A8  `_strip_html` drops nav/header/footer/aside/form
  A9  action=fetch accepts `urls` and reports one page per URL
  A10 option normalisation and the keyless `site:` rewrite
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1054-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR",
           "GRAPH_DIR", "ROLES_DIR", "COSTS_DIR", "THREADS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import tools as T  # noqa: E402

results = []


def check(name, ok):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name)


def _hit(q, host=None):
    return {"title": "T " + q, "url": "https://%s/%s" % (host or "ex.com", q),
            "snippet": "s" * 400}


def _fake(q, n, opts=None):
    return [_hit(q)]


T._search_tavily = _fake
T._search_brave = _fake
T._search_duckduckgo = _fake
T._search_bing = _fake
T._WEB_IDS.clear()

res = T._web({"queries": ["alpha", "beta"], "max_results": 3}, "run-A")
check("A1a ok", res.get("ok") is True)
check("A1b two groups", len(res["data"]["groups"]) == 2
      and [g["query"] for g in res["data"]["groups"]] == ["alpha", "beta"])
check("A1c count", res.get("count") == 2)
flat = res["results"]
check("A2a ids", [r.get("id") for r in flat] == ["w1", "w2"])
check("A2b hosts", all(r.get("host") == "ex.com" for r in flat))
check("A3 stdout carries ids", "[w1]" in res["stdout"] and "[w2]" in res["stdout"])
check("A4 payload <= 6000", len(json.dumps(res["data"])) <= 6000)

res2 = T._web({"query": "gamma"}, "run-A")
check("A5 ids continue per run", [r["id"] for r in res2["results"]] == ["w3"])

T._search_tavily = lambda q, n, opts=None: [_hit("same", "dup.com")]
res3 = T._web({"queries": ["x", "y"]}, "run-B")
check("A6 URL de-dupe across queries", res3.get("count") == 1)


def _dead(q, n, opts=None):
    raise RuntimeError("missing TAVILY_API_KEY")


T._search_tavily = _dead
T._search_brave = _dead
T._search_duckduckgo = lambda q, n, opts=None: None
T._search_bing = lambda q, n, opts=None: None
bad = T._web({"query": "nope"}, "run-C")
check("A7a refused", bad.get("ok") is False)
check("A7b chain named", "tavily(missing TAVILY_API_KEY)" in bad.get("error", "")
      and "duckduckgo(0 hits)" in bad.get("error", ""))
check("A7c data still present", isinstance(bad.get("data"), dict)
      and bad["data"].get("action") == "search")

stripped = T._strip_html("<nav>menu</nav><p>real</p><footer>foot</footer>")
check("A8 nav/footer stripped", "menu" not in stripped and "foot" not in stripped
      and "real" in stripped)

T._web_fetch = lambda u, mb: ({"url": u, "text": "hello " + u, "via": "direct",
                               "host": "ex.com"}, None)
fetched = T._web({"action": "fetch", "urls": ["https://a.example/1", "https://b.example/2"]},
                 "run-D")
check("A9a fetch ok", fetched.get("ok") is True)
check("A9b two pages", len(fetched["data"]["pages"]) == 2
      and all(p.get("ok") for p in fetched["data"]["pages"]))
check("A9c both texts in stdout", "hello https://a.example/1" in fetched["stdout"]
      and "hello https://b.example/2" in fetched["stdout"])

opts = T._web_opts({"days": "3", "include_domains": ["a.com"], "exclude_domains": "b.com",
                    "search_depth": "ADVANCED"})
check("A10a opts normalised", opts["days"] == 3 and opts["include_domains"] == ["a.com"]
      and opts["exclude_domains"] == ["b.com"] and opts["search_depth"] == "advanced")
q = T._web_domain_ops("x", opts)
check("A10b site operators", "site:a.com" in q and "-site:b.com" in q)

print("\n%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
