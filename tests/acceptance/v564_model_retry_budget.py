#!/usr/bin/env python3
"""v564 (STAGED — M10 typed model-error retry budgets): classify first, retry well.

Contract (`M10-model-retry-budget.md`): `classify_retry(err)` ->
{disposition, retries, backoff}; quota -> 0 retries + quota event; fatal ->
fail fast; transient -> 3 retries; unknown -> fail fast. `_open_with_retry`
obeys the classification.
"""

import os
import sys
import tempfile
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TMP = tempfile.mkdtemp(prefix="sf-v564-")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import rllm  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _http_error(code):
    return urllib.error.HTTPError("http://127.0.0.1:8080/v1/chat/completions",
                                  code, "E%d" % code, {}, None)


if getattr(rllm, "classify_retry", None) is None:
    for n in ("1a", "1b", "1c", "1d", "1e", "2a", "2b", "2c", "2d", "3a"):
        check(n + " typed retry budgets", False, "M10 not implemented")
    print("TOTAL %d/%d" % (sum(results), len(results)))
    sys.exit(1)

# ---- 1. the classifier -------------------------------------------------------
c = rllm.classify_retry(_http_error(429))
check("1a 429 is quota with zero retries",
      c.get("disposition") == "quota" and c.get("retries") == 0, c)
c = rllm.classify_retry(_http_error(401))
check("1b 401 is fatal with zero retries",
      c.get("disposition") == "fatal" and c.get("retries") == 0, c)
c = rllm.classify_retry(_http_error(503))
check("1c 503 is transient with three retries",
      c.get("disposition") == "transient" and c.get("retries") == 3, c)
c = rllm.classify_retry(urllib.error.URLError("connection refused"))
check("1d URLError is transient",
      c.get("disposition") == "transient" and c.get("retries") == 3, c)
c = rllm.classify_retry(ValueError("weird"))
check("1e unknown errors fail fast",
      c.get("retries") == 0, c)

# ---- 2. the retry loop obeys the classification ------------------------------
events = []
_orig_publish = rllm.publish
rllm.publish = lambda kind, **kw: events.append((kind, kw))
_orig_urlopen = urllib.request.urlopen
_orig_sleep = rllm.time.sleep
rllm.time.sleep = lambda *_: None


class _Resp(object):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _run_seq(seq):
    calls = {"n": 0}

    def fake(req, timeout):
        i = calls["n"]
        calls["n"] += 1
        item = seq[min(i, len(seq) - 1)]
        if isinstance(item, Exception):
            raise item
        return _Resp()

    urllib.request.urlopen = fake
    return rllm._open_with_retry(object(), 5), calls["n"]


try:
    out, n = _run_seq([_http_error(503), _http_error(503), "ok-marker"])
    check("2a two transient 503s then success (3 urlopen calls)",
          n == 3, n)
    try:
        _run_seq([_http_error(503)] * 10)
        raised = False
    except urllib.error.HTTPError:
        raised = True
    check("2b persistent 503 raises after 1+3 attempts", raised, "")
    try:
        _run_seq([_http_error(429)])
        raised429 = False
    except urllib.error.HTTPError:
        raised429 = True
    check("2c quota 429 raises on the first attempt", raised429, "")
    try:
        _run_seq([_http_error(401)])
        raised401 = False
    except urllib.error.HTTPError:
        raised401 = True
    check("2d fatal 401 raises on the first attempt", raised401, "")

    kinds = [k for k, _ in events]
    check("3a transient retries publish model.retry with a disposition",
          any(k == "model.retry" for k in kinds)
          and any(kw.get("disposition") == "transient"
                  for k, kw in events if k == "model.retry"), kinds)
finally:
    urllib.request.urlopen = _orig_urlopen
    rllm.publish = _orig_publish
    rllm.time.sleep = _orig_sleep

print("TOTAL %d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
