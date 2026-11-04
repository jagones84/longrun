#!/usr/bin/env python3
"""v791 — the invalid-reply threshold is CONFIG, not a constant (I-1).

`INVALID_REPLY_CAP = 4` (agent.py:316) drove SIX decision sites plus one report
string, so the operator could not tune the recovery behaviour measured on
2026-11-02 (session 777378644e9c). Its sibling knob `dispatch_wait_secs` already
lives in `config/tools.yaml` runtime (v783); this one was missed. The constant
stays as the documented FALLBACK, so a config-less run is byte-identical.

Contract locked here:
  * `keepgoing.DEFAULTS` and `config/tools.yaml` both carry `invalid_reply_cap: 4`;
  * `agent.invalid_reply_cap(cfg)` resolves explicit cfg -> env -> config file ->
    DEFAULTS, and floors at 1 (the retry is a safety valve, never off);
  * the three-way strategy switch (`retry` / `selfcheck` / `prose`) happens at the
    CONFIGURED cap, not at 4;
  * the loop DOES read the knob (the pure function keeps its default argument).

Deterministic, no live model, no network, no server.

Run: python3 tests/acceptance/v791_invalid_reply_cap_config.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v791-")
CFG = os.path.join(TMP, "cfg")
os.makedirs(CFG, exist_ok=True)
os.environ["LONGRUN_CONFIG_DIR"] = CFG
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = os.path.join(TMP, "graphs")
os.environ["LONGRUN_PROJECTS_DIR"] = os.path.join(TMP, "projects")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server                # noqa: E402,F401 — breaks the import cycle
from longrun.plan import keepgoing             # noqa: E402
from longrun.agent import agent                # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _agent_src():
    with open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
              encoding="utf-8") as fh:
        return fh.read()


# ---- A. the knob exists in BOTH owners -------------------------------------
check("A1 keepgoing.DEFAULTS carries invalid_reply_cap = 4",
      keepgoing.DEFAULTS.get("invalid_reply_cap") == 4,
      repr(keepgoing.DEFAULTS.get("invalid_reply_cap")))

try:
    with open(os.path.join(REPO, "config", "tools.yaml"), encoding="utf-8") as fh:
        _yaml = fh.read()
except OSError as e:  # pragma: no cover
    _yaml = ""
    print("WARN cannot read config/tools.yaml: %s" % e)
check("A2 config/tools.yaml documents invalid_reply_cap: 4",
      "\n  invalid_reply_cap: 4" in _yaml, "")

# ---- B. the resolver: cfg -> env -> file -> DEFAULTS ----------------------
check("B1 the reader exists", hasattr(agent, "invalid_reply_cap"))
check("B2 explicit cfg wins", agent.invalid_reply_cap({"invalid_reply_cap": 7}) == 7,
      repr(getattr(agent, "invalid_reply_cap", None)))

os.environ["LONGRUN_INVALID_REPLY_CAP"] = "9"
check("B3 env overrides the config file", agent.invalid_reply_cap({}) == 9)
check("B4 cfg still beats env",
      agent.invalid_reply_cap({"invalid_reply_cap": 3}) == 3)
os.environ.pop("LONGRUN_INVALID_REPLY_CAP", None)

check("B5 an empty cfg falls back to the shipped 4",
      agent.invalid_reply_cap({}) == 4, repr(agent.invalid_reply_cap({})))

# a REAL config file: `registry.CONFIG_YAML` is the ONE owner of the path (it is
# anchored to the repo, NOT to `LONGRUN_CONFIG_DIR`), so the test redirects it to a
# temp file instead of touching the shipped one.
import longrun.tools.registry as reg   # noqa: E402
_orig_yaml = reg.CONFIG_YAML
tmp_yaml = os.path.join(TMP, "tools_override.yaml")
with open(tmp_yaml, "w", encoding="utf-8") as fh:
    fh.write("runtime:\n  invalid_reply_cap: 6\n")
reg.CONFIG_YAML = tmp_yaml
reg.load_config(reload=True)
check("B6 the config file is read by keepgoing.cfg()",
      int(keepgoing.cfg().get("invalid_reply_cap")) == 6,
      repr(keepgoing.cfg().get("invalid_reply_cap")))
check("B7 the reader follows the config file",
      agent.invalid_reply_cap({}) == 6, repr(agent.invalid_reply_cap({})))

# ---- C. the floor: 1, 0 and None are never "off" --------------------------
check("C1 cap 0 floors at 1", agent.invalid_reply_cap({"invalid_reply_cap": 0}) == 1)
check("C2 a negative cap floors at 1",
      agent.invalid_reply_cap({"invalid_reply_cap": -5}) == 1)
check("C3 None in cfg is ignored, not a crash",
      agent.invalid_reply_cap({"invalid_reply_cap": None}) == 6,
      repr(agent.invalid_reply_cap({"invalid_reply_cap": None})))
check("C4 a garbage value never raises",
      agent.invalid_reply_cap({"invalid_reply_cap": "abc"}) in (4, 6),
      repr(agent.invalid_reply_cap({"invalid_reply_cap": "abc"})))

# ---- D. the strategy switch happens at the CONFIGURED cap ------------------
check("D1 below the cap -> retry", agent._after_invalid_reply(3, 0, True, cap=4) == "retry")
check("D2 at the cap with a self-check left -> selfcheck",
      agent._after_invalid_reply(4, 1, True, cap=4) == "selfcheck")
check("D3 at the cap with nothing left -> prose",
      agent._after_invalid_reply(4, 1, False, cap=4) == "prose")
check("D4 a raised cap keeps retrying past 4",
      agent._after_invalid_reply(5, 1, True, cap=6) == "retry")
check("D5 the switch moves with the cap",
      agent._after_invalid_reply(6, 1, True, cap=6) == "selfcheck")
check("D6 and still ends in prose",
      agent._after_invalid_reply(6, 1, False, cap=6) == "prose")

# ---- E. the LOOP reads the knob, the pure function keeps its default -------
_src = _agent_src()
check("E1 the loop reads the knob once per turn",
      "_invalid_cap = invalid_reply_cap(" in _src, "")
check("E2 the decision sites use the knob",
      _src.count("_invalid_cap)") >= 3, "count=%d" % _src.count("_invalid_cap)"))
check("E3 the decision path uses the knob, not the constant",
      _src.count("_invalid_streak - _invalid_cap + 1") == 3
      and _src.count("- INVALID_REPLY_CAP + 1") == 0,
      "knob=%d const=%d" % (_src.count("_invalid_streak - _invalid_cap + 1"),
                            _src.count("- INVALID_REPLY_CAP + 1")))
check("E4 the pure default is still the constant",
      "_after_invalid_reply(streak, selfcheck_left, unfinished, cap=INVALID_REPLY_CAP)"
      in _src, "")

print("%d/%d checks" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
