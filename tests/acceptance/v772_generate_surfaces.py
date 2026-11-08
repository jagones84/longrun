#!/usr/bin/env python3
"""v772 — the ✨ control: ONE registry, ONE engine, the RIGHT context and model.

Operator request (2026-11-02, `.agent/docs/USER_NOTES.md` §"LLM AUTO-EDIT"): an AI
control on every editable text surface, whose writer KNOWS the context of that exact
surface, and whose prompt data lives in ONE place ("pay attentio on wher ethis
hardocded prompt data"). The distinct point: a chat prompt is written by the CHAT's own
model, not by a global agent.

Deterministic: no live model, no network, no server (the model call is stubbed).
Run: python3 tests/acceptance/v772_generate_surfaces.py
"""
import os
import re
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v772-")
for _k in ("DATA_DIR", "CONFIG_DIR", "SESSIONS_DIR", "ROLES_DIR", "DB", "COSTS_DIR",
           "EDITS_DIR", "RUNS_DIR", "GRAPH_DIR", "WORKSPACES_ROOT", "GOALS_DIR",
           "AGENTS_FILE", "TEAMS_FILE"):
    val = os.path.join(TMP, _k.lower() + (".json" if _k.endswith("_FILE") else ""))
    if not _k.endswith("_FILE") and _k != "DB":
        os.makedirs(val, exist_ok=True)
    os.environ["LONGRUN_" + _k] = val
# the machine's real config (roles.generate) is what the model policy reads
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(REPO, "config")
# RH-28: that dir is REAL, so a write must not survive the run — `remember_workspace()`
# persists config.json there (stores.py), which leaked a dead /tmp workspace path into
# the checkout. Snapshot it and put it back byte-for-byte at the end.
_CFGJSON = os.path.join(os.environ["LONGRUN_CONFIG_DIR"], "config.json")
_CFGJSON_BEFORE = None
if os.path.exists(_CFGJSON):
    with open(_CFGJSON, "rb") as _f:
        _CFGJSON_BEFORE = _f.read()
sys.path.insert(0, os.path.join(REPO, "src"))

from longrun.gen import generate as GEN                    # noqa: E402
from longrun.gen import surfaces as S                      # noqa: E402
from longrun.memory import stores                          # noqa: E402
from longrun.model import routing                          # noqa: E402

results = []


def check(name, cond, detail=""):
    ok = bool(cond)
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + str(detail)) if detail else ""))


# ============================================================================
# A — ONE registry: the prompt data has a single owner and the move changed nothing
# ============================================================================
check("A1 every surface carries a system prompt (no silent hole)",
      all(s.system.strip() for s in S.SURFACES.values())
      and len(S.SURFACES) >= 30, len(S.SURFACES))
check("A2 the automate views are DERIVED, not a second copy",
      S.SECTION_PROMPTS["rules"] is S.SURFACES["rules"].system
      and S.AUTOMATE_INSPECT_SECTIONS["teamorg"] == "agents")
from longrun.agent import longrun_agent as LRA             # noqa: E402
check("A3 longrun_agent reads the SAME objects (owner moved, no duplicate)",
      LRA.SECTION_PROMPTS is S.SECTION_PROMPTS
      and LRA.AUTOMATE_ALLOWED_SECTIONS is S.AUTOMATE_ALLOWED_SECTIONS
      and LRA.AUTOMATE_ALLOWED_SECTIONS == ("rules", "teamorg", "agents", "teams", "orbit"))
check("A4 the automate aliases resolve to the same surface (not a second button)",
      S.resolve("orbit").id == "orbit"
      and S.resolve("orbit").system == S.SURFACES["teamorg"].system
      and all(r["id"] != "orbit" for r in S.registry()))
check("A5 the automate prompt TEXT is unchanged by the move (it was moved, not rewritten)",
      "VEO, the burattino of agents" in S.SECTION_PROMPTS["teamorg"]
      and "write updated rules" in S.SECTION_PROMPTS["rules"]
      and "operator-only safety switches" in S.SECTION_PROMPTS["config"])
