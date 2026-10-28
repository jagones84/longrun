#!/usr/bin/env python3
"""v682 — H2-2 behavioural contrast: a deterministic diff between two runs.

Harness²'s Probe produces "a behavioral contrast … rather than verify task
correctness" (`papers/harness2/harness2_2610.14224.txt:285-290`), and its Composer
ties every decision to "a concrete observation rather than a presumed score gain"
(`:291-297`). Without a mechanical diff, adopted edits are vibes.

The rules pinned here are deliberately conservative:
  - a NEW error class with no fix is a regression, whatever else improved;
  - a LOST deliverable with no fix is a regression;
  - `improved` requires a fixed error class, no new class, and no lost deliverable;
  - `unchanged` requires no error delta, no deliverable delta and the same tools;
  - everything else is `mixed` — never a silent "improved".
More steps never mean "improved": the paper's own table shows score moving the
other way (`harness2_2610.14224.txt:443-478`, the `#Steps` columns).

No model, no network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v682-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "DATA_DIR", "HARNESS_DIR", "RUNS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_HOOKS"] = os.path.join(TMP, "hooks.yaml")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import contrast as C  # noqa: E402

results = []


def check(name, ok, detail=""):
    """Record one assertion (repo convention)."""
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def rec(steps, files=(), deliverables=(), prompt=None, skills="s1", hooks="h1"):
    """A minimal record shaped like `harness.record.build` output."""
    return {
        "schema": 1, "run_id": "r", "session_id": "s", "goal": "g", "ts": 0.0,
        "model": "m", "workspace": "/ws",
        "harness": {"revision": "rev", "prompt": prompt,
                    "skills": {"count": 1, "sha256": skills},
                    "hooks": {"count": 1, "sha256": hooks},
                    "config": {}, "overlay": None},
        "budget": {"steps": len(steps), "seconds": 1.0, "tokens": 100},
        "steps": steps,
        "files_touched": list(files),
        "deliverables": [{"path": p, "bytes": 1, "sha256": h} for p, h in deliverables],
    }


def step(tool, ok=True, err="", ts=1.0):
    """One step entry (only the fields the contrast reads)."""
    return {"n": 1, "tool": tool, "ok": ok, "error": err, "exit_code": 0 if ok else 1,
            "ts": ts, "node": None, "backend": "", "args_keys": [], "args_len": 2,
            "args_digest": "d", "obs_chars": 0}


OK_STEPS = [step("fs.read"), step("fs.write"), step("shell")]
BAD_STEPS = [step("fs.read"), step("shell", ok=False, err="exit 7 connection refused"),
             step("shell", ok=False, err="exit 7 connection refused"), step("fs.write")]

# ------------------------------------------------------------- A: identity ---
same = C.diff(rec(OK_STEPS, deliverables=[("a.md", "aa")]),
              rec(OK_STEPS, deliverables=[("a.md", "aa")]))
check("A1 a record against itself is 'unchanged'", same["verdict"] == "unchanged", same["verdict"])
check("A2 identity reports zero deltas",
      same["errors"]["fixed"] == [] and same["errors"]["introduced"] == []
      and same["deliverables"]["only_base"] == [] and same["deliverables"]["only_cand"] == []
      and same["steps"]["saved"] == 0, same["steps"])

# --------------------------------------------------------------- B: fix -----
fixed = C.diff(rec(BAD_STEPS, deliverables=[("a.md", "aa")]),
               rec(OK_STEPS, deliverables=[("a.md", "aa")]))
check("B1 fixing the only error class is 'improved'", fixed["verdict"] == "improved", fixed["verdict"])
check("B2 the fixed class is named", fixed["errors"]["fixed"] != []
      and "connection refused" in fixed["errors"]["fixed"][0], fixed["errors"])
check("B3 fewer steps are reported as a delta, not as a win",
      fixed["steps"]["saved"] == 1, fixed["steps"])

# --------------------------------------------------------- C: regression -----
regress = C.diff(rec(OK_STEPS, deliverables=[("a.md", "aa")]),
                 rec(BAD_STEPS, deliverables=[("a.md", "aa")]))
check("C1 introducing an error class is 'regressed'", regress["verdict"] == "regressed", regress["verdict"])
check("C2 the introduced class is named",
      regress["errors"]["introduced"] != [] and regress["errors"]["fixed"] == [],
      regress["errors"])

lost = C.diff(rec(OK_STEPS, deliverables=[("a.md", "aa"), ("b.md", "bb")]),
              rec(OK_STEPS, deliverables=[("a.md", "aa")]))
check("C3 losing a deliverable is 'regressed'", lost["verdict"] == "regressed", lost["verdict"])
check("C4 the lost deliverable is named", lost["deliverables"]["only_base"] == ["b.md"],
      lost["deliverables"])

# -------------------------------------------------------------- D: mixed -----
mixed = C.diff(rec(BAD_STEPS, deliverables=[("a.md", "aa")]),
               rec(OK_STEPS + [step("shell", ok=False, err="exit 2 permission denied")],
                   deliverables=[("a.md", "aa")]))
check("D1 one fix plus one new error is 'mixed', never 'improved'",
      mixed["verdict"] == "mixed", mixed["verdict"])

# ------------------------------------------------------- E: deliverables ----
changed = C.diff(rec(OK_STEPS, deliverables=[("a.md", "aa")]),
                 rec(OK_STEPS, deliverables=[("a.md", "zz")]))
check("E1 a rewritten deliverable is reported as changed",
      changed["deliverables"]["changed"] == ["a.md"], changed["deliverables"])
check("E2 a rewritten deliverable alone is not 'improved'", changed["verdict"] == "mixed",
      changed["verdict"])

# ---------------------------------------------------------- F: signatures ---
sig1 = C.diff(rec([step("shell", ok=False, err="exit 7 after 3 retries")]),
              rec([step("shell", ok=False, err="exit 7 after 9 retries")]))
check("F1 an error signature ignores the numbers inside it",
      sig1["errors"]["fixed"] == [] and sig1["errors"]["introduced"] == [],
      sig1["errors"])
sig2 = C.diff(rec([step("shell", ok=False, err="HTTP 500 from api.example.com/v1")]),
              rec([step("shell", ok=True)]))
check("F2 a different message is a different class",
      len(sig2["errors"]["fixed"]) == 1, sig2["errors"])

# ------------------------------------------------------------- G: harness ----
hd = C.diff(rec(OK_STEPS, prompt={"sha256": "p1", "size": 10}),
            rec(OK_STEPS, prompt={"sha256": "p2", "size": 20}, skills="s2"))
check("G1 changed harness components are named",
      hd["harness"]["changed"] == ["prompt", "skills"], hd["harness"])

# ------------------------------------------------------------ H: evidence ----
text = C.evidence_text(fixed, max_chars=400)
check("H1 evidence text is deterministic and bounded",
      text == C.evidence_text(fixed, max_chars=400) and 0 < len(text) <= 400, len(text))
check("H2 evidence text names the verdict", "improved" in text)
check("H3 an empty/unknown record does not raise",
      C.diff({}, {})["verdict"] == "incomparable")

# ------------------------------------------------------- I: comparability ----
other = rec(OK_STEPS, deliverables=[("a.md", "aa")])
other["goal"] = "a different task"
incomparable = C.diff(rec(OK_STEPS, deliverables=[("a.md", "aa")]), other)
check("I1 two different goals are 'incomparable', never 'regressed'",
      incomparable["verdict"] == "incomparable" and incomparable["comparable"] is False,
      incomparable["verdict"])
check("I2 the reason says the contrast is not evidence",
      "NOT evidence" in C.evidence_text(incomparable))
check("I3 the same goal stays comparable",
      same["comparable"] is True)

import shutil  # noqa: E402
shutil.rmtree(TMP, ignore_errors=True)

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
