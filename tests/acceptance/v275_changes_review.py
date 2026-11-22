#!/usr/bin/env python3
"""v275 — change REVIEW flow + compact rail buttons + chat timestamps (JAG-275).

(1) The edit journal now has a REVIEW flow: a change stays PENDING until the
    operator APPROVES it (keep the file as written, drop the entry) or REJECTS it
    (`undo`: restore the pre-image / remove a created file). `edits.approve` must
    NEVER touch the file; `edits.undo` must restore it.
(2) The rail action buttons are compact, and every chat turn (user / harness /
    LLM / tool card) carries a small date+time stamp.

Deterministic, no live server. Run: python3 tests/v275_changes_review.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v275-")
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "DB"):
    os.environ["LONGRUN_" + _k] = os.path.join(TMP, _k)
for _k in ("CONFIG_DIR", "SESSIONS_DIR", "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR"):
    os.makedirs(os.environ["LONGRUN_" + _k], exist_ok=True)
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.tools import edits as E        # noqa: E402
from longrun.core import api_v02 as A      # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


key = "sess1"
made = os.path.join(TMP, "made.md")
note = os.path.join(TMP, "note.md")
with open(note, "w", encoding="utf-8") as f:
    f.write("v1\n")
with open(made, "w", encoding="utf-8") as f:
    f.write("hello\nworld\n")

with open(note, "w", encoding="utf-8") as f:
    f.write("v1\nv2\n")            # the change is ALREADY applied on disk
E.record(key, made, "", "hello\nworld\n", action="created")
E.record(key, note, "v1\n", "v1\nv2\n", action="modified")
check("two files are pending", E.summary(key)["totals"]["files"] == 2,
      str(E.summary(key)["totals"]))

# --- APPROVE one: the entry drops, the file is KEPT ---------------------------
r = E.approve(key, made)
check("approve returns ok", r.get("ok") is True, str(r))
check("approved file stays on disk (approve never rewrites)", os.path.isfile(made))
check("approved file leaves the pending list",
      all(f["path"] != made for f in E.summary(key)["files"]))
check("the other file is still pending",
      any(f["path"] == note for f in E.summary(key)["files"]))

# --- REJECT one (undo): the entry drops, the file is RESTORED -----------------
E.undo(key, note)
with open(note, encoding="utf-8") as f:
    check("rejected file is restored to its pre-image", f.read() == "v1\n")
check("rejected file leaves the pending list", E.summary(key)["totals"]["files"] == 0)

# --- REJECT a CREATED file removes it -----------------------------------------
E.record(key, made, "", "hello\nworld\n", action="created")
E.undo(key, made)
check("rejecting a created file removes it from disk", not os.path.isfile(made))

# --- APPROVE ALL keeps the files, clears the journal --------------------------
with open(note, "w", encoding="utf-8") as f:
    f.write("v1\nv2\n")            # the change is ALREADY applied on disk
with open(made, "w", encoding="utf-8") as f:
    f.write("hi\n")
E.record(key, note, "v1\n", "v1\nv2\n", action="modified")
E.record(key, made, "", "hi\n", action="created")
E.approve(key)
with open(note, encoding="utf-8") as f:
    _note_body = f.read()
check("approve all clears the journal", E.summary(key)["totals"]["files"] == 0)
check("approve all does NOT touch the files",
      _note_body == "v1\nv2\n" and open(made, encoding="utf-8").read() == "hi\n")

# --- REJECT ALL restores/removes, then clears ---------------------------------
with open(note, "w", encoding="utf-8") as f:
    f.write("v1\n")
E.record(key, note, "v1\n", "v1\nv9\n", action="modified")
E.record(key, made, "hi\n", "hi\nho\n", action="modified")
E.undo(key)
with open(note, encoding="utf-8") as f:
    _note_body2 = f.read()
check("reject all clears the journal", E.summary(key)["totals"]["files"] == 0)
check("reject all restores every file", _note_body2 == "v1\n")

# --- HTTP handlers delegate ---------------------------------------------------
E.record(key, note, "v1\n", "v1\nvZ\n", action="modified")
check("edits_approve handler -> ok", A.edits_approve({"session": key, "path": note}).get("ok") is True)
E.record(key, note, "v1\n", "v1\nvZ\n", action="modified")
check("edits_undo handler -> ok", A.edits_undo({"session": key, "path": note}).get("ok") is True)

# --- UI: compact rail buttons + chat timestamps (static source checks) --------
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    ui = f.read()
check("rail buttons are compact (scoped CSS)",
      "#inspector button.ghost { font-size: 11px" in ui)
check("panel has approve-all + reject-all", "approveEdits(null)" in ui and "rejectEdits(null)" in ui)
check("each change row has approve/reject buttons",
      'class="ghost ed-ok"' in ui and 'class="ghost ed-no"' in ui)
check("approve posts to /api/edits/approve", '"/api/edits/approve"' in ui)
check("reject posts to /api/edits/undo", '"/api/edits/undo"' in ui)
# 2026-11-22 (ROUND 177): the per-row clock was NARROWED to a date-only stamp on the
# user/agent rows only ("gli orari … elimina tutto. la data va messa … solo degli user
# messages e risposte dell'agente, non delle fasi intermedie"). `_tsSpan` is gone,
# replaced by `_dateSpan`.
check("the date-only helper exists (`_tsSpan` -> `_dateSpan`)",
      "function _dateSpan(ts)" in ui and "_tsSpan(" not in ui)
check("the date stamp is wired into the user/agent rows (who + _stampWho)",
      # `_dateSpan(` appears exactly 3 times in the source: its definition, the `who()`
      # header (the user/agent row) and `_stampWho` (the finalized live answer). >=3 is
      # the real floor, not a soft number; a narrowed-away stamp fails again.
      ui.count("_dateSpan(") >= 3, str(ui.count("_dateSpan(")))
check("history replay forwards the user date but no longer a ts into toolCard",
      # ROUND 177: the tool/thought rows carry no time, so the replay calls
      # `toolCard(v.tool, undefined)` — the ts argument is dropped.
      'who("user", m.content, m.ts, m.sender, m.subjob, m.chapter' in ui
      and "toolCard(v.tool, undefined);" in ui
      and "toolCard(v.tool, undefined, v.ts)" not in ui)

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

