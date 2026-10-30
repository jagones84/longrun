#!/usr/bin/env python3
"""v728 — JobBench as an EXTERNAL-arms benchmark, with the upstream judge (EV-23).

The operator asked for an official benchmark from the web to measure Longrun and
Harness² on the same tasks, same model, same scoring. This pins the plumbing:

  A  the official corpus is discovered, and the instruction is the upstream one
  B  a workspace is staged exactly as the benchmark expects (inputs copied, empty output)
  C  deliverables are read from `output/` only
  D  an arm that delivered nothing is a rubric-weighted ZERO, not a judge failure
  E  a delivered arm is graded by the UPSTREAM judge with the official arguments
  F  a judge that could not run is `None`, never 0
  G  the comparison report states the parity block and the per-arm means
  H  Harness²'s arm is its own official sweep (it has no HTTP task endpoint)

Deterministic and offline: the dataset is a temporary fixture, the judge is a
scripted stand-in that writes the same details payload the upstream one does.
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v728-")
JB = os.path.join(TMP, "jobbench")
TASK = os.path.join(JB, "dataset", "main", "biostatisticians", "task1")
os.makedirs(os.path.join(TASK, "task_folder"), exist_ok=True)
with open(os.path.join(TASK, "task_folder", "TASK_INSTRUCTIONS.txt"), "w",
          encoding="utf-8") as f:
    f.write("Produce cohort_summary.csv from framingham.csv.\n")
with open(os.path.join(TASK, "task_folder", "framingham.csv"), "w", encoding="utf-8") as f:
    f.write("id,age\n1,50\n")
with open(os.path.join(TASK, "RUBRICS.json"), "w", encoding="utf-8") as f:
    json.dump({"rubrics": [{"weight": 4, "criterion": "a"}, {"weight": 6, "criterion": ["b", "c"]}]}, f)
os.makedirs(os.path.join(JB, "eval"), exist_ok=True)
with open(os.path.join(JB, "eval", "judge.py"), "w", encoding="utf-8") as f:
    f.write("")
os.environ["JOB_BENCH_REPO"] = JB
os.environ["JOB_BENCH_JUDGE_PYTHON"] = sys.executable
os.environ["BENCH_RUNS_DIR"] = os.path.join(TMP, "runs")
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "src"))

from benchmarks import jobbench  # noqa: E402
from benchmarks import jobbench_judge as JJ  # noqa: E402
from benchmarks import jobbench_compare as JC  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:400]) if detail and not ok else ""))


# A ----------------------------------------------------------------------
tasks = jobbench.tasks()
check("A1 the official corpus is discovered", len(tasks) == 1
      and tasks[0]["id"] == "biostatisticians/task1", tasks)
ws = os.path.join(TMP, "ws")
prompt = jobbench.prompt_for(tasks[0], ws) if tasks else ""
check("A2 the instruction names the real task folder and output dir",
      ws + "/task_folder" in prompt and ws + "/output" in prompt, prompt[:200])
check("A3 the instruction is the upstream one (verbatim prompt)", 
      "TASK_INSTRUCTIONS.txt" in prompt and "OUTPUT DIRECTORY" in prompt, prompt[:120])

# B, C -------------------------------------------------------------------
jobbench.stage(tasks[0], ws)
check("B1 the inputs were copied and output/ is empty",
      os.path.isfile(os.path.join(ws, "task_folder", "framingham.csv"))
      and os.path.isdir(os.path.join(ws, "output"))
      and os.listdir(os.path.join(ws, "output")) == [], os.listdir(ws))
check("C1 nothing outside output/ counts as a deliverable",
      jobbench.deliverables(ws) == [], jobbench.deliverables(ws))
with open(os.path.join(ws, "output", "cohort_summary.csv"), "w", encoding="utf-8") as f:
    f.write("n,mean\n1,50\n")
check("C2 a delivered file is reported by its relative path",
      jobbench.deliverables(ws) == ["cohort_summary.csv"], jobbench.deliverables(ws))

# D ----------------------------------------------------------------------
empty = os.path.join(TMP, "empty")
jobbench.stage(tasks[0], empty)
zero = JJ.score_run(tasks[0], empty, os.path.join(TMP, "zero.json"), "judge-x",
                    "http://127.0.0.1:1/v1", "", timeout=30)
check("D1 an empty delivery is a real zero", zero.get("ok") is True
      and zero.get("score") == 0.0 and zero.get("max") == 10.0, zero)
check("D2 it is labelled as no_output, not as a judge failure",
      zero.get("no_output") is True, zero)

# E ----------------------------------------------------------------------
JUDGE = os.path.join(JB, "eval", "judge.py")
ARGV = os.path.join(TMP, "judge_argv.json")
with open(JUDGE, "w", encoding="utf-8") as f:
    f.write(
        "import json, sys\n"
        "argv = sys.argv[1:]\n"
        "json.dump(argv, open(%r, 'w'))\n"
        "details = argv[argv.index('--details-file') + 1]\n"
        "json.dump({'total_score': 7.5, 'max_score': 10.0, 'judge_model': 'judge-x',\n"
        "           'rubrics': [{'result': {'criteria_count': 3, 'criteria_passed': 2}}]},\n"
        "          open(details, 'w'))\n" % ARGV)
sc = JJ.score_run(tasks[0], ws, os.path.join(TMP, "e.json"), "judge-x",
                  "https://openrouter.ai/api/v1", "test-key", evaluated_model="longrun-x",
                  timeout=120)
check("E1 the upstream judge grades the delivered files", sc.get("ok") is True
      and sc.get("score") == 7.5 and sc.get("max") == 10.0, sc)
check("E2 the official arguments were used",
      "--rubrics-file" in open(ARGV, encoding="utf-8").read()
      and "--judge-model" in open(ARGV, encoding="utf-8").read()
      and "--api-base" in open(ARGV, encoding="utf-8").read()
      and "--evaluated-model" in open(ARGV, encoding="utf-8").read(),
      open(ARGV, encoding="utf-8").read()[:300])
check("E3 the criteria counts survive", sc.get("criteria_passed") == 2
      and sc.get("criteria_count") == 3, sc)

# F ----------------------------------------------------------------------
with open(JUDGE, "w", encoding="utf-8") as f:
    f.write("import sys\nsys.stderr.write('boom: no quota\\n')\nsys.exit(1)\n")
bad = JJ.score_run(tasks[0], ws, os.path.join(TMP, "f.json"), "judge-x",
                   "https://openrouter.ai/api/v1", "k", timeout=120)
check("F1 a judge that could not run is not a zero", bad.get("ok") is False
      and "score" not in bad and "boom" in str(bad.get("error")), bad)

# G ----------------------------------------------------------------------
rows = [{"task": "biostatisticians/task1", "arm": "longrun", "delivered": 1, "ok": True,
         "score": {"ok": True, "score": 7.5, "max": 10.0}},
        {"task": "biostatisticians/task1", "arm": "harness2", "delivered": 1, "ok": True,
         "score": {"ok": True, "score": 5.0, "max": 10.0}}]
payload, text = JC.report(os.path.join(TMP, "report"), rows,
                          {"solver_longrun": "openrouter:z-ai/glm-5.3-flash",
                           "solver_harness2": "openrouter/z-ai/glm-5.3-flash",
                           "judge_model": "z-ai/glm-5.3-flash"})
check("G1 the report keeps the parity block",
      payload["parity"]["judge_model"] == "z-ai/glm-5.3-flash"
      and payload["parity"]["solver_longrun"] != payload["parity"]["solver_harness2"], payload["parity"])
check("G2 the mean ratio is per arm",
      payload["arms"]["longrun"]["mean_ratio"] == 0.75
      and payload["arms"]["harness2"]["mean_ratio"] == 0.5, payload["arms"])
check("G3 compare.md renders both arms", "| longrun |" in text
      and "| harness2 |" in text, text[:300])

# H ----------------------------------------------------------------------
cmd = JC.harness2_command([tasks[0]], "openrouter/z-ai/glm-5.3-flash")
check("H1 Harness² is driven by its own official sweep",
      "harness2.cli.run_sweep" in " ".join(cmd) and "--bench" in cmd
      and "jb" in cmd and "--substrate" in cmd, cmd)
check("H2 the sweep is restricted to the same tasks",
      "biostatisticians" in cmd and cmd[cmd.index("--max-tasks") + 1] == "1", cmd)

# I ----------------------------------------------------------------------
SRC = open(os.path.join(REPO, "benchmarks", "longrun_adapter.py"), encoding="utf-8").read()
check("I1 the adapter sets the session workspace on the REAL route",
      '"/api/workspace"' in SRC and "/api/sessions/%s/workspace" not in SRC,
      SRC.count("/api/workspace"))
check("I2 an external caller finds the token where the template says it lives",
      "_REPO_ENV_FILE" in SRC and "os.path.join(os.getcwd(), \".env\")" in SRC,
      "token lookup must try the repo .env, not only ~/.longrun/config/env")
check("I3 the bearer that answers /api/status wins (a stale copy cannot fake a zero)",
      "_first_working_token" in SRC and '"/api/status"' in SRC, SRC.count("_first_working_token"))

# J — the output layout is organised BY DESIGN ------------------------------
import time as _time  # noqa: E402

_default = JC.default_out(["longrun"], "openrouter:z-ai/glm-5.3-flash", 3,
                          scope="biostatisticians")
_want = "%s_jobbench_openrouter-z-ai-glm-5.3-flash_longrun_biostatisticians_n3" \
    % _time.strftime("%Y-%m-%d")
check("J1 the run folder names date, suite, model, arm and scope",
      _default.name == _want and _default.parent == JC.RUNS_ROOT, (_default.name, _want))
os.makedirs(_default, exist_ok=True)
_second = JC.default_out(["longrun"], "openrouter:z-ai/glm-5.3-flash", 3,
                         scope="biostatisticians")
check("J2 a repeated run never overwrites the previous one",
      _second.name == _want + "-2", _second.name)
JC.write_manifest(_default, run_id=_default.name, suite="jobbench", status="running",
                  arms=["longrun"], model="openrouter:z-ai/glm-5.3-flash", n_tasks=3)
JC.write_manifest(_default, status="ok", arms_summary={"longrun": {"mean_ratio": 0.5}})
_man = json.load(open(os.path.join(_default, "run.json"), encoding="utf-8"))
check("J3 one manifest per run carries both the start and the outcome",
      _man.get("status") == "ok" and _man.get("arms") == ["longrun"]
      and _man.get("arms_summary", {}).get("longrun", {}).get("mean_ratio") == 0.5, _man)
_text = JC.rebuild_index()
check("J4 the index is derived from the manifests",
      _default.name in _text and "| ok |" in _text
      and os.path.isfile(os.path.join(JC.RUNS_ROOT, "INDEX.md")), _text[:300])

# K — a benchmark turn may ask for the tool budget it needs ---------------
AGENT = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8").read()
HTTP = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"), encoding="utf-8").read()
check("K1 the chat turn accepts a per-turn tool budget, clamped to the loop cap",
      "max_steps=None):" in AGENT and "min(int(_want_steps), CHAT_TOOL_MAX_ITERS)" in AGENT,
      "chat_once must accept max_steps and clamp it")
check("K2 both chat endpoints carry the caller's budget",
      'max_steps=body.get("max_steps")' in HTTP
      and 'max_steps=qs.get("max_steps")' in HTTP, "httpapi must thread max_steps")
SRC_AD = open(os.path.join(REPO, "benchmarks", "longrun_adapter.py"), encoding="utf-8").read()
check("K3 the benchmark arm sends its budget and records it",
      'body["max_steps"] = int(self.max_steps)' in SRC_AD
      and '"max_steps": max_steps' in open(
          os.path.join(REPO, "benchmarks", "jobbench_compare.py"), encoding="utf-8").read(),
      "the arm must send max_steps and the row must show it")

# L — a settings save cannot eat the operator's comments (EV-24) -----------
from longrun.model import routing as _rt  # noqa: E402

_old = "# why this exists\nquota_cooldown: true\nroles:\n  chat:\n    model: a\n"
_new = "roles:\n  chat:\n    model: b\nquota_cooldown: false\n"
_kept = _rt._preserve_comments(_old, _new)
check("L1 a comment block survives a re-serialised save",
      "# why this exists\nquota_cooldown: false" in _kept, _kept)
check("L2 an anchor that disappeared loses only its own note",
      "roles:" in _kept and _kept.count("#") == 1, _kept)
_rsrc = open(os.path.join(REPO, "src", "longrun", "model", "routing.py"), encoding="utf-8").read()
check("L3 save_config is the path that uses it",
      "_preserve_comments(old, new)" in _rsrc, "save_config must not strip comments")

print("\n---\nv728: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
