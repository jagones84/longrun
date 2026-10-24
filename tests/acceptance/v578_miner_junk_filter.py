#!/usr/bin/env python3
"""v578 — miner junk filter + flood cap + self-maintenance sweep.

The `improve.mine` tool flooded the chat with 191 proposals like
shell.exec-shell.exec-shell.exec: single-tool repeats are loops, not skills.
Fix: mine() skips single-tool patterns, scan() skips existing drafts and caps
at 10 NEW per run, prune_junk() deletes the junk backlog.

Deterministic, no live model, no network.
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v578-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "DB"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR"):
    os.makedirs(os.environ["LONGRUN_" + _k], exist_ok=True)
os.environ["LONGRUN_REQUIRE_HELDOUT"] = "0"
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.util import selfevolve as E  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


C = {"min_len": 2, "min_count": 3, "max_len": 6}

# 1) single-tool repeats are junk: never mined.
junk = E.mine([["shell.exec"] * 4] * 5, dict(C))
check("1a single-tool repeat is not mined", junk == [], repr(junk[:2]))

junk2 = E.mine([["shell.exec", "shell.exec", "fs.read"]] * 4, dict(C))
check("1b no mined pattern contains a consecutive dupe",
      all(not any(a == b for a, b in zip(m["pattern"], m["pattern"][1:]))
          for m in junk2),
      repr(junk2[:2]))

alt = E.mine([["shell.exec", "fs.read", "shell.exec", "fs.edit"]] * 3, dict(C))
check("1c non-consecutive multi-tool use still mines",
      any(len(set(m["pattern"])) >= 2 for m in alt), repr(alt[:2]))

# 2) real multi-tool repeats still mined.
SEQ = ["fs.read", "fs.edit"]
good = E.mine([[SEQ[0], SEQ[1], "shell.exec"]] * 3, dict(C))
check("2a multi-tool pattern is mined",
      any("fs.read" in m["pattern"] and "fs.edit" in m["pattern"] for m in good),
      repr(good[:2]))

# 3) scan skips existing drafts + caps at 10 NEW.
out = os.path.join(TMP, "props")
os.makedirs(out, exist_ok=True)
seqs = []
for i in range(15):
    seqs += [[("tool.a%d" % i), ("tool.b%d" % i), "shell.exec"]] * 3
first = E.scan(seqs, out, dict(C))
check("3a scan caps at 10 NEW drafts", len(first) == 10, str(len(first)))
second = E.scan(seqs, out, dict(C))
check("3b second scan drafts only the remainder (no re-flood)",
      len(second) == 5 and not (set(first) & set(second)), "%d" % len(second))
third = E.scan(seqs, out, dict(C))
check("3c third scan emits nothing new", third == [], str(len(third)))

# 4) prune_junk removes the legacy junk backlog.
jd = os.path.join(out, "shell.exec-shell.exec-shell.exec")
os.makedirs(jd, exist_ok=True)
with open(os.path.join(jd, "proposal.json"), "w", encoding="utf-8") as f:
    json.dump({"pattern": ["shell.exec"] * 4, "status": "proposed"}, f)
rep = E.prune_junk(out)
check("4a prune_junk removes junk dir",
      "shell.exec-shell.exec-shell.exec" in (rep.get("removed") or []),
      repr(rep.get("removed")))
check("4b junk dir is gone", not os.path.exists(jd))
check("4c real drafts survive the sweep",
      os.path.isdir(os.path.join(out, first[0].split(os.sep)[-1])) if first else False)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
