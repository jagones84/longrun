#!/usr/bin/env python3
"""v383 — the reasoning delta has no single field name across providers (JAG-383).

llama.cpp / vLLM (OpenAI-compatible) stream reasoning in `delta.reasoning_content`,
but OpenRouter streams it in `delta.reasoning` (+ a structured `reasoning_details`).
Reading only `reasoning_content` silently DROPPED every OpenRouter model's chain of
thought (e.g. the A8 Master's `deepseek/deepseek-v4.1-flash`): the live CoT drawer
stayed empty and the persisted `reasoning` was null, so the WebUI showed "no thoughts".

Deterministic, NO real network: the transport is stubbed, so this exercises the REAL
`_router_stream` parsing end to end.
Run: python3 tests/acceptance/v383_reasoning_field.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="sf-383-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(tmp, "events.db")
for d in ("cfg", "sessions"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import rllm  # noqa: E402
from longrun.core import server  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# ---- transport stubs --------------------------------------------------------
class _Resp:
    def __init__(self, lines=b"", body=b""):
        self._lines = list(lines)
        self._body = body
        self.fp = None  # `resp.fp.raw._sock` raises -> the stream poll is skipped

    def readline(self):
        return self._lines.pop(0) if self._lines else b""

    def read(self):
        return self._body


class _CM:
    def __init__(self, resp):
        self._resp = resp

    def __enter__(self):
        return self._resp

    def __exit__(self, *a):
        return False


_orig = {k: getattr(rllm, k) for k in ("_reachable", "_open_with_retry", "_set_read_idle")}
rllm._reachable = lambda url, timeout=None: True
rllm._set_read_idle = lambda *a, **k: None


def _serve(lines):
    rllm._open_with_retry = lambda req, timeout, **_kw: _CM(_Resp(lines=lines))


def _sse(*chunks):
    out = []
    for c in chunks:
        out.append(("data: " + json.dumps(c) + "\n").encode("utf-8"))
    out.append(b"data: [DONE]\n")
    return out


def _delta(d):
    return {"choices": [{"delta": d}]}


try:
    # ---- A: OpenRouter `reasoning` is captured ------------------------------
    _serve(_sse(_delta({"reasoning": "step one "}),
                _delta({"reasoning": "step two"}),
                _delta({"content": "ANSWER"})))
    seen = []
    answer, think = rllm._router_stream([{"role": "user", "content": "hi"}],
                                        "openrouter:deepseek/deepseek-v4.1-flash",
                                        lambda ch, t: seen.append((ch, t)), guard=False)
    check("A1 OpenRouter `reasoning` deltas are captured (not dropped)",
          think == "step one step two", "think=%r" % think)
    check("A2 the answer is still captured", answer == "ANSWER", "answer=%r" % answer)
    check("A3 think deltas are emitted upstream (channel=think)",
          ("think", "step one ") in seen and ("think", "step two") in seen, "seen=%r" % seen)

    # ---- B: llama.cpp / vLLM `reasoning_content` still works -----------------
    _serve(_sse(_delta({"reasoning_content": "RC-1"}),
                _delta({"content": "A2"})))
    answer, think = rllm._router_stream([{"role": "user", "content": "hi"}],
                                        "dgx:nex-n25-mini-uncensored-q8",
                                        lambda ch, t: None, guard=False)
    check("B1 `reasoning_content` still works (no regression for local models)",
          think == "RC-1" and answer == "A2", "think=%r answer=%r" % (think, answer))

    # ---- C: non-streaming fallback also reads `reasoning` --------------------
    calls = {"n": 0}

    def _open(req, timeout, **_kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("stream failed before any token")
        return _CM(_Resp(body=json.dumps(
            {"choices": [{"message": {"reasoning": "FB-REASON", "content": "FB-ANSWER"}}]}).encode()))

    rllm._open_with_retry = _open
    answer, think = rllm._router_stream([{"role": "user", "content": "hi"}],
                                        "openrouter:deepseek/deepseek-v4.1-flash",
                                        lambda ch, t: None, guard=False)
    check("C1 the non-streaming fallback reads `reasoning` too",
          think == "FB-REASON" and answer == "FB-ANSWER", "think=%r answer=%r" % (think, answer))

    # ---- D: source guards (both field names are consulted) -------------------
    with open(os.path.join(REPO, "src", "longrun", "model/rllm.py"), encoding="utf-8") as f:
        RLLM = f.read()
    check("D1 the streaming parser accepts BOTH field names",
          'delta.get("reasoning_content") or delta.get("reasoning")' in RLLM, "")
    check("D2 the fallback parser accepts BOTH field names",
          'msg.get("reasoning_content") or msg.get("reasoning")' in RLLM, "")
finally:
    for k, v in _orig.items():
        setattr(rllm, k, v)

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

