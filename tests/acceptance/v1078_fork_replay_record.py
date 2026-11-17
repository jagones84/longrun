#!/usr/bin/env python3
"""v1078 — a fork records what it can and cannot replay.

DeepSeek lists "resume, fork and replay" as one capability; round 7 shipped the
fork but a fork copies WORDS, never state. S1 (arXiv:2611.11216) measures the
same gap: declared settings reconstruct 42/71 executions, an RNG reset lifts
that to 68/71, and hidden state still diverges in 4. Longrun owns neither a
model seed nor a frozen workspace, so the fork must SAY which class of replay
it is instead of implying one.

Contract:
  R1 no cards -> `transcript-only`
  R2 a definite writer (fs.write/fs.edit) -> `effects-not-restored`
  R3 only a maybe-writer (shell/python/git) -> `unverified-effects`
  R4 cards after the fork cutoff are not counted
  R5 the workspace identity is stamped (head + dirty), refreshed per fork
  R6 outside a repo the record fails open to null and never breaks the fork
  R7 the record is persisted with the session and printed by the CLI

Deterministic: temp data/config dirs, a temp git repo, no server, no model.
Run: python3 tests/acceptance/v1078_fork_replay_record.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1078-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "data", "sessions")
for d in ("data/sessions", "cfg"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import stores  # noqa: E402
from longrun.util import tracing  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


def mk(sid, cards, workspace=""):
    s = stores.get_or_create_session(sid, title=sid, workspace=workspace)
    s["messages"] = [{"role": "user", "content": "q1", "ts": 100.0},
                     {"role": "assistant", "content": "a1", "ts": 200.0},
                     {"role": "user", "content": "q2", "ts": 300.0},
                     {"role": "assistant", "content": "a2", "ts": 400.0}]
    s["tool_cards"] = [dict(c) for c in cards]
    stores.save_session(s)
    return s


# ---- R1: no cards ------------------------------------------------------------
mk("r1", [])
f1 = stores.fork_session("r1").get("session") or {}
r1 = f1.get("replay") or {}
check("R1a an empty prefix is transcript-only", r1.get("fidelity") == "transcript-only", r1)
check("R1b the counters are zero", (r1.get("cards"), r1.get("writes"),
                                    r1.get("possible")) == (0, 0, 0), r1)

# ---- R2: a definite writer ---------------------------------------------------
mk("r2", [{"tool": "fs.read", "ok": True, "ts": 150.0},
          {"tool": "fs.write", "ok": True, "ts": 250.0},
          {"tool": "fs.edit", "ok": False, "ts": 260.0}])
r2 = (stores.fork_session("r2").get("session") or {}).get("replay") or {}
check("R2a a writer means effects-not-restored",
      r2.get("fidelity") == "effects-not-restored", r2)
check("R2b both writers are counted and named",
      r2.get("writes") == 2 and r2.get("write_tools") == {"fs.edit": 1, "fs.write": 1}, r2)
check("R2c the maybe-writers stay zero", r2.get("possible") == 0, r2)

# ---- R3: only maybe-writers --------------------------------------------------
mk("r3", [{"tool": "shell.exec", "ok": True, "ts": 150.0},
          {"tool": "python.run", "ok": True, "ts": 160.0},
          {"tool": "fs.read", "ok": True, "ts": 170.0}])
r3 = (stores.fork_session("r3").get("session") or {}).get("replay") or {}
check("R3a a shell/python prefix is unverified-effects",
      r3.get("fidelity") == "unverified-effects", r3)
check("R3b shell and python are counted as possible writers",
      r3.get("possible") == 2 and r3.get("writes") == 0, r3)

# ---- R4: the cutoff ----------------------------------------------------------
mk("r4", [{"tool": "fs.read", "ok": True, "ts": 150.0},
          {"tool": "fs.write", "ok": True, "ts": 350.0}])
r4s = stores.fork_session("r4", at=2).get("session") or {}
r4 = r4s.get("replay") or {}
check("R4a a writer AFTER the cutoff is not inherited",
      r4.get("cards") == 1 and r4.get("writes") == 0
      and r4.get("fidelity") == "transcript-only", r4)
check("R4b the whole-prefix fork does count it",
      ((stores.fork_session("r4").get("session") or {}).get("replay") or {}
       ).get("fidelity") == "effects-not-restored")

# ---- R5/R6: the workspace identity ------------------------------------------
HAVE_GIT = bool(shutil.which("git"))
WS = os.path.join(TMP, "ws")
os.makedirs(WS)
if HAVE_GIT:
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    subprocess.run(["git", "init", "-q"], cwd=WS, check=True,
                   capture_output=True, env=env)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "base"],
                   cwd=WS, check=True, capture_output=True, env=env)
mk("r5", [{"tool": "fs.read", "ok": True, "ts": 150.0}], workspace=WS)
r5 = (stores.fork_session("r5").get("session") or {}).get("replay") or {}
check("R5a a clean repo stamps its head and dirty=0",
      bool(r5.get("head")) and r5.get("dirty") == 0, r5)
open(os.path.join(WS, "new.txt"), "w").write("x")
r5b = (stores.fork_session("r5").get("session") or {}).get("replay") or {}
check("R5b a dirty tree is counted", r5b.get("dirty") == 1, r5b)
if HAVE_GIT:
    subprocess.run(["git", "add", "new.txt"], cwd=WS, check=True,
                   capture_output=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "second"], cwd=WS, check=True,
                   capture_output=True, env=env)
    r5c = (stores.fork_session("r5").get("session") or {}).get("replay") or {}
    check("R5c the head is refreshed per fork, never a boot-time cache",
          r5c.get("head") and r5c.get("head") != r5.get("head")
          and r5c.get("dirty") == 0, (r5.get("head"), r5c.get("head")))
PLAIN = os.path.join(TMP, "not-a-repo")
os.makedirs(PLAIN, exist_ok=True)
mk("r6", [], workspace=PLAIN)
r6 = (stores.fork_session("r6").get("session") or {}).get("replay") or {}
check("R6a outside a repo the record fails open to null",
      r6.get("head") is None and r6.get("dirty") is None
      and r6.get("fidelity") == "transcript-only", r6)
check("R6b a missing workspace directory never breaks the fork",
      bool((stores.fork_session("r6", workspace=os.path.join(TMP, "gone"))
            .get("session") or {}).get("id")))

# ---- R7: persistence + surfaces ---------------------------------------------
saved = stores.load_session(f1.get("id")) or {}
check("R7a the record is persisted with the session",
      (saved.get("replay") or {}).get("fidelity") == "transcript-only", saved.get("replay"))
check("R7b it is JSON-safe", isinstance(json.dumps(r2), str))
CLI = open(os.path.join(REPO, "src", "longrun", "core", "forge.py"),
           encoding="utf-8").read()
SRC = open(os.path.join(REPO, "src", "longrun", "memory", "stores.py"),
           encoding="utf-8").read()
DOC = open(os.path.join(REPO, "docs", "CLI.md"), encoding="utf-8").read()
check("R7c the CLI prints it", '"replay": s.get("replay")' in CLI)
check("R7d the fork sets it", "new[\"replay\"] = replay_record(" in SRC)
check("R7e the docs name the classes", "effects-not-restored" in DOC
      and "unverified-effects" in DOC)
ABS = (stores.fork_session("r2", workspace=WS).get("session") or {}).get("replay") or {}
check("R7f an explicit workspace override wins",
      ABS.get("workspace") == WS, ABS.get("workspace"))

shutil.rmtree(TMP, ignore_errors=True)
print("\n---\nv1078: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
raise SystemExit(0 if all(RESULTS) else 1)
