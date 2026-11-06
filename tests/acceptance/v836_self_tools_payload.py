#!/usr/bin/env python3
"""v836 — a hint is a pointer, not a payload (self diagnostic actions render).

Live evidence (polyglot arm, session b3a6b29e897c): the model asked for a tool
contract with `self {action:"tools", tool:"fs.write"}` and got EXACTLY 146 chars
back — the verdict line plus "hint: paths, config, docs…" — although the system
prompt promises the full input contract BEFORE the first call. The contract was
in `info["tools"]` all along: `observation()` treated `hint` as the body, so the
JSON fallback that would have dumped it never ran. Every `self` diagnostic
action (logs / context / tools / diagnostics / sj / trace) was affected.

Deterministic, no model. Run: python3 tests/acceptance/v836_self_tools_payload.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import tools  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


SELF = tools._DISPATCH["self"]

# --- A: the live call that failed — the contract must reach the model ---------
res = SELF({"action": "tools", "tool": "fs.read"}, "v836")
obs = tools.observation(res, max_chars=200000)
check("A1 self.tools{fs.read} renders more than the pointer line",
      len(obs) > 400, str(len(obs)))
check("A2 the rendered observation carries the contract fields",
      "properties" in obs and "required" in obs, obs[:300])
check("A3 the contract names the tool's own arguments",
      "pattern" in obs or "path" in obs, obs[:300])

# --- B: the second half of the fix — the payload dict survives the fallback ---
check("B1 the raw result still carries the contract",
      isinstance(res.get("tools"), dict) and res["tools"].get("ok") is True,
      str(type(res.get("tools"))))

# --- C: another diagnostic action whose payload used to be dropped ------------
ctx = tools.observation(SELF({"action": "context"}, "v836"), max_chars=200000)
check("C1 self.context renders its own payload, not only the hint",
      "result:" in ctx and '"context"' in ctx, ctx[:300])

# --- D: a hint with nothing else stays a hint (no invented payload) ----------
bare = tools.observation({"tool": "x", "ok": True, "exit_code": 0,
                          "backend": "host", "sandboxed": False,
                          "hint": "call self.info"}, max_chars=200000)
check("D1 hint-only result renders head + hint and no empty result line",
      "result:" not in bare and "hint: call self.info" in bare, repr(bare))

# --- E: a warning must not swallow the structured fields either --------------
warned = tools.observation({"tool": "x", "ok": True, "exit_code": 0,
                            "backend": "host", "sandboxed": False,
                            "warning": "ran on the host", "bytes": 32},
                           max_chars=200000)
check("E1 warning + counters -> warning AND the counter",
      "warning: ran on the host" in warned and "bytes" in warned, repr(warned))

# --- F: no regression on the stdout path -------------------------------------
shell = tools.observation({"tool": "shell", "ok": True, "exit_code": 0,
                           "backend": "host", "sandboxed": False,
                           "stdout": "HELLO", "hint": "see self.info"},
                          max_chars=200000)
check("F1 a stdout result still has no JSON fallback",
      "HELLO" in shell and "result:" not in shell, repr(shell))

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
