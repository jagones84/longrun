#!/usr/bin/env python3
"""v1053 (RED) — the composer `/` menu is grouped and the doc bar is graphical.

Pins the frontend contract of v1051/v1052: the backend catalogue is applied on
boot, the menu renders plugins -> commands -> skills with an icon/hint/key footer,
plugin rows open a member submenu, `/plan` and `/spec` are intercepted before
`/goal`, and the durable plan bar mirrors the goal bar. Deterministic: source
contracts only, no browser, no server, no model.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
AGENT = open(os.path.join(REPO, "src", "longrun", "agent", "agent.py"), encoding="utf-8").read()
SLASH = open(os.path.join(REPO, "src", "longrun", "core", "slash.py"), encoding="utf-8").read()

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ------------------------------------------------------------- A: catalogue
check("A1 the frontend keeps only a first-paint FALLBACK (let, replaced on boot)",
      "let SLASH_COMMANDS = [" in UI and "SLASH_COMMANDS = r.commands.map(c => Object.assign({}, c," in UI)
check("A2 the index is rebuilt from ONE function",
      "const SLASH_BY_ID = {};" in UI and "function _indexSlash() {" in UI
      and "Object.keys(SLASH_BY_ID).forEach(k => { delete SLASH_BY_ID[k]; });" in UI)
check("A3 the loader reads the backend route",
      "async function loadSlashCatalog() {" in UI
      and 'api("GET", "/api/slash" + (sessionId ? "?session="' in UI)
check("A4 the loader applies plugins and docs too",
      "_SLASH_PLUGINS = Array.isArray(r.plugins) ? r.plugins : [];" in UI
      and "_DOCS = (r.docs && typeof r.docs === \"object\") ? r.docs : null;" in UI)
check("A5 the fallback carries all six commands",
      all(('id: "%s"' % cid) in UI for cid in ("goal", "plan", "spec", "plugins", "skills", "compact")))
check("A6 the backend catalogue keeps the LOCAL actions for skills/plugins/compact",
      "const _SLASH_RUN = {" in UI
      and "skills: () => openSkillMenu()," in UI
      and "plugins: () => openPluginMenu()," in UI
      and "compact: () => compactNow()," in UI
      and "_SLASH_RUN[c.id] ? { run: _SLASH_RUN[c.id] } : {}" in UI)

# --------------------------------------------------------------- B: menu UI
check("B1 the menu is a listbox with named sections",
      'role="listbox" aria-label="commands"' in UI and 'h.className = "slashsec"' in UI)
check("B2 the sections are rendered in the frontier order",
      "addSection(\"plugins\")" in UI and "addSection(\"commands\")" in UI
      and 'addSection("skills · "' in UI)
check("B3 a row has an icon slot, a label, a hint and a key",
      'class="slashico"' in UI and 'class="slashmain"' in UI
      and 'class="slashhint"' in UI and 'class="slashkey"' in UI)
check("B4 the footer names the keys and the empty state is explicit",
      'foot.className = "slashfoot";' in UI and "⇥ complete · ↵ run · esc close" in UI
      and 'box.innerHTML = \'<div class="slashempty">' in UI)
check("B5 rows are styled by the stylesheet, not inline",
      'li.style.cssText = "padding:6px 10px' not in UI)
check("B6 the highlight is exposed to assistive tech",
      "it.el.setAttribute(\"aria-selected\"" in UI)

# ----------------------------------------------------------- C: plugin menu
check("C1 a plugin row opens the SAME menu in plugin mode",
      "function _openPluginMenu(p) {" in UI and "_slashPluginOnly = p.id;" in UI)
check("C2 `/plugins` is a submenu opener",
      "function openPluginMenu() {" in UI and "_slashPluginsOnly = true;" in UI)
check("C3 the submenu offers the whole plugin and its members",
      'addRow("/plugin:" + _plugin.name,' in UI
      and 'addSection("other members")' in UI)
check("C4 a plugin member is inserted as a normal skill token",
      'addRow("/" + s.name,' in UI
      and 'if (!_missing) _apply("/" + s.name + " ");' in UI)
check("C5 a missing member is listed but not runnable",
      '_missing ? "muted" : ""' in UI and "if (!_missing) _apply" in UI)
check("C6 the + menu exposes plugins",
      'data-a="plugins"' in UI and '/plugins</span>' in UI)

# ------------------------------------------------------- D: /plan and /spec
check("D1 send() intercepts /plan and /spec before /goal",
      r"const _docCall = raw.match(/^\/(plan|spec)\b[ \t]*([\s\S]*)$/i);" in UI
      and UI.index(r"const _docCall = raw.match(/^\/(plan|spec)") < UI.index(r'if (/^\/goal\b/i.test(msg))'))
check("D2 the queue still owns a NON-document command sent while a turn runs",
      # v1051b: /plan and /spec are decided FIRST — a live turn or a stuck
      # Knowledge ingest swallowed them silently ("/spec does nothing").
      UI.index("if (turnSSE[sessionId]) {") < UI.index(r'if (/^\/goal\b/i.test(msg))'))
check("D3 an empty /plan keeps the text and says why",
      'toast("type the request after /" + _docKind, "warn"); return;' in UI)
check("D4 the call goes to the document endpoint, never to the chat stream",
      # v1051b re-pin: the POST carries an abort signal so a dead planner cannot
      # leave the pending card spinning for ever.
      'api("POST", "/api/docs/" + kind, { session: sid, prompt: ask }' in UI
      and '/api/chat' not in UI.split("async function _runDocCommand")[1][:900])
check("D5 a failure restores the request in the composer",
      'inp.value = "/" + kind + " " + ask;' in UI)
check("D6 a real skill with the same name still wins",
      'String(s.name || "").toLowerCase() === _docCall[1].toLowerCase()' in UI)
check("D7 the document command is decided BEFORE the attachment and queue guards",
      # v1051b: a stuck Knowledge ingest or a live turn used to swallow /spec
      # silently (no bubble, no card, no HTTP request).
      UI.index("const _docCall = raw.match") < UI.index("if (_attachmentPending(sessionId))")
      and UI.index("const _docCall = raw.match") < UI.index("if (turnSSE[sessionId])"))

# --------------------------------------------------------------- E: doc bar
check("E1 the bar is durable markup next to the goal bar",
      'id="docBar"' in UI and 'id="docTitle"' in UI and 'id="docBadge"' in UI)
check("E2 approve/reject/unlock are named controls",
      'data-call="docApprove"' in UI and 'data-call="docReject"' in UI
      and 'data-call="docUnlock"' in UI
      and 'aria-label="approve the document"' in UI
      and 'aria-label="reject the document"' in UI
      and 'aria-label="unlock plan mode"' in UI)
check("E3 the bar reads the backend, not a local guess",
      "async function loadDocBar() {" in UI
      and 'api("GET", "/api/docs?session=" + encodeURIComponent(sid))' in UI)
check("E4 the bar follows a session switch, a reload and a finished turn",
      "loadDocBar();       // v1051: the plan/spec bar follows the session" in UI
      and "loadCosts(); loadDocBar();" in UI
      and "linkifyAll(); loadDocBar();" in UI)
check("E5 approve/reject are disabled while a turn is streaming",
      "const busy = !!turnSSE[sid];" in UI and '$("docApprove").disabled = busy;' in UI)
check("E6 a stale file is never presented as usable",
      'badge.textContent = a.stale ? "file missing"' in UI and '$("docTitle").disabled = !a || !!a.stale;' in UI)
check("E7 the transcript card is a view of the same record",
      "function _renderDocCard(r) {" in UI
      and 'd.querySelector(".dc-approve").onclick = () => docApprove();' in UI)
check("E8 every decision is an SSE event",
      '"docs.created": () => loadDocBar(),' in UI and '"docs.approved": () => loadDocBar(),' in UI
      and '"docs.rejected": () => loadDocBar(),' in UI and '"docs.unlocked": () => loadDocBar(),' in UI)

# ---------------------------------------------------------------- F: styling
check("F1 the bar reuses the goal-bar anatomy and theme tokens",
      "#docBar {" in UI and "#docBar.approved" in UI and "#docBar.stale" in UI
      and "var(--acc)" in UI.split("#docBar {")[1][:600])
check("F2 the menu panel has sections, a sticky footer and a muted row",
      "#slashMenu .slashsec {" in UI and "#slashMenu .slashfoot {" in UI
      and "#slashMenu .slashrow.muted {" in UI)
check("F3 the phone rule gives the panel the composer width",
      "@media (max-width: 560px) {" in UI and "#slashMenu { left: 8px !important; right: 8px !important; }" in UI)
check("F4 the card is styled from the same vocabulary",
      ".docCard {" in UI and ".docCard .dc-acts {" in UI)

# ------------------------------------------------------- G: server agreement
check("G1 the server resolves plugin: tokens",
      r'_SKILL_SLASH_RE = re.compile(r"(^|\s)/([A-Za-z0-9_.\-:]+)")' in AGENT
      and 'low.startswith("plugin:")' in AGENT and "_slash.plugin_block(name)" in AGENT)
check("G2 a UI command is never mistaken for a skill",
      '"plan", "spec",\n                    "plugins", "plugin"}' in AGENT)
check("G3 the backend catalogue owns plan/spec/plugins",
      '{"id": "plan"' in SLASH and '{"id": "spec"' in SLASH and '{"id": "plugins"' in SLASH)
check("G4 the chips understand the plugin token",
      't.indexOf("plugin:") === 0' in UI)

# ------------------------------------- H: /reset, /unlock and the removable bar
# Live 2026-11-16: (a) there was no /reset at all; (b) the plan/spec bar stayed on
# screen for ever after a command and no control could remove it; (c) an attached
# image in the composer could not be opened. Every pin below is one of those.
check("H1 the fallback and the backend both carry /reset and /unlock",
      'id: "reset"' in UI and 'id: "unlock"' in UI
      and '{"id": "reset"' in SLASH and '{"id": "unlock"' in SLASH)
check("H2 both commands run LOCALLY through the one action map",
      "reset: () => resetChat()," in UI and "unlock: () => docUnlock()," in UI)
check("H3 /reset reuses the ONE session-creation path (no second creator)",
      "async function createSession(title, ws) {" in UI
      and "async function createNewSession() {" in UI
      and "const r = await createSession($(\"nsTitle\").value, $(\"nsWs\").value);" in UI
      and "const r = await createSession(\"\", ws);" in UI
      and UI.count('api("GET", "/api/sessions/new?') == 1)
check("H4 the bar ALWAYS offers unlock (proposed and approved included)",
      '$("docUnlock").hidden = false;' in UI
      and '|| proposed;' not in UI.split('$("docUnlock").hidden')[1][:80])
check("H5 /unlock is honest: it forgets the record, the file stays",
      "leave this document's mode?" in UI and "the file stays on disk" in UI)
check("H6 a composer attachment chip opens like its transcript twin",
      "function _attPath(a) {" in UI
      and '_openAttachment((a.visual || _isImage(p)) ? "img" : "file", p);' in UI
      and 'class="attopen"' in UI)
check("H7 open and remove are SIBLING buttons (no nested interactive control)",
      "role=\"' + (p" not in UI
      and "row.querySelectorAll(\".attopen\").forEach" in UI
      and 'class="attchip" data-i="' in UI
      and ".attchip .attopen:focus-visible" in UI)

# ------------------------------- I: the exceptions of autonomous session usage
check("I1 a document command sent while a turn runs is QUEUED, not dropped",
      "if (turnSSE[sessionId]) {\n      enqueueMsg({ raw: raw, text: raw, atts: [] });" in UI
      and 'toast("/" + _docKind + " queued' in UI)
check("I2 /unlock refuses mid-turn, exactly like the disabled ⏏",
      'toast("a turn is running — /unlock when it finishes", "warn"); return null;' in UI)
check("I3 a session switch hides the old bar synchronously (reset and rail)",
      "function _docBarForget() {" in UI
      and UI.count("_docBarForget();") >= 2
      and UI.index("_docBarForget();") < UI.index("async function loadDocBar()"))
check("I4 a planner that lands after a session switch never paints the new chat",
      "if (sid !== sessionId) {" in UI.split("async function _runDocCommand")[1][:2600])
check("I5 a dead service says so, instead of a raw fetch error",
      "the service did not answer (restart or network)" in UI)
check("I6 an empty /unlock says there is nothing to unlock",
      'toast("no document or plan mode in this session", "warn"); return null;' in UI)
check("I7 a new/reset session shows ITS queue, never the one it left",
      "renderQueue();   // JAG-174: the NEW session's queue" in UI)
check("I8 /reset starts with an empty composer (no attachment from the old chat)",
      "_attachments = []; _renderAttach(); _renderPendingCtxItems();" in UI.split("async function resetChat")[1][:900])
check("I9 a flushed /plan never wipes the box or the operator's draft",
      "if (text === undefined) {\n      inp.value = \"\"; if (inp.style) inp.style.height = \"\"; _draftClear(sessionId);\n    }" in UI)
check("I10 /plan says it ignores composer attachments (the planner has no tools)",
      "does not include the \" + _attachments.length" in UI)
check("I11 the send button says a /command QUEUES while a turn runs (never steered)",
      # Operator asked: "does commands enter in chat queue or steer as other messages?".
      # v863 C3 pins the BEHAVIOUR (a command is never steered); this pins that the UI
      # hint tells the truth about it instead of echoing the steer wording.
      "this command waits for the next turn — a /command is never steered into a running turn" in UI)

print("\n---\nv1053: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
