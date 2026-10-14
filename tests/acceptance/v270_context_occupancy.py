#!/usr/bin/env python3
"""v270 — Context panel: per-category TOKEN occupation + openable paths (JAG-269).

`context_items(session)` now also returns a token attribution (how much of the
window each category occupies) plus the real budget / used / pct from the ctx
meter, and every file / rule / skill item carries a real `path` the UI opens in
the editor.

Deterministic, no live server, no network. Run: python3 tests/v270_context_occupancy.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v270-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "DB"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as S  # noqa: E402
from longrun.memory import skills as SK  # noqa: E402
from longrun.tools import registry  # noqa: E402

registry._external_tools = lambda: {}

os.makedirs(S.SESSIONS_DIR, exist_ok=True)
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
with open(os.path.join(os.environ["LONGRUN_CONFIG_DIR"], "RULES.md"), "w",
          encoding="utf-8") as f:
    f.write("# Rules\nPlan before act.\nSource driven development.\n")

REAL = os.path.join(TMP, "notes.md")     # JAG-272: only REAL files are listed
with open(REAL, "w", encoding="utf-8") as f:
    f.write("a real note\n")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


_names = [s["name"] for s in SK.list_skills()]
skill_name = _names[0] if _names else "no-such-skill"


def obs(tool, body):
    return "[harness] Observation for tool %s:\n[%s] exit=0\n%s" % (tool, tool, body)


sid = "t1"
S.save_session({"id": sid, "title": sid, "messages": [
    {"role": "user", "content": "please do the task"},
    {"role": "assistant",
     "content": '{"action":"tool","tool":"shell","args":{"command":"ls -la"}}'},
    {"role": "user", "content": obs("shell", "stdout: " + "A" * 600)},
    {"role": "assistant",
     "content": '{"action":"tool","tool":"fs.read","args":{"path":"%s"}}' % REAL},
    {"role": "user", "content": obs("fs.read", "path: %s\n" % REAL + "B" * 600)},
    {"role": "assistant",
     "content": '{"action":"tool","tool":"web","args":{"action":"fetch"}}'},
    {"role": "user", "content": obs("web", "1. Foo Bar\nhttps://example.com/a\n" + "C" * 600)},
    {"role": "assistant",
     "content": '{"action":"tool","tool":"skills","args":{"action":"read","name":"%s"}}'
                % skill_name},
    {"role": "user", "content": obs("skills", "  %s :: a skill\n" % skill_name + "D" * 600)},
    {"role": "user", "content": "[harness] Noted. Continue strictly: mark the next step 'doing'."},
    {"role": "assistant", "content": "Here is the final plain-text answer."},
]})

r = S.context_items(sid)
tok = r["tokens"]
cats = r["categories"]
check("session is available", r["available"] is True)
check("shell output -> 'other' tokens", tok["other"] > 0, str(tok))
check("fs.read output -> 'files' tokens", tok["files"] > 0, str(tok))
check("web output -> 'web' tokens", tok["web"] > 0, str(tok))
check("skills output -> 'skills' tokens", tok["skills"] > 0, str(tok))
check("harness reminder -> 'harness' tokens", tok["harness"] > 0, str(tok))
check("plain messages -> 'conversation' tokens", tok["conversation"] > 0, str(tok))
check("global RULES.md -> 'rules' tokens", tok["rules"] > 0, str(tok))
check("tokens_total is the sum of the buckets",
      r["tokens_total"] == sum(tok.values()), str(r["tokens_total"]))
check("budget/pct are present and non-negative",
      r["budget_tokens"] >= 0 and r["used_tokens"] >= 0 and r["pct"] >= 0.0,
      "budget=%s used=%s pct=%s" % (r["budget_tokens"], r["used_tokens"], r["pct"]))

check("file items carry a path (openable in the editor)",
      bool(cats["files"]) and all(x.get("path") for x in cats["files"]), str(cats["files"])[:120])
check("rule items carry a path",
      bool(cats["rules"]) and all(x.get("path") for x in cats["rules"]), str(cats["rules"])[:120])
check("other items carry a count",
      bool(cats["other"]) and all(x.get("count") is not None for x in cats["other"]),
      str(cats["other"])[:120])
if _names:
    check("a used skill resolves to its SKILL.md path",
          any(x.get("path") for x in cats["skills"]), str(cats["skills"])[:160])
else:
    check("a used skill resolves to its SKILL.md path (no skills installed: skipped)", True)

u = S.context_items("nope")
check("unknown session -> not available + zeroed tokens",
      u["available"] is False and u["tokens_total"] == 0
      and u["tokens"]["files"] == 0 and u["pct"] == 0.0, str(u))

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
