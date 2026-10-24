#!/usr/bin/env python3
"""v530 — the agent's `shell` tool and the RH Terminal panel are ONE shell (JAG-2.9).

Before: the panel kept a persistent shell (JAG-281) while the agent's `shell` tool
spawned a SEPARATE process through the sandbox. The operator could not see what the
agent ran, the agent could not see what the operator typed, and `cd`/exports never
crossed over.

After: when the command would run on the host anyway (sandbox backend `none`) the
tool runs it in that same persistent terminal and captures its output; `action=read`
returns the session (both origins) and `action=reset` starts a fresh shell. Under
docker/bwrap/nsjail the agent keeps the sandbox — a host terminal would silently
escape the isolation.

Deterministic, no model. Run: python3 tests/acceptance/v530_shared_terminal.py
"""
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry  # noqa: E402
from longrun.tools import term     # noqa: E402
from longrun.tools import tools as T  # noqa: E402

WIN = os.name == "nt"
PWD = "(Get-Location).Path" if WIN else "pwd"
SLEEP5 = "Start-Sleep -Seconds 5" if WIN else "sleep 5"

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  :: " + str(detail)[:160]))


TMP = tempfile.mkdtemp(prefix="v530-")
SUB = os.path.join(TMP, "sub")
os.makedirs(SUB, exist_ok=True)

# ---------------------------------------------------------------- A) capture ---
sh = term.get("v530", TMP)
r = sh.run_capture("echo cap-ok", timeout=30)
check("A1 run_capture returns the stdout and exit 0",
      r.get("exit_code") == 0 and "cap-ok" in (r.get("stdout") or ""), r)

r = sh.run_capture("definitely_not_a_command_530", timeout=30)
check("A2 a failing command reports a NON-zero exit (not swallowed)",
      r.get("exit_code") not in (0, None), r.get("exit_code"))

# ------------------------------------------------------- B) state persists ----
cd = ('Set-Location -LiteralPath "%s"' % SUB) if WIN else ('cd "%s"' % SUB)
sh.run_capture(cd, timeout=30)
r = sh.run_capture(PWD, timeout=30)
check("B1 cwd survives between two separate calls",
      os.path.normcase(os.path.realpath((r.get("stdout") or "").strip())) ==
      os.path.normcase(os.path.realpath(SUB)), r.get("stdout"))

# ------------------------------------------------------------- C) one buffer --
sh.run("echo typed-by-human", origin="user")   # the operator typing
time.sleep(2.0)
r = T._shell({"action": "read", "lines": 20}, "v530")
tail = r.get("stdout") or ""
check("C1 action=read returns the session to the agent",
      r.get("ok") is True and "typed-by-human" in tail, tail[-120:])
check("C2 the read distinguishes the operator from previous agent runs",
      "[you]" in tail or "[agent]" in tail, tail[-120:])

# ------------------------------------------------------------ D) timeout ------
t0 = time.time()
r = sh.run_capture(SLEEP5, timeout=1)
check("D1 a command past its timeout is reported, not hung",
      r.get("timed_out") is True and r.get("exit_code") == 124, r.get("exit_code"))
check("D2 the shell survives a timeout (child interrupted, no reset)",
      (time.time() - t0) < 6 and r.get("interrupted") is True
      and term.peek("v530") is not None, "elapsed=%.1f" % (time.time() - t0))
r = sh.run_capture("echo alive-530", timeout=30)
check("D2b the next call runs in the same shell",
      r.get("exit_code") == 0 and "alive-530" in (r.get("stdout") or ""), r)

# --------------------------------- E) routing: host -> the shared terminal ----
_orig_probe = T.sandbox.probe
_orig_run = T.sandbox.run
try:
    T.sandbox.probe = lambda force=False: {"backend": "none"}
    r = T._shell({"command": "echo via-tool"}, "v530r")
    check("E1 backend=none runs in the session terminal",
          r.get("backend") == "terminal" and r.get("terminal") is True
          and "via-tool" in (r.get("stdout") or ""), r)

    # --------------------------------- F) routing: isolated -> the sandbox ----
    T.sandbox.probe = lambda force=False: {"backend": "docker"}
    T.sandbox.run = lambda command, **kw: {"exit_code": 0, "stdout": "sandboxed-ok",
                                           "stderr": "", "backend": "stub",
                                           "sandboxed": True}
    r = T._shell({"command": "echo x"}, "v530r")
    check("F1 an isolating backend NEVER uses the host terminal",
          r.get("backend") == "stub" and r.get("sandboxed") is True, r)
finally:
    T.sandbox.probe = _orig_probe
    T.sandbox.run = _orig_run

# --------------------------------------------------------------- G) schema ----
props = registry.TOOL_SCHEMAS["shell"]["properties"]
check("G1 the shell schema exposes action + lines",
      "action" in props and "lines" in props, sorted(props))
check("G2 `command` is required for action=run and waived for read/reset",
      registry.TOOL_SCHEMAS["shell"]["required"] == ["command"]
      and registry.TOOL_SCHEMAS["shell"].get("required_waived_by") == {
          "action": ["read", "reset"]},
      registry.TOOL_SCHEMAS["shell"].get("required"))
check("G3 action=run without a command is refused at runtime",
      T._shell({"action": "run"}, "v530x").get("ok") is False)

# --------------------------------------------------------------- H) reset -----
check("H1 action=reset drops the session shell",
      T._shell({"action": "reset"}, "v530r").get("ok") is True
      and term.peek("v530r") is None)

# ------------------------------------------------------- I) the panel's TABS ----
# The RH panel showed ONLY the session shell, while the `shell` tool keys its
# terminal on the RUN id: every agent run (and every subagent) had a terminal of
# its own that the operator could not see. The panel now tabs them.
term.get("run_v530", TMP).run_capture("echo run-only", timeout=30)
term.get("v530", TMP).run_capture("echo session-only", timeout=30)
from longrun.core import server as _server  # noqa: E402,F401 — breaks the import cycle
from longrun.core import api_v02 as _api    # noqa: E402
_lst = _api.term_list({"session": "v530"})
_by_key = {t["key"]: t for t in (_lst.get("terminals") or [])}
check("I1 the terminal list exposes the session AND an agent run",
      "v530" in _by_key and "run_v530" in _by_key, sorted(_by_key))
check("I2 the session shell is current and the run is labelled",
      _by_key["v530"].get("current") is True
      and _by_key["run_v530"].get("role") == "run")
API_SRC = open(os.path.join(REPO, "src", "longrun", "core", "api_v02.py"),
               encoding="utf-8").read()
UI_SRC = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("I3 the list route exists", 'if path == "/api/term/list"' in API_SRC)
check("I4 the panel tabs every shell and polls the SELECTED one",
      'id="termTabs"' in UI_SRC and "async function termTabs()" in UI_SRC
      and 'qs.set("session", _termSel())' in UI_SRC)
term.reset("run_v530")

term.reset("v530")

print("---")
print("%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
