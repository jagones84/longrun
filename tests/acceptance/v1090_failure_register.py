#!/usr/bin/env python3
"""v1090 — the failure register reads the traces the agents actually made.

Round 21 (Signals, arXiv:2611.04507). `failure_candidates` used to read only the
harness run records; measured 2026-11-18, those were 4 records against 2704 live
session cards / 155 failures in 138 sessions, so the improver ranked a few
percent of the evidence. The register now:

  A  uses ONE failure predicate for both corpora (`runtree.failed`)
  B  labels every class into a FAMILY, and every family into one fix (+ check)
  C  ranks the LIVE session cards, newest first, by reach (sessions) and volume
  D  merges both corpora into the same (tool, class) buckets and groups them
     into issues — one per (tool, family) — with a severity
  E  is reachable as `self.failures`, read-only, with an explicit `limit`

Deterministic: temp session/runs dirs, no model, no network, no server.
Run: python3 tests/acceptance/v1090_failure_register.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="sf-1090-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(_tmp, "sessions")
os.environ["LONGRUN_HARNESS_DIR"] = os.path.join(_tmp, "harness")
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)
os.makedirs(os.path.join(os.environ["LONGRUN_HARNESS_DIR"], "runs"), exist_ok=True)

sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import registry  # noqa: E402
from longrun.tools import tools as T  # noqa: E402
from longrun.util import runtree  # noqa: E402
from longrun.util import selfevolve  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


SESS = os.environ["LONGRUN_SESSIONS_DIR"]
RUNS = os.path.join(os.environ["LONGRUN_HARNESS_DIR"], "runs")


def session(sid, cards):
    with open(os.path.join(SESS, sid + ".json"), "w", encoding="utf-8") as f:
        json.dump({"id": sid, "messages": [], "tool_cards": cards}, f)


def record(name, steps):
    with open(os.path.join(RUNS, name + ".json"), "w", encoding="utf-8") as f:
        json.dump({"run_id": name, "steps": steps}, f)


# ------------------------------------------------- A: one failure predicate --
check("A1 ok=False is a failure", runtree.failed({"ok": False}) is True)
check("A2 a non-zero exit code is a failure",
      runtree.failed({"ok": True, "exit_code": 2}) is True)
check("A3 exit 0 on a good card is not a failure",
      runtree.failed({"ok": True, "exit_code": 0}) is False)
check("A4 a card with no verdict fails CLOSED (the boundary default)",
      runtree.failed({}) is True)

# ------------------------------------------------------- B: families --------
FAM = [
    ("permission denied by policy: <path>", "permission"),
    ("shell: timeout — the terminal was reset", "timeout"),
    ("missing REQUIRED argument(s) 'command'", "missing-argument"),
    ("no such file: <path>", "not-found"),
    ("Traceback (most recent call last): ...", "syntax"),
    ("no steps received — this call changed nothing", "no-change"),
    ("[shell.exec] exit=<n> ok=False", "nonzero-exit"),
    ("something nobody has seen before", "tool-error"),
]
for head, family in FAM:
    got = selfevolve.failure_family("shell.exec", head)
    check("B·%s ← %r" % (family, head[:34]), got == family, got)

for family in ("permission", "timeout", "missing-argument", "not-found",
               "syntax", "no-change", "nonzero-exit", "tool-error"):
    action, check_id = selfevolve.FAMILY_FIX[family]
    check("B·fix for %s is one imperative line" % family,
          bool(action) and action == action.strip() and len(action.split()) >= 4,
          action)
    if check_id:
        check("B·check %r for %s is a real test file" % (check_id, family),
              any(fn.startswith(check_id + "_")
                  for fn in os.listdir(os.path.join(REPO, "tests", "acceptance"))),
              check_id)

# ------------------------------------------------------ C: severity --------
check("C1 ten occurrences are an error", selfevolve._severity(10, 1) == "error")
check("C2 three sessions are an error", selfevolve._severity(1, 3) == "error")
check("C3 three occurrences are a warning", selfevolve._severity(3, 1) == "warning")
check("C4 two sessions are a warning", selfevolve._severity(1, 2) == "warning")
check("C5 one occurrence in one session is info", selfevolve._severity(1, 1) == "info")

# ------------------------------- D: the live session corpus (fixtures) ------
session("s1", [
    {"tool": "shell.exec", "ok": False, "error": "permission denied by policy: /etc/shadow"},
    {"tool": "shell.exec", "ok": False, "error": "permission denied by policy: /root/x"},
    {"tool": "shell", "ok": False,
     "error": 'Traceback (most recent call last):\n  File "<stdin>", line 1'},
    {"tool": "fs.read", "ok": True, "exit_code": 0, "error": ""},
    {"tool": "shell.exec", "ok": True, "exit_code": 2, "error": ""},
])
session("s2", [
    {"tool": "shell.exec", "ok": False, "error": "timed out after 60s"},
    {"tool": "todo.update", "ok": False,
     "error": "no steps received — this call changed nothing"},
    {"tool": "shell.exec", "ok": False,
     "error": "missing REQUIRED argument(s) 'command'"},
])
session("s3", [
    {"tool": "shell.exec", "ok": False, "error": "permission denied by policy: /tmp/a"},
    {"tool": "fs.read", "ok": False, "error": "no such file: /a"},
])

live = selfevolve.session_failures(sessions_dir=SESS)
classes = {tuple((c["tool"], c["error"])): c for c in live.get("classes") or []}
check("D1 all three sessions are scanned", live.get("sessions") == 3, live.get("sessions"))
check("D2 a successful card and an exit-0 card are not classes",
      not any(c["tool"] == "fs.read" and "no such" not in c["error"]
              for c in live.get("classes") or []),
      [c["tool"] for c in live.get("classes") or []])
perm = classes.get(("shell.exec", "permission denied by policy: <path>"))
check("D3 the same class across sessions is ONE row with its reach",
      perm and perm.get("count") == 3 and perm.get("sessions") == 2, perm)
check("D4 an exit-code-only failure is classed by its exit",
      any(c["tool"] == "shell.exec" and "exit=<n>" in c["error"]
          for c in live.get("classes") or []),
      [c["error"] for c in live.get("classes") or []])
check("D5 the ranking is by volume, descending",
      [c["count"] for c in live.get("classes") or []]
      == sorted([c["count"] for c in live.get("classes") or []], reverse=True),
      [c["count"] for c in live.get("classes") or []])
check("D6 every row keeps at most two samples",
      all(len(c.get("samples") or []) <= 2 for c in live.get("classes") or []), "")
check("D7 a missing sessions dir is an empty register, not a raise",
      selfevolve.session_failures(sessions_dir=os.path.join(_tmp, "nope"))
      .get("classes") == [], "")

# ------------------------- E: both corpora, one grouping, issues -----------
record("r1", [
    {"tool": "shell.exec", "ok": False, "error": "permission denied by policy: /etc/shadow"},
    {"tool": "shell.exec", "ok": False, "error": "SIGKILL"},
    {"tool": "fs.read", "ok": True, "error": ""},
])

merged = selfevolve.failure_candidates(limit=50, include_sessions=True)
mrows = {tuple((r["tool"], r["error"])): r for r in merged.get("classes") or []}
row = mrows.get(("shell.exec", "permission denied by policy: <path>")) or {}
check("E1 the same class from both corpora is one row",
      row.get("count") == 4 and row.get("runs") == 1 and row.get("sessions") == 2,
      row)
check("E2 its label says both sources", row.get("source") == "both", row.get("source"))
check("E3 a runs-only class says runs", (mrows.get(("shell.exec", "SIGKILL")) or {})
      .get("source") == "runs", mrows.get(("shell.exec", "SIGKILL")))
check("E4 the register counts the corpora it read",
      merged.get("runs") == 1 and merged.get("sessions") == 3,
      (merged.get("runs"), merged.get("sessions")))
check("E5 every class carries family, severity, action and a stable id",
      all(r.get("family") and r.get("severity") and r.get("action")
          and str(r.get("id") or "").startswith("fail-")
          for r in merged.get("classes") or []),
      [r.get("id") for r in merged.get("classes") or []])
issues = merged.get("issues") or []
by_key = {(i["tool"], i["family"]): i for i in issues}
check("E6 classes are grouped into one issue per (tool, family)",
      (by_key.get(("shell.exec", "permission")) or {}).get("count") == 4,
      by_key.get(("shell.exec", "permission")))
check("E7 an issue names the classes that support it",
      len((by_key.get(("shell.exec", "permission")) or {}).get("classes") or []) == 1,
      by_key.get(("shell.exec", "permission")))
check("E8 the default call does NOT read the operator's store",
      selfevolve.failure_candidates(limit=5).get("sessions") == 0, "")
check("E9 limit=0 falls back to the default, never a crash",
      len(selfevolve.failure_candidates(limit=0).get("classes") or []) >= 1, "")

_order = selfevolve._issues_from([
    {"tool": "a", "family": "tool-error", "count": 2, "sessions": 1, "runs": 0,
     "source": "runs", "error": "x"},
    {"tool": "b", "family": "timeout", "count": 12, "sessions": 1, "runs": 0,
     "source": "sessions", "error": "y"},
    {"tool": "c", "family": "not-found", "count": 3, "sessions": 1, "runs": 0,
     "source": "sessions", "error": "z"},
])
check("E10 issues are sorted severity first, then volume",
      [i["tool"] for i in _order] == ["b", "c", "a"], [i["tool"] for i in _order])

# ---------------------------------------------------- F: the surface --------
_enum = set(((registry.TOOL_SCHEMAS.get("self") or {})
             .get("properties", {}).get("action", {}) or {}).get("enum", []))
check("F1 the `self` schema documents action=failures", "failures" in _enum,
      sorted(_enum))
check("F2 the sub-tool field map names the fields it reads (round 28 added `since`)",
      registry._SUBTOOL_FIELDS.get("self", {}).get("failures") == ["limit", "since"],
      registry._SUBTOOL_FIELDS.get("self", {}).get("failures"))
check("F3 it has guidance",
      bool(registry._SUBTOOL_GUIDANCE.get("self.failures")), "")
check("F4 it is read-only for a plan turn",
      "self.failures" in registry.PLAN_READ_ONLY_TOOLS, "")

res = T.execute("self", {"action": "failures", "limit": 3})
payload = res.get("failures") or {}
check("F5 the tool returns the register", res.get("action") == "failures"
      and isinstance(payload.get("issues"), list) and payload.get("sessions") == 3,
      (res.get("action"), payload.get("sessions")))
check("F6 the limit bounds the issues",
      len(payload.get("issues") or []) <= 3, len(payload.get("issues") or []))
# Round 44: the answer ends with its own check coverage, so the line count is
# issues + 1; the footer is not a failure row and must not look like one.
_lines = res.get("failure_lines") or []
check("F7 every reported line is one sentence with its fix, plus the coverage footer",
      len(_lines) == len(payload.get("issues") or []) + 1
      and all(" — " in ln and "session(s): " in ln for ln in _lines[:-1])
      and _lines[-1].startswith("(checks: "), _lines)
check("F8 the unknown-action hint names the new action",
      "failures" in (T.execute("self", {"action": "nope"}).get("error") or ""), "")

print("\n---\nv1090: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