check("A6 the UI registry ships no prompt text (prompts stay server-side)",
      S.registry() and all("system" not in r for r in S.registry()))
check("A7 every registry row is renderable (id, kind, label, apply, session_scoped)",
      all({"id", "kind", "label", "apply", "session_scoped"} <= set(r) for r in S.registry()))
check("A8 both kinds are exposed",
      {r["kind"] for r in S.registry()} == {"generate", "automate"}
      and any(r["kind"] == "generate" for r in S.registry()))

# ============================================================================
# B — the engine: the RIGHT model per surface, the REAL context, and NO write
# ============================================================================
CHAT = S.SURFACES["chat.prompt"]
GLB = S.SURFACES["rules.global"]
check("B0 a chat surface is session-scoped and a global one is not",
      CHAT.session_scoped is True and CHAT.role == "chat" and GLB.session_scoped is False)

_saved_tm = routing.turn_model
routing.turn_model = lambda sess, model=None: "sess:pinned-model"
_m = GEN._model_for(CHAT, "sid123")
routing.turn_model = _saved_tm
check("B1 a session-scoped surface runs on THAT SESSION's own model", _m == "sess:pinned-model", _m)
check("B2 a global surface runs on the `generate` role (one operator knob)",
      GEN._model_for(GLB, None) == "openrouter:z-ai/glm-5.3-flash",
      GEN._model_for(GLB, None))

# the real chat, from the store the turn loop writes
sid = stores.get_or_create_session(None, "v772-chat")["id"]
sess = stores.load_session(sid)
sess["workspace"] = TMP
stores.append_message(sess, "user", "make the widget red")
stores.append_message(sess, "assistant", "done, the widget is red now")
_c = GEN.context_for(CHAT, {"session": sid})
check("B3 the composer gatherer carries the chat's REAL turns",
      any("widget red" in (t.get("text") or "") for t in _c.get("recent_turns", [])),
      _c.get("recent_turns"))
check("B4 it also carries the workspace and the plan, and the goal once one exists",
      _c.get("workspace") == TMP and "plan" in _c and "goal" not in _c, sorted(_c))
from longrun.plan import goal as GOAL                     # noqa: E402
GOAL.start(sid, "ship the red widget")
_c2 = GEN.context_for(CHAT, {"session": sid})
check("B4b a durable goal reaches the gatherer as the objective + its status",
      (_c2.get("goal") or {}).get("objective") == "ship the red widget"
      and (_c2.get("goal") or {}).get("status") == "active", _c2.get("goal"))

# the field's own text is context too, and a hint is obeyed
_um = GEN._user_message(CHAT, _c, "old text here", "in Italian")
check("B5 the field's current text and the operator hint reach the model",
      "old text here" in _um and "in Italian" in _um and "do not contradict" in _um.lower())

# NO WRITE: the engine returns text and touches no store
_sessions_before = sorted(os.listdir(os.environ["LONGRUN_SESSIONS_DIR"]))
_before = open(os.path.join(os.environ["LONGRUN_SESSIONS_DIR"], sid + ".json"),
               encoding="utf-8").read()
from longrun.util import improve as IMP                    # noqa: E402
_saved_ss = IMP.single_shot
IMP.single_shot = lambda msgs, model=None, role="reviewer", timeout=180, max_tokens=4000: \
    ("```\nDRAFTED TEXT\n```", model or "stub")
_out = GEN.generate("chat.prompt", session=sid, current="keep me", hint="")
IMP.single_shot = _saved_ss
_after = open(os.path.join(os.environ["LONGRUN_SESSIONS_DIR"], sid + ".json"),
              encoding="utf-8").read()
check("B6 generate() returns the draft, cleaned of the fence", _out.get("text") == "DRAFTED TEXT", _out)
check("B7 generate() WRITES NOTHING (the operator saves, not the engine)",
      _after == _before
      and sorted(os.listdir(os.environ["LONGRUN_SESSIONS_DIR"])) == _sessions_before)

