#!/usr/bin/env python3
"""v346 — fs.read observations must carry the file CONTENT (regression).

Root cause of a real, silent failure: tools.observation() rendered stdout / stderr
/ path but NEVER `content`. fs.read returns its payload in `content`, so every
fs.read reached the model as an EMPTY observation (exit=0, no error) — the agent
was blind to every file it read, and to the "read more with fs.read" offload files
the harness told it to open. A weak model then fumbles an otherwise easy task.

Deterministic, no model. Run: python3 tests/acceptance/v346_fs_read_observation.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import tools  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


# --- A: the observation of an fs.read result includes the CONTENT -------------
res = {"tool": "fs.read", "ok": True, "exit_code": 0, "backend": "host",
       "sandboxed": False, "path": "/tmp/x.kt",
       "content": "package com.x\nfun main() { println(42) }\n", "bytes": 38}
obs = tools.observation(res)
check("A1 fs.read observation includes the content", "fun main() { println(42) }" in obs,
      repr(obs)[:200])
check("A2 it still names the path", "/tmp/x.kt" in obs, "")

# --- B: end-to-end through the real fs.read implementation -------------------
live = tools._fs_read({"path": "setup.cfg"}, "v346")
check("B1 _fs_read returns ok with content",
      live.get("ok") is True and "mutmut" in (live.get("content") or ""),
      "bytes=%s" % live.get("bytes"))
check("B2 the observation of that read carries 'mutmut'", "mutmut" in tools.observation(live), "")

# --- C: no regression for stdout/stderr tools --------------------------------
obs_shell = tools.observation({"tool": "shell", "ok": True, "exit_code": 0,
                               "backend": "host", "sandboxed": False,
                               "stdout": "HELLO-STDOUT", "stderr": "warn-err"})
check("C1 shell stdout is still rendered", "HELLO-STDOUT" in obs_shell, "")
check("C2 shell stderr is still rendered", "warn-err" in obs_shell, "")

# --- D: truncation still bounded (content cannot flood the context) ----------
big = {"tool": "fs.read", "ok": True, "exit_code": 0, "backend": "host",
       "sandboxed": False, "path": "/tmp/big", "content": "x" * 100000}
check("D1 a huge read is truncated to the budget",
      len(tools.observation(big, max_chars=800)) < 1200, "")

# --- E: fs.read can return a LINE RANGE, not only a byte prefix (JAG-509) ----
# Reading lines 40-60 of a large file used to mean guessing byte offsets and
# eye-filtering a truncated dump. The tool now takes a 1-based inclusive range.
import tempfile as _tf  # noqa: E402

_tmp = _tf.mkdtemp(prefix="v346-lines-")
_fixture = os.path.join(_tmp, "lines.txt")
with open(_fixture, "w", encoding="utf-8") as _f:
    _f.write("".join("line %d\n" % i for i in range(1, 11)))
_orig_spec = tools.registry.tool_spec
tools.registry.tool_spec = lambda name: ({"roots": [_tmp]} if name == "fs.read"
                                         else _orig_spec(name))
try:
    _part = tools._fs_read({"path": _fixture, "start_line": 3, "end_line": 5}, "v346")
    _head = tools._fs_read({"path": _fixture, "end_line": 2}, "v346")
    _tail = tools._fs_read({"path": _fixture, "start_line": 9}, "v346")
    _whole = tools._fs_read({"path": _fixture}, "v346")
    _past = tools._fs_read({"path": _fixture, "start_line": 50}, "v346")
    _capped = tools._fs_read({"path": _fixture, "start_line": 1, "max_bytes": 8}, "v346")
finally:
    tools.registry.tool_spec = _orig_spec

check("E1 a line range returns exactly those lines",
      _part.get("ok") is True and _part.get("content") == "line 3\nline 4\nline 5\n"
      and _part.get("start_line") == 3 and _part.get("end_line") == 5
      and _part.get("returned_lines") == 3 and _part.get("total_lines") == 10
      and _part.get("truncated") is False, str(_part)[:240])
check("E2 an end_line alone reads from line 1 and is not a byte prefix",
      _head.get("content") == "line 1\nline 2\n" and _head.get("end_line") == 2, "")
check("E3 an open-ended range runs to the last line",
      _tail.get("content") == "line 9\nline 10\n" and _tail.get("end_line") == 10
      and _tail.get("truncated") is False, str(_tail.get("content")))
check("E4 no range still returns the whole file",
      _whole.get("content") == "".join("line %d\n" % i for i in range(1, 11)), "")
check("E5 a range past EOF is an honest empty read (not a crash, not junk)",
      _past.get("ok") is True and _past.get("content") == ""
      and _past.get("returned_lines") == 0 and _past.get("total_lines") == 10,
      str(_past)[:200])
check("E6 the byte budget still caps a line range",
      _capped.get("ok") is True and len(_capped.get("content") or "") <= 8
      and _capped.get("truncated") is True, str(_capped)[:200])

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

