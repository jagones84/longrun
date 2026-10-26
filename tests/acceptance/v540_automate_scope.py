#!/usr/bin/env python3
"""v540 — longrunAgent automation is scoped to text surfaces (Rules + Teamorg).

The operator's rule: an agent may help with prompts and rules, never rewrite
runtime configuration on its own. The code stays in place, but every other
section is neither mounted in the WebUI nor accepted by the endpoint.
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="sf-v540-")
os.environ["LONGRUN_CONFIG_DIR"] = os.path.join(TMP, "cfg")
os.environ["LONGRUN_DATA_DIR"] = os.path.join(TMP, "data")
os.environ["LONGRUN_DB"] = os.path.join(TMP, "events.db")
sys.path.insert(0, os.path.join(ROOT, "src"))

from longrun.agent import longrun_agent as LRA  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name
          + ((" :: " + str(detail)) if detail else ""))


with open(os.path.join(ROOT, "webui", "index.html"), encoding="utf-8") as f:
    UI = f.read()
with open(os.path.join(ROOT, "src", "longrun", "orbit", "web", "orbit.html"),
          encoding="utf-8") as f:
    ORBIT = f.read()

check("A1 the UI allowlist is exactly Rules + Teamorg",
      'const AUTOMATE_ALLOWED_SECTIONS = new Set(["rules", "teamorg"]);' in UI
      and "function _automateAllowed(section)" in UI)
check("A2 the widget refuses to build an active bar for other sections",
      "function makeAutomateWidget(section, getContext)" in UI
      and "if (!_automateAllowed(section)) {" in UI
      and "bar.hidden = true;   // code stays" in UI)
check("A3 Settings only mounts a category whose section is allowed",
      "if (!_automateAllowed(spec.section)) return;" in UI)
check("A4 the Codebase inspector still has no agent Automate bar",
      'mountSectionAutomate(\'section[data-insp="codebase"]\'' not in UI)
check("A5 the mapping table stays in the codebase (nothing deleted)",
      "const AUTOMATE_CATS = {" in UI
      and all(("  " + k + ": { section:") in UI
              for k in ("models", "subagents", "tools", "mcp", "skills",
                        "knowledge", "rules", "config")))
check("A6 Orbit keeps the Teamorg bar, which is an allowed surface",
      'id="lraAutoBtn"' in ORBIT and "teamorg" in LRA.SECTION_PROMPTS)
check("A7 the server allowlist mirrors the UI",
      LRA.AUTOMATE_ALLOWED_SECTIONS == ("rules", "teamorg", "agents", "teams", "orbit"))
# The Rules panel mounts ONE widget per card (global + project, each with its real
# scope). The category-level mount ran FIRST and added a third button whose ctx
# said scope=global — two of the three sent the same scope.
check("A8 the Rules panel owns its widgets; the category does not add a third",
      'const AUTOMATE_CAT_SKIP = new Set(["rules"]);' in UI
      and "if (AUTOMATE_CAT_SKIP.has(name)) return;" in UI
      and '[["rulesGlobalCard", "global"], ["rulesProjectCard", "project"]]' in UI
      and 'c.appendChild(makeAutomateWidget("rules", () => ({ scope })))' in UI)
check("A9 an automate run refreshes the surface it edited (both paths)",
      "loadSessions(); loadAgents(); loadSettingsForms(); loadRulesPanel(); loadRules();" in UI
      and "loadSettingsForms();\n        loadRulesPanel();\n        loadRules();" in UI)

blocked = LRA.automate("tools", "disable the sandbox")
check("B1 a config section is refused with a disabled marker",
      blocked.get("ok") is False and blocked.get("disabled") is True
      and "disabled for section 'tools'" in str(blocked.get("error")), blocked)
check("B2 the refusal names the allowed surfaces",
      blocked.get("allowed_sections") == list(LRA.AUTOMATE_ALLOWED_SECTIONS))
for section in ("models", "subagents", "harness", "mcp", "config", "index",
                "knowledge", "providers", "routing", "team_policy"):
    res = LRA.automate(section, "change it")
    check("B3 %s is refused before any session reset" % section,
          res.get("disabled") is True and res.get("ok") is False, res)

allowed = LRA.automate("rules", "")
check("B4 Rules passes the gate and then asks for an instruction",
      allowed.get("error") == "instruction required"
      and not allowed.get("disabled"), allowed)
teamorg = LRA.automate("teamorg", "")
check("B5 Teamorg passes the gate too",
      teamorg.get("error") == "instruction required"
      and not teamorg.get("disabled"), teamorg)

shutil.rmtree(TMP, ignore_errors=True)
print("v540: %d/%d PASS" % (sum(results), len(results)))
raise SystemExit(0 if all(results) else 1)