check("B8 an automate surface is refused by the generate engine",
      GEN.generate("rules", session=sid).get("ok") is False
      and "automate surface" in GEN.generate("rules", session=sid).get("error", ""))
check("B9 an unknown surface is refused (never a silent no-op)",
      GEN.generate("nope.nope").get("ok") is False)

# ============================================================================
# C — the override is TEXT-only (a bad YAML can never reshape the control)
# ============================================================================
_cfg = os.path.join(os.environ["LONGRUN_CONFIG_DIR"], "generate.yaml")
with open(_cfg, "w", encoding="utf-8") as f:
    f.write("surfaces:\n  chat.prompt:\n    system: 'OVERRIDDEN'\n    apply: 'append'\n    role: 'agent'\n")
try:
    _ov = S.overrides()
    check("C1 the YAML overrides the prompt text",
          _ov.get("chat.prompt") == "OVERRIDDEN", _ov)
    check("C2 the overridden surface's SHAPE is unchanged (apply/role stay code-owned)",
          S.SURFACES["chat.prompt"].apply == "replace"
          and S.SURFACES["chat.prompt"].role == "chat"
          and S.SURFACES["chat.prompt"].session_scoped is True)
    check("C3 the UI registry still ships no prompt text even with an override present",
          all("system" not in r for r in S.registry()))
finally:
    os.remove(_cfg)

# ============================================================================
# D — the frontend contract: ONE affordance, driven by the backend, that never saves
# ============================================================================
UI = open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8").read()
ORBIT = open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"),
             encoding="utf-8").read()
check("D1 the browser keeps NO surface list of its own",
      "const AUTOMATE_ALLOWED_SECTIONS = new Set" not in UI
      and "async function loadGenSurfaces(" in UI
      and '"/api/generate/surfaces"' in UI)
check("D2 one entry point, idempotent by the surface id (never two buttons)",
      "async function mountSparkle(host, surfaceId, opts)" in UI
      and "'[data-gen-surface=\"' + surfaceId" in UI
      and "el.dataset.genSurface = surfaceId" in UI)
check("D3 the ✨ button posts /api/generate and fills the field",
      "function genBar(surfaceId, opts)" in UI
      and '"/api/generate"' in UI
      and "btn.textContent = \"✨\"" in UI)
check("D4 a draft is undoable and announces the change to the app (input event)",
      "function _genApply(field, text, apply, st)" in UI
      and 'new Event("input", { bubbles: true })' in UI
      # RH-5: the undo is an ICON now (`↶`), rendered by the ONE state helper.
      and '_genState(st, "undo"' in UI)
_rg = UI[UI.find("async function runGenerate("):UI.find("function genBar(")]
check("D5 the ✨ path posts ONLY to /api/generate (it never saves the field)",
      'api("POST", "/api/generate"' in _rg
      and all(s not in _rg for s in ('"/api/rules"', '"/api/goal"', '"/api/settings"',
                                     '"/api/roles"', '"/api/memory"', '"/api/workspace"')))
check("D6 the ✨ is mounted on the composer, the goal objective and the plan step",
      '["chat.prompt", "#inp"' in UI
      and '["goal.objective", "#goalEditBox"' in UI
      and '["plan.input", "#planInp"' in UI)
check("D7 the Rules fields and the ROLE.md/subagent briefs are covered too",
      '["rulesGlobalCard", "rulesGlobalText", "rules.global"]' in UI
      and '"agent.role"' in UI and '"subagent.brief"' in UI)
check("D8 the Orbit deck uses the same glyph and the same server surface",
      'class="btn gen-only" id="lraAutoBtn"' in ORBIT and '"/api/generate"' in ORBIT
      and 'surface: "agent.role"' in ORBIT)
check("D9 the ✨ is the documented glyph (no ⚡ left as the generate affordance)",
      "⚡ Automate</button>" not in UI)

