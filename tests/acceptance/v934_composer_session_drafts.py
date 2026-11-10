#!/usr/bin/env python3
"""v934 — the message box keeps an UNSENT draft per session.

Operator (2026-11-10): *"se scrivo un draft e non lo invio, poi cambio sessione devo
ritrovare il draft che c'era nell'altra sessione ... cosi i draft che metto nei chat
box non scompaiono"*.

Contract:
  A) the draft is keyed by the SESSION id and pruned with the live sessions;
  B) it is saved while typing, on blur and on page hide — a switch right after a
     keystroke cannot lose the last word;
  C) a session switch flushes the outgoing text and sets the box to the INCOMING
     session's draft (empty when it has none) — text never leaks across sessions;
  D) sending/queueing clears the entry, so a sent message never comes back;
  E) restoring never overwrites text already in the box (boot path);
  F) the storage stays ONE map in the WebUI: no backend field, no second key.

A) - F) are read from the shipped file; the same functions are then EXECUTED in
node when it is available (the WebUI is vanilla JS, so the block can run against a
stub localStorage). Without node the behavioural half prints SKIP and the static
contract still pins the wiring.

Run: python3 tests/acceptance/v934_composer_session_drafts.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def src(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


UI = src("webui", "index.html")

BEGIN = "/* ---- composer drafts:"
END = "/* ---- end composer drafts ---- */"
block = ""
if BEGIN in UI and END in UI:
    block = UI[UI.index(BEGIN):UI.index(END)]

# ---- A: one map, keyed by the session ----------------------------------------
check("A1 the draft is ONE localStorage map named sf_drafts",
      '_draftStorageKey = "sf_drafts";' in UI and UI.count('"sf_drafts"') == 1,
      "hits=%d" % UI.count('"sf_drafts"'))
check("A2 the map is pruned against the live session list (like scroll/todo state)",
      "_pruneDraftState(out.sessions);" in UI
      and "function _pruneDraftState(sessions) {" in UI
      and "if (!live.has(sid)) { delete map[sid]; changed = true; }" in UI)
check("A3 no backend draft field exists (the session record is untouched)",
      not re.search(r'"draft"\s*:', src("src", "longrun", "memory", "stores.py")))

# ---- B: saved while typing, on blur, on page hide ----------------------------
check("B1 each keystroke schedules a save",
      'refreshSendBtn(); _draftSaveSoon(sessionId); });' in UI)
check("B2 leaving the box flushes the pending save",
      '$("inp").addEventListener("blur", () => { _draftSaveSoon(sessionId); _draftFlush(); });' in UI)
check("B3 a hidden/closing tab flushes too",
      'window.addEventListener("pagehide"' in UI and 'if (document.hidden) { _draftSaveSoon(sessionId); _draftFlush(); }' in UI)
check("B4 the save is debounced, not a write per keystroke",
      "_draftTimer = setTimeout(() => { _draftTimer = null; _draftFlush(); }, 250);" in UI)

# ---- C: a switch moves the text with the session -----------------------------
check("C1 selectSession flushes the OUTGOING session and swaps the box",
      "const _fromSid = sessionId;" in UI and "_draftSwap(_fromSid, s.id);" in UI)
check("C2 a new chat starts empty (the old draft never rides along)",
      "const _prevSid = sessionId;" in UI and "_draftSwap(_prevSid, s.id);" in UI)
check("C3 the boot path restores the stored draft",
      "_draftRestore(sessionId);" in UI)

# ---- D: the text left the box -> the entry is gone ---------------------------
check("D1 every place that empties the composer clears its draft",
      UI.count("_draftClear(sessionId)") == 3, "%d sites" % UI.count("_draftClear(sessionId)"))
check("D2 only a send FROM the box clears it (a flushed queue item must not delete the draft)",
      "if (text === undefined) _draftClear(sessionId);" in UI)

# ---- E/F: guards -------------------------------------------------------------
check("E1 restoring refuses a non-empty box",
      "if (String(inp.value || \"\").trim()) return false;" in UI)
check("F1 an oversized paste is not stored (never truncated)",
      "v.trim() && v.length <= _DRAFT_MAX" in UI and "_DRAFT_MAX = 100000" in UI)

# ---- Behavioural half: run the shipped block in node -------------------------
if not block:
    check("G0 the draft block is present and delimited", False, "markers missing")
elif not shutil.which("node"):
    print("SKIP the draft functions were not executed (node not installed)")
else:
    harness = r"""
