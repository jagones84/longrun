#!/usr/bin/env python3
"""v607 — research degrades LOUD, never silently (and the chain stays usable).

A dead summary model (no key, retired catalogue id, router down) used to
degrade to the bare "Research summary about: …" stub with no trace of why the
citations were gone — the feature looked broken with zero diagnostics.
Now: primary -> local:default fallback -> stub, and EVERY fallback carries a
warning (result dict + event + WebUI log line).

Deterministic: the LLM + KB are stubbed, no network, no model.
Run: python tests/acceptance/v607_research_loud_fallback.py
"""
import os
import sys
import tempfile

_tmp = tempfile.mkdtemp(prefix="sf-v607-")
os.environ["LONGRUN_DATA_DIR"] = _tmp
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


from longrun.research import executor as E  # noqa: E402
from longrun.research import researchcfg as RC  # noqa: E402
from longrun.memory import knowledge as KB  # noqa: E402

_calls = []
_NB = "default"  # v608 fix: the default notebook always exists in a fresh DB;
# the old random id never existed, so add_source_text failed, zero chunks were
# collected, the LLM was never called and T1/T2 failed for the wrong reason.


def _ok_llm(prompt, model):
    _calls.append(model)
    return {"summary": "CITED SUMMARY via " + model}


def _dead_llm(prompt, model):
    _calls.append(model)
    return None


def _stub_search(query, n):
    return [{"title": "T", "url": "https://t.example",
             "snippet": "snip"}], "tavily"


def _stub_fetch(url):
    return "page text about the topic " * 20


_real_llm, _real_search, _real_fetch = E.LLM, E.SEARCH, E.fetch_text
_real_rc_models = list(RC.MODELS)
E.SEARCH, E.fetch_text = _stub_search, _stub_fetch
try:
    _calls.clear()
    E.LLM = _ok_llm
    out = E.run("fallback probe", notebook=_NB,
                depth="shallow", n=1, max_rounds=1, llm_model="custom:primary")
    check("T1 a live primary model is used with no warning",
          out.get("ok") and not out.get("warning")
          and _calls == ["custom:primary"], _calls)

    _calls.clear()
    E.LLM = _dead_llm
    out = E.run("fallback probe", notebook=_NB,
                depth="shallow", n=1, max_rounds=1, llm_model="custom:dead")
    check("T2 a dead primary falls back to the local router, LOUDLY",
          out.get("ok") and out.get("warning")
          and "local router" in out["warning"]
          and _calls == ["custom:dead", "local:default"], _calls)

    E.fetch_text = lambda url: (_ for _ in ()).throw(Exception("fetch down"))
    _calls.clear()
    E.LLM = _dead_llm
    out = E.run("fallback probe", notebook=_NB,
                depth="shallow", n=1, max_rounds=1, llm_model="custom:dead")
    check("T3 fetch failure imports nothing (no phantom sources)",
          out.get("sources_added") == 0, out.get("sources_added"))
finally:
    E.LLM, E.SEARCH, E.fetch_text = _real_llm, _real_search, _real_fetch
    RC.MODELS[:] = _real_rc_models
    # default notebook must survive (it cannot be deleted) — nothing to clean.

HTML = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("T4 the WebUI research log surfaces the warning",
      "if (r.warning) append(" in HTML)
CFGSRC = open(os.path.join(REPO, "src", "longrun", "research", "researchcfg.py"),
              encoding="utf-8").read()
check("T5 no retired catalogue id ships (verified live 2026-10-25)",
      "gpt-4o-mini-search-preview" not in CFGSRC
      and "openrouter:perplexity/sonar" in CFGSRC)

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
