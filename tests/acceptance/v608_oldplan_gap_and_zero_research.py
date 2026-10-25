#!/usr/bin/env python3
"""v608 — OLD PLAN gap label + research zero-source warning.

1. OLD PLAN counts DISTINCT stored plans, not max id. A deleted plan (JAG-514)
   leaves a gap (plans 1-6,8-14 = 13 plans). The header must name the missing
   ids so "13 vs 14" never reads as a miscount.
2. Research with zero fetched sources must warn LOUDLY (search dead vs fetch
   failed) instead of silently storing a stub — the "nothing embedded"
   case. NotebookLM contract: URLs land as notebook sources automatically.
Deterministic, no network, no model.
"""
import os
import sys
import tempfile

_tmp = tempfile.mkdtemp(prefix="sf-v608-")
os.environ["LONGRUN_DATA_DIR"] = _tmp
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("T1 OLD PLAN header names deleted-plan gaps",
      "(missing:" in HTML and "deleted)" in HTML
      and "DISTINCT stored plans" in HTML, "gap label")
check("T2 OLD PLAN still counts distinct plans + nodes",
      "OLD PLAN" in HTML and "_keys.length + ' plan(s)" in HTML, "count")

from longrun.research import executor as E  # noqa: E402

_real_search, _real_fetch, _real_llm = E.SEARCH, E.fetch_text, E.LLM
E.SEARCH = lambda q, n: ([{"title": "T", "url": "https://t.example",
                           "snippet": "s"}], "tavily")
E.fetch_text = lambda url: (_ for _ in ()).throw(Exception("boom"))
E.LLM = lambda prompt, model: None
try:
    out = E.run("gap probe", notebook="default",
                depth="shallow", n=1, max_rounds=1, llm_model="custom:dead")
    check("T3 zero fetched sources warns instead of silent stub",
          out.get("sources_added") == 0 and bool(out.get("warning"))
          and "0 sources" in out["warning"], out.get("warning", ""))
finally:
    E.SEARCH, E.fetch_text, E.LLM = _real_search, _real_fetch, _real_llm

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
