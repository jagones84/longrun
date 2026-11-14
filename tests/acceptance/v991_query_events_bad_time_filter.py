#!/usr/bin/env python3
"""v991 — a non-numeric time filter must be IGNORED, not crash the request.

`GET /api/events?since=<anything>` passes the raw query string to
`events.query_events`, which appended the SQL fragment BEFORE converting the
value. A bad value ("xyz") therefore left `ts >= ?` in the WHERE with no bound
argument and sqlite raised `ProgrammingError: Incorrect number of bindings`, so
the HTTP handler died and the caller got a closed connection instead of a 400
(measured 2026-11-14 on the live service).

Contract:
  A) a non-numeric `since` / `until` is ignored (no exception, every row);
  B) numeric strings and numbers still filter, both bounds;
  C) the bounds combine with kind / session;
  D) an empty value means "no filter".

Deterministic: temp DB, no server, no model.
Run: python3 tests/acceptance/v991_query_events_bad_time_filter.py
"""
import json
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="v991_")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.makedirs(os.environ["LONGRUN_DATA_DIR"], exist_ok=True)
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import events as E  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def row(ts, kind, **data):
    E.db().execute("INSERT INTO events(ts, kind, data) VALUES(?,?,?)",
                   (ts, kind, json.dumps(data)))
    E.db().commit()


row(100, "chat.done", session="s1")
row(200, "tool.result", session="s1")
row(300, "chat.done", session="s2")


def ids(**kw):
    return sorted(r["ts"] for r in E.query_events(**kw))


# ---- A: a bad value is ignored, never a crash ----------------------------
try:
    got = ids(since="xyz")
    check("A1 a non-numeric since is ignored", got == [100, 200, 300], got)
except Exception as exc:  # noqa: BLE001
    check("A1 a non-numeric since is ignored", False, "%s: %s" % (type(exc).__name__, exc))
try:
    got = ids(until="later")
    check("A2 a non-numeric until is ignored", got == [100, 200, 300], got)
except Exception as exc:  # noqa: BLE001
    check("A2 a non-numeric until is ignored", False, "%s: %s" % (type(exc).__name__, exc))
try:
    got = ids(since="xyz", until="later", kind="chat.done")
    check("A3 both bad values plus a kind filter", got == [100, 300], got)
except Exception as exc:  # noqa: BLE001
    check("A3 both bad values plus a kind filter", False, "%s: %s" % (type(exc).__name__, exc))

# ---- B: real filters still work -----------------------------------------
check("B1 since (string)", ids(since="150") == [200, 300], ids(since="150"))
check("B2 until (string)", ids(until="150") == [100], ids(until="150"))
check("B3 since (number)", ids(since=150) == [200, 300], ids(since=150))
check("B4 both bounds", ids(since="100", until="200") == [100, 200],
      ids(since="100", until="200"))

# ---- C: combining with kind / session -----------------------------------
check("C1 kind filter", ids(kind="chat.done") == [100, 300], ids(kind="chat.done"))
check("C2 session filter", ids(session="s1") == [100, 200], ids(session="s1"))
check("C3 session + since + bad until",
      ids(session="s1", since="150", until="?") == [200],
      ids(session="s1", since="150", until="?"))

# ---- D: empty means no filter -------------------------------------------
check("D1 empty since", ids(since="") == [100, 200, 300], ids(since=""))
check("D2 None since", ids(since=None) == [100, 200, 300], ids(since=None))

ok = sum(RESULTS)
print("\nv991: %d/%d PASS" % (ok, len(RESULTS)))
sys.exit(0 if ok == len(RESULTS) else 1)
