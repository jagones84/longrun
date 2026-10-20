#!/usr/bin/env python3
"""v506 — Live Matrix disable/enable toggle (pure Nucleus mode) & universal promote_to_nucleus across all src/Matrix and .Matrix artifacts."""
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
        from longrun.core import matrix
        from longrun.memory import skills
        from longrun.tools import matrix_guard, registry, tools
        registry._external_tools = lambda: {}

        matrix_guard.ensure_layout(tmp)
        os.makedirs(os.path.join(tmp, "webui", "assets"), exist_ok=True)
        nuc_html = os.path.join(tmp, "webui", "index.html")
        with open(nuc_html, "w", encoding="utf-8") as f:
            f.write('<!doctype html><html><body><div id="app">nucleus</div></body></html>')

        # Populate src/Matrix and .Matrix with tool, hook, rule, skill, shadow webui, plugins.js
        with open(os.path.join(tmp, "src", "Matrix", "tools", "live_probe.py"), "w", encoding="utf-8") as f:
            f.write(
                'TOOL_SCHEMA = {"description": "probe", "type": "object", "properties": {}}\n'
                'def execute(args, run_id=None): return {"ok": True, "stdout": "live"}\n'
            )
        with open(os.path.join(tmp, "src", "Matrix", "plan", "hooks.py"), "w", encoding="utf-8") as f:
            f.write("def score_candidate(text, base): return 0.99\n")
        with open(os.path.join(tmp, ".Matrix", "rules", "20-style.md"), "w", encoding="utf-8") as f:
            f.write("MATRIX_RULE_MARKER_20")
        sk_dir = os.path.join(tmp, ".Matrix", "skills", "mtx_skill")
        os.makedirs(sk_dir, exist_ok=True)
        with open(os.path.join(sk_dir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write("# mtx_skill\nMatrix skill description.\n")
        matrix.webui_init(tmp)
        with open(os.path.join(tmp, "src", "Matrix", "webui", "plugins.js"), "w", encoding="utf-8") as f:
            f.write("window.__MTX_PLUG = 1;\n")
        matrix.hotload(tmp)

        # A: Disable Matrix live via tools.execute("matrix", {"action": "disable"}) -> only Nucleus remains active
        dis_res = tools.execute("matrix", {"action": "disable"})
        skills.list_skills(reload=True)
        check("A disabling Matrix live turns off all src/Matrix and .Matrix effects (tools, hooks, rules, skills, webui)",
              dis_res.get("ok") is True
              and matrix.is_enabled() is False
              and matrix.discover_tools(tmp) == {}
              and matrix.discover_hooks(tmp) == {}
              and matrix.call_hook("plan", "score_candidate", "x", 0.5, default=0.5, repo_root=tmp) == 0.5
              and "MATRIX_RULE_MARKER_20" not in matrix.prompt_section_text(repo_root=tmp)
              and not any(s.get("name") == "mtx_skill" for s in skills.list_skills(reload=True))
              and matrix.webui_index_path(tmp) == nuc_html
              and "window.__MTX_PLUG" not in matrix.webui_plugins_js(tmp))

        # B: Re-enable Matrix live via tools.execute("matrix", {"action": "enable"}) -> all effects restored
        en_res = tools.execute("matrix", {"action": "enable"})
        skills.list_skills(reload=True)
        check("B re-enabling Matrix live restores all src/Matrix and .Matrix tools, hooks, rules, skills, and webui",
              en_res.get("ok") is True
              and matrix.is_enabled() is True
              and "live_probe" in matrix.discover_tools(tmp)
              and matrix.call_hook("plan", "score_candidate", "x", 0.5, default=0.5, repo_root=tmp) == 0.99
              and "MATRIX_RULE_MARKER_20" in matrix.prompt_section_text(repo_root=tmp)
              and any(s.get("name") == "mtx_skill" for s in skills.list_skills(reload=True))
              and "window.__MTX_PLUG" in matrix.webui_plugins_js(tmp))

        # C: Universal promote_to_nucleus works for module, skill, rule, and webui
        orig_load = registry.load_config
        cfg_cb = json.loads(json.dumps(orig_load()))
        cfg_cb.setdefault("approvals", {})["allow_matrix_promote"] = True
        cfg_cb["approvals"]["matrix_enabled"] = True
        registry.load_config = lambda reload=False: cfg_cb

        mod_file = os.path.join(tmp, "src", "Matrix", "util", "math_ext.py")
        with open(mod_file, "w", encoding="utf-8") as f:
            f.write("def triple(x):\n    return x * 3\n")

        # Verify all 4 targets via run_test
        for tgt in ("module:util/math_ext", "skill:mtx_skill", "rule:20-style.md", "webui:plugins.js"):
            matrix.run_test("verify_all.py", code="from Matrix.util import math_ext\nassert math_ext.triple(3) == 9\n",
                            target=tgt, repo_root=tmp)

        p_mod = matrix.promote_to_nucleus("module", "util/math_ext", repo_root=tmp)
        p_sk = matrix.promote_to_nucleus("skill", "mtx_skill", repo_root=tmp)
        p_rul = matrix.promote_to_nucleus("rule", "20-style.md", repo_root=tmp)
        p_wui = matrix.promote_to_nucleus("webui", "plugins.js", repo_root=tmp)
        registry.load_config = orig_load

        check("C promote_to_nucleus supports module, skill, rule, and webui (moves to Nucleus and deletes from Matrix)",
              p_mod.get("ok") is True and not os.path.exists(mod_file)
              and os.path.isfile(os.path.join(tmp, "src", "longrun", "util", "math_ext.py"))
              and p_sk.get("ok") is True and not os.path.exists(sk_dir)
              and os.path.isfile(os.path.join(tmp, "skills", "created", "mtx_skill", "SKILL.md"))
              and p_rul.get("ok") is True and not os.path.exists(os.path.join(tmp, ".Matrix", "rules", "20-style.md"))
              and os.path.isfile(os.path.join(tmp, ".longrun", "prompt.d", "20-style.md"))
              and p_wui.get("ok") is True and not os.path.exists(os.path.join(tmp, "src", "Matrix", "webui", "plugins.js"))
              and os.path.isfile(os.path.join(tmp, "webui", "assets", "matrix_promoted_plugins.js")))

        with open(os.path.join(REPO, "webui", "index.html"), encoding="utf-8") as f:
            html = f.read()
        with open(os.path.join(REPO, "README.md"), encoding="utf-8") as f:
            readme = f.read()
        check("D WebUI renders #apMatrixEnabled toggle and README documents Nucleus vs. Matrix self-evolution",
              'id="apMatrixEnabled"' in html
              and "matrix_enabled" in html
              and "src/Matrix" in readme
              and "promote_to_nucleus" in readme)
    finally:
        os.environ.pop("LONGRUN_MATRIX_SRC", None)
        os.environ.pop("LONGRUN_MATRIX_DOT", None)
        os.environ.pop("LONGRUN_DATA_DIR", None)

print("---")
print("%d/%d PASS" % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
