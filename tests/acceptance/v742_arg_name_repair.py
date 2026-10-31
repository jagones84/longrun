#!/usr/bin/env python3
"""v742 — an argument the model knows by another name is REPAIRED, not billed.

Diagnosed 2026-10-31 from the live event DB (not from a guess): of the failing
tool calls in one day, 25 were nothing but an invented argument name —

  shell.exec          8x   `cmd`            instead of `command`
  agent.get/team.get  5x   `id` / `name`    instead of `agent` / `team`
  glob.list           2x   `path`           instead of `pattern`
  sessions.read       1x   `session_id`     instead of `session`
  fs.edit             1x   `find`           instead of `search`
  ...and web.search received `fetch` (the argument of ANOTHER tool)

Each one costs a whole round (the model must re-issue the call) and some turns
simply ended there. `_shape_notes` already NAMED the mistake with a did-you-mean;
that is diagnosis, and it is kept. This pins the repair.

  A  a declared synonym is renamed and the call reaches the tool
  B  a lone identifier-shaped key on a single-required tool is renamed
  C  an AMBIGUOUS key is never guessed (`glob.list` + `path` could be `root`)
  D  a declared key is left alone; another tool's argument name is not adopted
  E  the shell description discourages the inline heredoc (the other half of the
     same day's failures: 14 python errors inside `shell.exec`)

Deterministic and offline: the schema is read from the registry, no model, no
network, no server.
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="longrun-v742-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDIT_DIR", "RUNS_DIR", "GRAPH_DIR", "DATA_DIR"):
    os.environ.setdefault("LONGRUN_" + _k, os.path.join(TMP, _k))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import tools as T  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ---- A: a declared synonym -------------------------------------------------
_N = T.normalize_args
check("A1 `cmd` becomes `command` on the shell",
      _N("shell.exec", {"cmd": "ls -la"}) == {"command": "ls -la"},
      _N("shell.exec", {"cmd": "ls -la"}))
check("A2 the other declared keys survive the rename",
      _N("shell.exec", {"cmd": "ls", "cwd": "/tmp"}) == {"command": "ls", "cwd": "/tmp"},
      _N("shell.exec", {"cmd": "ls", "cwd": "/tmp"}))
check("A3 `session_id` becomes `session`",
      _N("sessions.read", {"session_id": "abc"}) == {"session": "abc"},
      _N("sessions.read", {"session_id": "abc"}))
check("A4 `find` becomes `search` on fs.edit",
      _N("fs.edit", {"path": "/x", "find": "a", "replace": "b"})
      == {"path": "/x", "search": "a", "replace": "b"},
      _N("fs.edit", {"path": "/x", "find": "a", "replace": "b"}))

# ---- B: a lone identifier on a single-required tool ------------------------
check("B1 `id` becomes the entity of a `*.get`",
      _N("agent.get", {"id": "A1"}) == {"agent": "A1"},
      _N("agent.get", {"id": "A1"}))
check("B2 `name` becomes `team` on team.get",
      _N("team.get", {"name": "ops"}) == {"team": "ops"},
      _N("team.get", {"name": "ops"}))
check("B3 `<req>_id` is recognised too",
      _N("job.get", {"job_id": "J7"}) == {"job": "J7"},
      _N("job.get", {"job_id": "J7"}))

# ---- C: never guess an ambiguous key ---------------------------------------
check("C1 `path` on glob.list is NOT coerced (it could be `root`)",
      _N("glob.list", {"path": "/x"}) == {"path": "/x"},
      _N("glob.list", {"path": "/x"}))
check("C2 another tool's argument name is not adopted (web.search `fetch`)",
      _N("web.search", {"fetch": "http://x"}) == {"fetch": "http://x"},
      _N("web.search", {"fetch": "http://x"}))

# ---- D: a declared key is left exactly as it is ----------------------------
check("D1 a correct call is untouched",
      _N("fs.read", {"path": "/x"}) == {"path": "/x"},
      _N("fs.read", {"path": "/x"}))
check("D2 a synonym never overwrites a key that was already supplied",
      _N("shell.exec", {"command": "ls", "cmd": "rm -rf /"})
      == {"command": "ls", "cmd": "rm -rf /"},
      _N("shell.exec", {"command": "ls", "cmd": "rm -rf /"}))
check("D3 the real call reaches the tool (no usage error, no missing args)",
      not (T.execute("shell.exec", _N("shell.exec", {"cmd": "true"})) or {})
      .get("missing_args"),
      T.execute("shell.exec", _N("shell.exec", {"cmd": "true"})))

# ---- E: the inline heredoc is discouraged where the model chooses -----------
from longrun.tools import registry as REG  # noqa: E402

_shell_desc = str(((REG.tool_spec("shell.exec") or {}).get("schema") or {})
                  .get("description") or "")
check("E1 the shell description names the file-first route",
      "python.run" in _shell_desc and "fs.write" in _shell_desc, _shell_desc[-220:])
check("E2 it names the failure it prevents",
      "SyntaxError" in _shell_desc, _shell_desc[-160:])

print("\n---")
print("v742: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
