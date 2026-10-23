#!/usr/bin/env python3
"""v505 — editor file tree reveal/expand-collapse + Settings order + diagnostics verdict.

Operator feedback (three items):

  1) opening a file in the Editor left its folder COLLAPSED, so the active tab was
     not visible in the tree; and the tree had no expand-all / collapse-all
     control (the sessions list and the right-rail panels have one). The tree now
     reveals the active tab (including after a reload) and has ⊞ / ⊟ buttons.

  2) "run checks" in Settings > Diagnostics printed nothing when everything was
     healthy — a green verdict must say so explicitly.

  3) Settings listed the subagent model picker twice (Models + Subagents); the
     Models copy is gone and the categories follow the operator's order.

Deterministic, no model, no network, no server. Run: python3 tests/acceptance/v505_*.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + ((" — " + detail) if (detail and not cond) else ""))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as fh:
        return fh.read()


ed = _read("webui", "assets", "editor.js")
idx = _read("webui", "index.html")

# ---- A) editor tree: the active file is located, and the tree can fold/unfold
check("A1 the dock header has an expand-all button",
      'class="ed-expand ghost"' in ed and 'aria-label="expand all folders"' in ed)
check("A2 the dock header has a collapse-all button",
      'class="ed-collapse ghost"' in ed and 'aria-label="collapse all folders"' in ed)
check("A3 both buttons are wired to the tree helpers",
      '.ed-expand").onclick = () => expandAll()' in ed
      and '.ed-collapse").onclick = () => collapseAll()' in ed)
check("A4 expandAll walks the lazy folders and is bounded",
      "async function expandAll()" in ed and "budget" in ed and "toggleDir(" in ed)
check("A5 collapseAll uses the dir-row identity, not a text guess alone",
      "function collapseAll()" in ed and '.ed-trow[data-dir="1"]' in ed)
check("A6 dir rows keep their own name after a fold",
      'function _dirName(row)' in ed)

# reveal: open() and restoreTabs() both locate the file in the tree
check("A7 opening a file reveals it in the tree",
      re.search(r"revealInTree\(d\.path,\s*\{\s*showPane:\s*false\s*\}\)", ed) is not None)
check("A8 a restored active tab is revealed too (reload keeps the location)",
      "const _t = activeTab();" in ed
      and re.search(r"if \(_t && !_t\.temp\) revealInTree\(_t\.path", ed) is not None)
check("A9 the reveal walks collapsed levels level-by-level",
      "function _expandTo" in ed and "await _expandTo" in ed)
check("A10 never a blank tree on a session switch",          # JAG-505 guard kept
      'state.treeEl.querySelector(".ed-trow")' in ed)

# JAG-524: the tree pane mirrors ONE session's workspace, so it must know WHICH
# session it is showing. It used to survive a switch untouched — the old guard only
# asked "does the pane have rows?", and the PREVIOUS session's rows satisfied it, so
# the operator kept reading the wrong folder (live repro: session B showed
# `harness-e2e/` while GET /api/fs/list?session=B answered
# `/home/jagones/Repositories/TESTS`). A late reply could also paint the old root
# over the new session.
check("A11 the tree records the session it mirrors (never an empty-string guess)",
      "function _treeStale()" in ed and "state.treeSid !== SESSION()" in ed
      and "treeSid: null" in ed)
check("A12 a session switch reloads the tree even when it already holds rows",
      'else if (state.treeEl && (_treeStale() || !state.treeEl.querySelector(".ed-trow"))) {' in ed)
check("A13 show() reloads a tree that still belongs to another session",
      'if (state.treeEl && !state.treeEl.hidden && (_treeStale() || !state.treeEl.querySelector(".ed-trow"))) loadTree();' in ed)
check("A14 the reveal reloads a tree that still belongs to another session",
      'if (_treeStale() || !state.treeEl.querySelector(".ed-trow")) await loadTree()' in ed)
check("A15 a tree reply that lands after the switch is dropped, never painted",
      "state.treeSid = sid;" in ed
      and 'if (sid !== (localStorage.getItem("sf_session") || "")) return null;' in ed)
_lt = ed[ed.find("async function loadTree()"):]
_lt = _lt[:_lt.find("\n}\n")]      # the loadTree body only — a bare file-wide search
check("A16 the workspace-root change re-renders the tabs (no stale ⚠ marker)",
      "state.root = d.root" in _lt and "renderTabs();" in _lt)

# JAG-525: the search box is session-scoped too, but a switch left the PREVIOUS
# session's hits on screen — loadTree() gives up on the pane while a search owns it
# (JAG-501), so nothing re-anchored the pane to the new workspace.
check("A17 a session switch re-runs the active search instead of keeping its hits",
      'if (state.searchInput && state.searchInput.value.trim()) {' in ed
      and 'state.treeHits.innerHTML = "";' in ed
      and "state.search.run();" in ed)
check("A18 the pane still learns the new root while a search owns it",
      "async function _syncRoot()" in ed and "_syncRoot();" in ed)
check("A19 ONE session-guarded listing fetch feeds both callers",
      "async function _sessionListing()" in ed
      and ed.count("_sessionListing()") >= 3
      and ed.count("/api/fs/list?session=") == 2)   # the helper + a sub-folder expand

# ---- B) Settings categories: the operator's order, no duplicates -------------
m = re.search(r"const SETTINGS_CATS = \[(.*?)\n\];", idx, re.S)
cats = re.findall(r'\[\s*"([a-z]+)"\s*,', m.group(1)) if m else []
want = ["appearance", "keys", "models", "subagents", "orchestrate", "tools", "sandbox", "mcp",
        "skills", "rules", "knowledge", "compaction", "improvement", "diagnostics", "hooks",
        "harness", "config"]
check("B1 SETTINGS_CATS is parseable", bool(cats), "found %r" % (cats,))
check("B2 categories follow the operator's order",
      cats[:len(want)] == want, "got %r" % (cats,))
check("B3 Info stays last", bool(cats) and cats[-1] == "info", "got %r" % (cats,))
check("B4 no category is listed twice", len(cats) == len(set(cats)), "got %r" % (cats,))
check("B4a Hooks is a dedicated panel immediately above Harness",
      'data-cat="hooks"' in idx and "hooks" in cats and
      "harness" in cats and cats.index("hooks") + 1 == cats.index("harness")
      and '"file": "hooks.yaml", "id": "hooks", "panel": "hooks"' in
      _read("src", "longrun", "core", "settings.py"))
# no duplicate subagent picker inside Models; the single one lives in Subagents
def _cat_block(name):
    start = idx.find('data-cat="%s"' % name)
    if start < 0:
        return ""
    nxt = idx.find('class="sw-cat"', start)
    return idx[start:nxt if nxt > start else len(idx)]


check("B4b Sandbox has its own Settings panel immediately below Tools & approvals",
      "sandbox" in cats and cats.index("sandbox") == cats.index("tools") + 1
      and 'data-cat="sandbox"' in idx
      and 'id="sandboxPanel"' in _cat_block("sandbox")
      and 'id="sbxBackend"' not in _cat_block("tools")
      and "sandboxEl.innerHTML = sbCard" in idx
      and 'gateEnroll(sandboxEl.querySelector("#sbxCard"))' in idx)
check("B4c routing.yaml explains its raw-backup role and structured ownership",
      "Why routing.yaml is listed" in idx
      and "Settings → Subagents owns" in idx
      and "This editor is the raw advanced fallback, not a second config." in idx)
check("B4d Subagents no longer claims a duplicate Models picker",
      "No duplicate model/fallback controls live in Models." in idx
      and "the same value as the Models picker" not in idx)

models = _cat_block("models")
subs = _cat_block("subagents")
check("B5 Models no longer hosts a subagent model picker",
      'id="subagentModel"' not in models and "saveSubagentModel" not in models)
check("B6 Subagents owns the subagent model picker",
      'id="subModel"' in subs and 'data-cat="subagents"' in idx)
check("B7 the dead Models-era handler cannot fire",
      'data-call="saveSubagentModel"' not in idx)
keys = _cat_block("keys")
check("B8 New key appears before the configured key list",
      keys.find('id="showNewKey"') >= 0 and keys.find('id="showNewKey"') < keys.find('id="keysList"'))
check("B9 Skills panel filters with the shared slash skill matcher",
      'id="skillsFilter"' in idx and "function _skillSearchScore" in idx
      and "_rankSkills(_skillsCache, query)" in idx and "_rankSkills(_skills, q)" in idx)
check("B10 Subagents has one automatic fallback picker and no add button",
      'id="subFallbackPick"' in idx and 'id="subFallbacksList"' not in idx
      and 'data-call="subAddFallback"' not in idx
      and 'data-cat="subagents"' in idx)
keys = _cat_block("keys")
check("B8 New key is placed before the configured key list",
      keys.find('id="showNewKey"') >= 0 and keys.find('id="showNewKey"') < keys.find('id="keysList"'))
check("B9 Skills has a filter and shares the slash skill matcher",
      'id="skillsFilter"' in idx and "function _skillSearchScore" in idx
      and "_rankSkills(_skillsCache, query)" in idx and "_rankSkills(_skills, q)" in idx)

# ---- C) Diagnostics: a healthy run says so ----------------------------------
diag = idx[idx.find("function renderDiagnostics"):]
diag = diag[:diag.find("\nfunction ", 10)]
check("C1 the healthy verdict is rendered in the summary",
      "All checks passed" in diag and "diag-ok" in diag)
check("C2 the healthy verdict gets a green card, not an empty grey box",
      'empty.className = "card diag-ok"' in diag and "Healthy." in diag)
check("C3 a green style exists", ".diag-ok" in idx and "--ok" in idx)
check("C4 the check count is surfaced when available", "counts.checked" in diag)

# ---- D) the right rail hands the tree to the editor, without moving the rail --
check("D1 the Files panel no longer renders its own tree or search",
      'id="fileTree"' not in idx and 'id="fileSearch"' not in idx)
check("D2 the Workspace panel offers the editor hand-off, next to browse",
      "🗔 open editor" in idx and 'data-call="SparkEditorToggle"' in idx)
check("D3 ONE hand-off per surface, through ONE function (JAG-511/JAG-514)",
      idx.count('data-call="SparkEditorToggle"') == 2   # composer + inspector
      and idx.count("window.SparkEditor.toggle()") == 1  # only inside the function
      and 'class="ghost ws-ed"' not in idx)
check("D4 there is no second workspace-tree implementation",
      "function loadFiles" not in idx and "function _renderDir" not in idx)
check("D5 focusInsp can skip the scroll",
      "function focusInsp(name, opts)" in idx and "opts.scroll !== false" in idx)
check("D6 opening a file from a panel does not move the rail",
      'openPanel("files", { scroll: false })' in idx)

print("---")
ok = sum(results)
print("\nv505: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