# ============================================================================
# E — no second truth anywhere
# ============================================================================
PY = []
for dp, _d, names in os.walk(os.path.join(REPO, "src", "longrun")):
    for n in names:
        if n.endswith(".py"):
            PY.append(open(os.path.join(dp, n), encoding="utf-8").read())
BLOB = "\n".join(PY)
check("E1 the automate prompt data is defined ONCE in the python source",
      BLOB.count("VEO, the burattino of agents") == 1
      and BLOB.count('_AUTOMATE_ALLOWED = (') == 1
      and BLOB.count('("rules", "teamorg", "agents", "teams", "orbit")') == 1)
check("E2 the allowlist literal is not duplicated in the UI",
      len(re.findall(r'AUTOMATE_ALLOWED_SECTIONS', UI)) == 0)

# ============================================================================
# F — RH-5 (operator, 2026-11-03): the ✨ state is an ICON, never a sentence
#     "drafted undo? … occupa troppo spazio metti icona semplifica la grafica …
#      metti animazione icona quando sta lavorando l automatic edit."
# ============================================================================
check("F1 the state slot renders ICONS through one helper, never a sentence",
      "function _genState(st, kind, opts)" in UI
      and '"✓ drafted"' not in UI and "gen-undo" not in UI
      and '_genState(st, "undo"' in UI and '_genState(st, "warn"' in UI)
check("F2 the ✨ pulses while the draft is in flight, and its TEXT never changes",
      'btn.classList.add("busy")' in UI and "btn.classList.remove(\"busy\")" in UI
      and "aria-busy" in UI and "animation: genPulse" in UI
      and 'btn.textContent = "✨"' in UI and '"✨…"' not in UI)
check("F3 the pulse is off under prefers-reduced-motion",
      "@keyframes genPulse" in UI
      and "prefers-reduced-motion: reduce" in UI.split("@keyframes genPulse")[1][:400])
check("F4 an error is an icon whose tooltip carries the reason (click = the detail)",
      '_genState(st, "warn", { title: why, onclick: () => toast(why, "err") })' in UI)
check("F5 the empty slot collapses, so an idle surface reserves NO width",
      ".gen-bar .gen-status:empty" in UI
      and ".gen-bar .gen-spark, .gen-bar .gen-act {" in UI)
check("F6 the Control deck obeys the SAME rule (one product, one rule)",
      "function genState(host, kind, why)" in ORBIT
      and "gen-busy" in ORBIT and "@keyframes genPulse" in ORBIT
      and "✓ drafted" not in ORBIT and "✨…" not in ORBIT
      and 'genState(st, "ok"' in ORBIT and 'genState(st, "warn"' in ORBIT)
# RH-11 (operator, 2026-11-03): "l'autogenerate … lascia solo l'icona senza riquadro
# bianco attorno così è più estetica. Vale per tutte le icone autogenerate."
_genbar = UI.split(".gen-bar .gen-spark, .gen-bar .gen-act {")[1][:300]
check("F7 a ✨ control is FRAMELESS — the state is the glyph and its colour",
      "border: 0" in _genbar and "border: 1px solid var(--line)" not in _genbar
      and ".gen-bar .gen-act { color: var(--dim); cursor: pointer; }" in UI
      and ".gen-bar .gen-act.warn { color: var(--warn); }" in UI)
_genic = ORBIT.split(".gen-ic{")[1][:160]
check("F8 the Control deck's ✨/state icons are frameless too (one product)",
      "border:0" in _genic and "border:1px solid" not in _genic)

