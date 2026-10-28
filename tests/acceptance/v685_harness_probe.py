#!/usr/bin/env python3
"""v685 — H2-5 probe: same task, candidate harness, isolated and gated.

The probe is the only part of this lot that WRITES, so this test is mostly about
what it refuses:
  A  the copy is guarded (VCS/dependency trees skipped, escaping symlink skipped,
     oversized tree refused and the partial copy removed)
  B  staging writes only inside the probe stage, and refuses the kinds the agent
     loop cannot honour (prompt.tool_guidance need a merge the loop does not have)
  C  disabled by default: no copy, no spawn
  D  too many candidates / a tiny token budget refuse before anything is copied
  E  with an injected runner, a probe yields a record + a contrast and the
     operator's workspace is byte-identical afterwards
  F  a failed runner is reported, not swallowed

No model, no network, no docker.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v685-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "DATA_DIR", "HARNESS_DIR", "RUNS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_HOOKS"] = os.path.join(TMP, "hooks.yaml")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import probe as P  # noqa: E402

results = []


def check(name, ok, detail=""):
    """Record one assertion (repo convention)."""
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


WS = os.path.join(TMP, "ws")
os.makedirs(os.path.join(WS, "src"), exist_ok=True)
os.makedirs(os.path.join(WS, ".git"), exist_ok=True)
with open(os.path.join(WS, "src", "a.txt"), "w", encoding="utf-8") as f:
    f.write("keep me\n")
with open(os.path.join(WS, ".git", "HEAD"), "w", encoding="utf-8") as f:
    f.write("ref\n")
OUTSIDE = os.path.join(TMP, "outside.txt")
with open(OUTSIDE, "w", encoding="utf-8") as f:
    f.write("secret\n")
os.symlink(OUTSIDE, os.path.join(WS, "escape.txt"))

BASE = {
    "goal": "Reconcile schedule and budget",
    "model": "m", "workspace": WS, "harness": {}, "ts": 0.0,
    "budget": {"steps": 2, "seconds": 1.0, "tokens": 10},
    "steps": [
        {"n": 1, "tool": "fs.read", "ok": True, "error": "", "ts": 1.0},
        {"n": 2, "tool": "shell", "ok": False, "error": "exit 7 connection refused", "ts": 2.0},
    ],
    "files_touched": [], "deliverables": [],
}
CAND = {"kind": "skill", "name": "reconcile", "content": "When reconciling, inventory inputs.\n"}
ON = {"enabled": True, "max_candidates": 2, "max_seconds": 5, "max_steps": 3,
      "copy_max_mb": 8, "keep": False}


def tree_digest(path):
    """sha256 over every file path + content in a tree (isolation proof)."""
    h = hashlib.sha256()
    for base, _dirs, names in os.walk(path):
        for name in sorted(names):
            full = os.path.join(base, name)
            h.update(os.path.relpath(full, path).encode())
            try:
                with open(full, "rb") as f:
                    h.update(f.read())
            except OSError:
                h.update(b"<unreadable>")
    return h.hexdigest()


# ------------------------------------------------------------- A: the copy ---
dst = os.path.join(TMP, "copy1")
got = P.guarded_copy(WS, dst, max_mb=8)
check("A1 the copy keeps the real file", got["ok"] and os.path.isfile(os.path.join(dst, "src", "a.txt")))
check("A2 VCS internals are not copied", not os.path.exists(os.path.join(dst, ".git")))
check("A3 a symlink that leaves the root is skipped, not followed",
      "escape.txt" in got["skipped"] and not os.path.exists(os.path.join(dst, "escape.txt")),
      got["skipped"])
big = os.path.join(TMP, "copy2")
refused = P.guarded_copy(WS, big, max_mb=0)
check("A4 an oversized tree is refused and the partial copy removed",
      refused["ok"] is False and not os.path.exists(big), refused.get("reason"))

# ------------------------------------------------------------- B: staging ----
stage_dir = os.path.join(TMP, "stage")
ok_skill = P.stage("skill", CAND["name"], CAND["content"], stage_dir)
check("B1 a skill stages under skills/<category>/<name>/SKILL.md",
      ok_skill["ok"] and ok_skill["target"].endswith(os.path.join("reconcile", "SKILL.md")),
      ok_skill)
ok_guard = P.stage("guardrail", "g", "Inventory ALL inputs first.\n", stage_dir)
check("B2 a guardrail stages as Project_rules.md",
      ok_guard["ok"] and ok_guard["target"].endswith("Project_rules.md"))
for kind in ("prompt", "tool_guidance", "code"):
    bad = P.stage(kind, "x", "text", stage_dir)
    check("B3 %s is refused with a reason" % kind, bad["ok"] is False and bad["reason"], bad["reason"])
check("B4 staging wrote nothing inside the operator's workspace",
      not os.path.exists(os.path.join(WS, "skills")))

# ---------------------------------------------------------- C: off by default
calls = []


def fake_runner(_plan, _timeout):
    calls.append(1)
    return {"goal": BASE["goal"], "created": 1.0, "model": "m",
            "actions": [{"tool": "fs.read", "args": {"path": "a"}, "observation": "ok: yes"}]}, ""


off = P.run(BASE, [CAND], runner=fake_runner)
check("C1 disabled by default: skipped, no spawn", off["status"] == "skipped" and not calls, off)
check("C2 no probe directory was created", not os.path.isdir(P.root()))

# --------------------------------------------------------------- D: the gates
too_many = P.run(BASE, [CAND, CAND, CAND], runner=fake_runner, c=ON)
check("D1 more candidates than the cap is refused", too_many["status"] == "refused", too_many)
broke = P.run(BASE, [CAND], runner=fake_runner, c=ON, budget={"tokens_left": 10})
check("D2 a token budget under the floor is refused", broke["status"] == "refused", broke)
check("D3 neither refusal copied or spawned", not calls and not os.path.isdir(P.root()))

# ------------------------------------------------------------- E: the probe --
before = tree_digest(WS)
ran = P.run(BASE, [CAND], runner=fake_runner, c=ON)
check("E1 an enabled probe runs and records", ran["status"] == "ran"
      and len(ran["record"]["steps"]) == 1, ran.get("status"))
check("E2 the probe record carries the SAME goal (comparable)",
      ran["record"]["goal"] == BASE["goal"] and ran["contrast"]["comparable"] is True,
      ran["contrast"].get("verdict"))
check("E3 the contrast names the fixed error class",
      ran["contrast"]["errors"]["fixed"] == ["exit # connection refused"]
      and ran["contrast"]["verdict"] == "improved", ran["contrast"]["errors"])
check("E4 the operator's workspace is byte-identical afterwards", tree_digest(WS) == before)
check("E5 the scratch copy is removed when keep=false",
      not os.path.isdir(os.path.join(P.root(), ran["probe_id"])))

# --------------------------------------------------------- F: a failed run ---
def dead_runner(_plan, _timeout):
    return None, "runner exploded"


failed = P.run(BASE, [CAND], runner=dead_runner, c=ON)
check("F1 a failed runner is reported, not swallowed",
      failed["status"] == "failed" and "exploded" in failed["reason"], failed)

# ---------------------------------------------------- G: the one env switch ---
os.environ["LONGRUN_HARNESS_ENABLED"] = "1"
os.environ["LONGRUN_HARNESS_MAX_CANDIDATES"] = "1"
envc = P.cfg()
check("G1 LONGRUN_HARNESS_ENABLED=1 is the only switch an operator needs",
      envc["enabled"] is True and envc["max_candidates"] == 1, envc)
del os.environ["LONGRUN_HARNESS_ENABLED"]
del os.environ["LONGRUN_HARNESS_MAX_CANDIDATES"]
check("G2 unset means disabled (no accidental spend)",
      P.cfg()["enabled"] is False)
check("G3 a bad env value is ignored, not fatal",
      P.cfg(override=None)["max_steps"] == P.DEFAULTS["max_steps"])

shutil.rmtree(TMP, ignore_errors=True)

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
