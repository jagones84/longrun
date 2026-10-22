#!/usr/bin/env python3
"""v272 — context accounting that ADDS UP + only real files are openable (JAG-272).

  * `context_items` attributes the SYSTEM PROMPT too (system/tools/rules/skills/
    memory/plan) plus an explicit 'overhead' bucket, so sum(tokens) == used_tokens
    and the UI breakdown sums to the context total.
  * file items are kept ONLY when the path really exists (relatives resolved against
    the workspace/repo) — a text mention like "/battery.sh" was a dead click.

Deterministic, no live server, no network. Run: python3 tests/v272_context_accounting.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v272-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "DB"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.model import prompt as P  # noqa: E402
from longrun.core import server as S  # noqa: E402
from longrun.tools import registry  # noqa: E402

registry._external_tools = lambda: {}

os.makedirs(S.SESSIONS_DIR, exist_ok=True)
os.makedirs(os.environ["LONGRUN_CONFIG_DIR"], exist_ok=True)
with open(os.path.join(os.environ["LONGRUN_CONFIG_DIR"], "Global_rules.md"), "w",
          encoding="utf-8") as f:
    f.write("# Rules\nPlan before act.\n")

REAL = os.path.join(TMP, "real_note.md")
with open(REAL, "w", encoding="utf-8") as f:
    f.write("a real file\n")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def obs(tool, body):
    return "[harness] Observation for tool %s:\n[%s] exit=0\n%s" % (tool, tool, body)


sid = "a1"
S.save_session({"id": sid, "title": sid, "messages": [
    {"role": "user", "content": "read %s and also look at /no/such/missing_thing.py" % REAL},
    {"role": "assistant",
     "content": '{"action":"tool","tool":"fs.read","args":{"path":"%s"}}' % REAL},
    {"role": "user", "content": obs("fs.read", "path: %s\n" % REAL + "B" * 400)},
    {"role": "assistant",
     "content": '{"action":"tool","tool":"shell","args":{"command":"ls"}}'},
    {"role": "user", "content": obs("shell", "stdout: " + "A" * 400)},
    {"role": "assistant", "content": "Done."},
]})

r = S.context_items(sid)
tok = r["tokens"]
used = r["used_tokens"]
check("session available", r["available"] is True)

# --- P1: the breakdown sums to the measured total ---------------------------
check("tokens sum equals tokens_total",
      sum(tok.values()) == r["tokens_total"], "%s vs %s" % (sum(tok.values()), r["tokens_total"]))
check("tokens_total equals the measured used_tokens",
      r["tokens_total"] == used, "total=%s used=%s" % (r["tokens_total"], used))
check("the breakdown list sums to the same total",
      sum(b["tokens"] for b in r["breakdown"]) == r["tokens_total"],
      str([(b["label"], b["tokens"]) for b in r["breakdown"]])[:200])
check("the system prompt is attributed (system bucket > 0)", tok.get("system", 0) > 0, str(tok))
check("the tool schemas are attributed (tools bucket > 0)", tok.get("tools", 0) > 0, str(tok))
check("shell output -> other", tok.get("other", 0) > 0, str(tok))
check("fs.read output -> files", tok.get("files", 0) > 0, str(tok))

# --- P3: only REAL files are listed / openable ------------------------------
paths = [x.get("path") for x in r["categories"]["files"]]
check("a real file is kept (openable)", REAL in paths, str(paths))
check("a non-existent path is dropped (no dead click)",
      not any("missing_thing" in (p or "") for p in paths), str(paths))
check("every listed file exists on disk",
      all(p and os.path.isfile(p) for p in paths), str(paths))

# --- section_texts covers every section -------------------------------------
secs = P.section_texts(sess={"id": "a2"}, ws=None, tool_ctx="TOOLS")
ids = {s["id"] for s in P.SECTIONS}
check("section_texts returns every section id", ids.issubset(set(secs.keys())),
      str(sorted(set(secs.keys()) ^ ids)))
check("render_sections still equals the joined non-empty sections",
      P.render_sections(sess={"id": "a2"}, ws=None, tool_ctx="TOOLS").count("Longrun") >= 1)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
