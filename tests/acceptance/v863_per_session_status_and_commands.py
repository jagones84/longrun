#!/usr/bin/env python3
"""v863 — the rail tells the truth PER SESSION, and a command stays a command.

Two live reports (2026-11-07):
  * "la sidebar status non si aggiorna secondo la sessione specifica … non posso
    lanciare due etichettature su sessioni diverse in contemporanea";
  * "se scrivo /research e mando un messaggio queued, quando lo lancia non lo
    lancia come comando: lo invia come stringa".

  A) a naming run PUBLISHES its start with the session, so the rail can show WHICH
     chat is busy (`threads.named` still closes it);
  B) the in-flight guard is per SESSION: two different chats name at the same time,
     a second click on the SAME chat is refused;
  C) the composer keeps a leading `/` at position 0 (the attachment block used to
     be prepended, so the server's `_apply_skill_slash` never fired) and a command
     is never STEERED into a running turn (nothing resolves a slash there).

Deterministic: temp dirs, no model, no network.
"""
import atexit
import os
import shutil
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
tmp = tempfile.mkdtemp(prefix="sf-863-")
atexit.register(lambda: shutil.rmtree(tmp, ignore_errors=True))
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(tmp, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(tmp, "sessions")
os.environ["LONGRUN_DB"] = os.path.join(tmp, "events.db")
os.environ["LONGRUN_THREADS_DIR"] = os.path.join(tmp, "threads")
os.environ["LONGRUN_GRAPH_DIR"] = tmp
os.environ["LONGRUN_RUNS_DIR"] = os.path.join(tmp, "runs")
os.environ["LONGRUN_WORKSPACES_ROOT"] = os.path.join(tmp, "ws")
for d in ("cfg", "sessions", "threads", "runs", "ws"):
    os.makedirs(os.path.join(tmp, d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server          # noqa: E402 — breaks the import cycle
from longrun.core import httpapi as H    # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


events = []
_orig_pub = H.publish
H.publish = lambda kind, **kw: events.append(dict(kind=kind, **kw))

seen = []


def fake_name(sess, model=None, cancel=None):
    sid = (sess or {}).get("id")
    seen.append(sid)
    time.sleep(0.4)
    return {"ok": True, "session": sid, "titled": 0, "remaining": 0, "model": "fake"}


H.autoname_untitled = fake_name

r1 = H.autoname_async({"id": "v863-a", "messages": []})
r2 = H.autoname_async({"id": "v863-b", "messages": []})
r3 = H.autoname_async({"id": "v863-a", "messages": []})
check("A1 two DIFFERENT chats name at the same time",
      r1.get("started") is True and r2.get("started") is True, (r1, r2))
check("B1 a second click on the SAME chat is refused while it runs",
      r3.get("started") is False, r3)
started = [e for e in events if e.get("kind") == "threads.naming"]
check("A2 the start is published WITH the session (the rail can paint it)",
      {e.get("session") for e in started} == {"v863-a", "v863-b"}, started)

time.sleep(1.2)
done = [e for e in events if e.get("kind") == "threads.named"]
check("A3 the run closes with threads.named for each session",
      {e.get("session") for e in done} == {"v863-a", "v863-b"}, done)
check("A4 the guard is released (a later click starts again)",
      H.autoname_async({"id": "v863-a", "messages": []}).get("started") is True)
time.sleep(0.8)
H.publish = _orig_pub

src = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
check("C1 the rail tracks naming PER session", "let namingSessions = Object.create(null);" in src)
check("C2 the row paints it from the event",
      'es.addEventListener("threads.naming"' in src and "setNaming(d.session" in src)
check("C3 a command is never steered into a running turn",
      "!_isCmd && (localStorage.getItem(\"sf_qmode\")" in src)
check("C4 a command keeps position 0 (attachments go after it)",
      "_isCmd ? raw + \"\\n\\n\" + _attBlock" in src)
check("C5 the rail marker is per session, not a global busy flag",
      "row.classList.toggle(\"naming\", !!on)" in src
      and "namingSessions[sid] = true" in src)
check("C6 an attachment never displaces a command on the IMMEDIATE path",
      'msg.startsWith("/") ? msg + "\\n\\n" + _attBlock' in src)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
