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

Then the operator asked how a modern IDE edits (*"how moder IDE code edit files?"*)
and wanted the same class of tool. Section E pins the 2026-11-06 upgrade:

  E  a line WINDOW (`start_line`/`end_line`) so a huge file is patched without
     restating it, a BATCH (`edits: [...]`) applied all-or-nothing, `dry_run`, and
     the Claude-Code stale guard (a file that moved on disk after `fs.read` is
     refused unless `force=true`). Both caps are `config/tools.yaml` -> `limits:`.

Pinned here: A refuses non-UTF-8 without touching the file, A keeps the mode and is
atomic, A still refuses ambiguity, B names a window read that fits, C has ONE owner,
E never writes partially and never edits a stale view.

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
    if name in ("fs.write", "fs.edit", "fs.read"):
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

# ---- E: window, batch, dry run, stale guard (2026-11-06) --------------------
_w = os.path.join(WS, "window.py")
with open(_w, "w", encoding="utf-8") as f:
    f.writelines(["value = 1\n"] * 30)
r = T._fs_edit({"path": _w, "search": "value = 1", "replace": "value = 2",
                "start_line": 10, "end_line": 10}, "v828")
check("E1 a line window makes a 30x-repeated search unambiguous",
      r.get("ok") is True and r.get("replacements") == 1, r)
_wl = open(_w, encoding="utf-8").read().splitlines()
check("E2 only the line inside the window changed",
      _wl[9] == "value = 2" and _wl[0] == "value = 1" and _wl[29] == "value = 1",
      (_wl[0], _wl[9], _wl[29]))
r = T._fs_edit({"path": _w, "search": "not_here_at_all", "replace": "x",
                "start_line": 20, "end_line": 25}, "v828")
check("E3 a search outside the window is a miss that names the window",
      r.get("ok") is False and "not found" in str(r.get("error"))
      and "lines 20-25" in str(r.get("error")), r.get("error"))

_b = os.path.join(WS, "batch.txt")
with open(_b, "w", encoding="utf-8") as f:
    f.write("alpha\nbeta\ngamma\n")
r = T._fs_edit({"path": _b, "edits": [{"search": "alpha", "replace": "A"},
                                      {"search": "gamma", "replace": "G"}]}, "v828")
check("E4 a batch applies every row", r.get("ok") is True and r.get("edits") == 2
      and r.get("per_edit") == [1, 1], r)
check("E5 the batched text is the edited one",
      open(_b, encoding="utf-8").read() == "A\nbeta\nG\n")
r = T._fs_edit({"path": _b, "edits": [{"search": "beta", "replace": "B"},
                                      {"search": "nope", "replace": "x"}]}, "v828")
check("E6 a batch with one bad row writes NOTHING",
      r.get("ok") is False and "edit 2" in str(r.get("error")), r.get("error"))
check("E7 the file still holds the pre-batch text",
      open(_b, encoding="utf-8").read() == "A\nbeta\nG\n")
r = T._fs_edit({"path": _b, "search": "beta", "replace": "B", "dry_run": True}, "v828")
check("E8 dry_run reports the change and writes nothing",
      r.get("ok") is True and r.get("dry_run") is True and r.get("replacements") == 1
      and open(_b, encoding="utf-8").read() == "A\nbeta\nG\n", r)
_old_cap = os.environ.get("LONGRUN_FS_EDIT_MAX_EDITS")
os.environ["LONGRUN_FS_EDIT_MAX_EDITS"] = "1"
try:
    r = T._fs_edit({"path": _b, "edits": [{"search": "A", "replace": "a"},
                                          {"search": "G", "replace": "g"}]}, "v828")
    check("E9 the batch cap is a config value", r.get("ok") is False
          and "fs_edit_max_edits" in str(r.get("error")), r.get("error"))
finally:
    if _old_cap is None:
        os.environ.pop("LONGRUN_FS_EDIT_MAX_EDITS", None)
    else:
        os.environ["LONGRUN_FS_EDIT_MAX_EDITS"] = _old_cap
r = T._fs_edit({"path": _b}, "v828")
check("E10 a call with neither search nor edits is refused", r.get("ok") is False, r)

# the Claude-Code stale guard: a file that moved after fs.read is not edited
_s = os.path.join(WS, "stale.txt")
with open(_s, "w", encoding="utf-8") as f:
    f.write("one\n")
check("E11 fs.read succeeds and stamps the file",
      T._fs_read({"path": _s}, "v828").get("ok") is True)
_st = os.stat(_s)
os.utime(_s, ns=(_st.st_atime_ns, _st.st_mtime_ns + 5_000_000_000))
r = T._fs_edit({"path": _s, "search": "one", "replace": "two"}, "v828")
check("E12 an edit on a file changed since fs.read is refused",
      r.get("ok") is False and r.get("stale") is True, r)
check("E13 the refused edit left the file alone",
      open(_s, encoding="utf-8").read() == "one\n")
r = T._fs_edit({"path": _s, "search": "one", "replace": "two", "force": True}, "v828")
check("E14 force=true edits the version the model holds",
      r.get("ok") is True and open(_s, encoding="utf-8").read() == "two\n", r)
with open(_s, "w", encoding="utf-8") as f:
    f.write("three\n")
T._fs_read({"path": _s}, "v828")
_st = os.stat(_s)
os.utime(_s, ns=(_st.st_atime_ns, _st.st_mtime_ns + 5_000_000_000))
r = T._fs_write({"path": _s, "content": "four\n"}, "v828")
check("E15 fs.write refuses a stale overwrite too",
      r.get("ok") is False and r.get("stale") is True, r)
_old_guard = os.environ.get("LONGRUN_FS_EDIT_STALE")
os.environ["LONGRUN_FS_EDIT_STALE"] = "0"
try:
    T._fs_read({"path": _s}, "v828")
    _st = os.stat(_s)
    os.utime(_s, ns=(_st.st_atime_ns, _st.st_mtime_ns + 5_000_000_000))
    r = T._fs_write({"path": _s, "content": "five\n"}, "v828")
    check("E16 the stale guard is switchable from config", r.get("ok") is True, r)
finally:
    if _old_guard is None:
        os.environ.pop("LONGRUN_FS_EDIT_STALE", None)
    else:
        os.environ["LONGRUN_FS_EDIT_STALE"] = _old_guard

_schema = (_orig_spec("fs.edit") or {}).get("schema") or {}
check("E17 the schema advertises the new arguments",
      all(k in (_schema.get("properties") or {})
          for k in ("edits", "start_line", "end_line", "dry_run", "force"))
      and bool(_schema.get("anyOf")))

print("\n---")
print("v828: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
sys.exit(0 if all(RESULTS) else 1)
