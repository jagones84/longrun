#!/usr/bin/env python3
"""v364 — queued-message attachments, themed text colours, working links, ctx bars (JAG-364).

Deterministic (no model, no network):

  A) a QUEUED message carries its attachments: the queue chip shows the user text
     plus a marker for the images / files / text it carries, not the raw blob;
  B) a theme sets TEXT colours too — every theme card previews its text + accent
     colour, the code surfaces resolve through tokens, and no hardcoded status text
     colour survives;
  C) a relative chat link OPENS: the server resolves it against the session
     workspace AND its ancestors, so a link to a SIBLING project resolves;
  D) the context breakdown is a list of horizontal bars (coloured like the donut,
     sorted big -> small, with short labels) — and the donut is kept.

Run: python3 tests/acceptance/v364_queue_theme_links_ctx.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    HTML = f.read()
with open(os.path.join(REPO, "webui", "assets", "editor.js"), encoding="utf-8") as f:
    EDITOR = f.read()

sys.path.insert(0, os.path.join(REPO, "src"))

results = []


def check(name, cond, extra=""):
    ok = bool(cond)
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(extra)) if extra else ""))


# --- A: queued messages carry their attachments ------------------------------
check("A1 there is a marker helper for a message's attachments",
      "function _attMark(atts)" in HTML and '"🖼 "' in HTML and '"📄 "' in HTML, "")
check("A2 the queue chip renders the user text + the attachment marker",
      "function renderQueue" in HTML and "_attMark(it.atts)" in HTML
      and 'a.className = "qatt"' in HTML, "")
check("A3 enqueuing keeps the user text separate from the model payload",
      "enqueueMsg({ raw: _rawMsg," in HTML and " text: raw" in HTML
      and "atts: _attSnap })" in HTML, "")
check("A4 steering names the user text, not the raw blob",
      '"🎯 steer: " + it.text' in HTML, "")
check("A5 flushing shows the user text but sends the raw payload",
      "send(it.raw, it.text)" in HTML and "function send(text, display)" in HTML, "")
check("A6 the marker has its own themed style",
      ".qchip .qatt" in HTML, "")
check("A7 a bare string in the queue is still tolerated",
      "function _qNorm(m)" in HTML and "typeof m === \"object\"" in HTML, "")

# --- B: a theme sets TEXT colours --------------------------------------------
check("B1 every theme carries its text + accent colour for the preview",
      HTML.count(', t: "#') == 9 and HTML.count(', a: "#') == 9, "")
check("B2 the swatch previews the text colour (Aa) + the accent",
      'class="tv"' in HTML and 'class="ta"' in HTML, "")
check("B3 the preview has its own style",
      ".themecard .sw .tv" in HTML and ".themecard .sw .ta" in HTML, "")
check("B4 no hardcoded status TEXT colour survives",
      all(x not in HTML for x in (
          "#nowbar .nst.doing { color: #ffcf6a",
          ".tctree .st.doing { color: #fbbf24",
          ".tctree .st.done { color: #34d399",
          ".tctree .st.blocked { color: #ff7777",
          ".tctree .st.superseded { color: #94a3b8"))
      and ".tctree .st.done { color: var(--ok);" in HTML
      and ".tctree .st.blocked { color: var(--err);" in HTML, "")
check("B5 the code surfaces resolve through tokens",
      ".bubble.md-content code { background: var(--chipbg)" in HTML
      and ".bubble.md-content pre { background: var(--bg-3)" in HTML, "")
check("B6 the queue dropdown options use tokens",
      "#qmode option { background: var(--menubg); color: var(--txt); }" in HTML, "")
check("B7 the ghost/copy hover borders follow the accent",
      "button.ghost:hover { color: var(--txt); border-color: var(--acc); }" in HTML
      and ".msg .copy:hover { color: var(--txt); border-color: var(--acc); }" in HTML, "")

# --- C: a relative chat link opens (server-side ancestor walk) ---------------
with open(os.path.join(REPO, "src", "longrun", "core/api_v02.py"), encoding="utf-8") as f:
    SRC = f.read()
check("C1 the resolver walks the workspace ancestors (bounded)",
      "for _ in range(12):" in SRC and "the workspace, then its ancestors" in SRC, "")

api = None
try:
    from longrun.core import api_v02 as api  # noqa: E402
except Exception as e:  # noqa: BLE001
    print("SKIP import longrun.api_v02: %s" % e)

if api is not None:
    tmp = tempfile.mkdtemp(prefix="sf-v364-")
    ws = os.path.join(tmp, "Repositories", "TESTS", "Jago")
    os.makedirs(ws)
    sibling = os.path.join(tmp, "Repositories", "sparkpulse-server")
    os.makedirs(sibling)
    target = os.path.join(sibling, "status_server.py")
    with open(target, "w", encoding="utf-8") as f:
        f.write("x")
    local = os.path.join(ws, "app")
    os.makedirs(local)
    local_file = os.path.join(local, "build.gradle.kts")
    with open(local_file, "w", encoding="utf-8") as f:
        f.write("y")
    _browse, _ws = api._browse_roots, api._ws_root
    api._browse_roots = lambda: [tmp]
    api._ws_root = lambda qs=None: ws
    try:
        got_sib = api._resolve_fs_arg("sparkpulse-server/status_server.py", {"session": "s"})
        got_ws = api._resolve_fs_arg("app/build.gradle.kts", {"session": "s"})
        got_miss = api._resolve_fs_arg("nope/missing.py", {"session": "s"})
    finally:
        api._browse_roots, api._ws_root = _browse, _ws
    check("C2 a SIBLING-project relative link resolves via the ancestors",
          got_sib == target, got_sib)
    check("C3 a workspace-local relative link still wins", got_ws == local_file, got_ws)
    check("C4 a missing path falls back to the workspace candidate",
          got_miss == os.path.join(ws, "nope/missing.py"), got_miss)
else:
    check("C2 a SIBLING-project relative link resolves via the ancestors", False, "api_v02 import failed")
    check("C3 a workspace-local relative link still wins", False, "api_v02 import failed")
    check("C4 a missing path falls back to the workspace candidate", False, "api_v02 import failed")

# --- D: the context breakdown is horizontal bars -----------------------------
check("D1 the breakdown container + rows exist",
      '.ctxbd' in HTML and 'class="ctxbd"' in HTML and 'class="bdbar"' in HTML, "")
check("D2 the bars are sorted big -> small",
      ".sort((a, b) => b.tokens - a.tokens)" in HTML, "")
check("D3 the labels are shortened (full label in the tooltip)",
      "function _shortLabel(l)" in HTML and "const CTX_ABBR" in HTML
      and '"other tool output": "tool out"' in HTML, "")
check("D4 the donut is kept next to the bars",
      "function _ctxDonut" in HTML and ".ctxdonut" in HTML, "")
check("D5 the bar colour comes from the same palette as the donut",
      "col: CTX_COLS[i % CTX_COLS.length]" in HTML, "")
check("D6 the old stacked-bar class is still gone (no ctxbar substring)",
      ".ctxbar" not in HTML, "")

# --- E: the JS responsiveness matches the CSS viewport (JAG-366) -------------
check("E1 the app's overlay thresholds use the layout viewport (clientWidth)",
      "function _vw() { return document.documentElement.clientWidth" in HTML
      and "function _overlayLeft() { return _vw() <= 900; }" in HTML
      and "function _overlayRight() { return _vw() <= 1100; }" in HTML
      and "r.left < _vw() - 1" in HTML, "")
check("E2 the editor dock's overlay decision + drag clamps use the layout viewport",
      "function _vw() { return document.documentElement.clientWidth" in EDITOR
      and "const overlay = _vw() < 1024;" in EDITOR
      and "_vw() - 120" in EDITOR and "_vw() - 160" in EDITOR, "")
check("E3 the viewport meta is mobile-ready (device-width + viewport-fit)",
      'name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"' in HTML, "")
check("E4 on a phone the chat column drops its desktop 420px floor (no right-edge clip)",
      '[data-col="chat"] { min-width: 0; }' in HTML
      and 'min-width: 420px; display: flex; flex-direction: column' in HTML, "")
# JAG-3xx: on a phone the settings' fixed 190px nav column left no room and could not be
# reduced — it is now a horizontal TOP tab strip inside a full-screen window.
check("E5 on a phone the settings nav is a top tab strip (no fixed left column)",
      "@media (max-width: 640px)" in HTML
      and "#settingsWin .sw-nav { flex: 0 0 auto; display: flex" in HTML, "")
# JAG-3xx: the settings window drag/resize must work by touch, so it uses pointer events.
check("E6 the settings window is movable/resizable by touch (pointer events)",
      'handle.addEventListener("pointerdown", e => {' in HTML
      and "handle.setPointerCapture(e.pointerId)" in HTML
      and "function _clampBox(box)" in HTML, "")

print("---")
ok = sum(results)
print("%d/%d PASS" % (ok, len(results)))
sys.exit(0 if ok == len(results) else 1)