# ============================================================================
# G — the composer drafts for the CONVERSATION: the folder is a fact about the
#     chat only when the SESSION owns one. Live 2026-11-03: an empty chat
#     inherited the global default (on the operator's host that is the harness's
#     OWN repo) and the ✨ drafted "explore the repository at <harness repo>" in a
#     conversation about something else. Operator: "perché l'autogenerate parla
#     di orbit che non c'entra un cazzo di nulla con la chat?"
# ============================================================================
from longrun.memory import rules as RULES                  # noqa: E402
_nof = stores.get_or_create_session(None, "v772-empty-chat")["id"]
_s = stores.load_session(_nof)
_s.pop("workspace", None)
stores.save_session(_s)
_def = RULES.get_workspace()
check("G1 an empty chat does NOT inherit the global default folder",
      bool(_def) and os.path.isdir(_def)
      and "workspace" not in GEN.context_for(CHAT, {"session": _nof}),
      "default=%r ctx=%s" % (_def, GEN.context_for(CHAT, {"session": _nof})))
check("G2 the change is SCOPED to the composer (the default still reaches the others)",
      GEN.context_for(S.SURFACES["goal.objective"], {"session": _nof}).get("workspace") == _def)
_s2 = stores.load_session(_nof)
_s2["workspace"] = TMP
stores.save_session(_s2)
check("G3 a chat that OWNS a folder still carries it in the composer context",
      GEN.context_for(CHAT, {"session": _nof}).get("workspace") == TMP)
check("G4 an empty conversation is HANDLED, not invented: the prompt asks the operator",
      "NO conversation yet" in S.SURFACES["chat.prompt"].system
      and "OPENING message" in S.SURFACES["chat.prompt"].system
      and "never assume" in S.SURFACES["chat.prompt"].system)
check("G5 only the composer passes own_workspace_only (one owner for the rule)",
      "own_workspace_only=True" in open(os.path.join(
          REPO, "src", "longrun", "gen", "generate.py"), encoding="utf-8").read()
      and GEN._GATHER["chat.prompt"]({"session": _nof}).get("workspace") == TMP)
# RH-29 (operator, 2026-11-03): a FILLED composer is OPTIMIZED, never overwritten by a
# brand-new message, and the ✨'s name says which job it will do.
check("G6 a FILLED composer is OPTIMIZED, never answered or replaced by a new message",
      "OPTIMIZE the operator's draft" in S.SURFACES["chat.prompt"].system
      and "REPLACES it" in S.SURFACES["chat.prompt"].system
      and "no new features, names, paths or numbers" in S.SURFACES["chat.prompt"].system)
_rows = {m.group(1): m.group(0)
         for m in re.finditer(r'\["([a-z.]+)", "[^"]+"[^\]]*\]', UI)}
check("G7 the ✨'s NAME follows the field's state, and only the composer optimizes",
      "opts.filledTitle" in UI and "_syncName()" in UI
      and "optimize what I typed" in (_rows.get("chat.prompt") or "")
      and not any("optimize" in (_rows.get(k) or "") for k in
                  ("goal.objective", "plan.input", "memory.content",
                   "blackboard.topic", "kb.notebook")))

# ============================================================================
# H — RH-18 (operator, 2026-11-03): ONE ✨ designs a whole NEW subagent role.
#     "nella scheda settings subagents non c'è un autogeneration per creare un nuovo
#      subagent (ovviamente deve conoscere i già presenti e che prompt hanno).
#      Devi dividere tutto, nome e prompt etcetera."
# ============================================================================
_NEW = S.SURFACES.get("subagent.new")
check("H1 there is a `subagent.new` GENERATE surface and it returns JSON, not one field",
      _NEW is not None and _NEW.kind == S.GENERATE and _NEW.apply == "json"
      and _NEW.ctx == "subagent.new")
check("H2 its prompt asks for the NAME and the BRIEF in one JSON object",
      _NEW is not None and '"name"' in _NEW.system and '"brief"' in _NEW.system
      and "JSON" in _NEW.system and "must differ from all of them" in _NEW.system)
