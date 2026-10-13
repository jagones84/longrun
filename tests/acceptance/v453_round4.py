#!/usr/bin/env python3
"""v453 — JAG-451 round 4: fs.read of large files, chapter [UNTITLED], sand-theme buttons.

Three operator points, each pinned deterministically (no model, no network):

  A) Offload files must hold the RAW tool payload, not the observation wrapper.
     A big `chapters`/`fs.read` output used to be written to data/offload/… WITH
     its `[tool] exit=…` header, so when the agent read it back it saw a nested
     header and could not tell where the data began. `_clean_offload` strips that
     wrapper, and the offload reference now passes a large `max_bytes` so a file
     bigger than the fs.read default is still readable in one call.

  B) `chapters list` marks every unnamed free group `[UNTITLED]`, so the agent
     finds ALL of them (its own prompt used the `title=` token, which collided
     with the render output and left groups silently untitled).

  C) The floating chat controls (reveal/focus, expand/collapse, name-threads)
     were drawn dark-on-dark in the light Sand theme (a hardcoded dark background
     + `--dim`). They now use theme tokens.

Run: python3 tests/acceptance/v453_round4.py
"""
import os
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v453-")
for _k, _v in (("CONFIG_DIR", "cfg"), ("SESSIONS_DIR", "sessions"),
               ("GRAPH_DIR", "graphs"), ("THREADS_DIR", "threads"),
               ("DATA_DIR", "data")):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _v)
    os.makedirs(os.path.join(TMP, _v), exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server           # noqa: E402  (import order: server before agent)
from longrun.agent import agent as A      # noqa: E402
from longrun.memory import stores         # noqa: E402
from longrun.memory import threads as th  # noqa: E402
from longrun.tools import registry        # noqa: E402
from longrun.tools import tools as T      # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


# ---- A: offload is clean + a large read reaches the model --------------------
wrap = ("[chapters] exit=0 backend=host sandboxed=False\n"
        "stdout: THREAD (this session) — 2 group(s)\n  #1 free [UNTITLED] …")
check("A1 _clean_offload drops the [tool] header",
      A._clean_offload(wrap).startswith("THREAD (this session)"), A._clean_offload(wrap)[:40])
check("A2 _clean_offload drops the stdout:/content: prefix",
      "[chapters]" not in A._clean_offload(wrap) and "stdout: " not in A._clean_offload(wrap))
check("A3 _clean_offload is a no-op for already-clean text",
      A._clean_offload("plain payload\n") == "plain payload\n")

# behavioral: _offload_observation writes the CLEAN text (not the wrapper)
sess = {"id": "v453-offload"}
ref = A._offload_observation(sess, "chapters", wrap)
offdir = os.path.join(TMP, "data", "offload", "v453-offload")
files = os.listdir(offdir) if os.path.isdir(offdir) else []
check("A4 the offload file is created", len(files) == 1, files)
if files:
    raw = open(os.path.join(offdir, files[0]), encoding="utf-8").read()
    check("A5 the offload file holds the CLEAN payload (no [tool] wrapper)",
          "[chapters]" not in raw and raw.startswith("THREAD (this session)"), raw[:50])
check("A6 the offload reference names the file path", "FULL OUTPUT FILE:" in ref
      and "offload/v453-offload" in ref)
check("A7 the offload reference passes a large max_bytes (reads the whole file)",
      '"max_bytes":262144' in ref, "")

# a LARGE read (well past the 1600 default) still reaches the model at the chat
# loop's real observation budget (CHAT_OBS_FULL = LONGRUN_OFFLOAD_MAX, 200000).
big = {"tool": "fs.read", "ok": True, "exit_code": 0, "backend": "host",
       "sandboxed": False, "path": "/tmp/big.txt", "content": ("x" * 79 + "\n") * 1000}
obs = T.observation(big, max_chars=200000)
check("A8 a ~80KB read is NOT truncated at the chat-loop budget",
      len(obs) >= 79000 and "x" * 79 in obs, "obs_len=%d" % len(obs))

# ---- B: chapters marks untitled free groups --------------------------------
sid = "v453-threads"
stores.save_session({"id": sid, "title": "t", "created": time.time(), "messages": []})
s = stores.load_session(sid)
stores.append_message(s, "user", "first ask")
stores.append_message(s, "assistant", "first answer")
stores.append_message(s, "user", "second ask")
stores.append_message(s, "assistant", "second answer")
groups = th.outline(sid)
check("B1 two free groups derived", len(groups) == 2
      and all(g["kind"] == "free" for g in groups), [g["kind"] for g in groups])
out = T.execute("chapters", {"session": sid, "action": "list"}, run_id=sid).get("stdout", "")
check("B2 untitled free groups are flagged [UNTITLED] in list",
      out.count("free [UNTITLED]") == 2, out[:140])
T.execute("chapters", {"session": sid, "action": "title", "id": groups[0]["id"],
                       "title": "request to first"}, run_id=sid)
out = T.execute("chapters", {"session": sid, "action": "list"}, run_id=sid).get("stdout", "")
check("B3 after titling one, exactly one [UNTITLED] remains", out.count("free [UNTITLED]") == 1)
desc = (registry.TOOL_SCHEMAS.get("chapters") or {}).get("description", "")
check("B4 the chapters schema teaches the [UNTITLED] marker", "[UNTITLED]" in desc)

# ---- C: sand-theme button contrast -----------------------------------------
html = _read("webui", "index.html")
check("C1 the floating chat controls no longer use a hardcoded dark background",
      "background: rgba(20,24,40,.72)" not in html)
check("C2 the controls use var(--txt) on var(--panel2) (visible on the light Sand theme)",
      "#treeTools button {" in html and "background: var(--panel2)" in html
      and "color: var(--txt)" in html)
check("C3 the nameThreads prompt points at the [UNTITLED] marker",
      "explicit [UNTITLED] marker" in html)

# ---- D: pre-compaction auto-naming + a visible compaction card --------------
# (Compaction is triggered at 70% of the model budget, read from config/compaction.yaml.)
from longrun.model import compaction_config as cc   # noqa: E402
from longrun.model import rllm                      # noqa: E402
check("D1 the trigger threshold lives in config/compaction.yaml (70%)",
      float(cc.load()["trigger_pct"]) == 70.0 and float(rllm.AUTOCOMPACT_PCT) == 70.0,
      cc.load()["trigger_pct"])
check("D2 the target_pct is also file-driven", float(rllm.AUTOCOMPACT_TARGET_PCT) == 30.0)

# the safety net: every untitled free group gets a deterministic name + summary
sid4 = "v453-titles"
stores.save_session({"id": sid4, "title": "t", "created": time.time(), "messages": []})
s4 = stores.load_session(sid4)
stores.append_message(s4, "user", "please audit the longrun codebase for bugs")
stores.append_message(s4, "assistant", "on it")
stores.append_message(s4, "user", "now summarise the book report")
stores.append_message(s4, "assistant", "done")
untitled = [g for g in th.outline(sid4) if g["kind"] == "free" and not g.get("title")]
check("D3 two free groups start untitled", len(untitled) == 2, len(untitled))
n_named = th.autotitle_untitled(sid4)
check("D4 autotitle_untitled names every untitled free group", n_named == 2, n_named)
titles = [g.get("title") or "" for g in th.outline(sid4) if g["kind"] == "free"]
check("D5 the derived title reads 'request to …'", all(t.startswith("request to ") for t in titles),
      titles)
check("D6 it is idempotent (a second pass names nothing new)",
      th.autotitle_untitled(sid4) == 0)
check("D7 a model-set title is never overwritten",
      (th.set_title(sid4, th.outline(sid4)[0]["id"], "keep me")[0],
       th.autotitle_untitled(sid4),
       th.outline(sid4)[0]["title"])[2] == "keep me")
# prepare_session_for_turn names BEFORE compacting
_api = _read("src", "longrun", "core", "httpapi.py")
check("D8 prepare_session_for_turn auto-titles before it compacts",
      _api.index("autotitle_untitled") < _api.index("compact_session(sess[\"id\"], target"),
      "")
check("D9 an auto-compaction drops a user-visible card at the tail of the chat",
      '{"kind": "compact", "text": sys_marker' in _api)

print("---")
okc = sum(results)
print("\nv453: %d/%d PASS" % (okc, len(results)))
sys.exit(0 if okc == len(results) else 1)
