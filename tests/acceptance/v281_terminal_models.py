#!/usr/bin/env python3
"""v281 — real terminal, model menu, browser copy-URLs, max-context + thinking effort.

Locks in JAG-281:
  * term.py is a PERSISTENT per-session shell (cd/env survive across commands);
  * /api/term/{exec,poll,reset} are wired;
  * the model popover is anchored above its own button and opaque;
  * the Browser panel copies all stacked URLs;
  * the provider form can declare a context_length (id:context_length);
  * thinking effort is OPT-IN and only then adds `reasoning_effort` (safe default).

Deterministic, no live model. Run: python3 tests/v281_terminal_models.py
"""
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v281-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "DB"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR"):
    os.makedirs(os.environ["LONGRUN_" + _k], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import api_v02 as A     # noqa: E402
from longrun.core import server as S       # noqa: E402
from longrun.tools import term as T         # noqa: E402
import longrun.tools.registry as REG        # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def _drain(sh, cmd, timeout=8.0):
    start = sh.seq
    sh.run(cmd)
    end = time.time() + timeout
    while time.time() < end:
        p = sh.poll(start)
        if any(e["kind"] == "done" for e in p["events"]):
            return p
        time.sleep(0.05)
    return sh.poll(start)


def _out(p):
    return "".join(e["text"] for e in p["events"] if e["kind"] == "out")


# --- 1) term.py: a PERSISTENT shell ------------------------------------------
sh = T.get("v281", cwd=TMP)
check("a command streams its stdout", "hello-term" in _out(_drain(sh, "echo hello-term")))
_drain(sh, "cd /tmp && pwd")
check("the cwd PERSISTS across commands (real terminal)",
      "/tmp" in _out(_drain(sh, "pwd")))
check("shell arithmetic works", "42" in _out(_drain(sh, "echo $((20+22))")))
check("a command with no trailing newline still completes",
      "hi" in _out(_drain(sh, "printf hi")))
_p = _drain(sh, "false")
check("the exit code is reported",
      any(e["kind"] == "done" and e["code"] == 1 for e in _p["events"]))
check("reset drops the shell", T.reset("v281") is True and T.peek("v281") is None)

# --- 2) the HTTP surface -----------------------------------------------------
r = A.term_exec({"session": "v281t", "cmd": "echo api-term"})
check("term_exec accepts a command", r.get("ok") is True)
_deadline = time.time() + 5.0
pol = {"events": []}
while time.time() < _deadline:
    pol = A.term_poll({"session": "v281t", "cursor": "0"})
    if any(e.get("kind") == "out" and "api-term" in e.get("text", "")
           for e in pol.get("events", [])):
        break
    time.sleep(0.05)
check("term_poll returns the streamed output",
      any(e.get("kind") == "out" and "api-term" in e.get("text", "")
          for e in pol.get("events", [])))
check("term_poll reports the cwd", isinstance(pol.get("cwd"), str))
check("term_reset kills the shell", A.term_reset({"session": "v281t"}).get("ok") is True)
check("term_exec requires a command", A.term_exec({"session": "x"}).get("error") == "cmd required")

# --- 3) thinking effort (opt-in) ---------------------------------------------
_orig = REG.load_config
REG.load_config = lambda reload=False: {"reasoning": {"enabled": True, "effort": "high"}}
check("enabled reasoning adds reasoning_effort",
      S._completion_body("m", [{"role": "user", "content": "hi"}], False)
      .get("reasoning_effort") == "high")
REG.load_config = lambda reload=False: {"reasoning": {"enabled": False, "effort": "high"}}
check("disabled reasoning OMITS the field (safe default)",
      "reasoning_effort" not in S._completion_body("m", [], False))
REG.load_config = lambda reload=False: {"reasoning": {"enabled": True, "effort": "bogus"}}
check("an unknown effort is not sent",
      "reasoning_effort" not in S._completion_body("m", [], False))
REG.load_config = _orig
check("the body keeps the OpenAI-compatible shape",
      S._completion_body("m", [{"role": "user", "content": "x"}], True).get("stream") is True)

# --- 4) source wiring --------------------------------------------------------
with open(os.path.join(REPO, "src", "longrun", "model/rllm.py"), encoding="utf-8") as f:
    srv = f.read()
with open(os.path.join(REPO, "src", "longrun", "core/api_v02.py"), encoding="utf-8") as f:
    av = f.read()
with open(os.path.join(REPO, "src", "longrun", "tools/term.py"), encoding="utf-8") as f:
    trm = f.read()
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    ui = f.read()

check("server has the reasoning helper + field",
      "def _reasoning_effort" in srv and 'body["reasoning_effort"] = effort' in srv)
check("update_policy accepts a reasoning section", 'body.get("reasoning")' in av)
check("GET /api/tools exposes reasoning",
      '"reasoning": registry.load_config().get("reasoning")' in av)
check("the terminal routes are registered",
      '"/api/term/exec"' in av and '"/api/term/poll"' in av and '"/api/term/reset"' in av)
check("term.py uses a persistent bash + a completion sentinel",
      '"/bin/bash"' in trm and "__SF_DONE__" in trm)

# --- 5) UI -------------------------------------------------------------------
check("the model popover is anchored above its own button",
      ".model-wrap { position: relative" in ui and "bottom: calc(100% + 8px)" in ui)
check("the model popover is opaque (not translucent)",
      "background: var(--menubg)" in ui and "--menubg: #0f1320" in ui
      and "position: fixed; bottom: 92px" not in ui)
check("the duplicate Browser panel is gone (JAG-403h)",
      'data-insp="browser"' not in ui and "function browserGo" not in ui
      and "function _renderBrowserUrls" not in ui)
check("the terminal uses exec/poll/reset (persistent shell)",
      "function termSend" in ui and "/api/term/exec" in ui
      and "/api/term/poll" in ui and "function termReset" in ui)
check("the terminal has command history (up/down)",
      "ArrowUp" in ui and "_termHist" in ui)
check("the provider form can declare context_length",
      "id:context_length" in ui and "context_length: parseInt" in ui)
check("the models panel has a thinking-effort control",
      'id="reEffort"' in ui and "function saveReasoning" in ui
      and "loadReasoning" in ui)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

