#!/usr/bin/env python3
"""v177 — deleting a session removes ALL its artifacts (JAG-179).

The red X called DELETE /api/sessions/<id>, which unlinked ONLY the transcript.
The session's task graph, run metrics and edit journal (all keyed by the session
id) were left behind as orphans — 586 graph files for 76 sessions was exactly
this leak. This test proves the cascade: transcript + graph + run + edits (+ the
`.bak-*` / `.reset-*` backups) all go, and a NEIGHBOURING session is untouched.

Run:  python3 tests/v177_session_delete_cascade.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import atexit  # noqa: E402
import shutil  # noqa: E402
tmp = tempfile.mkdtemp(prefix="sf-177-")
atexit.register(lambda: shutil.rmtree(tmp, ignore_errors=True))
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(tmp, "events.db")
os.environ["LONGRUN_GRAPH_DIR"] = tmp  # taskgraph appends "graphs" itself
os.environ["LONGRUN_EDITS_DIR"] = os.path.join(tmp, "edits")
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(tmp, "runs")
for d in ("cfg", "sessions", "graphs", "edits", "runs"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

import py_compile  # noqa: E402
py_compile.compile(os.path.join(REPO, "src", "longrun", "core/server.py"), doraise=True)
print("[compile] server.py OK")

from longrun.core import server  # noqa: E402
from longrun.plan import taskgraph  # noqa: E402
from longrun.plan import goal as goal_mod  # noqa: E402
from longrun.model import runmetrics  # noqa: E402
from longrun.tools import edits  # noqa: E402


def make_artifacts(sid):
    """Create every per-session artifact + the backup variants."""
    taskgraph.ensure(sid, session_id=sid)
    runmetrics.start(sid)
    edits._save(sid, [{"path": "/tmp/x", "ts": 1, "kind": "write"}])
    goal_mod.start(sid, "the durable goal of this session")   # G-1: data/goals/<sid>.json
    open(os.path.join(tmp, "sessions", sid + ".json.bak-test"), "w").write("{}")
    open(os.path.join(tmp, "graphs", sid + ".json.reset-1"), "w").write("{}")


def paths(sid):
    return [
        os.path.join(tmp, "sessions", sid + ".json"),
        os.path.join(tmp, "sessions", sid + ".json.bak-test"),
        taskgraph._path(sid),
        taskgraph._path(sid) + ".reset-1",
        runmetrics._path(sid),
        edits._key_file(sid),
        goal_mod.path(sid),      # G-1: a deleted session must not leave its goal behind
    ]


sid = server.get_or_create_session(None, title="v177")["id"]
other = server.get_or_create_session(None, title="v177-other")["id"]
make_artifacts(sid)
make_artifacts(other)

before = [p for p in paths(sid) if os.path.isfile(p)]
print("artifacts before:", len(before), "of", len(paths(sid)))
assert len(before) == len(paths(sid)), "setup incomplete: %r" % (paths(sid),)

removed = server._purge_session_artifacts(sid)
print("removed:", len(removed), removed)

left = [os.path.basename(p) for p in paths(sid) if os.path.isfile(p)]
assert not left, "JAG-179 leak: %s survived the delete" % left

# a NEIGHBOURING session must be untouched
survivors = [os.path.basename(p) for p in paths(other) if os.path.isfile(p)]
assert len(survivors) == 7, "delete touched another session: %r" % survivors

# wiring: the HTTP DELETE handler must call the cascade helper
src = open(os.path.join(REPO, "src", "longrun", "core/server.py"), encoding="utf-8").read()
src += open(os.path.join(REPO, "src", "longrun", "core/httpapi.py"), encoding="utf-8").read()
assert "_purge_session_artifacts(sid)" in src, "DELETE handler is not wired to the cascade"

print("RESULT: ALL OK")

