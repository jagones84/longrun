#!/usr/bin/env python3
"""v1174 — an exported trace keeps the diagnosis and loses the identity (round 106).

Source: arXiv:2611.20389, "Where the Evidence Lives: Measuring Privacy and
Diagnosability of Exported AI-Agent Traces". The paper's executable test is a
pair: (1) a diagnostic program reads the export and must still repair/find the
fault; (2) an identifier matcher reads the same export and must not recover the
subject. It shows conventional redaction can do the opposite: strip the evidence
and leave counters that re-identify.

This test runs that pair against `core/trace_export.py`:

  A. diagnosability — a program that only sees the export finds the failed call;
  B. privacy        — session/workspace/model are execution-scoped pseudonyms,
                      counters are bucketed, the system prompt is withheld, and
                      no bearer token / key / absolute path survives;
  C. the audit profile keeps raw ids and exact counts but STILL redacts secrets;
  D. the integrity digest is stable for equal input and changes with the record.

Deterministic: pure function over a session dict; no server, no model.

Run: python3 tests/acceptance/v1174_trace_export_profiles.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import trace_export as X      # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


SESSION = {
    "id": "sess_CUSTOMER42",
    "workspace": "/home/alice/Repositories/acme-billing",
    "model": "openrouter:vendor/model-x",
    "messages": [
        {"role": "system", "content": "You are ACME's agent. Operator alice@acme.io."},
        {"role": "user", "content": "Read /home/alice/Repositories/acme-billing/customers.csv"},
        {"role": "assistant", "content": "Running the export with Bearer sk-live-ABCD1234EFGH"},
    ],
    "tool_cards": [
        {"tool": "fs.read", "ok": True, "args": "{\"path\":\"/home/alice/x.csv\"}",
         "result": "a,b\n1,2\n", "exit_code": 0},
        {"tool": "shell.exec", "ok": False, "args": "{\"command\":\"npm test\"}",
         "result": "", "error": "CommandNotFound: npm not installed", "exit_code": 127},
        {"tool": "fs.read", "ok": True, "args": "{\"path\":\"/home/alice/y.csv\"}",
         "result": "z\n", "exit_code": 0},
    ],
}

SHARE = X.build(SESSION, "share")
AUDIT = X.build(SESSION, "audit")

# ---- A. diagnosability: the repair program ----------------------------------
def diagnose(doc):
    """The program the paper says must be tested WITH the export it will read."""
    bad = [f for f in doc.get("failures") or [] if f.get("exit_code") == 127]
    if not bad:
        return None
    return bad[0].get("tool")


check("the export carries a format and a digest",
      SHARE.get("format") == "longrun-evidence/1"
      and len((SHARE.get("integrity") or {}).get("digest") or "") == 32,
      SHARE.get("integrity"))
check("a diagnostic program finds the failed call in the share export",
      diagnose(SHARE) == "shell.exec", diagnose(SHARE))
check("the error CLASS survives (that is the diagnosable part)",
      "CommandNotFound" in ((SHARE.get("failures") or [{}])[0].get("error_class") or ""),
      SHARE.get("failures"))
check("the failed card keeps its exit code and tool name",
      any(r.get("kind") == "tool" and r.get("tool") == "shell.exec"
          and r.get("exit_code") == 127 for r in SHARE["records"]))

# ---- B. privacy: the identifier matcher -------------------------------------
def identifies(doc):
    blob = str(doc)
    needles = ["sess_CUSTOMER42", "/home/alice", "acme-billing", "alice@acme.io",
               "sk-live-ABCD1234EFGH", "openrouter:vendor/model-x"]
    return [n for n in needles if n in blob]


left = identifies(SHARE)
check("the share export leaks no identifier", not left, left)
check("session/workspace/model are pseudonyms",
      SHARE["session"].startswith("e") and SHARE["workspace"].startswith("e")
      and SHARE["model"].startswith("e"),
      (SHARE["session"], SHARE["workspace"], SHARE["model"]))
check("the system prompt is withheld in share",
      any(r.get("kind") == "message" and r.get("role") == "system"
          and "withheld" in (r.get("text") or "") for r in SHARE["records"]))
buckets = {"0", "1", "2-5", "6-20", "21+"}
check("counters are bucketed, never exact",
      SHARE["summary"]["messages"] in buckets
      and SHARE["summary"]["tool_calls"] in buckets
      and SHARE["reidentification"]["exact_counters_emitted"] == 0,
      SHARE["summary"])
check("pseudonyms are consistent within one export",
      SHARE["workspace"] != SHARE["session"] != SHARE["model"]
      and SHARE["reidentification"]["pseudonyms"] == 3
      and X.build(SESSION, "share")["workspace"] == SHARE["workspace"],
      SHARE["reidentification"])

# ---- C. audit: the operator's own copy --------------------------------------
check("audit keeps the raw ids", AUDIT["session"] == "sess_CUSTOMER42")
check("audit keeps exact counters",
      AUDIT["summary"]["messages"] == 3 and AUDIT["summary"]["tool_calls"] == 3,
      AUDIT["summary"])
check("audit still redacts a bearer token and a key",
      "sk-live-ABCD1234EFGH" not in str(AUDIT)
      and "<path>" in str(AUDIT.get("records")),
      identifies(AUDIT))

# ---- D. integrity ------------------------------------------------------------
same = X.build(SESSION, "share")
check("the digest is stable for the same input",
      same["integrity"]["digest"] == SHARE["integrity"]["digest"])
changed = dict(SESSION)
changed["tool_cards"] = SESSION["tool_cards"] + [
    {"tool": "web.search", "ok": True, "args": "{}", "result": "ok", "exit_code": 0}]
check("the digest changes when the record changes",
      X.build(changed, "share")["integrity"]["digest"] != SHARE["integrity"]["digest"])

print("\n%d/%d checks passed" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
