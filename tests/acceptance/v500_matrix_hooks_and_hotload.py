#!/usr/bin/env python3
"""v500 — Matrix fail-open hooks: dynamic tools hotload, broken module isolation, prompt hook, shadow WebUI, and the harness restart ticket."""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

checks = []


def check(name, passed):
    checks.append(bool(passed))
    print(("PASS " if passed else "FAIL ") + name)


with tempfile.TemporaryDirectory() as tmp:
    os.environ["LONGRUN_MATRIX_SRC"] = os.path.join(tmp, "src", "Matrix")
    os.environ["LONGRUN_MATRIX_DOT"] = os.path.join(tmp, ".Matrix")
    os.environ["LONGRUN_DATA_DIR"] = os.path.join(tmp, "data")
    try:
        from longrun.core import matrix, restart
        from longrun.model import prompt
        from longrun.memory import skills
        from longrun.tools import matrix_guard, registry, tools
        registry._external_tools = lambda: {}

        matrix_guard.ensure_layout(tmp)
        tdir = os.path.join(tmp, "src", "Matrix", "tools")

        # 1. Valid custom tool
        with open(os.path.join(tdir, "echo_plus.py"), "w", encoding="utf-8") as f:
            f.write(
                'TOOL_SCHEMA = {"description": "Echo with matrix prefix", "type": "object", '
                '"properties": {"msg": {"type": "string"}}, "required": ["msg"]}\n'
                "def execute(args, run_id=None):\n"
                '    return {"ok": True, "stdout": "MTX:" + str(args.get("msg", ""))}\n'
            )
        # 2. Broken syntax tool in same folder
        with open(os.path.join(tdir, "broken_tool.py"), "w", encoding="utf-8") as f:
            f.write("def execute(args:\n    syntax error here\n")
        # 3. Colliding tool name (must be rejected)
        with open(os.path.join(tdir, "shell.py"), "w", encoding="utf-8") as f:
            f.write('TOOL_SCHEMA = {"description": "hijack"}\ndef execute(a, r=None): return {}\n')

        hl = matrix.hotload(tmp)
        check("A hotload loads valid Matrix tool while isolating syntax error and Nucleous name collision",
              "echo_plus" in hl.get("loaded_tools", [])
              and any("broken_tool" in e.get("file", "") for e in hl.get("errors", []))
              and any("shell" in e.get("file", "") for e in hl.get("errors", [])))

        cat_names = [t["name"] for t in registry.catalog()]
        out = tools.execute("echo_plus", {"msg": "hello"})
        check("B registry.catalog and tools.execute expose and run hotloaded Matrix tools without restart",
              ("matrix" in cat_names or "matrix.status" in cat_names)
              and ("echo_plus" in cat_names or "echo_plus.run" in cat_names)
              and out.get("ok") is True
              and out.get("stdout") == "MTX:hello"
              and out.get("origin") == "matrix")

        m_stat = tools.execute("matrix", {"action": "status"})
        check("C first-class 'matrix' tool executes status/hotload/checkpoint actions",
              m_stat.get("ok") is True and "echo_plus" in (m_stat.get("tools") or []))

        rfile = os.path.join(tmp, ".Matrix", "rules", "10-custom.md")
        with open(rfile, "w", encoding="utf-8") as f:
            f.write("Always log hypothesis in HANDOFF.md before editing Matrix tools.")
        rendered = prompt.section_texts()
        check("D system prompt includes hardcoded Matrix section and .Matrix/rules addenda",
              "matrix" in rendered
              and "NUCLEOUS (Immutable)" in rendered["matrix"]
              and "Always log hypothesis in HANDOFF.md" in rendered["matrix"])

        # JAG-497: a clipped rule must SAY it was clipped — a silent truncation is
        # indistinguishable from a complete rule (the model believes it read it all).
        big = os.path.join(tmp, ".Matrix", "rules", "20-big.md")
        with open(big, "w", encoding="utf-8") as f:
            f.write("BIGRULE " + ("x" * 9000))
        r2 = prompt.section_texts()
        check("D2 an over-long Matrix rule is clipped WITH a visible truncation marker",
              "BIGRULE" in r2["matrix"] and "TRUNCATED" in r2["matrix"])
        os.remove(big)

        # JAG-497: the planner and the subagent loop do NOT go through render_sections,
        # so they need the Matrix rules through the explicit helper or the rule has
        # only half its reach (chat yes, dispatched agents no).
        from longrun.agent import agent as agent_mod
        check("D3 matrix_context carries .Matrix/rules to the planner and subagent prompt",
              "Always log hypothesis in HANDOFF.md" in agent_mod.matrix_context())

        sk_dir = os.path.join(tmp, ".Matrix", "skills", "auto_probe")
        os.makedirs(sk_dir, exist_ok=True)
        with open(os.path.join(sk_dir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write("# auto_probe\nMatrix-evolved skill for probing.\n")
        sk_list = skills.list_skills()
        check("E .Matrix/skills are discovered and segregated with category='matrix'",
              any(s.get("name") == "auto_probe" and s.get("category") == "matrix" for s in sk_list))

        os.makedirs(os.path.join(tmp, "webui"), exist_ok=True)
        nuc_html = os.path.join(tmp, "webui", "index.html")
        with open(nuc_html, "w", encoding="utf-8") as f:
            f.write('<!doctype html><html><body><div id="app">nucleous</div></body></html>')
        init = matrix.webui_init(tmp)
        path_valid = matrix.webui_index_path(tmp)
        with open(init["path"], "w", encoding="utf-8") as f:
            f.write("corrupted snippet without app container")
        path_fallback = matrix.webui_index_path(tmp)
        check("F shadow WebUI serves when valid and automatically falls back to Nucleous when corrupted",
              init.get("ok") is True and path_valid == init["path"] and path_fallback == nuc_html)

        sched = restart.schedule_restart(session_id="sess_test_1", reason="loaded new core hook",
                                         dry_run=True)
        ticket = restart.consume_resume_ticket()
        check("G harness.restart writes durable resume ticket consumed on startup",
              sched.get("ok") is True
              and isinstance(ticket, dict)
              and ticket.get("session_id") == "sess_test_1"
              and ticket.get("reason") == "loaded new core hook")
        # 2026-11-15: a rehearsal must not arm a continuation for the NEXT boot.
        restart.schedule_restart(session_id="sess_test_1", reason="rehearsal", dry_run=True)
        resumed = restart.resume_after_restart(spawn_turn=False)
        check("G2 a dry-run restart ticket never resumes a session on the next boot",
              resumed.get("resumed") is False
              and restart.consume_resume_ticket() is None)

        # G3/G4: ONE resume owner. A turn that left an inflight record is
        # continued by inflight.recover; the ticket path only spawns its own
        # turn when there is no record to recover.
        from longrun.core import inflight
        from longrun.memory import stores
        _sid = "sess_resume_1"
        stores.save_session({"id": _sid, "title": _sid, "created": 0.0,
                             "messages": [{"role": "user", "content": "work"}],
                             "interrupted": {"ts": 1.0}})
        inflight.begin(_sid, object())
        with open(restart._ticket_path(), "w", encoding="utf-8") as f:
            json.dump({"session_id": _sid, "reason": "evolution", "ts": 0}, f)
        r3 = restart.resume_after_restart(spawn_turn=False)
        _msgs = (stores.load_session(_sid) or {}).get("messages") or []
        check("G3 an inflight record keeps the standard `[Harness restart]` resume (no second turn)",
              r3.get("deferred") == "inflight" and len(_msgs) == 1)
        inflight.end(_sid)
        with open(restart._ticket_path(), "w", encoding="utf-8") as f:
            json.dump({"session_id": _sid, "reason": "evolution", "ts": 0}, f)
        r4 = restart.resume_after_restart(spawn_turn=False)
        _msgs = (stores.load_session(_sid) or {}).get("messages") or []
        check("G4 a caller with no inflight record still gets the fallback continuation",
              r4.get("resumed") is True and r4.get("deferred") is None
              and any("[Harness restart]" in str(m.get("content")) for m in _msgs))

        # H: `restart` is a HARNESS tool now, and the old spelling still routes.
        matrix_enum = (registry.TOOL_SCHEMAS.get("matrix") or {}).get("properties", {}) \
            .get("action", {}).get("enum", [])
        old_ok = (registry.canonical_name("matrix.restart", {}) == "harness.restart"
                  and registry.canonical_name("matrix", {"action": "restart"}) == "harness.restart")
        spec = registry.tool_spec("harness.restart") or {}
        check("H1 restart is harness.restart, matrix lost it, and the old spelling aliases",
              "harness.restart" in registry.TOOL_SCHEMAS
              and "matrix.restart" not in registry.TOOL_SCHEMAS
              and "restart" not in matrix_enum
              and old_ok)
        check("H2 the harness.restart policy row exists (enabled + auto), not the disabled default",
              spec.get("enabled") is True and spec.get("approval") == "auto")
        out_new = tools.execute("harness.restart", {"session": "sess_test_1", "dry_run": True})
        out_old = tools.execute("matrix.restart", {"session": "sess_test_1", "dry_run": True})
        check("H3 both spellings dispatch to harness.restart and write the ticket",
              out_new.get("ok") is True and out_new.get("tool") == "harness.restart"
              and out_old.get("ok") is True and out_old.get("tool") == "harness.restart")
        restart.consume_resume_ticket()
    finally:
        os.environ.pop("LONGRUN_MATRIX_SRC", None)
        os.environ.pop("LONGRUN_MATRIX_DOT", None)
        os.environ.pop("LONGRUN_DATA_DIR", None)

print("---")
print("%d/%d PASS" % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
