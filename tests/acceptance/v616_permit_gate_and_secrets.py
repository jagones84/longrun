#!/usr/bin/env python3
"""v616 — the permit gate is ONE truth and secrets never reach the model.

Operator proof: session b7329cccf94c ("Head of Longrun Testing") had NO
Teamorg grant, so job.get rightly answered 126 — while "FULL = anything
goes, anywhere" was written in the Tool panel. And the same agent then
lifted LONGRUN_TOKEN from the repo .env via shell and curled the HTTP API
around the gate. Three fixes, each pinned:

  A  ONE gate: registry.classify() delegates verdict+reason to
     longrun_agent.check_dual_permission (the execute path's function).
     No second inline copy of the denial to drift.
  B  ONE choke point: tools.execute() scrubs operator secret VALUES from
     every model-bound result (shell/fs/python/…). Names stay, values go.
  C  Honest copy: FULL names its three locks; exclusive rows show
     "grant still required", never "FULL => auto".
  D  The system-prompt "delta" stays display-only: the model always gets
     the full prompt; only the chat reprint is deduped.

Deterministic: temp dirs, probe env names, no server, no model, no network.
Run: python3 tests/acceptance/v616_permit_gate_and_secrets.py
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="sf-v616-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "ROLES_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_JOBS_FILE"] = os.path.join(TMP, "jobs.json")
os.environ["LONGRUN_TOKEN_V616_PROBE"] = "v616-super-secret-98765"
os.environ["LONGRUN_TOKEN_V616_SHORT"] = "abc"
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry as REG  # noqa: E402
from longrun.tools import tools as TOOLS  # noqa: E402
from longrun.agent import longrun_agent as LRA  # noqa: E402
from longrun.memory import stores as STORES  # noqa: E402


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


HTML = _read("webui", "index.html")
AGENT_SRC = _read("src", "longrun", "agent", "agent.py")
REG_SRC = _read("src", "longrun", "tools", "registry.py")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


SID = "v616-gate-probe"
STORES.get_or_create_session(SID)

# ---------------- A: one gate, one message ----------------------
_d, _r = REG.classify("job.get", {"run_id": SID})
_ok, _why = LRA.check_dual_permission("job.get", SID)
check("A1 classify and check_dual_permission deny identically (one truth)",
      _d == "denied" and _r == _why and "dual-permission gate" in _why, _r)
check("A2 no second inline copy of the denial survives in the registry",
      "requires longrunAgent " not in REG_SRC
      and "system session or allow_longrun_agent grant)" not in REG_SRC
      and "check_dual_permission(tool, sess_ref)" in REG_SRC)
LRA.set_session_access(SID, True)
_d2, _r2 = REG.classify("job.get", {"run_id": SID})
check("A3 the Teamorg grant opens the gate on BOTH paths",
      LRA.session_has_access(SID) is True
      and LRA.check_dual_permission("job.get", SID)[0] is True
      and "dual-permission" not in str(_r2), (_d2, _r2))
LRA.set_session_access(SID, False)

# ---------------- B: secrets never reach the model ----------------------
PROBE = "v616-super-secret-98765"
check("B1 probe secret is collected, short values are not",
      PROBE in TOOLS._secret_values() and "abc" not in TOOLS._secret_values())
dirty = {"ok": True, "stdout": "grep found LONGRUN_TOKEN_V616_PROBE=" + PROBE + " here",
         "nested": {"content": "again " + PROBE}, "args": {"x": "clean"}}
clean = TOOLS._scrub_result_secrets(dirty)
check("B2 values redacted in stdout AND nested content",
      PROBE not in str(clean) and clean["stdout"].count("[redacted-secret]") == 1
      and "[redacted-secret]" in clean["nested"]["content"], clean)
check("B3 names survive (presence stays visible), keys untouched",
      "LONGRUN_TOKEN_V616_PROBE=" in clean["stdout"]
      and set(clean.keys()) == {"ok", "stdout", "nested", "args"})
echoed = TOOLS.execute("no.such.tool.v616", {"x": PROBE})
check("B4 execute() scrubs even echoed args on the error path",
      PROBE not in str(echoed) and echoed["args"]["x"] == "[redacted-secret]"
      and echoed["exit_code"] == 127, echoed.get("exit_code"))


class _MagicList(list):
    def __contains__(self, key):
        return super().__contains__(key) or super().__contains__(key + ".run")


_mag = TOOLS._scrub_result_secrets({"tools": _MagicList(["echo_plus.run"])})
check("B5 scrub preserves container types with magic membership (v500-C)",
      isinstance(_mag["tools"], _MagicList) and "echo_plus" in _mag["tools"])

# ---------------- C: honest FULL copy ----------------------
check("C1 FULL no longer claims anything-goes",
      "anything goes, anywhere" not in HTML
      and "Three things stay locked even on FULL" in HTML
      and "per-session Teamorg grant" in HTML)
check("C2 exclusive rows say grant-required, never FULL-auto",
      "grant still required" in HTML
      and 'const isExcl = String(t.origin || "") === "exclusive"' in HTML)

# ---------------- D: system-delta is display-only ----------------------
check("D1 the prompt still goes to the model every turn (dedup is display)",
      "display rule, not a context change" in AGENT_SRC
      and 'inject_kind="system-delta"' in AGENT_SRC
      and "the model always receives the current prompt" in AGENT_SRC)

print("---")
ok = sum(results)
print("\nv616: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
