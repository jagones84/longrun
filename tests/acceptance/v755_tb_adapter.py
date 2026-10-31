#!/usr/bin/env python3
"""v755 — Longrun as an arm in Terminal-Bench (the official, end-state graded suite).

The adapter ships the runtime INTO the task container (Claw-SWE-Bench's design:
take the runtime with you), starts the server there, and drives it over REST through
`docker exec`. Three failures were paid for on 2026-10-31 and are pinned here:

1. the REST client embedded the JSON body with `%s`, so python got a dict literal and
   `json.loads` raised — every call answered with a traceback (`lr-hello`, 0%);
2. the upload shipped `src/` but not `config/`, so the harness fell back to a default
   provider base_url of `http://127.0.0.1:8080` (the operator's local router), which
   does not exist inside a container (`provider unreachable`, `lr-hello2`, 0%);
3. `hello-world` then passed end-to-end with the real model (`lr-hello3`, 100%).

Deterministic: no docker, no model, no network.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v755-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "src"))

try:
    from benchmarks import terminal_bench_agent as TB          # noqa: E402
    _IMPORT_ERR = ""
except Exception as exc:  # noqa: BLE001
    TB = None
    _IMPORT_ERR = repr(exc)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


if TB is None:
    print("FAIL the adapter module cannot be imported at all: %s" % _IMPORT_ERR)
    print("0/1 checks")
    sys.exit(1)

check("A0 the adapter defines the harness identity", TB.LongrunAgent.name() == "longrun")
if not TB.HAS_TB:
    print("NOTE terminal_bench is not installed in this python: class stand-ins active")

# ---- A. the in-container REST client is generated, not string-concatenated -----
code = TB._api_client_code("POST", "/api/sessions", {"title": "tb"})
compile(code, "<api-client>", "exec")          # raises if the program is malformed
check("A1 the generated client compiles", True)
check("A2 the JSON body is embedded as a STRING literal (repr), not as a dict",
      "_bd = '{\"title\": \"tb\"}'" in code, [ln for ln in code.splitlines() if "_bd =" in ln])
check("A3 no body means the null sentinel", "_bd = 'null'" in TB._api_client_code("GET", "/x"))
check("A4 the method and path travel verbatim",
      "method='POST'" in code and "/api/sessions" in code)

# ---- B. the agent identity and the knobs a run must state ---------------------
check("B1 tb finds the arm by its name", TB.LongrunAgent.name() == "longrun")
agent = TB.LongrunAgent(model_name="openrouter:z-ai/glm-5.3-flash", timeout=60, max_steps=7)
check("B2 the model is an explicit argument", agent.model_name == "openrouter:z-ai/glm-5.3-flash")
check("B3 timeout and step budget are honoured", (agent.timeout, agent.max_steps) == (60.0, 7))
check("B4 a harness fault must never look like a solved task",
      "FailureMode.UNKNOWN" in open(os.path.join(
          REPO, "benchmarks/terminal_bench_agent.py"), encoding="utf-8").read())

# ---- C. the upload carries the CONFIG, which is what makes the model reachable --
src = open(os.path.join(REPO, "benchmarks/terminal_bench_agent.py"), encoding="utf-8").read()
check("C1 the upload ships config/ (providers.yaml is what points at OpenRouter)",
      'REPO / "config"' in src)
check("C2 the shipped providers.yaml really names the OpenRouter endpoint",
      "https://openrouter.ai/api/v1" in open(
          os.path.join(REPO, "config/providers.yaml"), encoding="utf-8").read())

# ---- D. the suite manifest is explicit and starts with its control task --------
manifest = os.path.join(REPO, "benchmarks/terminal_bench_tasks.txt")
tasks = [ln.strip() for ln in open(manifest, encoding="utf-8")
         if ln.strip() and not ln.startswith("#")]
check("D1 the manifest has a plumbing control first", tasks[0] == "hello-world", tasks[:3])
check("D2 no task is listed twice", len(tasks) == len(set(tasks)), tasks)
check("D3 every entry is a bare task id (no paths, no flags)",
      all((" " not in t and "/" not in t) for t in tasks))
tb_home = os.environ.get("TB_HOME", "/home/jagones/Repositories/terminal-bench")
task_root = os.path.join(tb_home, "original-tasks")
if os.path.isdir(task_root):
    missing = [t for t in tasks if not os.path.isdir(os.path.join(task_root, t))]
    check("D4 every id exists in the official checkout", not missing, missing)

    def _label(task_id):
        """The benchmark's own `difficulty:` line for a task, or empty."""
        path = os.path.join(task_root, task_id, "task.yaml")
        try:
            for line in open(path, encoding="utf-8"):
                if line.startswith("difficulty:"):
                    return line.split(":", 1)[1].strip()
        except OSError:
            return ""
        return ""

    # An easy slice saturates: the alphabetically-first 10 polyglot tasks were solved
    # 10/10 by BOTH arms (2026-10-31) and ranked nothing. The same rule applies here,
    # so every scored entry must carry the benchmark's OWN hard label; hello-world is
    # the plumbing control and is never scored.
    labels = {t: _label(t) for t in tasks if t != "hello-world"}
    check("D5 every scored entry carries difficulty: hard",
          all(v == "hard" for v in labels.values()), labels)
else:
    print("SKIP D4/D5 the terminal-bench checkout is not on this machine")

# The suite is not "the official tasks": it is the official HARD tasks this host can
# actually run. A task whose oracle fails (port-compressor: its own reference solution
# trips test_no_unsafe_rust) or whose image needs x86 is not a suite member, however
# official it is. The screen table is local evidence (.agent is gitignored).
screen = os.path.join(REPO, ".agent/BENCHMARKS/tb_arm64_hard_screen.tsv")
if os.path.isfile(screen):
    verdicts = {}
    for line in open(screen, encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= 2 and parts[0] != "task":
            verdicts[parts[0]] = parts[1]  # the newest row for a task wins
    unscoped = [t for t in tasks if verdicts.get(t) != "PASS"]
    check("D6 every entry passed the arm64 oracle screen", not unscoped, unscoped)
else:
    print("SKIP D6 the arm64 screen table is not on this machine")

# ---- E. the launcher is the only entry point, and it refuses to overwrite ------
launcher = open(os.path.join(REPO, "scripts/bench-terminal-bench.sh"), encoding="utf-8").read()
check("E1 the launcher passes the adapter import path",
      "benchmarks.terminal_bench_agent:LongrunAgent" in launcher)
check("E2 it refuses an existing run folder", "refusing to reuse" in launcher)
check("E3 it exports the repo on PYTHONPATH so tb can import the adapter",
      'PYTHONPATH="$REPO"' in launcher)

# ---- F. provider key lookup: environment wins, the operator's dotenv is a fallback
os.environ["OPENROUTER_API_KEY"] = "from-env"
check("F1 the environment wins over ~/.hermes/.env",
      TB._dotenv_key("OPENROUTER_API_KEY") == "from-env")
os.environ.pop("OPENROUTER_API_KEY", None)
check("F2 a missing key is empty, never a guess", TB._dotenv_key("NO_SUCH_KEY_VAR_955") == "")

print("%d/%d checks" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
