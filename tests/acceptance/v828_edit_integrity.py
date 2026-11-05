#!/usr/bin/env python3
"""v828 — the edit tools cannot corrupt a file, and the wire carries one instruction (2026-11-05).

Operator: *"is the edit tool work precisely?"* — three defects found by reading it:

  A  `fs.edit` read the target with `errors="replace"` and rewrote the WHOLE file,
     so a latin-1/binary file was silently re-encoded with U+FFFD where its bytes
     did not decode. It also wrote with a plain `open(path, "w")`: a crash mid-write
     truncated the file, and an atomic replace alone would reset a 0755 script to
     0644. `fs.write`'s overwrite path had the same non-atomic write.
  B  the offloaded-observation reference told the model to read 256 KB back in one
     `fs.read` (which the observation limit immediately offloads again) or to grep
     the file with the shell (refused: the path is outside the session workspace).
  C  the batch path appended a second "Continue: …" to a text that already ended
     with one, so one message carried two different instructions.

Pinned here: A refuses non-UTF-8 without touching the file, A keeps the mode and is
atomic, A still refuses ambiguity, B names a window read that fits, C has ONE owner.

Deterministic and offline: temp dirs, no server, no model, no network.
Run: python3 tests/acceptance/v828_edit_integrity.py
"""
import os
import stat
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="v828-")
for _name, _tail in {"LONGRUN_DATA_DIR": "data", "LONGRUN_CONFIG_DIR": "cfg",
                     "LONGRUN_DB": "events.db", "LONGRUN_SESSIONS_DIR": "sessions",
                     "LONGRUN_GRAPH_DIR": "graphs"}.items():
    os.environ[_name] = os.path.join(TMP, _tail)
sys.path.insert(0, os.path.join(REPO, "src"))

# import order matters: `agent` imports `server`, which imports `agent` back.
from longrun.core import server  # noqa: E402,F401
from longrun.agent import agent as A  # noqa: E402
from longrun.tools import tools as T  # noqa: E402
from longrun.tools import registry as _reg  # noqa: E402

WS = os.path.join(TMP, "ws")
os.makedirs(WS, exist_ok=True)
_orig_spec = _reg.tool_spec


def _fake_spec(name):
    if name in ("fs.write", "fs.edit"):
        return {"roots": [WS]}
    return _orig_spec(name)


T.registry.tool_spec = _fake_spec          # v596 pattern: a writable root

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def _read_bytes(p):
    with open(p, "rb") as f:
        return f.read()


# ---- A: no silent re-encoding ------------------------------------------------
_latin = os.path.join(WS, "latin.txt")
with open(_latin, "wb") as f:
    f.write(b"caf\xe9 au lait\n")            # latin-1 é, not valid UTF-8
r = T._fs_edit({"path": _latin, "search": "caf", "replace": "tea"}, "v828")
check("A1 fs.edit refuses a non-UTF-8 file", r.get("ok") is False, r)
check("A2 it says WHY and names the honest routes",
      "not valid UTF-8" in str(r.get("error")) and "python.run" in str(r.get("error")),
      r.get("error"))
check("A3 the refused file is byte-for-byte untouched",
      _read_bytes(_latin) == b"caf\xe9 au lait\n", _read_bytes(_latin))

# ---- B: the write is atomic and keeps the mode ------------------------------
_script = os.path.join(WS, "run.sh")
with open(_script, "w", encoding="utf-8") as f:
    f.write("#!/bin/sh\necho one\n")
os.chmod(_script, 0o755)
r = T._fs_edit({"path": _script, "search": "echo one", "replace": "echo two"}, "v828")
check("B1 a valid UTF-8 edit still applies", r.get("ok") is True, r)
check("B2 the content is the edited text",
      open(_script, encoding="utf-8").read() == "#!/bin/sh\necho two\n")
check("B3 the file keeps its 0755 mode (os.replace would reset it)",
      stat.S_IMODE(os.stat(_script).st_mode) == 0o755,
      oct(stat.S_IMODE(os.stat(_script).st_mode)))

# ---- B4: ambiguity is still refused, file untouched --------------------------
_amb = os.path.join(WS, "amb.txt")
with open(_amb, "w", encoding="utf-8") as f:
    f.write("same\nsame\n")
r = T._fs_edit({"path": _amb, "search": "same", "replace": "diff"}, "v828")
check("B4 two matches without replace_all is still refused",
      r.get("ok") is False and "matches 2 times" in str(r.get("error")), r.get("error"))
check("B5 the ambiguous file is untouched",
      open(_amb, encoding="utf-8").read() == "same\nsame\n")

# ---- B6: fs.write's overwrite is atomic too ---------------------------------
_sh = os.path.join(WS, "tool.sh")
with open(_sh, "w", encoding="utf-8") as f:
    f.write("old\n")
os.chmod(_sh, 0o755)
r = T._fs_write({"path": _sh, "content": "new\n"}, "v828")
check("B6 fs.write overwrites atomically",
      r.get("ok") is True and open(_sh, encoding="utf-8").read() == "new\n", r)
check("B7 fs.write keeps the mode as well",
      stat.S_IMODE(os.stat(_sh).st_mode) == 0o755,
      oct(stat.S_IMODE(os.stat(_sh).st_mode)))

# ---- B8: the source uses the atomic writer, never a truncating open ---------
_tools_src = open(os.path.join(REPO, "src", "longrun", "tools", "tools.py"),
                  encoding="utf-8").read()
_edit_body = _tools_src.split("def _fs_edit(")[1].split("\ndef ")[0]
_write_body = _tools_src.split("def _fs_write(")[1].split("\ndef ")[0]
check("B8 fs.edit writes through the atomic helper",
      "write_text(path, new)" in _edit_body and 'open(path, "w"' not in _edit_body)
check("B9 fs.edit no longer decodes with errors='replace'",
      'open(path, "r", encoding="utf-8", errors="replace")' not in _edit_body)
check("B10 fs.write's overwrite goes through the same helper",
      "write_text(path, content)" in _write_body)

# ---- C: the offloaded-observation hint is followable ------------------------
_ref = A._offload_observation({"id": "v828"}, "shell.exec", "line\n" * 4000)
check("C1 the reference still names the full file and a preview",
      "FULL OUTPUT FILE" in _ref and "Preview — first" in _ref)
check("C2 it no longer sends the model to grep a path outside the workspace",
      "grep it with the shell tool" not in _ref and "scoped to the session workspace" in _ref)
check("C3 it names a WINDOW read that fits the observation limit",
      "start_line" in _ref and "end_line" in _ref and "max_bytes\":262144" not in _ref)

# ---- D: ONE Continue on the batch path --------------------------------------
_agent_src = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"),
                  encoding="utf-8").read()
_batch_call = _agent_src.split("obs = _apply_chat_batch(sess, act, on_event, api_v02,")[1]
_branch = _batch_call.split("continue", 1)[0]
check("D1 the batch branch injects the builder's text as-is",
      '_inject(obs, "observation")' in _branch and "Continue:" not in _branch, _branch[-200:])
_builder = _agent_src.split("def _apply_chat_batch(")[1].split("\ndef ")[0]
check("D2 the batch builder is the ONE owner of its Continue line",
      "Continue: call the next tool, delegate, or report the result." in _builder)

print("\n---")
print("v828: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