// stubs: the block only needs a storage, the box and three repaint helpers
const _store = Object.create(null);
globalThis.localStorage = {
  getItem: k => (k in _store ? _store[k] : null),
  setItem: (k, v) => { _store[k] = String(v); },
  removeItem: k => { delete _store[k]; },
};
const _box = { value: "", style: {} };
globalThis.$ = id => (id === "inp" ? _box : null);
globalThis.sessionId = "s1";
globalThis._growInp = () => {};
globalThis._renderCmdChips = () => {};
globalThis.refreshSendBtn = () => {};
globalThis.window = { addEventListener: () => {} };
globalThis.document = { addEventListener: () => {}, hidden: false };

__BLOCK__

const out = [];
const t = (name, ok, detail) => out.push({ name, ok: !!ok, detail: detail === undefined ? "" : String(detail) });

// 1 type + switch away + come back
_box.value = "ri eccoti.";
_draftSaveSoon("s1"); _draftFlush();
t("G1 the typed text is stored under its session id", !!JSON.parse(_store.sf_drafts || "{}").s1);
_draftSwap("s1", "s2");
t("G2 switching to a session with no draft EMPTIES the box (no leak)", _box.value === "", _box.value);
_draftSwap("s2", "s1");
t("G3 coming back restores it", _box.value === "ri eccoti.", _box.value);

// 2 isolation: type a different paragraph in the OTHER session, then go back
_draftSwap("s1", "s2");          // now in s2
_box.value = "second draft";     // typed while s2 is the active session
_draftSaveSoon("s2"); _draftFlush();
_draftSwap("s2", "s1");
t("G4 coming back to s1 shows s1's own text", _box.value === "ri eccoti.", _box.value);
_draftSwap("s1", "s2");
t("G5 and s2 kept its own", _box.value === "second draft", _box.value);

// 3 sent -> gone
_box.value = "";
_draftClear("s1");
_draftSwap("s2", "s1");
t("G6 a sent message never comes back", _box.value === "", _box.value);

// 4 boot restore never overwrites what is being typed
_draftSave("s3", "old");
_box.value = "typing now";
t("G7 boot restore refuses a non-empty box", _draftRestore("s3") === false && _box.value === "typing now", _box.value);
_box.value = "";
t("G8 and restores into an empty one", _draftRestore("s3") === true && _box.value === "old", _box.value);

// 5 whitespace + cap
_draftSave("s4", "   \n  ");
t("G9 a whitespace-only draft is dropped", !JSON.parse(_store.sf_drafts || "{}").s4);
_draftSave("s5", "x".repeat(_DRAFT_MAX + 1));
t("G10 an over-cap paste is not stored", !JSON.parse(_store.sf_drafts || "{}").s5);

// 6 delete -> pruned
const map0 = JSON.parse(_store.sf_drafts || "{}");
map0.dead = "orphan"; _store.sf_drafts = JSON.stringify(map0);
_pruneDraftState([{ id: "s1" }, { id: "s2" }, { id: "s3" }]);
const map1 = JSON.parse(_store.sf_drafts || "{}");
t("G11 deleting a session drops its draft, live ones stay",
  !("dead" in map1) && "s3" in map1, JSON.stringify(map1));

// 7 one key, one map
t("G12 the whole feature is a single localStorage key", Object.keys(_store).join(",") === "sf_drafts", Object.keys(_store).join(","));

console.log(JSON.stringify(out));
"""
    harness = harness.replace("__BLOCK__", block)
    js = os.path.join(tempfile.mkdtemp(prefix="v934_"), "harness.js")
    with open(js, "w", encoding="utf-8") as f:
        f.write(harness)
    run = subprocess.run(["node", js], capture_output=True, text=True, timeout=60)
    if run.returncode != 0:
        check("G0 the shipped draft block runs in node", False, (run.stderr or "").strip()[:400])
    else:
        try:
            rows = json.loads(run.stdout.strip().splitlines()[-1])
        except Exception as e:  # noqa: BLE001
            rows = []
            check("G0 the node harness returns its results", False, "%s :: %s" % (e, run.stdout[:200]))
        for r in rows:
            check(r["name"], r["ok"], r["detail"])

print("\nv934: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
