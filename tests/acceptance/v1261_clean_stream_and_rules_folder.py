#!/usr/bin/env python3
"""v1261 — a TRAE-clean transcript, and the project rules FOLDER loaded whole.

Operator (2026-11-22, round 177): *"guarda che orrore gli orari e gli exit code e la roba a
destra nel chat stream elimina tutto. la data va messa sulla sinistra e solo degli user
messages e risposte dell'agente, non delle fasi intermedie. così è più pulito."*; *"perché
dopo thought aumenta la spaziatura nel thread? perché wrote non ha sulla destra il file che
ha scritto come edit e read?"*; *"vengono caricate tutte, non solo project_rules … proprio
come fa trae … nel RH panel … hyperlink che me li apre nell'editor"*.

  A  the stream carries no clock, no exit code, no right meta
  B  a date-only stamp on the LEFT of user messages and agent answers only
  C  a Thought row keeps the transcript rhythm (no 16px message gap)
  D  a written file keeps its path in the persisted card (valid JSON under the cap)
  E  every `.md` of the project rules folder is loaded and listed as a link

Deterministic and offline. Run: python3 tests/acceptance/v1261_clean_stream_and_rules_folder.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))


def src(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


UI = src("webui", "index.html")
STORES = src("src", "longrun", "memory", "stores.py")
RULES = src("src", "longrun", "memory", "rules.py")
TOOLS_YAML = src("config", "tools.yaml")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)[:240]) if detail and not ok else ""))


def between(text, start, end):
    i = text.find(start)
    return text[i:text.find(end, i)] if i >= 0 else ""


# ---- A: the stream shows no clock / exit code / right meta ------------------
check("A1 no timestamp helper survives in the WebUI",
      "_tsSpan" not in UI.replace("`_tsSpan` printed MM-DD HH:MM:SS on every row", ""))
TOOL = between(UI, "function toolCard(tool, args) {", "function toggleTool(")
check("A2 a tool row has no meta cell, no stamp, and keeps the diff stat",
      "tc-meta" not in TOOL and "_dateSpan" not in TOOL and "tc-stat" in TOOL)
check("A3 no exit code / backend / summary is painted in the row",
      'data.exit_code' not in TOOL and 'exit " +' not in TOOL)
INJ = between(UI, "det.innerHTML = '<summary><span class=\"tc-ic\"", "det.querySelector(\".hrole\")")
check("A4 a harness injection carries no stamp either",
      "_dateSpan" not in INJ and "mts" not in INJ)
check("A5 the row's right side is the diff stat, and an in-flight row pulses its glyph",
      ".toolcard .tc-stat { margin-left: auto;" in UI
      and ".toolcard.pending .tc-ic { animation: thpulse" in UI)

# ---- B: one date, on the left, messages only --------------------------------
DATE = between(UI, "function _dateSpan(ts) {", "function _stampWho(")
check("B1 the stamp is a DATE (YYYY-MM-DD), never a clock",
      "getFullYear()" in DATE and "getHours" not in DATE and "getMinutes" not in DATE)
WHO = between(UI, "function who(role, text, ts", "  const b = d.querySelector(\".bubble\");")
check("B2 the message header puts the date FIRST (left) and then the label",
      "_dateSpan(ts) +" in WHO and WHO.find("_dateSpan(ts)") < WHO.find("who-lbl"))
check("B3 a live answer is stamped when the server finalizes it",
      "_stampWho(curAns, d.ts || (Date.now() / 1000));" in UI)
check("B4 the answer header is left-aligned (the copy keeps `margin-left:auto`)",
      ".msg.ai .who { justify-content: flex-start;" in UI
      and ".msg .copy { margin-left: auto;" in UI)

# ---- C: a Thought row does not grow the thread ------------------------------
check("C1 every thought wrapper is the `think` variant",
      UI.count('d.className = "msg ai think"') == 2 and UI.count('t.className = "msg ai think"') == 1)
check("C2 the message gap does not apply to that wrapper",
      ".msg.think { margin-bottom: 0; }" in UI)

# ---- D: the written file survives the card's 4 KB cap ----------------------
sys.path.insert(0, os.path.join(REPO, "src"))
from longrun.memory import stores  # noqa: E402

big = json.dumps({"path": ".agent/x/Written file.md", "content": "A" * 9000}, ensure_ascii=False)
kept = stores._card_args(big)
check("D1 a long write keeps VALID JSON with its path",
      len(kept) <= 4000 and json.loads(kept)["path"] == ".agent/x/Written file.md")
check("D2 the persisted card uses the clip, not the old blob cut",
      '"args": _card_args(args),' in STORES and '"args": args_str[:4000],' not in STORES)
tmp = tempfile.mkdtemp(prefix="lr-v1261-")
sess = {"messages": []}
_real_save = stores.save_session
stores.save_session = lambda s: None
try:
    stores.persist_tool_card(sess, "fs.write", True, args=json.loads(big), exit_code=0)
finally:
    stores.save_session = _real_save
card = sess["tool_cards"][0]
check("D3 a real persist keeps the path the UI names the file with",
      json.loads(card["args"]).get("path") == ".agent/x/Written file.md")

# ---- E: the rules FOLDER is loaded whole -----------------------------------
check("E1 the workspace rules folder is discovered",
      'return os.path.join(ws or get_workspace(), ".trae", "rules")' in RULES
      and "extra_dirs=project_rules_dirs(ws)" in RULES)
check("E2 folders load even without the native Project_rules.md",
      "# folders load even when the native file is absent" in RULES)
ws_real = REPO
from longrun.memory import rules  # noqa: E402

col = rules.collect(ws=ws_real)
names = [os.path.basename(p) for p in col["project"]["files"]]
check("E3 every .md of .trae/rules is in the loaded set",
      "project_rules.md" in names and "git-commit-message.md" in names, names)
block = rules.rules_prompt_block(ws=ws_real)
check("E4 the composed block holds the whole corpus (no mid-file cut)",
      not block.endswith("[truncated]") and all(n in block for n in names))
check("E5 the prompt cap in config fits the corpus",
      "rules_prompt_max_bytes: 131072" in TOOLS_YAML and rules.MAX_BYTES >= 131072)
st = rules.status(ws=ws_real)
check("E6 the panel gets one row per loaded file, with sizes",
      [r["name"] for r in st["project"]["file_rows"]] == names
      and all("chars" in r for r in st["project"]["file_rows"]))
check("E7 the RH panel renders the file LINKS and drops the single editable textarea",
      'data-rulepath="' in UI and 'b.onclick = () => openInEditor(b.dataset.rulepath);' in UI
      and 'id="rule_project"' not in UI)

# ---- F: Settings ▸ Rules is the FOLDER list, with a per-file always-apply switch --
# A54 (round 177): the project editor showed the COMPOSED corpus while saving one file.
# ROUND 179 (operator, Trae parity): project rules are FILES — one folder link, one row
# per `.md`, each with an "always apply" switch; no single editable project file.
from unittest import mock  # noqa: E402

_tmp = tempfile.mkdtemp(prefix="lr-v1261-f-")
_fd = os.path.join(_tmp, ".trae", "rules")
os.makedirs(_fd, exist_ok=True)
_one = os.path.join(_fd, "one.md")
with open(_one, "w", encoding="utf-8") as f:
    f.write("FOLDER RULE\n")
_native = os.path.join(_tmp, "native_project.md")
with open(_native, "w", encoding="utf-8") as f:
    f.write("NATIVE RULE\n")
with mock.patch.object(rules, "project_rules_path", lambda ws=None: _native):
    _st = rules.status(ws=_tmp)
check("F1 file_text is the native file only, while text is the composed corpus",
      _st["project"]["file_text"] == "NATIVE RULE\n"
      and "FOLDER RULE" in _st["project"]["text"]
      and _st["project"]["file_text"] != _st["project"]["text"])
with mock.patch.object(rules, "always_apply_map",
                       lambda ws=None: {os.path.abspath(_one): False}), \
        mock.patch.object(rules, "project_rules_path", lambda ws=None: _native):
    _col = rules.collect(ws=_tmp)
check("F2 a file switched OFF leaves the prompt (and the loaded list)",
      "FOLDER RULE" not in _col["project"]["text"]
      and "NATIVE RULE" in _col["project"]["text"]
      and all(not p.endswith("/one.md") for p in _col["project"]["files"]))
_state = tempfile.mkdtemp(prefix="lr-v1261-state-")
with mock.patch.object(rules, "project_dir", lambda ws=None: _state), \
        mock.patch.object(rules, "project_rules_path", lambda ws=None: _native):
    _r1 = rules.set_always_apply(_one, False, ws=_tmp)
    _r2 = rules.set_always_apply("/etc/passwd", False, ws=_tmp)
    _st2 = rules.status(ws=_tmp)
check("F3 the switch persists and refuses a path outside the rules",
      _r1.get("ok") is True and _r1.get("always_apply") is False
      and _r2.get("ok") is False
      and [r["always_apply"] for r in _st2["project"]["all_rows"]
           if r["name"] == "one.md"] == [False]
      and os.path.isfile(os.path.join(_state, "rules_state.json")))
ROWS = between(UI, "function _rulesProjectRows(rows) {", "async function loadRules()")
check("F4 every rule row is a link plus its own always-apply checkbox",
      'class="rfile" data-rulepath="' in ROWS and 'data-rulealways="' in ROWS
      and "always apply" in ROWS and "always_apply: chk.checked" in ROWS
      and 'api("POST", "/api/rules"' in ROWS)
LOAD = between(UI, "async function loadRules() {", "async function saveRules(")
check("F5 the project card is ONE clickable folder path and has NO project textarea",
      'data-rulesdir="' in LOAD and "openRulesDir(_dir)" in LOAD
      and "rulesProjectText" not in UI and "rulesFiles" not in UI)
RR = between(UI, "function _rulesRefRow(kind, label, src) {", "function _rulesRow(")
check("F6 the RH panel shows one folder link and drops the green footer sentence",
      'data-rulesdir="' in RR and "every .md is loaded in this session" not in RR
      and "folder · " not in RR)
EDITOR = src("webui", "assets", "editor.js")
check("F7 the folder link OPENS the dock and reveals that folder (closed / phone too)",
      "async function openRulesDir(dir)" in UI and "ed.showDock()" in UI
      and "ed.revealInTree(dir)" in UI
      and "showDock: () => { buildDock(); show(); }," in EDITOR
      and "\n  revealInTree,\n" in EDITOR)

print("\n---\nv1261: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
