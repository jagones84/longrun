#!/usr/bin/env python3
"""v1101 — a refusal is a policy answer, never read as breakage.

Round 32 (AgentDebugX, arXiv:2607.18754 — the RECOVER axis). Round 31 measured
recovery; this round asked WHICH classes never recover. Measured 2026-11-18 over
the live store, the `recovery_rate 0.0` residue is refusals: `fs.write · gate`
("approval expired"), `sessions.read · permission` ("read refused: a session
cannot message itself"), `fs.edit · permission` (a protected nucleus), `job.get`
("not a coordinator"), `webui.inspect` ("not authorized"). Two of them were filed
as `tool-error`/`nonzero-exit` because the 80-char class head cut the word.

  A  one predicate: `is_refusal(gate|permission)`, nothing else
  B  the prefixed refusal shapes are attributed by the TAIL, and a bare
     "refused" in a schema dump still does not pull
  C  the issue carries the flag; the count cannot be read as a verdict
  D  the draft says "refusal(s)" and that recovery is not the measure
  E  the severity policy is NOT widened to permission (a deliberate deferral)

Deterministic: temp session/runs dirs, no model, no network, no server.
Run: python3 tests/acceptance/v1101_refusal_family.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1101-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(_tmp, "data")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_HARNESS_DIR"] = os.path.join(_tmp, "harness")
for _d in (os.environ["LONGRUN_CONFIG_DIR"], os.environ["LONGRUN_SESSIONS_DIR"],
           os.path.join(os.environ["LONGRUN_HARNESS_DIR"], "runs")):
    os.makedirs(_d, exist_ok=True)

sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import tools as T  # noqa: E402
from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ------------------------------------------------------- A: the predicate ----
fam = selfevolve.is_refusal
check("A1 `gate` is a refusal", fam("gate") is True, fam("gate"))
check("A2 `permission` is a refusal", fam("permission") is True, fam("permission"))
check("A3 breakage families are not", not any(fam(f) for f in
      ("timeout", "tool-error", "nonzero-exit", "missing-argument", "syntax",
       "not-found", "no-change")), "")
check("A4 an empty/None family is not a refusal (fail-closed)",
      fam(None) is False and fam("") is False, (fam(None), fam("")))
check("A5 the predicate and the exported tuple are one truth",
      tuple(selfevolve.REFUSAL_FAMILIES) == ("gate", "permission")
      and all(fam(f) for f in selfevolve.REFUSAL_FAMILIES),
      selfevolve.REFUSAL_FAMILIES)

# ------------------------------------------------ B: live refusal shapes ----
# The head is `error_class` (80 chars): `read refused` loses its last letters, so
# the word only survives in the raw text — that is the whole point of the tail.
SR_PREFIX = ("[sessions.read] exit=<n> ok=False backend=host sandboxed=False "
             "ERROR: read refus")
SR_RAW = ("[sessions.read] exit=126 ok=False backend=host sandboxed=False ERROR: "
          "read refused: a session cannot message itself through this tool "
          'result: {"permission_denied": true, "session": "05375becac58"}')
check("B1 the prefixed `read refused` is `permission`",
      selfevolve.failure_family("sessions.read", SR_PREFIX, SR_RAW) == "permission",
      selfevolve.failure_family("sessions.read", SR_PREFIX, SR_RAW))
check("B2 without the text the same head stays `nonzero-exit` (the tail did the work)",
      selfevolve.failure_family("sessions.read", SR_PREFIX) == "nonzero-exit",
      selfevolve.failure_family("sessions.read", SR_PREFIX))
WEB_HEAD = ("session 'fd98ee64e89f' is not authorized to use 'webui.inspect' — "
            "dual-permissio")
check("B3 `not authorized` is read past the wrapper",
      selfevolve.failure_family("webui.inspect", WEB_HEAD,
                                WEB_HEAD + "n gate requires the architect session")
      == "permission", selfevolve.failure_family("webui.inspect", WEB_HEAD))
JOB_HEAD = ("[job.get] exit=<n> ok=False backend=host sandboxed=False "
            "ERROR: agent A179 (Writ")
check("B4 `not a coordinator` is read past the wrapper",
      selfevolve.failure_family("job.get", JOB_HEAD,
                                JOB_HEAD + "er) is not a coordinator — it has "
                                "nobody reporting to it") == "permission",
      selfevolve.failure_family("job.get", JOB_HEAD, JOB_HEAD))
check("B5 a generic `refused` in an argument dump does NOT pull (the override is narrow)",
      selfevolve.failure_family("shell.exec", "[shell.exec] exit=<n> ok=False",
                                "Arg types: {'refused': bool, 'permission': str}")
      == "nonzero-exit",
      selfevolve.failure_family("shell.exec", "[shell.exec] exit=<n> ok=False",
                                "Arg types: {'refused': bool, 'permission': str}"))
check("B6 `approval expired` is a GATE, not an error of the tool",
      selfevolve.failure_family(
          "fs.write",
          "Action 'fs.write' NOT executed: approval expired (id 7529f41096).")
      == "gate",
      selfevolve.failure_family(
          "fs.write",
          "Action 'fs.write' NOT executed: approval expired (id 7529f41096)."))
check("B7 a plan-mode refusal stays `gate` through the wrapper (v1096 B)",
      selfevolve.failure_family(
          "shell.exec", "[shell.exec] exit=<n> ok=False",
          "plan mode: only read-only tools work") == "gate", "")

# -------------------------------------- C/D: the issue, the draft, surface ---
SESS = os.environ["LONGRUN_SESSIONS_DIR"]
GATE = "Action 'fs.write' NOT executed: approval expired (id 7529f41096)."
TIMEOUT = "timeout — the terminal was reset"


def session(sid, cards):
    with open(os.path.join(SESS, sid + ".json"), "w", encoding="utf-8") as f:
        json.dump({"id": sid, "messages": [], "tool_cards": cards}, f)


# The gate fails TWICE and a later fs.write in the same stage succeeds: recovery
# IS measured (2 of 2) — and still must not be read as "the wall was fixed".
session("s1", [
    {"tool": "fs.write", "ok": False, "error": GATE, "node": "n1"},
    {"tool": "fs.write", "ok": False, "error": GATE, "node": "n1"},
    {"tool": "fs.write", "ok": True, "exit_code": 0, "error": "", "node": "n1"},
    {"tool": "shell.exec", "ok": False, "error": TIMEOUT, "node": "n2"},
    {"tool": "shell.exec", "ok": False, "error": TIMEOUT, "node": "n2"},
])

merged = selfevolve.failure_candidates(limit=50, include_sessions=True)
iss = {(i["tool"], i["family"]): i for i in merged.get("issues") or []}
gate_i = iss.get(("fs.write", "gate")) or {}
to_i = iss.get(("shell.exec", "timeout")) or {}
check("C1 a gate issue is flagged as a refusal",
      gate_i.get("refusal") is True and gate_i.get("count") == 2, gate_i)
check("C2 a timeout issue is not", to_i.get("refusal") is False, to_i)
check("C3 the refusal keeps its honest recovery count (the reading changes, not the data)",
      gate_i.get("recovered") == 2 and gate_i.get("recovery_rate") == 1.0, gate_i)

OUT = os.path.join(_tmp, "repairs")
drafts = selfevolve.issue_drafts(OUT, limit=10, min_severity="info")
by = {w["issue"]: w for w in drafts.get("written") or []}
gate_d = by.get("fail-fs-write-gate") or {}
to_d = by.get("fail-shell-exec-timeout") or {}
g_body = (open(os.path.join(gate_d["path"], "REPAIR.md"), encoding="utf-8").read()
          if gate_d else "")
t_body = (open(os.path.join(to_d["path"], "REPAIR.md"), encoding="utf-8").read()
          if to_d else "")
check("D1 the gate draft calls them refusals, not failures",
      "refusal(s)" in g_body and "failure(s)" not in g_body, g_body[:300])
check("D2 and says recovery is not the measure for the family",
      "not the measure for this family" in g_body
      and "the wall still stands" in g_body, g_body[:600])
check("D3 the timeout draft keeps the ordinary recovery verdict",
      "failure(s)" in t_body and "**Recovered:** 0 of 2 — no later success" in t_body,
      t_body[:400])
prop = json.load(open(os.path.join(gate_d["path"], "proposal.json"),
                      encoding="utf-8")) if gate_d else {}
check("D4 proposal.json carries the flag (the reader does not re-derive it)",
      prop.get("refusal") is True, prop.get("refusal"))

res = T.execute("self", {"action": "failures", "limit": 20})
lines = res.get("failure_lines") or []
gate_line = next((ln for ln in lines if "fs.write · gate" in ln), "")
to_line = next((ln for ln in lines if "· timeout" in ln), "")
check("D5 the surface labels the refusal",
      "recovered (refusal)" in gate_line, gate_line)
check("D6 and leaves a real failure unlabelled",
      to_line and "(refusal)" not in to_line, to_line)

# ------------------------------------------------ E: the severity deferral ---
check("E1 a gate never escalates past warning",
      selfevolve.severity_for("gate", 40, 9, 30) == "warning", "")
check("E2 a permission wall still reaches `error` — widening the cap is a separate "
      "measurement, not this label",
      selfevolve.severity_for("permission", 40, 9) == "error", "")

print("\n---\nv1101: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
