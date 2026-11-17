#!/usr/bin/env python3
"""v1076 — fork a session at a message: a NEW branch, the source untouched.

DeepSeek's harness lists "append-only session log you can resume, fork and replay"
as the walk-away capability Longrun still lacked (`.agent/docs/reference/
harness-strengths.md`, P2). Resume and rewind exist; a FORK did not. A fork is what
makes an A/B arm possible: the same prefix, a different model, with the source
transcript never rewritten.

Contract:
  K1 `messages[:at]` is copied; the source keeps every message
  K2 only the tool cards BEFORE the cutoff are copied (a later card is not inherited)
  K3 the fork has a new id, its own agent, and `forked_from`/`fork_at` provenance
  K4 `at=None` copies the whole transcript; `at=0` copies nothing
  K5 `model`/`title`/`workspace` can be overridden; the rest is inherited
  K6 an out-of-range/ non-integer `at` and an unknown session are refused
  K7 the HTTP route, the CLI verb and the docs exist

Deterministic: temp data/config dirs, no server, no model, no network.
Run: python3 tests/acceptance/v1076_session_fork.py
"""
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1076-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "data", "sessions")
for d in ("data/sessions", "cfg"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import stores  # noqa: E402
from longrun.agent import agents as agents_mod  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


SRC = "fork-src"
s = stores.get_or_create_session(SRC, title="Source", workspace="/tmp/ws-src")
s["model"] = "m1"
s["messages"] = [
    {"role": "user", "content": "q1", "ts": 100.0},
    {"role": "assistant", "content": "a1", "ts": 200.0},
    {"role": "user", "content": "q2", "ts": 300.0},
    {"role": "assistant", "content": "a2", "ts": 400.0},
]
s["tool_cards"] = [
    {"tool": "fs.read", "ok": True, "ts": 150.0},
    {"tool": "shell.exec", "ok": False, "exit_code": 1, "ts": 350.0},
]
stores.save_session(s)

# ---- K1/K2/K3: a prefix fork -----------------------------------------------
r = stores.fork_session(SRC, at=2)
f = r.get("session") or {}
check("K1a the prefix is copied", [m.get("content") for m in f.get("messages", [])]
      == ["q1", "a1"], f.get("messages"))
check("K1b the source keeps every message",
      len((stores.load_session(SRC) or {}).get("messages") or []) == 4)
check("K2 only the card before the cutoff is copied",
      [c.get("tool") for c in (f.get("tool_cards") or [])] == ["fs.read"],
      f.get("tool_cards"))
_aid = (agents_mod.REGISTRY.get(f.get("id")) or {}).get("id")
check("K3a a new id and its own agent", bool(f.get("id")) and f["id"] != SRC
      and bool(_aid) and _aid != (agents_mod.REGISTRY.get(SRC) or {}).get("id"),
      (f.get("id"), _aid))
check("K3b provenance is recorded",
      f.get("forked_from") == SRC and f.get("fork_at") == 2, f)
check("K3c the source is byte-stable in title/workspace/model",
      (stores.load_session(SRC) or {}).get("title") == "Source"
      and (stores.load_session(SRC) or {}).get("model") == "m1")

# ---- K4: whole transcript / empty prefix -----------------------------------
r_all = stores.fork_session(SRC)
check("K4a at=None copies everything",
      r_all.get("fork_at") == 4 and len(r_all["session"]["messages"]) == 4
      and len(r_all["session"].get("tool_cards") or []) == 2, r_all.get("fork_at"))
r0 = stores.fork_session(SRC, at=0)
check("K4b at=0 copies nothing",
      r0.get("fork_at") == 0 and r0["session"]["messages"] == []
      and not r0["session"].get("tool_cards"), r0.get("session"))

# ---- K5: overrides ----------------------------------------------------------
ro = stores.fork_session(SRC, at=4, title="arm B", model="m2", workspace="/tmp/ws-b")
fo = ro.get("session") or {}
check("K5 overrides win over the inherited values",
      fo.get("title") == "arm B" and fo.get("model") == "m2"
      and fo.get("workspace") == "/tmp/ws-b", fo)
check("K5b the inherited title gets no suffix when one is given",
      "fork" not in (fo.get("title") or ""), fo.get("title"))
check("K5c a default title says it is a fork",
      "(fork)" in ((stores.fork_session(SRC).get("session") or {}).get("title") or ""))

# ---- K6: refusals -----------------------------------------------------------
check("K6a out of range is refused, never clamped",
      stores.fork_session(SRC, at=9).get("ok") is False)
check("K6b a non-integer at is refused",
      stores.fork_session(SRC, at="x").get("ok") is False
      and stores.fork_session(SRC, at=True).get("ok") is False)
check("K6c an unknown session is refused",
      stores.fork_session("no-such-session").get("ok") is False)
check("K6d a traversal-shaped id is refused",
      stores.fork_session("../etc/passwd").get("ok") is False)

# ---- K7: the surfaces exist -------------------------------------------------
HTTP = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"),
            encoding="utf-8").read()
CLI = open(os.path.join(REPO, "src", "longrun", "core", "forge.py"),
           encoding="utf-8").read()
DOC = open(os.path.join(REPO, "docs", "CLI.md"), encoding="utf-8").read()
check("K7a the HTTP route exists",
      'path.endswith("/fork")' in HTTP and "fork_session(sid" in HTTP)
check("K7b the CLI verb exists", '"fork"' in CLI and 'sessions fork' in DOC)
check("K7c the endpoint is documented", "/api/sessions/<id>/fork" in DOC)

shutil.rmtree(TMP, ignore_errors=True)
print("\n---\nv1076: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
raise SystemExit(0 if all(RESULTS) else 1)
