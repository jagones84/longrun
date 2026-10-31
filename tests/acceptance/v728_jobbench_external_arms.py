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
# 2026-10-30: two longrun re-runs of the same task were killed at the wall clock
# (endpoint p50 19.5 s vs 2.4 s) and entered the mean as 0.000, so a 0.57 arm read
# as 0.19. A cut run has no score; it is counted as a TIMEOUT, and an arm with no
# completed task has no mean at all.
_rows_cut = [{"task": "t1", "arm": "longrun", "delivered": 3, "ok": True,
              "score": {"ok": True, "score": 9.0, "max": 10.0}, "duration_s": 138.1},
             {"task": "t2", "arm": "longrun", "delivered": 0, "ok": False,
              "error": "TimeoutError('timed out')",
              "score": {"ok": True, "score": 0.0, "max": 10.0, "no_output": True},
              "duration_s": 600.2},
             {"task": "t1", "arm": "openclaw", "delivered": 0, "ok": True,
              "score": {"ok": True, "score": 0.0, "max": 10.0, "no_output": True},
              "duration_s": 625.5}]
_p2, _t2 = JC.report(os.path.join(TMP, "report2"), _rows_cut, {})
check("G4 a TIMEOUT is not averaged as a zero (the mean covers completed tasks)",
      _p2["arms"]["longrun"]["mean_ratio"] == 0.9
      and _p2["arms"]["longrun"]["timeouts"] == 1, _p2["arms"]["longrun"])
check("G5 a run that finished with NO output has no mean instead of 0.000",
      _p2["arms"]["openclaw"]["mean_ratio"] is None
      and _p2["arms"]["openclaw"]["no_output"] == 1, _p2["arms"]["openclaw"])
check("G6 the per-task row says TIMEOUT / NO OUTPUT, never a bare 0",
      "| TIMEOUT |" in _t2 and "| NO OUTPUT |" in _t2, _t2[:600])

# H ----------------------------------------------------------------------
cmd = JC.harness2_command([tasks[0]], "openrouter/z-ai/glm-5.3-flash")
check("H1 Harness² is driven by its own official sweep",
      "harness2.cli.run_sweep" in " ".join(cmd) and "--bench" in cmd
      and "jb" in cmd and "--substrate" in cmd, cmd)
check("H2 the sweep is restricted to the same tasks",
      "biostatisticians" in cmd and cmd[cmd.index("--max-tasks") + 1] == "1", cmd)
_h2out = os.path.join(TMP, "h2out")
_rows_h2, _meta_h2 = JC.run_harness2(tasks, _h2out, solver_model="openrouter/x",
                                     judge_model="j", judge_base="u", key="k",
                                     timeout=60, judge_timeout=60, dry_run=True)
check("H3 a sweep gets its OWN run store, inside the run folder",
      _meta_h2.get("runs_dir") == os.path.join(_h2out, "harness2", "_h2runs")
      and os.path.isdir(_meta_h2["runs_dir"]),
      _meta_h2.get("runs_dir"))
_h2src = open(os.path.join(REPO, "benchmarks", "jobbench_compare.py"), encoding="utf-8").read()
check("H4 grading follows that store, so an old model_output is never picked up",
      "base = Path(h2_runs) /" in _h2src and '"OPENROUTER_API_KEY": key' in _h2src
      and '"HARNESS2_RUNS_DIR": str(h2_runs)' in _h2src,
      "the sweep env must carry the solver key and the per-run store")
# A sweep's rollouts finish and its IMPROVER sessions then hang forever, because
# Harness²'s proposer launches the OpenCode CLI without `stdin=` and the CLI reads
# an inherited open stdin (measured: inherit -> hung 45 s, DEVNULL -> 5 s).
check("H5 no child of the driver may inherit an open stdin",
      "stdin=subprocess.DEVNULL" in _h2src
      and "stdin=subprocess.DEVNULL" in open(
          os.path.join(REPO, "benchmarks", "jobbench_judge.py"), encoding="utf-8").read(),
      "run_harness2 and judge must both pass stdin=DEVNULL")
# A BUDGET, not a failure: Harness² writes each label's files as that rollout ends,
# so a sweep cut at the wall clock has still delivered something. Discarding those
# labels turned a slow arm into "no data" instead of "this much quality in this much
# time" — measured 2026-10-30, one task is 7 OpenCode sessions and ~55 min.
_h2repo = os.path.join(TMP, "h2repo")
os.makedirs(os.path.join(_h2repo, ".venv", "bin"), exist_ok=True)
_py = os.path.join(_h2repo, ".venv", "bin", "python")
with open(_py, "w", encoding="utf-8") as f:
    f.write("#!/bin/sh\nsleep 5\n")
