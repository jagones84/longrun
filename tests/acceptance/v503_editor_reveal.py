#!/usr/bin/env python3
"""v503 — opening a file LOCATES it in the file tree (JAG-503).

The editor tree is lazy: a folder's children exist only after a click. So a file
opened from a chat hyperlink (or an external redirect) had NO row at all — its
ancestors were collapsed, `revealInTree` searched a tree that did not contain it,
and nothing was highlighted. Clicking a tab had the same blind spot for any file
deeper than the root.

Locked here:
  * folder rows carry `dataset.path` / `dataset.dir` / `dataset.depth`, so the
    reveal walk can find and expand an ancestor at every level;
  * `toggleDir()` is ONE async expander shared by the click handler and the walk
    (the walk must await each level, otherwise the child is not rendered yet);
  * `revealInTree` expands the ancestors before looking for the file row, and it
    never marks a folder row as the active file;
  * `open()` reveals the file (hyperlinks included) but a session restore does not
    (`reveal: false`), and a pane the operator closed stays closed.

Deterministic, no browser. Run: python3 tests/acceptance/v503_editor_reveal.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
with open(os.path.join(REPO, "webui", "assets", "editor.js"), encoding="utf-8") as f:
    JS = f.read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# --- A: the tree carries enough identity to be walked -------------------------
check("A1 folder rows expose their path", 'row.dataset.path = dir.path;' in JS)
check("A2 folder rows are marked as folders", 'row.dataset.dir = "1";' in JS)
check("A3 folder rows remember their depth", 'row.dataset.depth = String(depth);' in JS)
check("A4 one shared expander exists", "async function toggleDir(row, kids, dir, depth)" in JS)
check("A5 the click handler uses that expander", "toggleDir(row, kids, dir, depth)" in JS)
check("A6 the expander is idempotent (loaded flag on the DOM)",
      'kids.dataset.loaded === "1"' in JS and 'kids.dataset.loaded = "1";' in JS)

# --- B: the reveal walks the ancestors ----------------------------------------
check("B1 the reveal finds a row by path", "function _treeRow(path)" in JS)
check("B2 it walks the path segment by segment",
      "async function _expandTo(path)" in JS and "String(path).slice(root.length + 1).split(\"/\")" in JS)
check("B3 it AWAITS each level before looking further", "await toggleDir(row, kids" in JS)
check("B4 it bails when a folder fails to load", 'kids.dataset.loaded !== "1"' in JS)
check("B5 the reveal expands before the final lookup",
      "await _expandTo(path); hit = _treeRow(path);" in JS)
check("B6 a folder row is never marked active",
      'hit.dataset.dir !== "1"' in JS
      and 'r.dataset.dir !== "1" && r.textContent.trim().endsWith(base)' in JS)

# --- C: open() reveals, restore() does not ------------------------------------
check("C1 opening a file reveals it in the tree",
      "revealInTree(d.path, { showPane: false })" in JS)
check("C2 re-opening an existing tab reveals it too",
      "revealInTree(path, { showPane: false })" in JS)
check("C3 a closed pane stays closed", "opts && opts.showPane === false" in JS)
check("C4 restoring tabs does NOT expand the tree",
      "open(p, { reveal: false })" in JS)
check("C5 the tree search pick still reveals the hit",
      "loadTree().then(() => { if (hit && hit.path) revealInTree(hit.path); })" in JS)

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
