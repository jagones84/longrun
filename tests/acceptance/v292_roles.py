#!/usr/bin/env python3
"""v292 — Per-session ROLE.md: the role patch merged into the prompt (JAG-294).

Locked here:
  * `roles.py` stores ONE file per SESSION id (outside any workspace), so two
    agents sharing a folder never collide; empty write clears it;
  * the prompt has an `agent-role` DYNAMIC section (order >= 50, cache-safe) whose
    provider renders the session's role on top of the canonical prompt;
  * GET/POST/DELETE /api/roles — the single API both the primary WebUI and Orbit use;
  * agent names are unique across agents AND sessions (a duplicate is refused);
  * the CLI exposes roles/agents/jobs and the primary WebUI has the complete Rules
    panel (the per-session role + the global/project rules, JAG-361).

Deterministic, no live model. Run: python3 tests/v292_roles.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
TMP = tempfile.mkdtemp(prefix="sf-v292-")
os.environ["LONGRUN_AGENTS_FILE"] = os.path.join(TMP, "agents.json")
os.environ["LONGRUN_ROLES_DIR"] = os.path.join(TMP, "roles")
os.environ["LONGRUN_SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.makedirs(os.environ["LONGRUN_SESSIONS_DIR"], exist_ok=True)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


from longrun.agent import agents  # noqa: E402
from longrun.orchestrate import orchestration  # noqa: E402
from longrun.model import prompt  # noqa: E402
from longrun.orchestrate import roles  # noqa: E402

# --- storage: one file per session id --------------------------------------
w = roles.write("sess-a", "Role: analyst\n- be terse")
check("write returns ok + a per-session path", w["ok"] and w["path"].endswith("sess-a.md"))
check("read returns the text", roles.read("sess-a").startswith("Role: analyst"))
check("the key is filesystem-safe", roles.key("a/b c") == "a_b_c")
check("an empty write clears the file",
      roles.write("sess-a", "")["cleared"] and roles.read("sess-a") == "")
roles.write("sess-a", "R")
check("delete removes it", roles.delete("sess-a")["deleted"] and roles.read("sess-a") == "")
check("a session with no role reads empty", roles.read("nope") == "")

# --- prompt: the role rides as its own dynamic section ---------------------
sec = next((s for s in prompt.SECTIONS if s["id"] == "agent-role"), None)
check("agent-role is a DYNAMIC section", bool(sec) and sec["kind"] == "dynamic")
check("agent-role sits after the static front (order >= 50)", bool(sec) and sec["order"] >= 50)
roles.write("sess-a", "Role: analyst")
out = prompt._provider_role({"id": "sess-a"}, None, None)
check("the provider renders the role", "analyst" in out and "## Your role" in out)
check("a session with no role renders nothing", prompt._provider_role({"id": "nope"}, None, None) == "")

# --- API -------------------------------------------------------------------
class FakeHandler:
    def __init__(self):
        self.sent = None

    def _send(self, code, obj, ctype=None):
        self.sent = {"code": code, "obj": obj}
        return True


fh = FakeHandler()
ok = orchestration.handle(fh, "GET", "/api/roles", {"session": "sess-b"}, None)
check("GET /api/roles answers", ok and fh.sent["code"] == 200 and fh.sent["obj"]["text"] == "")

fh = FakeHandler()
ok = orchestration.handle(fh, "POST", "/api/roles", {}, {"session": "sess-b", "text": "Role: x"})
check("POST /api/roles writes", ok and fh.sent["obj"]["ok"] and roles.read("sess-b") == "Role: x")

fh = FakeHandler()
ok = orchestration.handle(fh, "DELETE", "/api/roles", {"session": "sess-b"}, None)
check("DELETE /api/roles clears", ok and roles.read("sess-b") == "")

fh = FakeHandler()
ok = orchestration.handle(fh, "GET", "/api/roles", {}, None)
check("GET without a session is a clean 400", ok and fh.sent["code"] == 400)

# --- unique names ----------------------------------------------------------
AR = agents.REGISTRY
AR.designate("s1", name="Alpha")
check("a fresh name is accepted", AR.get("s1").get("name") == "Alpha")
dup = AR.designate("s2", name="Alpha")
check("a duplicate agent name is refused", dup["ok"] is False and "already in use" in dup["error"])
check("the refused agent was not persisted", AR.get("s2") is None)
check("renaming to your own name is allowed", AR.designate("s1", name="Alpha")["ok"] is True)
ok2 = AR.designate("s2", name="Beta")
check("a different name is accepted", ok2["ok"] and AR.get("s2").get("name") == "Beta")
check("name_taken is case-insensitive", AR.name_taken("beta") is True)

# --- CLI + primary WebUI wiring --------------------------------------------
with open(os.path.join(REPO, "src", "longrun", "core/forge.py"), encoding="utf-8") as f:
    cli = f.read()
check("the CLI exposes roles/agents/jobs",
      'add_parser("roles")' in cli and 'add_parser("agents")' in cli
      and 'add_parser("jobs")' in cli and "def cmd_roles" in cli)
with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
    gui = f.read()
check("the primary WebUI has the Rules panel (per-session role)",
      'data-insp="rules"' in gui and "async function loadRole()" in gui
      and "/api/roles" in gui and "/api/rules" in gui)
with open(os.path.join(REPO, "src", "longrun", "orbit", "web", "orbit.html"), encoding="utf-8") as f:
    oui = f.read()
check("the Orbit deck edits the same role API",
      '"/api/roles?session="' in oui and 'data-p="role"' in oui)
# JAG-367: the Orbit prompt editor must SHOW the fetched ROLE.md. It loads it ASYNC,
# but render()'s dirty-guard (added to protect an in-progress edit from the 5s poll)
# also blocked that load render, so the textarea stayed "" and looked VOID even though
# the same ROLE.md the primary UI shows had content. The fix writes the fetched text
# straight into the textarea instead of relying on a (blocked) re-render.
check("the Orbit prompt editor writes the fetched ROLE.md into the textarea",
      "if (this.open !== sid) return;" in oui
      and "const ta = $(\"agBody\").querySelector('textarea[data-p=\"role\"]');" in oui
      and "if (ta) ta.value = this.openText;" in oui, "")
check("the Orbit prompt load no longer depends on a render the poll guard can block",
      "this.openText = (r && r.text) || \"\";\n      this.render(null, null);" not in oui, "")

print("---")
passed = sum(results)
print("%d/%d PASS" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)

