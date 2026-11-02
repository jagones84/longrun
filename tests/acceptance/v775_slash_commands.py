#!/usr/bin/env python3
"""v775 — the `/` command menu: a real command registry, and `/skills` that RUNS.

Operator, verbatim: *"comando /skill non fa nulla non capisco. dovrebbe essere
'/skills' cliccando ok si apre il MENU delle skills (che non deve essere presente
la lista da subito digitando solo '/', funge da submenu opener della lista dei
comandi). rivedi in generale quella parte dei comandi se e al top di frontiera."*

The defect was a silent no-op: the `/skills` command called `openPanel("skills")`,
which resolves to `#inspector section[data-insp="skills"]` — a section that DOES
NOT EXIST (live: the rail holds approvals/cost/context/plan/rules/files/codebase/
terminal/feed). The real picker already existed and only the `+` menu reached it.

Contract:
  A) ONE registry for the `/` commands (id/aliases/icon/hint/insert/run), read by
     the menu, by the composer chips AND by the send-time interception;
  B) `/skills` (alias `/skill`) OPENS the skill picker — it is a UI action, not a
     message that reaches the model;
  C) a bare "/" opens the COMMAND menu only (the submenu opener); the skill
     catalogue appears once the query filters it;
  D) frontier ergonomics: Tab completes the highlighted row, and the skills rank
     exact > prefix > contains;
  E) a message that IS one UI command runs instead of being sent as prose — while
     a REAL skill with that name still wins (the server's own rule);
  F) the lies are gone: no second dispatch chain, no chip tooltip describing an
     action the command does not perform.

Deterministic: source contracts only. No browser, no server, no model.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)[:300]) if detail and not ok else ""))


# ---- A: ONE registry ---------------------------------------------------------
check("A1 the registry is declared once, keyed by id, with the three commands",
      "const SLASH_COMMANDS = [" in UI
      and '{ id: "goal", icon: "◎", insert: "/goal ",' in UI
      and '{ id: "skills", aliases: ["skill"], icon: "🧩", insert: "",' in UI
      and '{ id: "compact", icon: "🗜", insert: "",' in UI)
check("A2 an id/alias index is built from that ONE table",
      "const SLASH_BY_ID = (() => {" in UI
      and "(c.aliases || []).forEach(a => { m[a] = c; })" in UI)
check("A3 the registry sits BEFORE send() (no boot-order/temporal-dead-zone miss)",
      UI.index("const SLASH_COMMANDS = [") < UI.index("function send(text, display, atts) {"))

# ---- B: /skills RUNS ---------------------------------------------------------
check("B1 /skills carries a real action: the skill picker",
      "run: () => openSkillPicker() }," in UI and "async function openSkillPicker()" in UI)
check("B2 /compact carries a real action too", "run: () => compactNow() }," in UI)
check("B3 the old no-op target is gone from the CODE (a comment may name it)",
      all('openPanel("skills")' not in ln.split("//")[0] for ln in UI.splitlines()),
      "openPanel(\"skills\") still executed")
check("B4 the second dispatch chain is gone (no per-command if/else)",
      'c.cmd === "skills"' not in UI and 'c.cmd === "compact"' not in UI and ".cmd.startsWith" not in UI)
check("B5 picking runs the command and rewrites the token from the SAME entry",
      '() => { _apply(c.insert === undefined ? "/" + c.id + " " : c.insert); if (c.run) c.run(); },' in UI)
check("B6 an EMPTY insert is a value (it consumes the token), never an absent one",
      # regression found LIVE: `c.insert || "/"+c.id` swapped the empty insert of
      # /skills for "/skills ", so picking it left the token in the composer.
      "c.insert === undefined ?" in UI and 'insert: ""' in UI)

# ---- C: "/" is the command menu ----------------------------------------------
check("C1 an EMPTY query matches every command (the submenu opener)",
      "function _slashCmdHits(q) {" in UI
      and "if (!q) return SLASH_COMMANDS.slice();" in UI)
check("C2 with no query the SKILL catalogue is not ranked at all",
      "const _matched = q ? _rankSkills(_skills, q) : [];" in UI)
check("C3 a non-empty query still searches the WHOLE catalogue (JAG-465 kept)",
      "const _SLASH_CAP = 60;" in UI and "const hits = _matched.slice(0, _SLASH_CAP).map(x => x.s);" in UI)

# ---- D: frontier ergonomics --------------------------------------------------
check("D1 Tab completes the highlighted row without running it",
      'if (e.key === "Tab") { e.preventDefault(); const it = _slashItems[_slashHi]; '
      'if (it && it.complete) it.complete(); return; }' in UI)
check("D2 every row carries a complete() (commands complete to /<id> )",
      "_slashItems.push({ el: li, pick: onPick, complete: onComplete || onPick });" in UI
      and '() => _apply("/" + c.id + " ")));' in UI)
check("D3 the skill rank is exact > prefix > contains",
      "if (name === query) return 5;" in UI and "if (name.startsWith(query)) return 4;" in UI
      and "if (name.includes(query)) return 3;" in UI)

# ---- E: a whole-message UI command runs instead of being sent ---------------
check("E1 send() intercepts a message that IS one UI command",
      r'const _solo = raw.match(/^\/([A-Za-z0-9_.\-]+)$/);' in UI
      and "if (_c && _c.run && !_ownSkill) {" in UI and "_c.run(); return;" in UI)
check("E2 a REAL skill with the same name still wins (the server's rule)",
      "const _ownSkill = (_skillsCache || []).some(s => String(s.name || \"\").toLowerCase() === _tok);" in UI)

# ---- F: the lies are gone ----------------------------------------------------
check("F1 the composer chips read the registry (ONE table, one tooltip)",
      "const _cmd = SLASH_BY_ID[t];" in UI
      and "else if (_cmd) push(_cmd.icon, _cmd.id, _cmd.hint, false);" in UI)
check("F2 the false chip tooltip is gone",
      "opens the Skills panel (pick from the / menu)" not in UI)
check("F3 the + menu prints the canonical spelling",
      '🧩 Skills…<span class="k">/skills</span>' in UI)

print("\n---\nv775: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
