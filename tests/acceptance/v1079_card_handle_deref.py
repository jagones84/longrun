#!/usr/bin/env python3
"""v1079 — a manifest handle dereferences to the tool card it names.

Round 8 put a mechanical MANIFEST into the compacted view, but a row was a dead
end: the model could read `shell.exec FAILED (exit=1)` and had no handle to the
record behind it (Folio L3, arXiv:2611.16627). Round 10 mints a short `id` on
every new card, prints `#<handle>` in the manifest, and accepts both that id and
`t<ms>` (a card persisted before ids) in ONE resolver used by the HTTP filter,
the CLI and the `sessions` tool.

Contract:
  C1 every new card gets a short unique id
  C2 the handle is the id, else `t<ms>` for a legacy card
  C3 every manifest row carries its handle, failures included
  C4 the resolver accepts `id`, `#id`, `t<ms>`; unknown/empty -> None
  C5 the surfaces exist: HTTP `?card=`, CLI `sessions card`, tool action, docs
  C6 the CLI prints the card it fetched (the path is exactly the filter)

Deterministic: temp data/config dirs, no server, no model.
Run: python3 tests/acceptance/v1079_card_handle_deref.py
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1079-")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "data", "sessions")
os.environ["LONGRUN_CLI_STATE"] = os.path.join(TMP, "cli_session.json")
for d in ("data/sessions", "cfg"):
    os.makedirs(os.path.join(TMP, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import stores  # noqa: E402
from longrun.model import context_engine as CE  # noqa: E402
from longrun.core import forge  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ---- C1: the id is minted ----------------------------------------------------
s = stores.get_or_create_session("cards", title="cards", workspace="")
a = stores.persist_tool_card(s, "shell.exec", False, args={"cmd": "false"},
                             error="boom", exit_code=1, after=0)
b = stores.persist_tool_card(s, "fs.read", True, args={"path": "x"}, after=0)
check("C1a a card carries a short id", isinstance(a.get("id"), str)
      and len(a["id"]) == 8 and all(ch in "0123456789abcdef" for ch in a["id"]), a)
check("C1b two cards never share an id", a.get("id") != b.get("id"))

# ---- C2: the handle ----------------------------------------------------------
LEGACY = {"tool": "fs.write", "ok": True, "ts": 150.0}
check("C2a with an id the handle is the id", CE.card_handle(a) == a["id"])
check("C2b a legacy card falls back to t<ms>", CE.card_handle(LEGACY) == "t150000",
      CE.card_handle(LEGACY))
check("C2c a card with neither id nor ts has no handle",
      CE.card_handle({"tool": "x"}) == "" and CE.card_handle(None) == "")

# ---- C3: the manifest rows carry it -----------------------------------------
_b = CE.manifest_block([LEGACY, a])
check("C3a a legacy row prints its t-handle", "#t150000 fs.write ok" in _b, _b)
check("C3b a new row prints its id and the failure", ("#%s shell.exec FAILED" % a["id"]) in _b, _b)
check("C3c the prefix says the handle is a dereference",
      "sessions card" in CE.MANIFEST_PREFIX, CE.MANIFEST_PREFIX)
LOW = {"id": "deadbeef", "tool": "fs.write", "ok": True, "ts": 0.5}
_out, _st = CE.compact([{"role": "user", "content": "q", "ts": 1.0},
                        {"role": "assistant", "content": "a", "ts": 2.0}],
                       100000, keep_recent=1, force=True, manifest=[LOW])
_summary = (_out[0].get("content") or "") if _out else ""
check("C3d the compacted summary carries a handle end to end",
      "#deadbeef fs.write ok" in _summary, (_st.get("manifest"), _summary[-200:]))

# ---- C4: the resolver --------------------------------------------------------
SESS = {"tool_cards": [LEGACY, a]}
check("C4a id and #id resolve", stores.card_by_handle(SESS, a["id"]) is a
      and stores.card_by_handle(SESS, "#" + a["id"]) is a)
check("C4b the legacy t-handle resolves", stores.card_by_handle(SESS, "t150000") is LEGACY)
check("C4c unknown, empty and None resolve to None",
      stores.card_by_handle(SESS, "nope") is None
      and stores.card_by_handle(SESS, "") is None
      and stores.card_by_handle(SESS, None) is None)
check("C4d a non-dict card is skipped, not fatal",
      stores.card_by_handle({"tool_cards": ["x", a]}, a["id"]) is a)

# ---- C5: the surfaces --------------------------------------------------------
HTTP = open(os.path.join(REPO, "src", "longrun", "core", "httpapi.py"), encoding="utf-8").read()
TOOLS = open(os.path.join(REPO, "src", "longrun", "tools", "tools.py"), encoding="utf-8").read()
FORGE = open(os.path.join(REPO, "src", "longrun", "core", "forge.py"), encoding="utf-8").read()
DOC = open(os.path.join(REPO, "docs", "CLI.md"), encoding="utf-8").read()
check("C5a the HTTP filter exists",
      'qs.get("card")' in HTTP and "card_by_handle(sess" in HTTP
      and "no card with that handle" in HTTP)
check("C5b the tool action exists", 'action in ("card", "tool")' in TOOLS
      and "card_by_handle(server.load_session" in TOOLS)
check("C5c the CLI verb exists", 'args.action == "card"' in FORGE
      and '"card"' in FORGE)
check("C5d the docs name the verb and the handle forms",
      "sessions card HANDLE" in DOC and "t<ms>" in DOC
      and "card=<handle>" in DOC)

# ---- C6: the CLI prints the card it fetched ---------------------------------
class Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


CARD = {"id": a["id"], "tool": "shell.exec", "ok": False, "exit_code": 1,
        "args": "{\"cmd\": \"false\"}", "error": "boom", "result": ""}
calls = []


def fake_req(method, path, body=None, **kw):
    calls.append((method, path))
    return {"session": "s1", "card": CARD}


out, err = io.StringIO(), io.StringIO()
old_req, old_cur = forge.req, forge._current_session
forge.req, forge._current_session = fake_req, (lambda: "s1")
try:
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        forge.cmd_sessions(Args(action="card", value=a["id"], workspace=None,
                                at=None, title=None, model=None))
    code = 0
except SystemExit as e:
    code = e.code if isinstance(e.code, int) else 1
finally:
    forge.req, forge._current_session = old_req, old_cur
check("C6a it asks for exactly that card",
      calls == [("GET", "/api/history?session=s1&card=%s" % a["id"])], calls)
check("C6b it prints the card", code == 0 and '"error": "boom"' in out.getvalue(), out.getvalue())
calls.clear()
out2, err2 = io.StringIO(), io.StringIO()
code2 = 0
forge.req, forge._current_session = fake_req, (lambda: "s1")
try:
    with contextlib.redirect_stdout(out2), contextlib.redirect_stderr(err2):
        forge.cmd_sessions(Args(action="card", value="", workspace=None,
                                at=None, title=None, model=None))
except SystemExit as e:
    code2 = e.code if isinstance(e.code, int) else 1
finally:
    forge.req, forge._current_session = old_req, old_cur
check("C6c a missing handle is a usage error, not a request",
      code2 == 2 and calls == [] and "usage:" in err2.getvalue(),
      (code2, calls, err2.getvalue()))

shutil.rmtree(TMP, ignore_errors=True)
print("\n---\nv1079: %d/%d PASS" % (sum(RESULTS), len(RESULTS)))
raise SystemExit(0 if all(RESULTS) else 1)
