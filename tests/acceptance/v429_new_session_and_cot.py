#!/usr/bin/env python3
"""v429 — New-session dialog opacity, workspace auto-creation, CoT collapse (JAG-429).

Three user-reported issues, pinned as static guards:

  1. the New-session dialog was translucent (its `.card` background showed through);
     it must paint an OPAQUE background.
  2. naming a not-yet-existing workspace refused with "no such folder"; naming a
     folder expresses the intent to use it, so it must be CREATED (`mkdir -p`),
     including missing parents.
  3. the chat cluster's collapse-all (⊟) must ALSO close the chain-of-thought
     blocks, but expand-all (⊞) must NEVER re-open them (deliberately one-way so
     the user's chosen tuck-away stays tucked).

Deterministic (no model, no network).

Run: python3 tests/acceptance/v429_new_session_and_cot.py
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


HTML = _read("webui", "index.html")
RULES = _read("src", "longrun", "memory", "rules.py")
HTTPAPI = _read("src", "longrun", "core", "httpapi.py")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def _fn(src, header, stop=None):
    """Slice one function body. `stop` = a terminator line marker (e.g. "\\ndef ");
    when None, treat C-style braces: stop at the header's own `}` or the first `}` line."""
    lines = src[src.index(header):].splitlines()
    if stop is not None:
        body = "\n".join(lines)
        return body[:body.index(stop) + 2]
    out = []
    for i, ln in enumerate(lines):
        out.append(ln)
        if i == 0 and ln.rstrip().endswith("}"):
            break
        if i > 0 and ln.strip() == "}":
            break
    return "\n".join(out)

# --- 1: the New-session dialog is opaque ------------------------------------
dlg = HTML[HTML.index("#newSessDlg {"):]
dlg = dlg[:dlg.index("}")]
check("1a #newSessDlg paints an opaque background",
      re.search(r"background:\s*var\(--menubg\)", dlg) is not None, "")
check("1b the opaque colour var is a solid hex (no alpha)",
      re.search(r"--menubg:\s*#[0-9a-fA-F]{6}\s*;", HTML) is not None, "")

# --- 2: workspace auto-creation ---------------------------------------------
check("2a rules.ensure_dir exists", "def ensure_dir(path):" in RULES, "")
ed = _fn(RULES, "def ensure_dir(path):", stop="\ndef ")
check("2b it creates the folder with parents (makedirs)",
      "os.makedirs(" in ed and "exist_ok=True" in ed, "")
check("2c it returns the abs path only when the dir now exists",
      "os.path.isdir(p)" in ed, "")

nw = HTTPAPI[HTTPAPI.index('if path == "/api/sessions/new":'):]
nw = nw[:nw.index("get_or_create_session")]
check("2d the route tries check_dir FIRST (honour an existing folder)",
      "check_dir(ws)" in nw, "")
check("2e then falls back to ensure_dir (create it) — never refuse silently",
      "ensure_dir(ws)" in nw, "")
check("2f it only errors if creation truly failed",
      "cannot create folder" in nw, "")

# --- 3: collapse-all also hides CoT, one-way --------------------------------
check("3a _allTodos() selects the todo groups (details.tctree)",
      "details.tctree" in _fn(HTML, "function _allTodos("), "")
cbody = _fn(HTML, "function collapseAllTodos(")
check("3b collapseAllTodos closes the todo groups",
      "_allTodos()" in cbody and "d.open = false" in cbody, "")
check("3c collapseAllTodos ALSO closes chain-of-thought",
      "details.think" in cbody, "")

ebody = _fn(HTML, "function expandAllTodos(")
check("3d expandAllTodos re-opens the todo groups",
      "_allTodos()" in ebody and "d.open = true" in ebody, "")
check("3e expandAllTodos does NOT touch chain-of-thought (one-way)",
      "think" not in ebody, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
