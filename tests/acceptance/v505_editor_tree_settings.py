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
check("A10 a session switch does not wipe the reveal-built tree",
      'state.treeEl.querySelector(".ed-trow")' in ed)

# ---- B) Settings categories: the operator's order, no duplicates -------------
m = re.search(r"const SETTINGS_CATS = \[(.*?)\n\];", idx, re.S)
cats = re.findall(r'\[\s*"([a-z]+)"\s*,', m.group(1)) if m else []
want = ["appearance", "keys", "models", "subagents", "tools", "mcp", "skills",
        "rules", "improvement", "diagnostics", "config"]
check("B1 SETTINGS_CATS is parseable", bool(cats), "found %r" % (cats,))
check("B2 categories follow the operator's order",
      cats[:len(want)] == want, "got %r" % (cats,))
check("B3 Info stays last", bool(cats) and cats[-1] == "info", "got %r" % (cats,))
check("B4 no category is listed twice", len(cats) == len(set(cats)), "got %r" % (cats,))

# no duplicate subagent picker inside Models; the single one lives in Subagents
def _cat_block(name):
    start = idx.find('data-cat="%s"' % name)
    if start < 0:
        return ""
    nxt = idx.find('class="sw-cat"', start)
    return idx[start:nxt if nxt > start else len(idx)]


models = _cat_block("models")
subs = _cat_block("subagents")
check("B5 Models no longer hosts a subagent model picker",
      'id="subagentModel"' not in models and "saveSubagentModel" not in models)
check("B6 Subagents owns the subagent model picker",
      'id="subModel"' in subs and 'data-cat="subagents"' in idx)
check("B7 the dead Models-era handler cannot fire",
      'data-call="saveSubagentModel"' not in idx)

# ---- C) Diagnostics: a healthy run says so ----------------------------------
diag = idx[idx.find("function renderDiagnostics"):]
diag = diag[:diag.find("\nfunction ", 10)]
check("C1 the healthy verdict is rendered in the summary",
      "All checks passed" in diag and "diag-ok" in diag)
check("C2 the healthy verdict gets a green card, not an empty grey box",
      'empty.className = "card diag-ok"' in diag and "Healthy." in diag)
check("C3 a green style exists", ".diag-ok" in idx and "--ok" in idx)
check("C4 the check count is surfaced when available", "counts.checked" in diag)

print("---")
ok = sum(results)
print("\nv505: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