os.chmod(_py, 0o755)
_orig_repo = JC.DEFAULT_HARNESS2
JC.DEFAULT_HARNESS2 = type(_orig_repo)(_h2repo)
try:
    _rows_to, _meta_to = JC.run_harness2(
        tasks, os.path.join(TMP, "h2budget"), solver_model="openrouter/x",
        judge_model="j", judge_base="u", key="k", timeout=1, judge_timeout=60)
finally:
    JC.DEFAULT_HARNESS2 = _orig_repo
check("H6 a sweep cut at the budget is GRADED, not thrown away",
      _meta_to.get("status") == "timeout" and len(_rows_to) == 1
      and _rows_to[0].get("timed_out") is True
      and _rows_to[0].get("duration_s") is not None,
      (_meta_to.get("status"), _rows_to))
check("H7 the budget is a wall clock on the whole process tree",
      'args.harness2_timeout' in _h2src
      and "max(args.timeout * len(tasks), 3600)" not in _h2src
      and "start_new_session=True" in _h2src and "os.killpg(pgid" in _h2src,
      "a 1 h floor would make a short run impossible, and a sweep leaves agents running")

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
# an index whose first row is not the newest run is a misleading index: the
# folder name is not chronological (`_n3` sorts before `_n1-2` lexically).
_older = JC.RUNS_ROOT / "2000-01-01_jobbench_old_longrun_n1"
JC.write_manifest(_default, started="2026-10-30T14:00:00")
JC.write_manifest(_older, run_id=_older.name, started="2000-01-01T00:00:00",
                  suite="jobbench", status="ok", arms=["longrun"], n_tasks=1)
_text = JC.rebuild_index()
check("J5 the index lists the newest run first, by the manifest's own clock",
      _text.index(_default.name) < _text.index(_older.name), _text[:400])

