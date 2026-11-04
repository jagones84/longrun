#!/usr/bin/env python3
"""v784 — `forge.py chat` printed nothing (and exited 1) on a SUCCESSFUL reply.

`/api/chat` answers `{"error": false, "reply": ...}` on success (httpapi.py, the
sync path). The CLI guarded with `if "error" in out:`, which is true whenever the
key is PRESENT — so every successful chat printed `error: False`, skipped the
reply, and exited 1. Measured live 2026-11-04:

    python3 forge.py chat "Reply with exactly PONG-CLI" --session 0e13bdb23c5b
    error: False                      # exit 1, no reply printed

The guard is "is the error TRUTHY", not "is the key there" — the documented exit
contract says `1` only on `{"error": ...}`, and a `False` is not an error.

  A  a successful reply prints the text and exits 0
  B  a real error still exits 1 with the message on stderr
  C  the call is the documented `POST /api/chat` with the message + session
  D  the `"error" in out` pattern is gone (chat / plan generate / history)

Deterministic: `req` is stubbed, no network, no server, no model.
"""
import contextlib
import io
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import forge  # noqa: E402

SRC = open(os.path.join(REPO, "src", "longrun", "core", "forge.py"), encoding="utf-8").read()
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


class Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def run_chat(reply_obj):
    """Drive `cmd_chat` (non-stream) with `req` stubbed; return (stdout, stderr, exit, calls)."""
    calls = {}

    def fake_req(method, path, body=None):
        calls.update(method=method, path=path, body=body)
        return reply_obj

    out, err = io.StringIO(), io.StringIO()
    code = 0
    old = forge.req
    forge.req = fake_req
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            forge.cmd_chat(Args(message="hi", session="s1", model=None, stream=False))
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    finally:
        forge.req = old
    return out.getvalue(), err.getvalue(), code, calls


# ------------------------------------------------- A: a success prints the reply --
o, e, code, calls = run_chat({"session": "s1", "error": False, "reply": "PONG-CLI"})
check("A1 a successful reply is printed", "PONG-CLI" in o, {"stdout": o, "stderr": e})
check("A2 success exits 0 (no false 'error: False')", code == 0, {"exit": code, "stderr": e})
check("A3 'error: False' is NOT printed", "error: False" not in (o + e), {"stdout": o, "stderr": e})

# ------------------------------------------------- B: a real error still fails --
o, e, code, _ = run_chat({"session": "s1", "error": "router down"})
check("B1 a real error exits 1", code == 1, {"exit": code})
check("B2 the error message reaches stderr", "router down" in e, {"stderr": e})

# ------------------------------------------------- C: the documented endpoint --
check("C1 the call is POST /api/chat", calls.get("method") == "POST" and calls.get("path") == "/api/chat",
      {k: calls.get(k) for k in ("method", "path")})
check("C2 the message + session are sent", (calls.get("body") or {}).get("message") == "hi"
      and (calls.get("body") or {}).get("session") == "s1", calls.get("body"))

# ------------------------------------------------- D: the buggy pattern is gone --
check("D1 the `\"error\" in out` pattern is gone from the CLI source", '"error" in out' not in SRC, "")
check("D2 the truthy guard is used", SRC.count('out.get("error")') >= 3, SRC.count('out.get("error")'))

print("\n---\nv784: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
