#!/usr/bin/env python3
"""v1006 — the DSML argument dialects deepseek-flash actually emits.

Live 2026-11-15 (session `fd98ee64e89f`, model `deepseek:deepseek-flash`):
139 tool cards, 18 failures, and 15 of them had ONE cause — the arguments were
written in a dialect the parser did not read. The model then repeated the same
shape ten times, and every retry was rejected as a usage error:

  A. `<parameter name="args">{…}</parameter>` with a SIBLING
     `<parameter name="tool">shell.exec</parameter>`. The old unwrap required
     `len(args) == 1`, so the envelope reached the tool as
     "unknown argument 'args'" / "unknown argument 'tool'".

  B. The arguments on their own marked tag, as a JSON value:
     `<… args="{"path": "/…", "start_line": 3010}"…>`. The attribute regex
     stopped at the first inner quote, so `args` became '{' or ''.

  C. The same tag with a bare attribute: `<… command="cd … | head -3"…>`.
     Only <parameter> children were read, so `args` was {} and every call failed
     "missing REQUIRED command".

Locked here, against the real parser (`agent._extract_action`) and the real
normalizer (`tools.normalize_args`). Deterministic, no model, no network.
Run: python3 tests/acceptance/v1006_dsml_argument_dialects.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1006-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(TMP, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(TMP, "runs")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as _s  # noqa: E402,F401  (server bootstraps agent)
from longrun.agent import agent as a  # noqa: E402
from longrun.tools import tools as t  # noqa: E402

D = "\uff5c\uff5cDSML\uff5c\uff5c"
OPEN = "<" + D
CLOSE = "</" + D

# A — the JSON envelope plus a sibling `tool` parameter (raw session shape).
ENVELOPE = (OPEN + ' calls>\n'
            + OPEN + ' invoke name="shell.exec">\n'
            + OPEN + ' parameter name="args">{"command": "cd /tmp && ls | head -3"}</'
            + D + ' parameter>\n'
            + OPEN + ' parameter name="tool">shell.exec</' + D + ' parameter>\n'
            + CLOSE + ' invoke>\n' + CLOSE + ' calls>')

# B — arguments as a JSON attribute on their own marked tag (raw session shape).
BODY_JSON = (OPEN + ' calls>\n'
             + OPEN + ' invoke name="fs.read">\n'
             + OPEN + ' args="{"path":"/tmp/a.py","start_line":3010,"end_line":3075}"'
             + D + '>\n'
             + CLOSE + ' invoke>\n' + CLOSE + ' calls>')

# C — a bare attribute, no <parameter> at all (raw session shape).
BODY_BARE = (OPEN + ' calls>\n'
             + OPEN + ' invoke name="shell.exec">\n'
             + OPEN + ' command="cd /tmp && ls -la | head -3"' + D + '>\n'
             + CLOSE + ' invoke>\n' + CLOSE + ' calls>')

# D — a scalar JSON attribute (memory.recent in the same session).
BODY_NUM = (OPEN + ' calls>\n'
            + OPEN + ' invoke name="memory.recent">\n'
            + OPEN + ' args="{"limit": 12}"' + D + '>\n'
            + CLOSE + ' invoke>\n' + CLOSE + ' calls>')

# E — well-formed parameters must stay untouched.
WELL_FORMED = (OPEN + ' calls>\n'
               + OPEN + ' invoke name="fs.write">\n'
               + OPEN + ' parameter name="path">/tmp/b.txt</' + D + ' parameter>\n'
               + OPEN + ' parameter name="content">hello\nworld</' + D + ' parameter>\n'
               + CLOSE + ' invoke>\n' + CLOSE + ' calls>')

# F — `git` REALLY takes `args` as a string; it must not be unwrapped.
GIT_ARGS = (OPEN + ' calls>\n'
            + OPEN + ' invoke name="git">\n'
            + OPEN + ' parameter name="args">status --short</' + D + ' parameter>\n'
            + CLOSE + ' invoke>\n' + CLOSE + ' calls>')

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ---- A: envelope + sibling tool -------------------------------------------
act = a._extract_action(ENVELOPE) or {}
args = act.get("args") or {}
check("A1 the envelope is unwrapped to shell.exec",
      act.get("tool") == "shell.exec" and act.get("action") == "tool", str(act)[:160])
check("A2 `command` is the real value",
      args.get("command") == "cd /tmp && ls | head -3", repr(args.get("command"))[:120])
check("A3 no `args`/`tool` key survives the unwrap",
      "args" not in args and "tool" not in args, sorted(args))

# ---- B: JSON attribute on a marked body tag --------------------------------
act = a._extract_action(BODY_JSON) or {}
args = act.get("args") or {}
check("B1 body `args=\"{…}\"` is decoded, not truncated",
      act.get("tool") == "fs.read" and args.get("path") == "/tmp/a.py", str(args)[:160])
check("B2 numeric arguments keep their type",
      args.get("start_line") == 3010 and args.get("end_line") == 3075, str(args))

# ---- C: bare attribute -----------------------------------------------------
act = a._extract_action(BODY_BARE) or {}
args = act.get("args") or {}
check("C1 a bare `command=\"…\"` is an argument",
      act.get("tool") == "shell.exec"
      and args.get("command") == "cd /tmp && ls -la | head -3", str(args)[:160])

# ---- D: scalar JSON attribute ---------------------------------------------
act = a._extract_action(BODY_NUM) or {}
args = act.get("args") or {}
check("D1 `args=\"{\"limit\": 12}\"` yields {\"limit\": 12}",
      act.get("tool") == "memory.recent" and args.get("limit") == 12, str(args))

# ---- E: no regression on the parameter dialect ----------------------------
act = a._extract_action(WELL_FORMED) or {}
args = act.get("args") or {}
check("E1 well-formed parameters are untouched",
      act.get("tool") == "fs.write" and args.get("path") == "/tmp/b.txt"
      and args.get("content") == "hello\nworld", str(args)[:160])

# ---- F: a real `args` string is not unwrapped ----------------------------
act = a._extract_action(GIT_ARGS) or {}
args = act.get("args") or {}
check("F1 git keeps its string `args`",
      act.get("tool") == "git" and args.get("args") == "status --short", str(args))

# ---- G: the normalizer, independent of the DSML parser -------------------
fixed = t.normalize_args("shell.exec", {"args": '{"command": "echo hi"}',
                                        "tool": "shell.exec"})
check("G1 normalize_args decodes a string envelope and drops `tool`",
      fixed == {"command": "echo hi"}, str(fixed))
kept = t.normalize_args("self", {"tool": "fs.read"})
check("G2 a tool that DECLARES `tool` keeps it (self.tools)",
      kept == {"tool": "fs.read"}, str(kept))

# ---- H: nothing ever carries the wire marker ----------------------------
markers = [v for text in (ENVELOPE, BODY_JSON, BODY_BARE, BODY_NUM, WELL_FORMED, GIT_ARGS)
           for v in ((a._extract_action(text) or {}).get("args") or {}).values()]
check("H1 no parsed argument contains the wire marker",
      all(D not in json.dumps(v) for v in markers), len(markers))

print("---")
okc = sum(results)
print("v1006: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