# K — a benchmark turn may ask for the tool budget it needs ---------------
AGENT = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8").read()
HTTP = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"), encoding="utf-8").read()
import re as _re  # noqa: E402
_sig = _re.search(r"def chat_once\(([^)]*)\)", AGENT, _re.S)
check("K1 the chat turn accepts a per-turn tool budget, clamped to the loop cap",
      bool(_sig) and "max_steps" in _sig.group(1)
      and "min(int(_want_steps), CHAT_TOOL_MAX_ITERS)" in AGENT,
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

# M — the NO-HARNESS control: a raw model, judged like the others ----------
check("M1 one model, three spellings: the raw arm takes the bare id",
      JC.bare_model_id("openrouter:z-ai/glm-5.3-flash") == "z-ai/glm-5.3-flash"
      and JC.bare_model_id("z-ai/glm-5.3-flash") == "z-ai/glm-5.3-flash",
      JC.bare_model_id("openrouter:z-ai/glm-5.3-flash"))

from benchmarks.protocol import HarnessResult  # noqa: E402


class _FakeRaw:
    """A model endpoint stand-in: records the prompt, answers with fixed text."""

    def __init__(self, text):
        self.text, self.prompts = text, []

    def send_task(self, ref, prompt, timeout=None):
        self.prompts.append(prompt)
        return HarnessResult(ok=True, output=self.text)

    def provenance(self):
        return {"harness": "bare", "base_url": "http://stub", "model": "m", "tools": 0}


with open(JUDGE, "w", encoding="utf-8") as f:      # the good stub judge again
    f.write(
        "import json, sys\n"
        "argv = sys.argv[1:]\n"
        "json.dump(argv, open(%r, 'w'))\n"
        "details = argv[argv.index('--details-file') + 1]\n"
        "json.dump({'total_score': 6.0, 'max_score': 10.0, 'judge_model': 'judge-x',\n"
        "           'rubrics': [{'result': {'criteria_count': 2, 'criteria_passed': 1}}]},\n"
        "          open(details, 'w'))\n" % ARGV)
_fake = _FakeRaw("# Findings\n\nthe model's own text\n")
_rows_raw, _prov_raw = JC.run_raw(tasks, os.path.join(TMP, "rawout"), model="openrouter:m",
                                  judge_model="judge-x", judge_base="http://127.0.0.1:1/v1",
                                  key="k", timeout=30, judge_timeout=120, adapter=_fake)
check("M2 the raw arm sends the SAME verbatim instruction, with no tools",
      _fake.prompts and "=== TASK FOLDER ===" in _fake.prompts[0]
      and _prov_raw.get("tools") == 0, _fake.prompts[0][:200] if _fake.prompts else "-")
check("M3 the model's text becomes the one deliverable the judge can read",
      _rows_raw[0]["delivered"] == 1 and _rows_raw[0]["files"] == ["answer.md"]
      and os.path.isfile(os.path.join(TMP, "rawout", "raw", JC._slug(tasks[0]["id"]),
                                      "workspace", "output", "answer.md")),
      _rows_raw[0].get("files"))
check("M4 it is graded by the same judge as every other arm",
      _rows_raw[0]["score"].get("score") == 6.0 and _rows_raw[0]["arm"] == "raw",
      _rows_raw[0].get("score"))
_empty_raw = _FakeRaw("")
_rows_empty, _ = JC.run_raw(tasks, os.path.join(TMP, "rawout2"), model="openrouter:m",
                            judge_model="judge-x", judge_base="http://127.0.0.1:1/v1",
                            key="k", timeout=30, judge_timeout=120, adapter=_empty_raw)
check("M5 a silent model delivers nothing and scores the real zero",
      _rows_empty[0]["delivered"] == 0
      and _rows_empty[0]["score"].get("no_output") is True, _rows_empty[0]["score"])

_three = ([{"task": "t/1", "arm": a, "delivered": 1, "ok": True,
            "score": {"ok": True, "score": v, "max": 10.0}}
           for a, v in (("harness2", 4.0), ("raw", 2.0), ("longrun", 6.0),
                         ("opencode", 3.0))])
_payload3, _text3 = JC.report(os.path.join(TMP, "report3"), _three, {"judge_model": "j"})
check("M6 the report orders the ladder raw -> opencode -> longrun -> harness2",
      _text3.index("| raw |") < _text3.index("| opencode |")
      < _text3.index("| longrun |") < _text3.index("| harness2 |"), _text3[-600:])
check("M7 the report states WHO is better, and the raw floor",
      "**Better on this run:**" in _text3 and "`longrun` at 0.600" in _text3
      and "floor" in _text3, _text3[-400:])
_cmd_oc = JC.opencode_command("/tmp/ws-pin", "openrouter/z-ai/glm-5.3-flash", "PROMPT")
check("P1 the bare-loop arm is OpenCode's own CLI, pointed at the task workspace",
      "src/index.ts" in _cmd_oc and _cmd_oc[_cmd_oc.index("--dir") + 1] == "/tmp/ws-pin"
      and not any(str(x).endswith("run_sweep") for x in _cmd_oc), _cmd_oc)
check("P2 it takes the SAME model spelling Harness2 uses, and the same prompt",
      _cmd_oc[_cmd_oc.index("--model") + 1] == "openrouter/z-ai/glm-5.3-flash"
      and "PROMPT" in _cmd_oc, _cmd_oc)
# EV-44: a non-interactive `opencode run` auto-REJECTS every permission ask, so
# the arm died in 4 steps with nothing delivered (measured 2026-10-30, 0/88) —
# that measures its permission gate, not its loop. The Longrun arm runs with
# approvals=full, so parity requires skipping the asks here too.
check("P4 the bare-loop arm runs with permissions skipped (parity with approvals=full)",
      "--dangerously-skip-permissions" in _cmd_oc, _cmd_oc)
_stream = ('{"type":"step_finish","part":{"tokens":{"input":100,"output":10,'
           '"reasoning":5},"cost":0.001}}\n'
           '{"type":"text","part":{"text":"done"}}\n'
           '{"type":"step_finish","part":{"tokens":{"input":50,"output":20},'
           '"cost":0.002}}\n')
_u_oc, _r_oc = JC._oc_usage(_stream)
check("P3 the substrate arm reports its own steps, tokens and dollars",
      _u_oc["steps"] == 2 and _u_oc["tokens_in"] == 150 and _u_oc["tokens_out"] == 35
      and abs(_u_oc["total_usd"] - 0.003) < 1e-9 and _r_oc == "done", (_u_oc, _r_oc))
_env_oc = JC._h2_env("K")
_h2dot = JC.DEFAULT_HARNESS2 / ".env"
check("P4 it reuses Harness2's own XDG wiring, never a second provider config",
      _env_oc.get("OPENROUTER_API_KEY") == "K"
      and (not _h2dot.is_file()
           or all(k in _env_oc for k in ("XDG_CONFIG_HOME", "XDG_DATA_HOME"))),
      sorted(_env_oc)[:6])
_tie = [{"task": "t/1", "arm": a, "delivered": 2, "ok": True, "duration_s": d,
         "score": {"ok": True, "score": 48.0, "max": 58.0}}
        for a, d in (("opencode", 306.0), ("longrun", 174.0), ("harness2", 1200.0))]
_payload_t, _text_t = JC.report(os.path.join(TMP, "report_tie"), _tie, {"judge_model": "j"})
check("M9 a tie at a REAL score is a result with its cost, not 'the floor won'",
      "Tied at the top" in _text_t and "No arm beat the floor" not in _text_t
      and "20.0min" in _text_t and "5.1min" in _text_t, _text_t[-500:])

_zero = [{"task": "t/1", "arm": a, "delivered": 1, "ok": True,
          "score": {"ok": True, "score": 0.0, "max": 72.0}} for a in JC.ARM_ORDER]
_payload0, _text0 = JC.report(os.path.join(TMP, "report0"), _zero, {"judge_model": "j"})
check("M8 an all-zero run crowns nobody (the floor is not a winner)",
      "**Better on this run:**" not in _text0 and "No arm beat the floor" in _text0,
      _text0[-400:])

# P5/P6 — OpenClaw as its OWN arm (a complete third-party harness) ------------
_cmd_ocw = JC.openclaw_command("/tmp/ws-ocw", "openrouter/z-ai/glm-5.3-flash",
                               "PROMPT", 600)
check("P5 the OpenClaw arm is one isolated headless turn in the task workspace",
      _cmd_ocw[:3] == [JC.OPENCLAW_BIN, "agent", "exec"]
      and _cmd_ocw[_cmd_ocw.index("--cwd") + 1] == "/tmp/ws-ocw"
      and _cmd_ocw[_cmd_ocw.index("--model") + 1] == "openrouter/z-ai/glm-5.3-flash"
      and _cmd_ocw[_cmd_ocw.index("--timeout") + 1] == "600"
      and "--json" in _cmd_ocw and "PROMPT" in _cmd_ocw, _cmd_ocw)
check("P5b OpenClaw runs on its own Node (the CLI refuses < 24.22)",
      "24.22" in JC.OPENCLAW_NODE_BIN and JC.OPENCLAW_NODE_BIN in
      JC._openclaw_env("K").get("PATH", ""), JC.OPENCLAW_NODE_BIN)
_u_ocw, _r_ocw = JC._openclaw_usage(json.dumps({
    "ok": True, "final": "done",
    "usage": {"input": 13016, "output": 36, "reasoningTokens": 2,
              "cost": {"total": 0.00138}},
    "assistantTurns": 2, "toolSummary": {"calls": 1, "failures": 0}}))
check("P6 the envelope's tokens/cost/steps are read, a broken one is zero",
      _u_ocw["tokens_in"] == 13016 and _u_ocw["tokens_out"] == 38
      and abs(_u_ocw["total_usd"] - 0.00138) < 1e-9 and _u_ocw["steps"] == 2
      and _u_ocw["tool_calls"] == 1 and _r_ocw == "done"
      and JC._openclaw_usage("not json")[0]["total_usd"] == 0.0)
check("P6b openclaw sits between the bare loop and this harness in the ladder",
      JC.ARM_ORDER.index("opencode") < JC.ARM_ORDER.index("openclaw")
      < JC.ARM_ORDER.index("longrun"))

# N — adding the other arms must not pay for the sweep twice ----------------
_prev = os.path.join(TMP, "prevrun")
_prev_base = os.path.join(_prev, "harness2", "_h2runs", "jb", "dataset",
                          "biostatisticians", "task1", "model_output")
for _label in ("jb-oc-agg1__biostatisticians__task1__base1",
               "jb-oc-agg1__biostatisticians__task1__v2"):
    os.makedirs(os.path.join(_prev_base, _label, "output"), exist_ok=True)
    with open(os.path.join(_prev_base, _label, "output", "reused.csv"), "w",
              encoding="utf-8") as f:
        f.write("a,b\n1,2\n")
_prev_store = os.path.join(_prev_base, "jb-oc-agg1__biostatisticians__task1__v2")
_rows_re, _meta_re = JC.run_harness2(tasks, os.path.join(TMP, "reuseout"),
                                     solver_model="openrouter/x", judge_model="judge-x",
                                     judge_base="http://127.0.0.1:1/v1", key="k",
                                     timeout=30, judge_timeout=60, reuse=_prev)
check("N1 a reused sweep grades the PREVIOUS model_output instead of spending",
      _meta_re.get("status") == "reused" and _meta_re.get("command") == []
      and _rows_re[0]["delivered"] == 1
      and _rows_re[0]["label"] == "jb-oc-agg1__biostatisticians__task1__v2",
      _meta_re)
check("N2 a self-improving sweep reports BOTH its improvement and its baseline",
      len(_rows_re[0].get("labels") or []) == 2
      and (_rows_re[0].get("baseline") or {}).get("label", "").endswith("base1")
      and (_rows_re[0].get("baseline") or {}).get("score", {}).get("ok") is True,
      _rows_re[0].get("baseline"))

# N3 — Harness² writes its deliverables FLAT in the label folder (measured
# 2026-10-30: three .xlsx at the root, no output/). The judge graded them 62/72
# while the row said "delivered 0", which reads as "this arm produced nothing".
_flat = os.path.join(_prev_base, "jb-oc-agg1__biostatisticians__task1__flat1")
os.makedirs(_flat, exist_ok=True)
with open(os.path.join(_flat, "Baseline_Subgroup_Analysis.xlsx"), "wb") as f:
    f.write(b"PK\x03\x04stub")
_rows_flat, _ = JC.run_harness2(tasks, os.path.join(TMP, "flatout"),
                                solver_model="openrouter/x", judge_model="judge-x",
                                judge_base="http://127.0.0.1:1/v1", key="k",
                                timeout=30, judge_timeout=60, reuse=_prev)
check("N3 a flat label (no output/ dir) is counted as delivered",
      _rows_flat[0]["label"].endswith("flat1") and _rows_flat[0]["delivered"] == 1
      and _rows_flat[0]["files"] == ["Baseline_Subgroup_Analysis.xlsx"],
      (_rows_flat[0].get("label"), _rows_flat[0].get("files")))

# O — the Longrun arm's own cost must SURVIVE the task -----------------------
# Measured 2026-10-30: a finished Longrun task reported score+files but no tokens
# and no dollars, because `delete_agent` removes the session and with it
# `~/.longrun/data/costs/<sid>.json`. Harness² logs per-step token cost in its
# trajectory, so a comparison that drops Longrun's cost compares only one side.
class _FakeLongrun:
    """The Longrun REST surface, faked: records the order of the two decisive calls."""

    def __init__(self, usage, out):
        self.calls, self._usage, self.out = [], usage, out

    def provenance(self):
        return {"harness": "longrun", "model": "m"}

    def setup(self):
        return None

    def teardown(self):
        return None

    def create_agent(self, task):
        from benchmarks.protocol import AgentRef
        return AgentRef(id="t", session="sid-1", meta={"task": task.get("id")})

    def send_task(self, ref, prompt, timeout=None):
        wout = os.path.join(self.out, "longrun", JC._slug(tasks[0]["id"]),
                            "workspace", "output")
        os.makedirs(wout, exist_ok=True)
        with open(os.path.join(wout, "cohort_summary.csv"), "w", encoding="utf-8") as f:
            f.write("n,mean\n1,50\n")
        return HarnessResult(ok=True, output="done", run_id="r1")

    def usage(self, session):
        self.calls.append("usage:%s" % session)
        return self._usage

    def delete_agent(self, ref):
        self.calls.append("delete:%s" % ref.session)
        return True


_usage = {"calls": 41, "tokens_in": 512000, "tokens_out": 9000,
          "total_usd": 0.0123, "latency_ms_p50": 4100}
_fake_lr = _FakeLongrun(_usage, os.path.join(TMP, "lrout"))
_rows_lr, _ = JC.run_longrun(tasks, os.path.join(TMP, "lrout"), model="openrouter:m",
                             judge_model="judge-x", judge_base="http://127.0.0.1:1/v1",
                             key="k", timeout=30, judge_timeout=120, adapter=_fake_lr)
check("O1 the cost ledger is read BEFORE the session is deleted",
      _fake_lr.calls[:2] == ["usage:sid-1", "delete:sid-1"], _fake_lr.calls)
check("O2 the task's tokens and dollars are in the result row and on disk",
      _rows_lr[0].get("usage", {}).get("total_usd") == 0.0123
      and _rows_lr[0]["usage"]["tokens_in"] == 512000
      and os.path.isfile(os.path.join(TMP, "lrout", "longrun",
                                      JC._slug(tasks[0]["id"]), "costs.json")),
      _rows_lr[0].get("usage"))
_fake_none = _FakeLongrun(None, os.path.join(TMP, "lrout2"))
_rows_none, _ = JC.run_longrun(tasks, os.path.join(TMP, "lrout2"), model="openrouter:m",
                               judge_model="judge-x", judge_base="http://127.0.0.1:1/v1",
                               key="k", timeout=30, judge_timeout=120, adapter=_fake_none)
check("O3 a missing ledger never breaks the arm (usage is {}, not a crash)",
      _rows_none[0].get("usage") == {} and _rows_none[0]["delivered"] == 1,
      _rows_none[0].get("usage"))

print("\n---\nv728: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
