#!/usr/bin/env python3
"""v756 — openclaw is the SECOND arm in Terminal-Bench (same tasks, same score).

Longrun had the only arm, so the official suite could compare a harness against the
ORACLE and nothing else. This pins the openclaw arm's contract, and it pins the two
facts that cost a probe to learn (2026-11-01):

1. openclaw REFUSES node 26.8.1 (`requires Node >=24.22.1 <25, or >=26.12.1`), so the
   payload pins the host's v24 node — shipping "some node" is not enough;
2. the model id is spelled differently: longrun says `openrouter:model`, openclaw says
   `openrouter/model`.

Deterministic: no docker, no model, no network.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v756-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, REPO)

import benchmarks.terminal_bench_openclaw as OC  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


SRC = open(os.path.join(REPO, "benchmarks/terminal_bench_openclaw.py"), encoding="utf-8").read()

# ---- A. identity -------------------------------------------------------------
check("A1 tb finds the arm by its name", OC.OpenClawAgent.name() == "openclaw")
agent = OC.OpenClawAgent(model_name="openrouter:z-ai/glm-5.3-flash", timeout=60)
check("A2 the model is an explicit argument",
      agent.model_name == "openrouter:z-ai/glm-5.3-flash")
check("A3 the timeout is honoured", agent.timeout == 60.0, agent.timeout)

# ---- B. the model spelling differs between the arms --------------------------
check("B1 longrun's provider:model becomes openclaw's provider/model",
      OC.openclaw_model("openrouter:z-ai/glm-5.3-flash") == "openrouter/z-ai/glm-5.3-flash",
      OC.openclaw_model("openrouter:z-ai/glm-5.3-flash"))
check("B2 a bare model id is left alone", OC.openclaw_model("z-ai/glm") == "z-ai/glm")
check("B3 empty stays empty", OC.openclaw_model("") == "")

# ---- C. the payload is the node openclaw ACCEPTS, plus its package -----------
check("C1 the payload pins a v24 node (26.x is refused by openclaw)",
      "v24." in str(OC.NODE_BIN), OC.NODE_BIN)
check("C2 that node really exists on this host", OC.NODE_BIN.is_file())
check("C3 the openclaw package exists", (OC.OC_PKG / "openclaw.mjs").is_file(), OC.OC_PKG)
check("C4 the tar carries both, at the names the run uses",
      'arcname="node"' in SRC and 'arcname="openclaw"' in SRC
      and "%s/openclaw/openclaw.mjs" in SRC)
check("C5 the payload is cached across trials (not rebuilt per container)",
      "PAYLOAD.is_file()" in SRC and "PAYLOAD.write_bytes" in SRC)

# ---- D. the run is headless, isolated, and cannot reach the host --------------
check("D1 embedded, not the gateway (a container has no gateway)",
      '"agent", "exec"' in SRC and '"--isolated"' in SRC)
check("D2 credentials come from the environment only",
      '"--auth-env-only"' in SRC and "OPENROUTER_API_KEY" in SRC)
check("D3 the prompt travels base64-encoded (no heredoc sentinel, no quoting)",
      "base64.b64encode" in SRC)
check("D4 the turn is detached and its exit code captured",
      "nohup" in SRC and "/tmp/oc/rc" in SRC)

# ---- E. a harness fault must never look like a solved task -------------------
class _Boom:
    def __init__(self):
        self.c = None


class _Sess:
    container = None


_sess = _Sess()
_sess.container = _Boom()
res = OC.OpenClawAgent().perform_task("do something", _sess)
check("E1 a broken container yields UNKNOWN, not success",
      getattr(res, "failure_mode", None) == OC.FailureMode.UNKNOWN,
      getattr(res, "failure_mode", None))
check("E2 tb's own FailureMode is used when terminal_bench is importable",
      (not OC.HAS_TB) or res.failure_mode is OC.FailureMode.UNKNOWN)

# ---- F. the launcher selects the arm and refuses an unknown one --------------
launcher = open(os.path.join(REPO, "scripts/bench-terminal-bench.sh"), encoding="utf-8").read()
check("F1 the launcher knows both arms",
      "benchmarks.terminal_bench_agent:LongrunHarness" in launcher
      and "benchmarks.terminal_bench_openclaw:OpenClawAgent" in launcher)
check("F2 an unknown arm is refused by name", "unknown ARM=" in launcher)
check("F3 the arm is a knob, not a separate script", "${ARM:-longrun}" in launcher)

print("%d/%d checks" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
