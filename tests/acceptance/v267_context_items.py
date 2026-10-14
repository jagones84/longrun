#!/usr/bin/env python3
"""v267 — Context-panel item breakdown (JAG-267).

`context_items(session)` derives, from the session's RETAINED transcript only, the
skills / rules / web / files / other items that are still in context. Because it
reads what is STILL there, compaction drops aged-out items automatically (the panel
resets by itself) and it can never mix two sessions.

Deterministic, no live server, no network. Run: python3 tests/v267_context_items.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v267-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "DB"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.core import server as S  # noqa: E402
from longrun.tools import registry  # noqa: E402

registry._external_tools = lambda: {}

os.makedirs(S.SESSIONS_DIR, exist_ok=True)
REAL = os.path.join(TMP, "notes.md")     # JAG-272: only REAL files are listed
with open(REAL, "w", encoding="utf-8") as f:
    f.write("a real note\n")
ATTACH_PDF = os.path.join(TMP, "contract scans.pdf")
ATTACH_IMAGE = os.path.join(TMP, "diagram image.png")
ATTACH_OTHER = os.path.join(TMP, "source archive.zip")
for _path in (ATTACH_PDF, ATTACH_IMAGE, ATTACH_OTHER):
    with open(_path, "wb") as f:
        f.write(b"attachment")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


sid = "c1"
S.save_session({"id": sid, "title": sid, "messages": [
    {"role": "user", "content": "hi"},
    {"role": "user",
     "content": "The user attached the following — read/consider them FIRST:\n"
                "- file: %s\n- file: %s\n- file: %s\n\nSummarize the files."
                % (ATTACH_PDF, ATTACH_IMAGE, ATTACH_OTHER)},
    {"role": "assistant",
     "content": '{"action":"tool","tool":"fs.read","args":{"path":"%s"}}' % REAL},
    {"role": "user",
     "content": "Observation for tool web:\n[web] exit=0\nstdout: "
                "1. Foo Bar\nhttps://example.com/a\n2. Baz Qux\nhttps://example.org/b\n"},
    {"role": "assistant",
     "content": '{"action":"tool","tool":"shell","args":{"command":"ls"}}'},
    {"role": "user",
     "content": "Observation for tool skills:\n10 skill(s) matching 'x':\n"
                "  systematic-debugging :: Debug stuff\n  tdd :: Test-driven dev\n"},
]})

r = S.context_items(sid)
cats = r["categories"]
check("session is available", r["available"] is True)
web = cats["web"]
check("web: both urls captured",
      any("example.com/a" in w.get("url", "") for w in web)
      and any("example.org/b" in w.get("url", "") for w in web), str(web))
check("web: title attached to the url",
      any(w.get("label") == "Foo Bar" for w in web), str(web))
sk = [x["label"] for x in cats["skills"]]
check("skills: names parsed from the observation",
      "systematic-debugging" in sk and "tdd" in sk, str(sk))
fi = [x["path"] for x in cats["files"]]
check("files: a REAL local path is listed (url paths excluded)",
      REAL in fi and not any("example.com" in p for p in fi), str(fi))
check("files: attached PDFs, images, and other file types are listed",
      all(path in fi for path in (ATTACH_PDF, ATTACH_IMAGE, ATTACH_OTHER)), str(fi))
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    ui = f.read()
check("WebUI shows selected attachments under a separate Pending category",
      '["pending", "Pending"]' in ui and "function _pendingCtxItems()" in ui
      and "pending attachment — send a message to add it to context" in ui)
check("sending clears the Pending category before backend context refresh",
      '_attachments = []; _renderAttach(); _renderPendingCtxItems();' in ui)
ot = [x["label"] for x in cats["other"]]
check("other: non-specialised tool counted", "shell" in ot, str(ot))
check("counts mirror the lists", r["counts"]["web"] == len(web) and r["total"] >= len(web))
check("unknown session -> not available", S.context_items("nope")["available"] is False)

# reset-on-compaction: drop the web observation -> its items leave the panel
kept = [m for m in S.load_session(sid)["messages"] if "example.com" not in str(m.get("content"))]
S.save_session({"id": sid, "title": sid, "messages": kept})
r2 = S.context_items(sid)
check("web items reset when their message leaves context",
      not any("example.com" in w.get("url", "") for w in r2["categories"]["web"]),
      str(r2["categories"]["web"]))

# strict session isolation
S.save_session({"id": "c2", "title": "c2",
                "messages": [{"role": "user", "content": "see https://isolated.test/x now"}]})
check("session A never shows session B items",
      not any("isolated.test" in w.get("url", "") for w in S.context_items(sid)["categories"]["web"]))
check("session B shows its own item",
      any("isolated.test" in w.get("url", "") for w in S.context_items("c2")["categories"]["web"]))

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
