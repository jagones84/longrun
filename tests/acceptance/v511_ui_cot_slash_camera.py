#!/usr/bin/env python3
"""v511 — Control/chat UI round: camera, "No team", collapsed CoT, slash anywhere (JAG-513).

Four operator-reported behaviours, pinned as static guards (the WebUI is vanilla
JS served by the process, so the contract lives in the source):

  1. Control ▸ AGENTS: clicking another agent MUST NOT move the camera — it only
     selects. The constellation carries the SAME relative viewport over instead of
     re-fitting, and a mode switch (agent ⇄ all) still re-fits.
  1b. the scope filter offers the "No team" bucket the AGENTS table already groups,
     and both the client filter and the server route understand it.
  2. the chain-of-thought is COLLAPSED by default, live included — nothing opens it
     but the user — and the chat sidebar has ONE control that collapses them all.
  3. "/" opens the command/skill menu ANYWHERE in the composer, not only when the
     whole input is a lone `/`, and picking a row replaces just that token.

Deterministic: no model, no network, no browser.
Run: python3 tests/acceptance/v511_ui_cot_slash_camera.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
        return f.read()


HTML = _read("webui", "index.html")
ORBIT = _read("src", "longrun", "orbit", "web", "orbit.html")
OAPI = _read("src", "longrun", "orbit", "api.py")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


def _fn(src, header, stop=None):
    """Slice one function body (C-style braces), or up to `stop`."""
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


# ------------------------------------------------ 1: select, never re-fit ----
openbody = _fn(ORBIT, "  async open(agent, mode){")
check("A1 selecting a DIFFERENT agent keeps the camera (no re-fit)",
      "_keepCam = true" in openbody and "this.focus.session !== agent.session" in openbody,
      "")
check("A1b a MODE switch (agent <-> all) is different content, so it still re-fits",
      "sameMode" in openbody and "mode === this.mode" in openbody, "")

drawbody = _fn(ORBIT, "    const prevBase = svg.__baseVB;", stop="this._keepCam = false;")
check("A2 the new graph keeps the SAME RELATIVE viewport (camera does not jump)",
      "_keepCam" in drawbody and "vb.w / ob[2]" in drawbody and "vb.h / ob[3]" in drawbody,
      "")
check("A2b the map is built with preserveAspectRatio (stable geometry)",
      'setAttribute("preserveAspectRatio", "xMidYMid meet")' in ORBIT, "")

# --------------------------------------------------------- 1b: No team -------
check("B1 the scope filter offers a 'No team' bucket",
      '<option value="__none__">No team</option>' in ORBIT, "")
check("B2 the client filter understands __none__ (agents without any team)",
      'team === "__none__" ? !((a.teams || []).length)' in ORBIT, "")
check("B3 the server scope understands __none__",
      'if team == "__none__":' in OAPI and 'not (a.get("teams") or [])' in OAPI, "")
check("B4 a team-only action refuses the 'No team' pseudo-scope",
      '"\'No team\' is not a team' in ORBIT, "")

# ------------------------------------------------------- 2: collapsed CoT ----
check("C1 no chain-of-thought block is emitted OPEN",
      'details class="think" open' not in HTML, "")
ensure = _fn(HTML, "function ensureThink() {")
check("C2 a LIVE chain-of-thought is created collapsed",
      'details class="think"' in ensure and " open>" not in ensure, "")
check("C3 ending a CoT (tool card) CLOSES it, never re-opens it",
      'const _t = curThink.querySelector("details"); if (_t) _t.open = false;' in HTML, "")
thead = _fn(HTML, "function collapseThoughts() {")
check("C4 one control collapses every CoT (one-way: nothing re-opens it)",
      "details.think" in thead and "d.open = false" in thead, "")
check("C5 the control is in the chat sidebar",
      'data-call="collapseThoughts"' in HTML, "")

# ----------------------------------------------------- 3: slash anywhere -----
# The whole function (it has nested blocks, so slice to the next top-level "}").
_i = HTML.index("function skillsAutocomplete() {")
slash = HTML[_i:HTML.index("\n}\n", _i) + 3]
check("D1 the menu no longer requires a LONE '/'",
      '!v.startsWith("/") || v.includes(" ")' not in HTML and "tokenStart" in slash, "")
check("D2 it locates the slash token at the CARET (start of text or after a space)",
      'upto.lastIndexOf(" /")' in slash and "inp.selectionStart" in slash, "")
check("D3 picking a row edits ONLY that token (the rest of the message survives)",
      "const before = v.slice(0, tokenStart), after = v.slice(caret);" in slash, "")
check("D4 the picker inserts through that helper",
      '_apply("/" + s.name + " ");' in slash, "")
check("D5 the '+' ▸ commands path parks the caret after the '/'",
      "setSelectionRange(inp.value.length, inp.value.length)" in HTML, "")

print("---")
ok = sum(results)
print("\nv511: %d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)
