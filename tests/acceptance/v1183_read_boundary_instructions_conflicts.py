#!/usr/bin/env python3
"""v1183 — memory read boundary, instruction adherence, conflict surfacing (round 114).

Sources:
  * arXiv:2611.19264 "Read Boundaries in Agent Memory" — several reads must share
    one epoch; a mismatch refuses service; a retry recovers via full rebuild.
  * arXiv:2611.13709 "Do They Do as They Are Told?" — explicit context-file
    instructions are measurable per directive; adherence splits sharply.
  * arXiv:2611.22461 "Surfacing Disagreement Beats Resolving It" — keep
    contradictions and pass the ranked conflict set; a cap that hides them is a
    measured harness bug.

Deterministic: plain data in, dicts out; no model, no network, no server.

Run: python3 tests/acceptance/v1183_read_boundary_instructions_conflicts.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1183-")
for _key in ("CONFIG_DIR", "SESSIONS_DIR", "GRAPH_DIR", "EDITS_DIR",
             "RUNS_DIR", "DATA_DIR", "THREADS_DIR", "COSTS_DIR", "MEMORY_DIR"):
    os.environ["LONGRUN_" + _key] = os.path.join(TMP, _key)
    os.makedirs(os.environ["LONGRUN_" + _key], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import read_boundary as RB        # noqa: E402
from longrun.memory import conflict_surface as CS    # noqa: E402
from longrun.harness import instruction_audit as IA   # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


# ---- 1. memory read boundary -----------------------------------------------
ok = RB.validate([{"key": "a", "epoch": 7}, {"key": "b", "epoch": 7}])
check("reads from one epoch are coherent evidence",
      ok["consistent"] is True and ok["epoch"] == 7 and ok["action"] == "serve", ok)
mixed = RB.validate([{"key": "a", "epoch": 7}, {"key": "b", "epoch": 8}])
check("reads from two epochs are refused, never mixed",
      mixed["consistent"] is False and mixed["reason"] == "mixed-epochs"
      and mixed["action"] == "retry", mixed)
stale = RB.validate([{"key": "a", "epoch": 6}], expected_epoch=7)
check("a read older than the expected epoch is stale",
      stale["reason"] == "stale-epoch" and stale["expected"] == 7, stale)
check("no reads is a retry, not a pass",
      RB.validate([])["reason"] == "no-reads" and RB.validate([])["action"] == "retry")

state = {"n": 0}


def flaky():
    state["n"] += 1
    epoch = 1 if state["n"] == 1 else 2
    return [{"key": "a", "epoch": epoch}, {"key": "b", "epoch": 2}]


first = RB.recall(flaky, attempts=2)
check("optimistic validation retries and serves a coherent second read",
      first["service"] == "served" and first["attempt"] == 2, first)
always = RB.recall(lambda: [{"key": "a", "epoch": 1}, {"key": "b", "epoch": 2}], attempts=2)
check("a persistent mismatch refuses service after the bounded retry",
      always["service"] == "refused" and always["reason"] == "mixed-epochs", always)
check("a failing reader is a read error, not evidence",
      RB.recall(lambda: (_ for _ in ()).throw(RuntimeError("boom")))["reason"]
      == "read-error")

rebuilt = {"done": False}


def reader_after_rebuild():
    return [{"key": "a", "epoch": 3}, {"key": "b", "epoch": 3}] if rebuilt["done"] \
        else [{"key": "a", "epoch": 1}, {"key": "b", "epoch": 2}]


res = RB.recall_with_rebuild(reader_after_rebuild,
                             lambda: rebuilt.update(done=True), attempts=1)
check("the full-rebuild fallback restores service",
      res["service"] == "served" and res.get("rebuilt") is True
      and res.get("first_refusal") == "mixed-epochs", res)

# ---- 2. instruction adherence ----------------------------------------------
TEXT = ("Never edit `data/events.db` by hand.\n"
        "Always run `pytest -q` before committing.\n"
        "Be careful with the configuration.\n"
        "Only touch `src/` when a test covers it.\n")
dirs = IA.directives(TEXT)
check("three explicit directives are extracted, the vague line is not",
      len(dirs) == 3 and [d["kind"] for d in dirs] == ["never", "always", "only"], dirs)
check("a directive carries its concrete object and line",
      dirs[0]["object"] == "data/events.db" and dirs[0]["line"] == 1, dirs[0])

followed = IA.audit(TEXT, [
    {"tool": "fs.read", "args": {"path": "data/events.db"}, "ok": True},
    {"tool": "shell.exec", "args": {"command": "pytest -q"}, "ok": True, "exit_code": 0},
    {"tool": "fs.write", "args": {"path": "src/app.py"}, "ok": True},
])
check("a read of the forbidden path does not violate the never-directive",
      followed["directives"][0]["state"] == "followed", followed["directives"][0])
check("the required check ran successfully", followed["directives"][1]["state"] == "followed")
check("a clean run reports no violations", followed["verdict"] == "clean", followed["counts"])

violated = IA.audit(TEXT, [
    {"tool": "fs.write", "args": {"path": "data/events.db"}, "ok": True},
    {"tool": "fs.write", "args": {"path": "src/app.py"}, "ok": True},
])
check("writing the forbidden path is a violation",
      violated["directives"][0]["state"] == "violated", violated["directives"][0])
check("a required step missing while writes happened is a violation",
      violated["directives"][1]["state"] == "violated", violated["directives"][1])
check("the verdict names violations", violated["verdict"] == "violations", violated["counts"])
check("a shell edit counts as a write",
      IA.audit("Never touch `data/events.db`.",
               [{"tool": "shell.exec", "args": {"command": "sed -i s/a/b/ data/events.db"}}]
               )["directives"][0]["state"] == "violated")
empty = IA.audit(TEXT, [])
check("no relevant cards leave the directives unobservable",
      empty["counts"]["not_observable"] == 3 and empty["verdict"] == "uneven", empty["counts"])

placement = IA.directives("Temporary scripts go to `.agent/trash/`. "
                          "Never put them in `scripts/`.")
check("polarity comes from the clause that names the object, not the line",
      len(placement) == 1 and placement[0]["kind"] == "never"
      and placement[0]["object"] == "scripts/", placement)
inside = IA.audit("Only touch `src/`.", [{"tool": "fs.write", "args": {"path": "src/a.py"}}])
check("an only-directive is not guessed from writes alone",
      inside["directives"][0]["state"] == "not-observable", inside)
outside = IA.audit("Only touch `src/`.", [{"tool": "fs.write", "args": {"path": "docs/a.md"}}])
check("a scope directive is not invented as a violation",
      outside["directives"][0]["state"] == "not-observable", outside)

# ---- 3. conflict surfacing -------------------------------------------------
CLAIMS = [
    {"subject": "service", "relation": "port", "object": "8790", "source": "config"},
    {"subject": "service", "relation": "port", "object": "8080", "source": "note-a"},
    {"subject": "service", "relation": "port", "object": "8080", "source": "note-b"},
    {"subject": "repo", "relation": "branch", "object": "Experimental-Refactor",
     "source": "git"},
]
con = CS.conflicts(CLAIMS)
check("a subject/relation with two objects is one conflict",
      len(con["conflicts"]) == 1 and con["conflicts"][0]["spread"] == 2, con)
check("values are ranked by support and keep their sources",
      [v["object"] for v in con["conflicts"][0]["values"]] == ["8080", "8790"]
      and con["conflicts"][0]["values"][0]["sources"] == ["note-a", "note-b"],
      con["conflicts"][0])
rendered = CS.render(CLAIMS)
check("the render keeps BOTH values and never picks a winner",
      "CONFLICTS" in rendered["text"] and "8790" in rendered["text"]
      and "8080" in rendered["text"], rendered["text"])
check("agreed facts are listed separately",
      "AGREED FACTS" in rendered["text"] and "Experimental-Refactor" in rendered["text"],
      rendered["text"])
check("a conflict set is not empty, so the verdict says so",
      rendered["verdict"] == "conflicts-present")
capped = CS.render(CLAIMS + [
    {"subject": "other", "relation": "mode", "object": "a", "source": "x"},
    {"subject": "other", "relation": "mode", "object": "b", "source": "y"},
], cap=1)
check("a cap reports what it omitted instead of hiding it",
      capped["omitted"] == 1 and "1 further conflict" in capped["text"], capped)
clean = CS.render([{"subject": "repo", "relation": "branch",
                    "object": "Experimental-Refactor", "source": "git"}])
check("no contradiction means a consistent render with no conflict block",
      clean["verdict"] == "consistent" and "CONFLICTS" not in clean["text"], clean)
check("claims without subject/relation/object are skipped, never invented",
      CS.conflicts([{"subject": "x"}, {"object": "y"}])["total"] == 0)

print("\n%d/%d checks passed" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