_NCTX = GEN.context_for(_NEW) if _NEW else {}
check("H3 the generator KNOWS the existing roles AND their prompts",
      isinstance(_NCTX.get("roles"), dict) and len(_NCTX.get("roles") or {}) >= 1
      and all(len(v) > 10 for v in (_NCTX.get("roles") or {}).values())
      and isinstance(_NCTX.get("existing_names"), list)
      and sorted(_NCTX["existing_names"]) == sorted(_NCTX.get("roles") or {}))
check("H4 a role stored as a plain STRING does not erase the whole neighbours map",
      GEN._role_brief("just a brief") == "just a brief"
      and GEN._role_brief({"brief": "b", "tools": ["fs.read"]}) == "b"
      and GEN._role_brief(None) == "")
check("H5 the panel mounts it and never overwrites an existing role",
      'mountSparkle($("subDraftHost"), "subagent.new"' in UI
      and "function subDraftAgent(text, st)" in UI
      and "_subRoles[name] = brief;" in UI
      and "already exists — draft again for a different one" in UI)
check("H6 it writes the name into the visible field and saves the brief",
      'if ($("subNewRole")) $("subNewRole").value = name;' in UI
      and "subRenderRoles();" in UI and "subSaveSoon();" in UI)
check("H7 the multi-field reply never goes through the single-field writer",
      "if (opts && typeof opts.onText === \"function\")" in UI
      and "opts.onText(r.text, st)" in UI)

# ============================================================================
# I — 2026-11-07 (operator, RH panel): the Plan/Goal box must GROW with the text,
#     and its ✨ must REORGANIZE what is already there — "see what the icon does
#     for the chat, same for the plan/goal but with a different intent".
# ============================================================================
check("I1 the Plan field is a multi-line box, not a one-line input",
      '<textarea aria-label="goal or plan node" id="planInp"' in UI
      and '<input aria-label="goal or plan node" id="planInp"' not in UI)
check("I2 it grows with its content through the ONE grower (composer + goal too)",
      "function _growField(el, max)" in UI
      and "function _growPlan() { _growField($(\"planInp\"), 132); }" in UI
      and "function _growGoalEdit()" in UI
      and '["planInp", "goalEditBox"].forEach(' in UI)
check("I3 Shift+Enter is a line break in a data-key TEXTAREA (Enter still runs)",
      'if (el.tagName === "TEXTAREA" && e.shiftKey) return;' in UI)
check("I4 the ✨ on the plan/goal names the REORGANIZE job when the field has text",
      "reorganize this step" in (_rows.get("plan.input") or "")
      and "reorganize this objective" in (_rows.get("goal.objective") or ""))
check("I5 the server prompts carry the FILLED branch for both surfaces",
      "CURRENT CONTENT OF THE FIELD decides the job" in S.SURFACES["plan.input"].system
      and "REORGANIZE that text into ONE step" in S.SURFACES["plan.input"].system
      and "REPLACES" in S.SURFACES["plan.input"].system
      and "REORGANIZE that text" in S.SURFACES["goal.objective"].system
      and "REPLACES" in S.SURFACES["goal.objective"].system)
# the browser's own dialogs are gone from the app flows: ONE themed dialog. The
# bootstrap token prompt is the only exception (it runs before the app exists).
check("I6 every dialog is the app's own (no native prompt/confirm/alert in the flows)",
      "function uiDialog(opts)" in UI and "function uiAsk(opts)" in UI
      and "function uiConfirm(title, hint, opts)" in UI
      and all(("prompt(" not in ln) for ln in UI.splitlines()
              if "TOKEN = prompt(" not in ln and not ln.strip().startswith("//")
              and not ln.strip().startswith("*") and "`prompt()`" not in ln)
      and all(("alert(" not in ln) for ln in UI.splitlines()
              if not ln.strip().startswith("//")))

if _CFGJSON_BEFORE is None:
    if os.path.exists(_CFGJSON):
        os.remove(_CFGJSON)
else:
    with open(_CFGJSON, "wb") as _f:
        _f.write(_CFGJSON_BEFORE)
shutil.rmtree(TMP, ignore_errors=True)
print("\n%d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
