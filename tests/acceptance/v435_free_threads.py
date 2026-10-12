"""v435 — "free" chat-thread groups (JAG-431g).

Between task groups a chat has "free" threads (a user turn + its answer). They are now
wrapped in a collapsible <details class="fgroup"> ("Free.N") so they collapse/expand
with the SAME ⊞/⊟ controls as the task groups. Pins the wiring in webui/index.html.

Deterministic, offline.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


HTML = _read("webui", "index.html")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def _fn(src, header):
    lines = src[src.index(header):].splitlines()
    out = []
    for i, ln in enumerate(lines):
        out.append(ln)
        if i == 0 and ln.rstrip().endswith("}"):
            break
        if i > 0 and ln.strip() == "}":
            break
    return "\n".join(out)


# --- the container + helpers -------------------------------------------------
check("1a the free-group state + helpers exist",
      all(s in HTML for s in ("function _freeKids(", "function _freeNew(",
                              "function _freeAppend(", "function _freeClose(")), "")
check("1b the group is labelled Free.N (+ the agent title when the chapter is known)",
      '"Free." + n' in HTML and "function _freePaint(" in HTML, "")
check("1c a .fgroup style is defined", ".fgroup > summary" in HTML, "")

# --- routing -----------------------------------------------------------------
la = _fn(HTML, "function _logAppend(")
check("2a free content is routed into _freeAppend when no task scope is active",
      "_freeAppend(el, chapter)" in la and "_activeScope" in la, "")
sc = _fn(HTML, "function _scope(")
check("2b _scope() prefers the active task scope, then the free group",
      "_activeScope" in sc and "_freeKids()" in sc, "")

who = _fn(HTML, "function who(")
check("2c a user turn opens a NEW free thread (unless inside a task group)",
      "_freeClose()" in who and "_freeAppend(d, chapter)" in who, "")
check("2d starting a task step closes the free group",
      HTML.count("_freeClose();") >= 3, "count=%d" % HTML.count("_freeClose();"))
check("2e reset clears the free groups",
      "_freeGroup = null; _freeN = 0;" in _fn(HTML, "function _resetChatTree("), "")

# --- the ⊞/⊟ controls also drive free groups --------------------------------
ag = _fn(HTML, "function _allGroups(")
check("3a the group selector includes details.fgroup", "details.fgroup" in ag, "")
check("3b expand/collapse-all operate on _allGroups()",
      "_allGroups()" in _fn(HTML, "function expandAllTodos(")
      and "_allGroups()" in _fn(HTML, "function collapseAllTodos("), "")
check("3c the controls show when any group exists",
      "_allGroups().length > 0" in _fn(HTML, "function _updateTreeTools("), "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
