#!/usr/bin/env python3
"""v754 — the benchmark must RANK, and an openclaw run must be VISIBLE.

Two operator complaints from 2026-10-31, both measured here:

1. "Taking high scores means the benchmark is bad — are there tests where models do
   NOT get 10/10?"  The 10-task slice was the alphabetically-first head of the
   track, so every arm scored 10/10 and the run ranked nothing. Selection is now a
   property of the task (`--order hardest`: test breadth x exemplar size, read from
   the exercise's own files) and a run where every arm solves everything reports
   SATURATED instead of a tie.

2. "I cannot see any openclaw session — where the hell do you launch it?"  The arm
   drove `openclaw agent exec`, an isolated embedded turn that stores NO session.
   It now drives `openclaw agent --session-key …`, which stores
   `agent:coordinator:<key>` and shows up in `sessions list` and the dashboard.

Deterministic, no live model, no network, no server.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v754-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "src"))

from benchmarks import polyglot, polyglot_compare          # noqa: E402
from benchmarks.jobbench_compare import (                  # noqa: E402
    _openclaw_env, _openclaw_usage, openclaw_command,
)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- a synthetic track: three exercises of clearly different size ----------
def _exercise(root, name, n_tests, exemplar_lines):
    d = root / "python" / "exercises" / "practice" / name
    (d / ".docs").mkdir(parents=True)
    (d / ".meta").mkdir(parents=True)
    (d / ".docs" / "instructions.md").write_text("do %s\n" % name, encoding="utf-8")
    (d / ".meta" / "config.json").write_text('{"authors": []}', encoding="utf-8")
    (d / ".meta" / "example.py").write_text(
        "\n".join("x%d = %d" % (i, i) for i in range(exemplar_lines)) + "\n",
        encoding="utf-8")
    (d / ("%s.py" % name)).write_text("pass\n", encoding="utf-8")
    (d / ("%s_test.py" % name)).write_text(
        "".join("def test_%d():\n    pass\n\n" % i for i in range(n_tests)),
        encoding="utf-8")
    return d


ROOT = Path(TMP) / "track"
_exercise(ROOT, "aaa-easy", n_tests=2, exemplar_lines=5)
_exercise(ROOT, "mmm-mid", n_tests=10, exemplar_lines=40)
_exercise(ROOT, "zzz-hard", n_tests=30, exemplar_lines=90)
os.environ["POLYGLOT_DIR"] = str(ROOT)

# ---- A. difficulty is read from the task, not invented ---------------------
hard = polyglot.load_tasks("python", only=["zzz-hard"])[0]
check("A1 test cases are counted from the test file", hard["tests"] == 30, hard["tests"])
check("A2 exemplar lines are counted from .meta/example.py",
      hard["exemplar_lines"] == 90, hard["exemplar_lines"])

# ---- B. hardest ordering happens BEFORE the limit -------------------------
order = [t["exercise"] for t in polyglot.load_tasks("python", order="hardest")]
check("B1 hardest first", order == ["zzz-hard", "mmm-mid", "aaa-easy"], order)
picked = [t["exercise"] for t in polyglot.load_tasks("python", limit=2, order="hardest")]
check("B2 the limit slices the HARD end, not the alphabet", picked == ["zzz-hard", "mmm-mid"],
      picked)
alpha = [t["exercise"] for t in polyglot.load_tasks("python", order="alpha")]
check("B3 alpha stays the track order", alpha == ["aaa-easy", "mmm-mid", "zzz-hard"], alpha)

# ---- C. the openclaw arm asks for a STORED session ------------------------
cmd = openclaw_command("/tmp/ws", "openrouter/z-ai/glm-5.3-flash", "PROMPT", 120,
                       session_key="polyglot:run:forth")
check("C1 it runs the Gateway agent, not the isolated exec",
      cmd[1:3] == ["agent", "--session-key"] and "exec" not in cmd, cmd[:4])
check("C2 the session key is explicit", cmd[3] == "polyglot:run:forth", cmd[3])
check("C3 the prompt travels in --message", "--message" in cmd
      and cmd[cmd.index("--message") + 1] == "PROMPT", cmd)
check("C4 no --state-dir (that was the invisible transport)", "--state-dir" not in cmd, cmd)
check("C5 no --cwd (agent has none; the prompt carries absolute paths)",
      "--cwd" not in cmd, cmd)
check("C6 json + the model override are kept",
      "--json" in cmd and "openrouter/z-ai/glm-5.3-flash" in cmd, cmd)
default = openclaw_command("/tmp/bench-task", "m", "p", 120)
check("C7 a key is derived when none is given", "--session-key" in default
      and default[default.index("--session-key") + 1].startswith("bench:"), default[3])

# ---- D. both --json envelopes are understood ------------------------------
GATEWAY = json.dumps({"runId": "r1", "status": "ok",
                      "result": {"payloads": [{"text": "done"}],
                                 "meta": {"agentMeta": {"assistantTurns": 4,
                                                        "usage": {"input": 100, "output": 20,
                                                                  "cost": {"total": 0.01}}},
                                          "toolSummary": {"calls": 3, "failures": 1}}}})
u1, r1 = _openclaw_usage(GATEWAY)
check("D1 gateway usage: steps", u1["steps"] == 4, u1)
check("D2 gateway usage: tokens in/out", (u1["tokens_in"], u1["tokens_out"]) == (100, 20), u1)
check("D3 gateway usage: tool calls + failures",
      (u1["tool_calls"], u1["tool_failures"]) == (3, 1), u1)
check("D4 gateway reply comes from payloads", r1 == "done", r1)
EXEC = json.dumps({"usage": {"input": 7, "output": 9, "cost": {"total": 0.002}},
                   "assistantTurns": 2, "toolSummary": {"calls": 5, "failures": 0},
                   "final": "ok!"})
u2, r2 = _openclaw_usage(EXEC)
check("D5 the old exec envelope still reads", (u2["tokens_in"], u2["tokens_out"], r2)
      == (7, 9, "ok!"), (u2, r2))
u3, _ = _openclaw_usage("not json")
check("D6 unparsable output invents no numbers", u3["tokens_in"] == 0 and u3["steps"] == 0, u3)

# ---- E. the gateway token is loaded from the unit EnvironmentFile ---------
gw = Path(TMP) / "gateway.env"
gw.write_text('OPENCLAW_GATEWAY_TOKEN=placeholder\nOTHER_FLAG=1\n', encoding="utf-8")
os.environ.pop("OPENCLAW_GATEWAY_TOKEN", None)
os.environ["OPENCLAW_GATEWAY_ENV"] = str(gw)
env = _openclaw_env("KEY")
check("E1 the gateway token reaches the peer env",
      env.get("OPENCLAW_GATEWAY_TOKEN") == "placeholder", env.get("OPENCLAW_GATEWAY_TOKEN"))
check("E2 a value already in the environment wins (never overridden)",
      env.get("OTHER_FLAG") == "1", env.get("OTHER_FLAG"))
os.environ["OPENCLAW_GATEWAY_TOKEN"] = "already-set"
check("E3 an exported token is not replaced by the file",
      _openclaw_env("KEY").get("OPENCLAW_GATEWAY_TOKEN") == "already-set")
os.environ.pop("OPENCLAW_GATEWAY_TOKEN", None)

# ---- F. a perfect run is reported as SATURATED, not as a ranking ----------
out = Path(TMP) / "run"
out.mkdir(parents=True)
parity = {"model": "m", "dataset": str(ROOT), "dataset_commit": "x", "n_tasks": 2,
          "order": "hardest",
          "task_stats": [{"id": "python/aaa-easy", "tests": 2, "exemplar_lines": 5},
                         {"id": "python/zzz-hard", "tests": 30, "exemplar_lines": 90}]}
flat_rows = [{"task": "python/aaa-easy", "arm": a, "resolved": True, "status": "passed",
              "duration_s": 1.0} for a in ("longrun", "openclaw")]
flat_rows += [{"task": "python/zzz-hard", "arm": a, "resolved": True, "status": "passed",
               "duration_s": 2.0} for a in ("longrun", "openclaw")]
flat = polyglot_compare._report(out, flat_rows, parity)
check("F1 every arm perfect => saturated", flat is True)
md = (out / "compare.md").read_text(encoding="utf-8")
check("F2 the report SAYS it cannot rank", "SATURATED" in md, md[:200])
check("F3 the verdict is machine-readable too",
      json.loads((out / "run.json").read_text(encoding="utf-8")).get("saturated") is True)
split_rows = [dict(r) for r in flat_rows]
split_rows[1]["resolved"] = False
split_rows[1]["status"] = "error"
out2 = Path(TMP) / "run2"
out2.mkdir(parents=True)
split = polyglot_compare._report(out2, split_rows, parity)
md2 = (out2 / "compare.md").read_text(encoding="utf-8")
check("F4 a disagreement is not saturated", split is False)
check("F5 the report counts the discriminating tasks",
      "Discriminating tasks: **1/2**" in md2, [ln for ln in md2.splitlines() if "Discrimin" in ln])
check("F6 per-task table shows the size signal",
      "| python/zzz-hard | 30 | 90 |" in md2, [ln for ln in md2.splitlines() if "zzz-hard" in ln])

print("%d/%d checks" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
