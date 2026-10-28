#!/usr/bin/env python3
"""v685 — H2-5 probe: production fails closed; injected trials are gated.

The probe is the only part of this lot that WRITES, so this test is mostly about
what it refuses:
  A  the copy is guarded (VCS/dependency trees skipped, escaping symlink skipped,
     oversized tree refused and the partial copy removed)
  B  staging writes only inside the probe stage, and refuses the kinds the agent
     loop cannot honour (prompt.tool_guidance need a merge the loop does not have)
  C  disabled by default; production refuses whole-run isolation before staging
  D  too many candidates / a tiny token budget refuse before anything is copied
  E  with an injected runner, a probe yields a record + a contrast and the
     operator's workspace is byte-identical afterwards (not confinement proof)
  F  a failed runner is reported, not swallowed

No model, no network, no docker.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v685-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "DATA_HOME", "DATA_DIR", "HARNESS_DIR",
           "RUNS_DIR", "PROJECTS_DIR", "SKILLS_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
    os.makedirs(os.path.join(TMP, _k), exist_ok=True)
os.environ["LONGRUN_HOOKS"] = os.path.join(TMP, "hooks.yaml")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.harness import probe as P  # noqa: E402
from longrun.harness import record as R  # noqa: E402
from longrun.harness import runner as RUNNER  # noqa: E402
from longrun.memory import rules, skills  # noqa: E402

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
for nested in (WS, os.path.join(WS, "nested", "copy")):
    refused = P.guarded_copy(WS, nested)
    check("A5 copying into the source or its descendant is refused before creation",
          refused["ok"] is False and "inside" in refused["reason"]
          and (nested == WS or not os.path.exists(nested)))

# ------------------------------------------------------------- B: staging ----
stage_dir = os.path.join(TMP, "stage")
ok_skill = P.stage("skill", CAND["name"], CAND["content"], stage_dir)
check("B1 a skill stages under skills/<category>/<name>/SKILL.md",
      ok_skill["ok"] and ok_skill["target"].endswith(os.path.join("reconcile", "SKILL.md")),
      ok_skill)
ok_guard = P.stage("guardrail", "g", "Inventory ALL inputs first.\n", stage_dir)
check("B2 a guardrail stages under rules/Project_rules.md",
      ok_guard["ok"] and ok_guard["target"] == os.path.join("rules", "Project_rules.md")
      and ok_guard["path"] == os.path.join(stage_dir, ok_guard["target"]))
for kind in ("prompt", "tool_guidance", "code", "script"):
    bad = P.stage(kind, "x", "text", stage_dir)
    check("B3 %s is refused with a reason" % kind, bad["ok"] is False and bad["reason"], bad["reason"])
check("B4 staging wrote nothing inside the operator's workspace",
      not os.path.exists(os.path.join(WS, "skills")))
# B5: the child must see the REAL skills PLUS the candidate — a skills root holding
# only the candidate would make the contrast measure the missing skills instead.
real_skill = os.path.join(skills.SKILLS_DIR, "fixture", "existing", "SKILL.md")
os.makedirs(os.path.dirname(real_skill), exist_ok=True)
with open(real_skill, "w", encoding="utf-8") as f:
    f.write("Existing fixture skill.\n")
_plan_b = P.plan(BASE, [CAND], ON, probe_id="b5")
_root = _plan_b["env"].get("LONGRUN_SKILLS_DIR") or ""
check("B5 the probe skills root is the real tree + the candidate",
      _root and _root != os.path.join(_plan_b["stage"], "skills")
      and os.path.isfile(os.path.join(_root, os.path.relpath(
          _plan_b["staged"]["reconcile"], os.path.join(_plan_b["stage"], "skills"))))
      and open(os.path.join(_root, "fixture", "existing", "SKILL.md"),
               encoding="utf-8").read() == "Existing fixture skill.\n")
P.cleanup("b5")

# ---------------------------------------------------------- C: off by default
calls = []


def _probe_dirs():
    """The probe scratch entries that exist right now (a refusal must add none)."""
    return set(os.listdir(P.root())) if os.path.isdir(P.root()) else set()


def _probe_session():
    """A session in the REAL shape (tool_cards), so the record is the real one."""
    return {
        "id": "probe-1", "created": 1.0, "model": "m", "workspace": WS,
        "messages": [{"role": "user", "content": BASE["goal"], "ts": 1.0}],
        "tool_cards": [{"tool": "fs.read", "ok": True, "args": {"path": "a.txt"},
                        "result": "keep me", "error": "", "exit_code": 0, "ts": 2.0}],
    }


def fake_runner(_plan, _timeout):
    calls.append(1)
    rec = R.build("probe-1", session=_probe_session())
    rec["goal"] = BASE["goal"]
    return {"record": rec, "goal": BASE["goal"], "created": 1.0, "model": "m",
            "error": ""}, ""


_dirs_before_c = _probe_dirs()
off = P.run(BASE, [CAND], runner=fake_runner)
check("C1 disabled by default: skipped, no spawn", off["status"] == "skipped" and not calls, off)
check("C2 no probe directory was created", _probe_dirs() == _dirs_before_c,
      _probe_dirs())
with patch.object(P, "plan", side_effect=AssertionError("production staged")), \
        patch.object(P, "_spawn", side_effect=AssertionError("production spawned")):
    production = P.run(BASE, [CAND], c=ON)
check("C3 enabled production refuses before staging or spawning",
      production["status"] == "refused" and "whole-run" in production["reason"]
      and production["isolation"]["available"] is False
      and _probe_dirs() == _dirs_before_c)
with patch("subprocess.run", side_effect=AssertionError("host executed")):
    payload, reason = P._spawn({"cmd": ["/bin/false"], "cwd": WS, "env": {}}, 1)
check("C4 direct legacy spawn also refuses host execution",
      payload is None and "whole-run" in reason)

# --------------------------------------------------------------- D: the gates
_dirs_before_d = _probe_dirs()
too_many = P.run(BASE, [CAND, CAND, CAND], runner=fake_runner, c=ON)
check("D1 more candidates than the cap is refused", too_many["status"] == "refused", too_many)
broke = P.run(BASE, [CAND], runner=fake_runner, c=ON, budget={"tokens_left": 10})
check("D2 a token budget under the floor is refused", broke["status"] == "refused", broke)
check("D3 neither refusal copied or spawned", not calls and _probe_dirs() == _dirs_before_d,
      _probe_dirs())

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
check("E5 the workspace copy is removed when keep=false (the small stage stays "
      "for Compose until cleanup())",
      not os.path.isdir(os.path.join(P.root(), ran["probe_id"], "workspace"))
      and os.path.isdir(os.path.join(P.root(), ran["probe_id"], "stage")),
      os.listdir(os.path.join(P.root(), ran["probe_id"])))
P.cleanup(ran["probe_id"])
check("E6 cleanup() removes the whole probe scratch",
      not os.path.isdir(os.path.join(P.root(), ran["probe_id"])))

# --------------------------------------------------------- F: a failed run ---
def dead_runner(_plan, _timeout):
    return None, "runner exploded"


failed = P.run(BASE, [CAND], runner=dead_runner, c=ON)
check("F1 a failed runner is reported, not swallowed",
      failed["status"] == "failed" and "exploded" in failed["reason"], failed)
check("F2 a failed runner leaves no scratch tree",
      not os.path.exists(os.path.join(P.root(), failed["probe_id"])))


def throwing_runner(_plan, _timeout):
    raise RuntimeError("injected crash")


failed = P.run(BASE, [CAND], runner=throwing_runner, c=ON)
check("F3 runner exceptions name the failure and clean scratch",
      failed["status"] == "failed" and "RuntimeError: injected crash" in failed["reason"]
      and not os.path.exists(os.path.join(P.root(), failed["probe_id"])))

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
os.environ["LONGRUN_HARNESS_MAX_STEPS"] = "not-an-integer"
check("G4 invalid numeric env keeps the default",
      P.cfg()["max_steps"] == P.DEFAULTS["max_steps"])
del os.environ["LONGRUN_HARNESS_MAX_STEPS"]

# ------------------------------------------- H: no record is a FAILURE ------
def hollow_runner(_plan, _timeout):
    return {"goal": BASE["goal"], "error": "", "actions": []}, ""


hollow = P.run(BASE, [CAND], runner=hollow_runner, c=ON)
check("H1 a runner with no record fails loudly (an empty record would read as "
      "'every base error fixed')", hollow["status"] == "failed"
      and "no record" in hollow["reason"]
      and not os.path.exists(os.path.join(P.root(), hollow["probe_id"])))
# H2 pins the defect found on 2026-10-28: `agent.agent_run` has no tool lane
# (`apply_agent_action` answers "unknown action"), so a probe driven by it records
# no tool names and no failures. The probe MUST drive the chat loop.
_runner_src = open(os.path.join(REPO, "src", "longrun", "harness", "runner.py"),
                   encoding="utf-8").read()
check("H2 the runner drives the real chat loop, not the tool-less agent_run",
      "chat_once(" in _runner_src and "agent_run(" not in _runner_src)

# ------------------------------------------ I: the child's own env is boxed ---
rules.save("global", "Global owner rule.\n")
rules.save("project", "Project owner rule.\n", ws=WS)
with open(os.path.join(WS, "AGENTS.md"), "w", encoding="utf-8") as f:
    f.write("Workspace additive rule.\n")
_plan_i = P.plan(BASE, [CAND], ON, probe_id="i1")
_env = _plan_i["env"]
check("I1 the child writes its session into the probe dir",
      _env.get("LONGRUN_SESSIONS_DIR", "").startswith(P.root()), _env.get("LONGRUN_SESSIONS_DIR"))
check("I2 the child's events DB is inside the probe dir",
      _env.get("LONGRUN_DB", "").startswith(P.root()), _env.get("LONGRUN_DB"))
check("I3 the step ceiling is the configured one (read at child import time)",
      _env.get("LONGRUN_CHAT_TOOL_STEPS") == str(ON["max_steps"]),
      _env.get("LONGRUN_CHAT_TOOL_STEPS"))
check("I4 the runner is spawned as a module of the repo under test",
      _plan_i["cmd"][1:3] == ["-m", "longrun.harness.runner"]
      and "--max-steps" not in _plan_i["cmd"], _plan_i["cmd"])
# I5: the chat loop's reflection pass WRITES memory + proposals; a probe must not
# land those in the operator's live inbox, so the child gets its own DATA_DIR.
check("I5 the child's DATA_DIR is boxed (the probe cannot write live memory/proposals)",
      _env.get("LONGRUN_DATA_DIR", "").startswith(P.root()), _env.get("LONGRUN_DATA_DIR"))
rules_path = _plan_i["cmd"][_plan_i["cmd"].index("--rules") + 1]
with open(rules_path, encoding="utf-8") as f:
    snapshot = json.load(f)
check("I6 rule snapshot comes from real owners, excluding copied AGENTS.md",
      snapshot == {"global": "Global owner rule.\n", "project": "Project owner rule.\n"}
      and open(os.path.join(_plan_i["workspace"], "AGENTS.md"),
               encoding="utf-8").read() == "Workspace additive rule.\n")
check("I7 model and goal are pinned without claiming confinement",
      _plan_i["cmd"][_plan_i["cmd"].index("--model") + 1] == BASE["model"]
      and _plan_i["cmd"][_plan_i["cmd"].index("--goal") + 1] == BASE["goal"]
      and P.isolation_status()["available"] is False)
check("I8 all rule owners are boxed in the planned child environment",
      all(os.path.commonpath([_env["LONGRUN_" + key], P.root()]) == P.root()
          for key in ("DATA_HOME", "CONFIG_DIR", "PROJECTS_DIR", "HARNESS_DIR")))
P.cleanup("i1")

# ------------------------------- J: one file per kind (live flaw, 2026-10-28) --
# A live cycle adopted TWO guardrails while the probe had applied only one: both
# wrote the same Project_rules.md and the second silently overwrote the first.
_G1 = {"kind": "guardrail", "name": "rules-a", "content": "Always inventory inputs.\n"}
_G2 = {"kind": "guardrail", "name": "rules-b", "content": "Never guess a path.\n"}
_plan_j = P.plan(BASE, [_G1, _G2], ON, probe_id="j1")
check("J1 the second candidate of the same kind is refused, by name",
      list(_plan_j["staged"].keys()) == ["rules-a"]
      and any("same file as" in r["reason"] for r in _plan_j["refusals"]),
      _plan_j["refusals"])
_guard_path = _plan_j["staged"]["rules-a"]
_guard = open(_guard_path, encoding="utf-8").read()
check("J2 the stage carries the FIRST candidate's text, not the second's",
      "Always inventory inputs" in _guard and "Never guess a path" not in _guard, _guard)
check("J3 guardrail is passed to the real owner bridge, not the workspace root",
      _guard_path == os.path.join(_plan_j["stage"], "rules", "Project_rules.md")
      and _plan_j["cmd"][_plan_j["cmd"].index("--guardrail") + 1] == _guard_path
      and not os.path.exists(os.path.join(_plan_j["workspace"], "Project_rules.md")))
with open(_plan_j["cmd"][_plan_j["cmd"].index("--rules") + 1], encoding="utf-8") as f:
    snapshot = json.load(f)
# The helper runs in-process here with temp-only rule owners, never a real child.
RUNNER.prepare_rules(_plan_j["workspace"], snapshot, _guard_path)
collected = rules.collect(ws=_plan_j["workspace"])
check("J4 the runtime rule owner consumes baseline plus the staged guardrail",
      collected["project"]["path"] == rules.project_rules_path(_plan_j["workspace"])
      and "Project owner rule." in collected["project"]["text"]
      and "Always inventory inputs." in collected["project"]["text"]
      and "Never guess a path." not in collected["project"]["text"]
      and collected["project"]["text"].count("Workspace additive rule.") == 1
      and not os.path.exists(os.path.join(_plan_j["workspace"], "Project_rules.md")))
P.cleanup("j1")

shutil.rmtree(TMP, ignore_errors=True)

print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
