#!/usr/bin/env python3
"""v1067 — the session's FILE is one tap away (JAG-933).

Operator: *"a way to copy the session file (absolute path) so you have the path in
hand and can hand it to another agent — look at the chat in this path … a copy
placed in the right point of the WebUI, at the top near the other one (copy name),
always an icon, no text."*

Two halves:

  A) Behavioural — the server hands out the REAL path: `list_sessions()` carries
     `path`, the absolute transcript file of that row, on THIS host (`LONGRUN_DATA_DIR`
     is a machine setting, so the browser cannot derive it), and the path is a ROW
     field only: it never reaches the document, so `save_session` cannot persist it
     into every transcript on disk.
  B) Static — the WebUI header hosts a drawn icon-only button beside the name copy,
     the click copies the SERVER's string, and with no known path it refuses
     (toasts) instead of putting something made up on the clipboard.

Deterministic: isolated temp dirs, no model, no network.
Run: python3 tests/acceptance/v1067_session_path_copy.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v1067-")
SESSIONS = os.path.join(TMP, "sessions")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_SESSIONS_DIR"] = SESSIONS
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
for _d in ("cfg", "sessions", "data"):
    os.makedirs(os.path.join(TMP, _d), exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.memory import stores       # noqa: E402

with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as _f:
    HTML = _f.read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def row(sid):
    return next((r for r in stores.list_sessions() if r.get("id") == sid), {})


def js_body(name):
    """The source of `function <name>(…) { … }` — whitespace-normalised so a check
    reads the CODE, not the line breaks."""
    i = HTML.find("function " + name + "(")
    if i < 0:
        return ""
    j = HTML.find("\n}", i)
    return " ".join(HTML[i:j if j > 0 else len(HTML)].split())


# --- A) the row carries the real, absolute transcript path --------------------
SID_A, SID_B = "jag933a", "jag933b"
for _sid, _title in ((SID_A, "copy my path"), (SID_B, "and mine")):
    stores.save_session({"id": _sid, "title": _title,
                         "messages": [{"role": "user", "content": "hi " + _sid},
                                      {"role": "assistant", "content": "ok"}]},
                        truncate=True)

r_a, r_b = row(SID_A), row(SID_B)
expect_a = os.path.join(os.path.realpath(SESSIONS), SID_A + ".json")
check("A1 the session row carries an absolute `path`",
      bool(r_a.get("path")) and os.path.isabs(r_a["path"]), r_a.get("path"))
check("A2 that path is the transcript THIS session owns",
      os.path.realpath(r_a.get("path") or "") == os.path.realpath(expect_a),
      "%r != %r" % (r_a.get("path"), expect_a))
check("A3 the file really is the session (it is readable and names the id)",
      os.path.isfile(r_a.get("path") or "")
      and json.load(open(r_a["path"], encoding="utf-8")).get("id") == SID_A, "")
check("A4 two sessions do not share a path",
      r_b.get("path") and r_b["path"] != r_a["path"], r_b.get("path"))
check("A5 the path is a ROW field, never a document field (save_session would persist it)",
      "path" not in stores.load_session(SID_A)
      and "path" not in json.load(open(expect_a, encoding="utf-8")), "")
check("A6 a session that predates the field still lists its path",
      all(os.path.isabs(r.get("path") or "") for r in stores.list_sessions()), "")

# --- B) the WebUI: an icon button beside the name copy, copying SERVER truth ---
i_copy = HTML.find('id="chatHeadCopy"')
i_path = HTML.find('id="chatHeadPath"')
check("B1 the header hosts the session-file button",
      'id="chatHeadPath"' in HTML and i_copy > 0 and i_path > i_copy, i_path)
check("B2 it is icon-only and icon-DRAWN (no glyph character standing in for an icon)",
      "<svg viewBox=\"0 0 24 24\"" in HTML[i_path:i_path + 700]
      and "⧉" not in HTML[i_path:i_path + 700], "")
check("B3 it is named for screen readers and for the pointer",
      'aria-label="copy session file path"' in HTML
      and 'title="copy the session file path"' in HTML, "")
check("B4 the icon inherits the button's colour and keeps a 24px tap target",
      "#chatHead .ch-copy svg { display: block; width: 16px; height: 16px; }" in HTML
      and 'stroke="currentColor"' in HTML[i_path:i_path + 700], "")
check("B5 the click copies the path the SERVER reported, never a rebuilt one",
      "_sessPath[s.id] = s.path || \"\"" in HTML
      and "_sessPath[sessionId]" in js_body("_copySessionPath"), js_body("_copySessionPath"))
check("B6 the copy goes through the shared clipboard helper",
      "copyText(p)" in js_body("_copySessionPath"), "")
check("B7 an unknown path is refused out loud, not copied empty",
      "session file path unavailable" in js_body("_copySessionPath"), "")
check("B8 the button is wired at init",
      '$("chatHeadPath"); if (_chp) _chp.onclick = _copySessionPath;' in HTML, "")
check("B9 no path is derived in the browser (the data home is a server setting)",
      "/data/sessions" not in HTML and "SESSIONS_DIR" not in HTML, "")
check("B10 the name copy is untouched beside it",
      "_copySessionName" in HTML and '$("chatHeadCopy"); if (_chc) _chc.onclick' in HTML, "")

print("---")
print("%d/%d PASS" % (sum(results), len(results)))
raise SystemExit(0 if all(results) else 1)
