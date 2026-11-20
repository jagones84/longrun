#!/usr/bin/env python3
"""v1241 — the DSML marker drift that made the harness tell a LIE (A8 "Master", 2026-11-21).

Operator: *"it was not true that the harness was saying in that case A8 master, why it
said so? fix, after diagnosis"*. The model drifted its native markup: it wrote a stray
`>` right after the marker and/or DOUBLED the marker before the tag name
(``<|DSML|> invoke name="tool">``, ``<|DSML|> <|DSML|> parameter name="tool">``), and it
closed a parameter with the marker ALONE (``python.run|DSML|>``, no `</`).

Every tag regex required the name right after the marker (``<|DSML| invoke``), so it saw
no `<invoke>`/`<parameter>`, `_dsml_action` returned None, and the loop told the model
"it named no tool the harness can run" — FALSE: the reply named a real tool
(`python.run`, a registered tool). The regexes now accept the drifted prefix and the bare
close, and the retry note says the truth ("could not parse").

Deterministic: source strings, no server, no model, no network.
Run: python3 tests/acceptance/v1241_dsml_marker_drift.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1241-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "ROLES_DIR"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server  # noqa: E402,F401 — resolve the agent<->server import cycle
from longrun.agent import agent as A  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


B = "\uff5c"                 # the full-width bar
M = B + B + "DSML" + B + B   # the `<|DSML|>` marker token


def act(text):
    return A._extract_action(text)


# ── A: the EXACT drifted reply (stray `>` after the marker + DOUBLED marker) ──
DRIFT = ("<" + M + " calls>\n" + "<" + M + ">\n"
         "<" + M + "> invoke name=\"tool\">\n"
         "<" + M + "> <" + M + "> parameter name=\"tool\">python.run</" + M + "></" + M + ">\n"
         "<" + M + "> <" + M + "> parameter name=\"args\" string=\"false\">{\"code\": \"print(1)\"}</" + M + "></" + M + ">\n"
         "</" + M + "></" + M + ">\n" + "</" + M + "></" + M + "> calls>")
_a = act(DRIFT)
check("A1 the drifted markup is still recognised as DSML", A._looks_like_dsml(DRIFT))
check("A2 it parses to the tool it NAMES (python.run) — NOT None",
      isinstance(_a, dict) and _a.get("tool") == "python.run", _a)
check("A3 ... with its arguments decoded",
      isinstance(_a, dict) and (_a.get("args") or {}).get("code") == "print(1)",
      (_a or {}).get("args"))

# ── B: the BARE marker close (no `</`) variant ───────────────────────────────
BARE = ("<" + M + " calls>\n" + "<" + M + ">\n"
        "<" + M + "> <" + M + "> parameter name=\"tool\">python.run" + M + ">\n"
        "<" + M + "> <" + M + "> parameter name=\"args\" string=\"false\">{\"code\": \"x\"}" + M + ">\n"
        "</" + M + "></" + M + ">")
_b = act(BARE)
check("B1 a parameter closed by the bare marker still names the tool",
      isinstance(_b, dict) and _b.get("tool") == "python.run", _b)
check("B2 ... with a clean value (the markup is not part of the arg)",
      isinstance(_b, dict) and (_b.get("args") or {}).get("code") == "x", (_b or {}).get("args"))

# ── C: the ORIGINAL working dialect is unchanged (regression guard) ──────────
OK = ("<" + M + " calls>\n"
      "<" + M + " invoke name=\"tool\">\n"
      "<" + M + " parameter name=\"tool\">shell.exec</" + M + " parameter>\n"
      "<" + M + " parameter name=\"args\" string=\"false\">{\"command\": \"ls\"}</" + M + " parameter>\n"
      "</" + M + " invoke>\n</" + M + " calls>")
_c = act(OK)
check("C1 the original working dialect still parses (no regression)",
      isinstance(_c, dict) and _c.get("tool") == "shell.exec", _c)

# ── D: the retry note no longer claims the falsehood ─────────────────────────
_SRC = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8").read()
check("D1 the retry says it could not PARSE (not the false 'named no tool')",
      "the harness could not parse into a tool call" in _SRC
      and "named no tool the harness can run" not in _SRC)

print("\n---\nv1241: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
