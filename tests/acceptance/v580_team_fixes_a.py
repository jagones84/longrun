#!/usr/bin/env python3
"""v580 — team fixes batch A: shell survival, observation warning, browser guard.

Fix1: a hung child (ssh prompt, dead host, unbalanced quote) used to nuke the
whole shared terminal via reset(). Now the shell leads its own process group and
the timeout path SIGINTs just the child; the shell (cwd/exports) survives and
only a failed interrupt falls back to reset. Timeout is also coerced to int.

Fix6: the sandbox/host-execution `warning` was invisible whenever a body was
present; observation() now always renders it. The `browser` tool with an empty
allow-list rejected every host; empty now means public-internet only through
the SSRF-guarded reader. Q1/Q2 WebUI wirings are locked as static guards.

Deterministic, no model, no network.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v580-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import term  # noqa: E402
from longrun.tools import tools as tools_mod  # noqa: E402
from longrun.tools import registry  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


# ---- Fix1: shell survives a hung child --------------------------------------
sh = term.get("v580-shell", TMP)
r = sh.run_capture("export V580_MARKER=yes", timeout=10)
check("F1a shell runs trivial commands", r.get("exit_code") == 0, r)
r = sh.run_capture("sleep 8", timeout=2)
check("F1b hung child times out with 124", r.get("exit_code") == 124 and r.get("timed_out") is True, r)
if os.name != "nt":
    check("F1c interrupt path taken, no reset", r.get("interrupted") is True, r.get("error"))
    r2 = sh.run_capture("echo alive-$V580_MARKER", timeout=10)
    check("F1d shell survived: next command runs",
          r2.get("exit_code") == 0 and "alive-" in (r2.get("stdout") or ""), r2.get("stdout", "")[:80])
    check("F1e shell survived: exports intact (no reset)",
          "alive-yes" in (r2.get("stdout") or ""), r2.get("stdout", "")[:80])
else:
    r2 = sh.run_capture("echo alive", timeout=10)
    check("F1d-win fallback: next command runs after reset",
          r2.get("exit_code") == 0, r2.get("stdout", "")[:80])
term.reset("v580-shell")

# string timeout must not crash (old code: TypeError in Event.wait)
sh2 = term.get("v580-str", TMP)
r = sh2.run_capture("sleep 5", timeout="2")
check("F1f string timeout coerced, 124 not crash",
      r.get("exit_code") == 124 and r.get("timed_out") is True, r)
term.reset("v580-str")

# ---- Fix6: warning is always visible -----------------------------------------
res = {"tool": "shell", "ok": True, "exit_code": 0, "backend": "none(host)",
       "sandboxed": False, "stdout": "hi",
       "warning": "no sandbox backend available — ran on the host"}
obs = tools_mod.observation(res)
check("F6a warning rendered with body present", "warning:" in obs and "ran on the host" in obs, obs[:160])
res_err = dict(res, ok=False, exit_code=1, error="boom", stdout="")
obs2 = tools_mod.observation(res_err)
check("F6b warning rendered on errors too", "warning:" in obs2, obs2[:160])
res_nowarn = {"tool": "shell", "ok": True, "exit_code": 0, "backend": "bwrap",
              "sandboxed": True, "stdout": "hi"}
check("F6c no warning line when none set", "warning:" not in tools_mod.observation(res_nowarn))

# ---- Fix6: browser SSRF guard + default --------------------------------------
from longrun.tools.tools import _public_host  # noqa: E402
ok, _ = _public_host("http://127.0.0.1/x")
check("F6d loopback blocked without network", ok is False, _)
ok, _ = _public_host("http://localhost/")
check("F6e localhost blocked without network", ok is False, _)
ok, host = _public_host("not a url")
check("F6f unparseable url blocked without network", ok is False, host)
br = (registry.load_config().get("tools") or {}).get("browser") or {}
check("F6g browser enabled by default", br.get("enabled") is True, br)
check("F6h browser still approval-gated", br.get("approval") == "required", br.get("approval"))
res = tools_mod._browser({"url": "http://127.0.0.1/"}, "v580")
check("F6i browser private host refused, no fetch attempted",
      res.get("ok") is False and "127.0.0.1" in str(res.get("error")), res.get("error"))

# ---- Q1/Q2 WebUI statics ----------------------------------------------------
HTML = _read("webui", "index.html")
check("Q1 tools.changed listener re-renders the tools panel",
      'addEventListener("tools.changed"' in HTML and "_approvalMode" in HTML)
Y = _read("config", "tools.yaml")
check("Q1b shipped browser default is enabled", "enabled: true" in Y.split("browser:")[1].split("\n\n")[0]
      if "browser:" in Y else False)
check("Q2 chat.done auto-rebuilds this session (reloadChat)",
      'chat.done' in HTML and "reloadChat()" in HTML
      and "d.session === sessionId) reloadChat()" in HTML)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
