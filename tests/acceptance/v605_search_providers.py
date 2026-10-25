#!/usr/bin/env python3
"""v605 (RED) — search providers are an explicit, ordered, fall-through chain.

`_web_search` today hardcodes tavily → brave → duckduckgo inside one body.
DeerFlow ships one tool per provider; Longrun keeps one tool but the chain
must be explicit (one function per provider), ordered (config-overridable)
and fall-through (a dead provider never kills the search).

Deterministic: urlopen + secrets are stubbed, no network, no model.
Run: python tests/acceptance/v605_search_providers.py
"""
import io
import json
import os
import sys
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


from longrun.tools import tools as T
from longrun.research import researchcfg as RC


def _with_clean_cfg(fn):
    """Run fn with an empty config so live user settings cannot leak in."""
    real = RC._base.load_config
    RC._base.load_config = lambda: {}
    try:
        return fn()
    finally:
        RC._base.load_config = real

check("T1 one function per provider + order override on _web_search",
      all(callable(getattr(T, n, None))
          for n in ("_search_tavily", "_search_brave", "_search_duckduckgo"))
      and "providers" in getattr(T._web_search, "__code__", None).co_varnames)

_calls = []


class _Resp:
    def __init__(self, payload):
        self._b = (payload if isinstance(payload, bytes)
                   else json.dumps(payload).encode("utf-8"))

    def read(self, n=-1):
        return self._b if n < 0 else self._b[:n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_BEHAVIOUR = {}


def _fake_urlopen(req, timeout=None):
    url = req.full_url if hasattr(req, "full_url") else str(req)
    _calls.append(url)
    for key, val in _BEHAVIOUR.items():
        if key in url:
            if isinstance(val, Exception):
                raise val
            return _Resp(val)
    raise AssertionError("unstubbed url: " + url)


_real_urlopen, _real_secret = urllib.request.urlopen, T._secret
_real_sp = RC.search_providers
urllib.request.urlopen = _fake_urlopen
T._secret = lambda k: {"TAVILY_API_KEY": "t", "BRAVE_API_KEY": "b"}.get(k, "")
RC.search_providers = lambda: ["tavily", "brave", "duckduckgo"]
try:
    _BEHAVIOUR.clear(); _calls.clear()
    _BEHAVIOUR["tavily"] = Exception("boom")
    _BEHAVIOUR["brave"] = {"web": {"results": [
        {"title": "B", "url": "https://b.example", "description": "snip"}]}}
    res, eng = T._web_search("q", 5)
    check("T2 a dead provider falls through to the next one",
          eng == "brave" and res and res[0]["url"] == "https://b.example",
          "%s %s" % (eng, res))

    _BEHAVIOUR.clear(); _calls.clear()
    _BEHAVIOUR["tavily"] = {"results": [
        {"title": "T", "url": "https://t.example", "content": "snip"}]}
    _BEHAVIOUR["brave"] = {"web": {"results": [
        {"title": "B", "url": "https://b.example", "description": "snip"}]}}
    res, eng = T._web_search("q", 5, providers=["brave", "tavily"])
    check("T3 a configured order wins over the default",
          eng == "brave" and _calls and "brave" in _calls[0], _calls[:2])

    res, eng = T._web_search("q", 5, providers=["nope", "tavily"])
    check("T4 unknown provider names are ignored",
          eng == "tavily" and res and res[0]["url"] == "https://t.example",
          "%s %s" % (eng, res))

    res, eng = T._web_search("   ", 5)
    check("T5 no regression (empty query short-circuits)",
          res is None and eng == "empty query", "%r %r" % (res, eng))
finally:
    urllib.request.urlopen = _real_urlopen
    T._secret = _real_secret
    RC.search_providers = _real_sp

check("T6 the chain order itself is config-overridable",
      callable(getattr(RC, "search_providers", None))
      and _with_clean_cfg(lambda: RC.search_providers()[:2]) == ["tavily", "brave"],
      _with_clean_cfg(lambda: RC.search_providers()))

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
