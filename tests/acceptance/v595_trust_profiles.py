#!/usr/bin/env python3
"""v595 (RED) — Codex trust profiles: named sandbox x approval bundles.

Codex ships per-profile `sandbox_mode x approval_policy`. Longrun has a global
`sandbox.backend` and a global `approvals.mode` but no per-session binding, so
a worker session cannot be locked to isolated execution. The slice:

- `sandbox.TRUST_PROFILES = ("locked", "standard", "open")` + pure
  `sandbox.trust_profile(name)` (unknown name raises, JAG-2.7 style).
- `sandbox.run(..., trust=None)`: `locked` forces an isolated backend (docker/
  bwrap/nsjail from the probe; fail-closed refusal when host-only),
  `open` is explicit host execution, `standard`/None keeps today's path.
- Session trust: `stores.get_or_create_session(..., trust=...)` stores it,
  `stores.set_session_trust(sid, trust)` validates + persists it.
- `_shell` (and `_python`) run through the session trust and SKIP the
  host-terminal shortcut when locked (a locked shell must never touch host).

Deterministic: isolated dirs, no model, no network.
Run: python3 tests/acceptance/v595_trust_profiles.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmp = tempfile.mkdtemp(prefix="lr-trust-v595-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_DATA_DIR"] = _tmp
for d in ("cfg", "sessions"):
    os.makedirs(os.path.join(_tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import sandbox  # noqa: E402
from longrun.memory import stores  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A: the profile vocabulary --------------------------------------------------
check("A1 sandbox.TRUST_PROFILES lists locked/standard/open",
      tuple(getattr(sandbox, "TRUST_PROFILES", ())) == ("locked", "standard", "open"),
      repr(getattr(sandbox, "TRUST_PROFILES", None)))
check("A2 sandbox.trust_profile exists", callable(getattr(sandbox, "trust_profile", None)))
tp = getattr(sandbox, "trust_profile", None)
if callable(tp):
    check("A3 locked resolves to an isolated-only policy",
          tp("locked").get("isolated_required") is True, repr(tp("locked")))
    check("A4 open resolves to explicit host",
          tp("open").get("backend") == "none", repr(tp("open")))
    check("A5 standard defers to global config",
          tp("standard").get("backend") is None, repr(tp("standard")))
    try:
        tp("rootkit")
        check("A6 unknown profile raises, never guesses", False, "no raise")
    except ValueError:
        check("A6 unknown profile raises, never guesses", True)
else:
    for n in ("A3", "A4", "A5", "A6"):
        check(n, False, "trust_profile missing")

# ---- B: run() honors trust ---------------------------------------------------------
sig_ok = "trust" in getattr(sandbox.run, "__code__", None).co_varnames
check("B0 sandbox.run accepts trust", sig_ok)
if sig_ok:
    r = sandbox.run("echo trust-probe-v595", run_id="v595",
                    trust="open", timeout=30)
    check("B1 open is explicit host execution",
          r.get("backend") == "none(host)" and r.get("sandboxed") is False
          and r.get("exit_code") == 0, repr({k: r.get(k) for k in ("backend", "sandboxed", "exit_code")}))
    r = sandbox.run("echo trust-probe-v595", run_id="v595",
                    trust="locked", timeout=30)
    iso = r.get("sandboxed") is True
    refused = "isolated" in str(r.get("error") or "") or "locked" in str(r.get("error") or "")
    check("B2 locked never runs silently on the host",
          iso or (r.get("exit_code") == 126 and refused),
          repr({k: r.get(k) for k in ("backend", "sandboxed", "exit_code", "error")}))
else:
    for n in ("B1", "B2"):
        check(n, False, "run(trust=) missing")

# ---- C: session trust ---------------------------------------------------------------
s = stores.get_or_create_session(None, title="v595", trust="locked")
check("C1 session creation stores trust",
      s.get("trust") == "locked", repr(s.get("trust")))
s2 = stores.get_or_create_session(s["id"])
check("C2 trust survives reload", s2.get("trust") == "locked")
check("C3 set_session_trust exists", callable(getattr(stores, "set_session_trust", None)))
st = getattr(stores, "set_session_trust", None)
if callable(st):
    check("C4 switch to open works", st(s["id"], "open") is True)
    try:
        st(s["id"], "rootkit")
        check("C5 invalid trust rejected", False, "no raise")
    except ValueError:
        check("C5 invalid trust rejected", True)
    check("C6 rejection leaves the old trust",
          stores.get_or_create_session(s["id"]).get("trust") == "open")
else:
    for n in ("C4", "C5", "C6"):
        check(n, False, "set_session_trust missing")

# ---- D: the shell honors locked sessions ----------------------------------------------
try:
    with open(os.path.join(REPO, "src", "longrun", "tools", "tools.py"),
              encoding="utf-8") as f:
        _tools = f.read()
except OSError as e:
    _tools = ""
    print("WARN cannot read tools.py: %s" % e)
_sh = _tools.split("def _shell(", 1)
_sh = _sh[1] if len(_sh) > 1 else ""
_nxt = _sh.find("\ndef ")
_sh = _sh[:_nxt] if _nxt >= 0 else _sh
check("D1 _shell resolves the session trust",
      "trust" in _sh and "sandbox.run(" in _sh)
check("D2 locked sessions skip the host-terminal shortcut",
      "locked" in _sh and "_shell_terminal" in _sh)
_py = _tools.split("def _python(", 1)
_py = _py[1] if len(_py) > 1 else ""
_nxt = _py.find("\ndef ")
_py = _py[:_nxt] if _nxt >= 0 else _py
check("D3 _python also passes trust", "trust" in _py and "sandbox.run(" in _py)

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
