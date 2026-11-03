#!/usr/bin/env python3
"""v781 — the tool CONTRACT the model is given must match the one the tool enforces.

Live 2026-11-03 (session b7329cccf94c), `grep.search`:
    input  {"path": ".../sessions/9b5db7c6a45f.json", "query": "VERIFY-...", "context": 2}
    out    exit=64 missing 'pattern'; unknown argument 'query'; unknown argument 'context'

Three defects, none of them task-specific:

  A  the handler read `query` as a fallback for `pattern` while the DECLARED schema
     did not: one contract advertised, another enforced, so the gate billed a round
     for a synonym the tool itself half-accepted (a second truth);
  B  `query` is the vocabulary of every OTHER searching tool here (web/memory/
     knowledge), so the alias table must translate it instead of billing it;
  C  `context` (the lines around a hit) existed nowhere in grep, although every
     frontier Grep tool takes it — the model asked for it and got a usage error;
  D  the discovery INDEX printed a truncated prose sentence and no argument names,
     so the required name was learnable only through a second call the model
     skipped. It also claimed to be "the whole index" while capping at 60 of 153.

Deterministic and offline: temp files only, no model, no network, no server.
"""
import os
import re
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v781-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDIT_DIR", "RUNS_DIR", "GRAPH_DIR", "DATA_DIR"):
    os.environ.setdefault("LONGRUN_" + _k, os.path.join(TMP, _k))
# The battery points LONGRUN_MATRIX_SRC at an EMPTY temp dir (no Matrix tools at
# all), so a grep test would have no schema to read and would fail for the wrong
# reason. Give the test its own Matrix zone holding ONE copy of the real module:
# the dispatch path, the schema and the handler are the production ones, and the
# repository is never written to.
MSRC = os.path.join(TMP, "matrix_src")
os.makedirs(os.path.join(MSRC, "tools"), exist_ok=True)
shutil.copyfile(os.path.join(REPO, "src", "Matrix", "tools", "grep.py"),
                os.path.join(MSRC, "tools", "grep.py"))
os.environ["LONGRUN_MATRIX_SRC"] = MSRC
os.environ["LONGRUN_MATRIX_DOT"] = os.path.join(TMP, "matrix_dot")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import diag  # noqa: E402
from longrun.tools import registry  # noqa: E402
from longrun.tools import tools as T  # noqa: E402

registry._external_tools = lambda: {}

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


WORK = os.path.join(TMP, "ws")
os.makedirs(WORK, exist_ok=True)
SAMPLE = os.path.join(WORK, "sample.py")
with open(SAMPLE, "w", encoding="utf-8") as f:
    f.write("alpha\n"
            "def main():\n"
            "    TODO fix this\n"
            "    gamma\n"
            "    delta\n")

# ---- A: one vocabulary — the schema declares what the handler enforces ---------
_schema = (registry.tool_spec("grep.search") or {}).get("schema") or {}
_props = _schema.get("properties") or {}
check("A1 grep.search declares `pattern` as its required regex",
      _schema.get("required") == ["pattern"]
      and "pattern" in _props, (_schema.get("required"), sorted(_props)))
check("A2 its description names `pattern` (not a natural-language query)",
      "pattern" in (_schema.get("description") or ""), _schema.get("description"))

# ---- B: the synonym is TRANSLATED, never billed -------------------------------
check("B1 `query` becomes `pattern` on grep.search",
      T.normalize_args("grep.search", {"path": SAMPLE, "query": "TODO"})
      == {"path": SAMPLE, "pattern": "TODO"},
      T.normalize_args("grep.search", {"path": SAMPLE, "query": "TODO"}))
check("B2 the same synonym works on glob (the other `pattern` tool)",
      T.normalize_args("glob.list", {"query": "*.py"}) == {"pattern": "*.py"},
      T.normalize_args("glob.list", {"query": "*.py"}))
check("B3 a tool that DECLARES `query` keeps it untouched",
      T.normalize_args("memory.recall", {"query": "x"}) == {"query": "x"}
      and T.normalize_args("web.search", {"query": "x"}) == {"query": "x"},
      T.normalize_args("web.search", {"query": "x"}))
check("B4 a declared key is never overwritten by the synonym",
      T.normalize_args("grep.search", {"pattern": "a", "query": "b"})
      == {"pattern": "a", "query": "b"},
      T.normalize_args("grep.search", {"pattern": "a", "query": "b"}))

_res = T.execute("grep.search", {"query": "TODO", "path": SAMPLE, "workspace": WORK})
check("B5 the billed call now REACHES the tool (no usage error)",
      _res.get("ok") is True and _res.get("count") == 1
      and _res.get("exit_code") == 0,
      (_res.get("exit_code"), _res.get("error"), _res.get("stdout")))

# ---- C: `context` exists and prints the window, ripgrep style -----------------
check("C1 grep.search declares `context`",
      (_props.get("context") or {}).get("type") == "integer", _props.get("context"))
_ctx = T.execute("grep.search", {"pattern": "TODO", "path": SAMPLE,
                                 "workspace": WORK, "context": 1})
_out = str(_ctx.get("stdout") or "")
check("C2 a hit is printed as file:line:text",
      "sample.py:3:    TODO fix this" in _out, _out)
check("C3 the neighbouring lines are printed as file-line-text",
      "sample.py-2-def main():" in _out and "sample.py-4-    gamma" in _out, _out)
check("C4 `matches` still holds the HITS only (context never fakes a match)",
      [m["line"] for m in (_ctx.get("matches") or [])] == [3],
      _ctx.get("matches"))
_no_ctx = T.execute("grep.search", {"pattern": "TODO", "path": SAMPLE, "workspace": WORK})
check("C5 context=0 keeps the old one-line-per-hit output",
      str(_no_ctx.get("stdout") or "") == "sample.py:3:    TODO fix this",
      _no_ctx.get("stdout"))

# ---- D: the index is truthful and carries the REQUIRED names ------------------
_idx = diag.tools_report()
check("D1 an index entry names its REQUIRED arguments",
      (_idx.get("tools", {}).get("grep.search", {}) or {}).get("required") == ["pattern"],
      _idx.get("tools", {}).get("grep.search"))
check("D2 a tool with no required argument does not grow a noise field",
      "required" not in (_idx.get("tools", {}).get("self", {}) or {}),
      _idx.get("tools", {}).get("self"))
_names = sorted(t["name"] for t in registry.catalog() if t.get("name"))
_shown = len(_idx.get("tools") or {})
if len(_names) > _shown:
    check("D3 a capped index SAYS how many it hid",
          re.search(r"showing \d+ of \d+ tools", str(_idx.get("capped") or ""))
          and _shown < len(_names), (_shown, len(_names), _idx.get("capped")))
else:
    check("D3 a capped index SAYS how many it hid (not capped here)", True)
check("D4 the hint still points at the per-tool contract",
      "BEFORE calling a tool" in str(_idx.get("hint") or ""), _idx.get("hint"))

print("\n---")
print("v781: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
